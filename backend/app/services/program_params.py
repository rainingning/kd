"""BE_FETD/FDEM3D 当前源参数镜像、工作副本和任务快照。"""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..em_param_schema import (
    ParamValidationError,
    parse_parameter_bytes,
    schema_version_for,
    serialize_parameter,
    validate_parameter_with_warnings,
)
from .program_template import program_template_dir, sha256_file, validate_program_template
from .programs import DCR_3D, get_program
from .storage import canonical_program_param_path, params_path


class ProgramParamsError(RuntimeError):
    pass


class ProgramParamsStaleError(ProgramParamsError):
    def __init__(self, current_sha256: str):
        self.current_sha256 = current_sha256
        super().__init__("当前参数已被其他操作更新")


@dataclass(frozen=True)
class ProgramParamsDocument:
    document: dict
    sha256: str
    updated_at: datetime
    program_key: str
    source_type: str
    filename: str
    warnings: tuple[str, ...] = ()
    schema_version: str = ""

    def as_dict(self) -> dict:
        return {
            "document": self.document,
            "sha256": self.sha256,
            "updated_at": self.updated_at,
            "program_key": self.program_key,
            "source_type": self.source_type,
            "filename": self.filename,
            "warnings": list(self.warnings),
            "schema_version": self.schema_version,
        }


def _choice(program_key: str, source_type: str):
    spec = get_program(program_key)
    if program_key == DCR_3D or spec.parameter_mode != "source-structured":
        raise ProgramParamsError(f"程序 {program_key} 不支持源参数页面")
    try:
        return spec, spec.choice_by_source(source_type)
    except ValueError as exc:
        raise ProgramParamsError(str(exc)) from exc


def _read_document(path: Path, program_key: str, source_type: str) -> ProgramParamsDocument:
    try:
        payload = path.read_bytes()
        document = parse_parameter_bytes(program_key, source_type, payload)
        _, warnings = validate_parameter_with_warnings(program_key, source_type, document)
        stat = path.stat()
    except ParamValidationError:
        raise
    except OSError as exc:
        raise ProgramParamsError(f"无法读取 {path.name}：{exc}") from exc
    return ProgramParamsDocument(
        document=document,
        sha256=sha256_file(path),
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        program_key=program_key,
        source_type=source_type,
        filename=path.name,
        warnings=tuple(warnings),
        schema_version=schema_version_for(program_key),
    )


def get_current_document(user_id: int, program_key: str, source_type: str) -> ProgramParamsDocument:
    _, choice = _choice(program_key, source_type)
    path = canonical_program_param_path(user_id, program_key, choice.filename)
    if not path.is_file():
        raise ProgramParamsError(f"当前 {choice.filename} 尚未初始化")
    return _read_document(path, program_key, source_type)


def get_default_document(program_key: str, source_type: str) -> ProgramParamsDocument:
    _, choice = _choice(program_key, source_type)
    validate_program_template(program_key=program_key)
    return _read_document(
        program_template_dir(program_key) / choice.filename,
        program_key,
        source_type,
    )


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_pair_atomic(canonical: Path, runtime: Path, payload: bytes) -> None:
    token = uuid.uuid4().hex
    pairs: list[tuple[Path, Path, Path]] = []
    for destination in (canonical, runtime):
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.save-{token}")
        backup = destination.with_name(f".{destination.name}.backup-{token}")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        pairs.append((temporary, destination, backup))
    installed: set[Path] = set()
    try:
        for temporary, destination, backup in pairs:
            if destination.exists():
                os.replace(destination, backup)
            os.replace(temporary, destination)
            installed.add(destination)
    except Exception:
        for temporary, destination, backup in reversed(pairs):
            temporary.unlink(missing_ok=True)
            if backup.exists():
                destination.unlink(missing_ok=True)
                os.replace(backup, destination)
            elif destination in installed:
                destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _, backup in pairs:
            temporary.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)


def ensure_program_params_files(
    user_id: int,
    program_key: str,
    *,
    template_dir: Path | None = None,
) -> dict[str, ProgramParamsDocument]:
    """初始化两种源当前文件；已有未知格式不覆盖。调用方须持用户锁。"""
    spec = get_program(program_key)
    if spec.parameter_mode != "source-structured":
        raise ProgramParamsError(f"程序 {program_key} 不使用双源当前参数")
    validate_program_template(template_dir, program_key)
    values: dict[str, ProgramParamsDocument] = {}
    for choice in spec.source_choices:
        canonical = canonical_program_param_path(user_id, program_key, choice.filename)
        runtime = params_path(user_id, program_key, choice.filename)
        if canonical.is_file():
            current = _read_document(canonical, program_key, choice.source_type)
            if not runtime.is_file() or sha256_file(runtime) != current.sha256:
                _copy_atomic(canonical, runtime)
        elif runtime.is_file():
            current = _read_document(runtime, program_key, choice.source_type)
            _copy_atomic(runtime, canonical)
        else:
            default_path = program_template_dir(program_key, template_dir) / choice.filename
            current = _read_document(default_path, program_key, choice.source_type)
            _copy_atomic(default_path, canonical)
            _copy_atomic(default_path, runtime)
        values[choice.source_type] = current
    return values


def save_current_document(
    user_id: int,
    program_key: str,
    source_type: str,
    document: dict,
    *,
    expected_sha256: str,
) -> ProgramParamsDocument:
    _, choice = _choice(program_key, source_type)
    canonical = canonical_program_param_path(user_id, program_key, choice.filename)
    runtime = params_path(user_id, program_key, choice.filename)
    if not canonical.is_file():
        raise ProgramParamsError(f"当前 {choice.filename} 尚未初始化")
    current_hash = sha256_file(canonical)
    if expected_sha256.lower() != current_hash:
        raise ProgramParamsStaleError(current_hash)
    content = serialize_parameter(program_key, source_type, document)
    payload = content.encode("utf-8") if isinstance(content, str) else content
    _write_pair_atomic(canonical, runtime, payload)
    return get_current_document(user_id, program_key, source_type)


def snapshot_current_files(
    user_id: int,
    program_key: str,
    destination: Path,
) -> dict[str, ProgramParamsDocument]:
    """快照一个程序的两种源参数到 staging。调用方须持用户锁。"""
    spec = get_program(program_key)
    if spec.parameter_mode != "source-structured":
        raise ProgramParamsError(f"程序 {program_key} 不使用双源当前参数")
    result: dict[str, ProgramParamsDocument] = {}
    for choice in spec.source_choices:
        source = canonical_program_param_path(user_id, program_key, choice.filename)
        if not source.is_file():
            raise ProgramParamsError(f"当前 {choice.filename} 尚未初始化")
        target = destination / choice.filename
        _copy_atomic(source, target)
        result[choice.source_type] = _read_document(target, program_key, choice.source_type)
    return result


def restore_runtime_from_canonical(user_id: int, program_key: str) -> dict[str, ProgramParamsDocument]:
    """恢复一个程序的两种源工作副本。调用方须持用户锁。"""
    spec = get_program(program_key)
    values: dict[str, ProgramParamsDocument] = {}
    for choice in spec.source_choices:
        current = get_current_document(user_id, program_key, choice.source_type)
        runtime = params_path(user_id, program_key, choice.filename)
        _copy_atomic(canonical_program_param_path(user_id, program_key, choice.filename), runtime)
        if sha256_file(runtime) != current.sha256:
            raise ProgramParamsError(f"恢复工作目录 {choice.filename} 后 SHA-256 不一致")
        values[choice.source_type] = current
    return values
