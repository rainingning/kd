"""DCR 当前参数权威镜像、工作目录副本和任务快照操作。"""
from __future__ import annotations

import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..param_schema import (
    SCHEMA_VERSION,
    ParamValidationError,
    parse_params_bytes,
    serialize_params,
    validate_params_with_warnings,
)
from .program_template import program_template_dir, sha256_file, validate_program_template
from .programs import DCR_3D, DCR_PARAMS_FILE
from .storage import canonical_params_path, params_path


class DcrParamsError(RuntimeError):
    pass


class DcrParamsStaleError(DcrParamsError):
    def __init__(self, current_sha256: str):
        self.current_sha256 = current_sha256
        super().__init__("当前参数已被其他操作更新")


@dataclass(frozen=True)
class DcrParamsDocument:
    document: dict
    sha256: str
    updated_at: datetime
    warnings: tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> dict:
        return {
            "document": self.document,
            "sha256": self.sha256,
            "updated_at": self.updated_at,
            "warnings": list(self.warnings),
            "schema_version": self.schema_version,
        }


def _read_document(path: Path) -> DcrParamsDocument:
    try:
        content = path.read_bytes()
        document = parse_params_bytes(content)
        _, warnings = validate_params_with_warnings(document)
        stat = path.stat()
    except ParamValidationError:
        raise
    except OSError as exc:
        raise DcrParamsError(f"无法读取 {DCR_PARAMS_FILE}：{exc}") from exc
    return DcrParamsDocument(
        document=document,
        sha256=sha256_file(path),
        updated_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        warnings=tuple(warnings),
    )


def get_current_document(user_id: int) -> DcrParamsDocument:
    path = canonical_params_path(user_id)
    if not path.is_file():
        raise DcrParamsError("当前 DCR 参数尚未初始化")
    return _read_document(path)


def get_default_document() -> DcrParamsDocument:
    validate_program_template(program_key=DCR_3D)
    return _read_document(program_template_dir(DCR_3D) / DCR_PARAMS_FILE)


def _copy_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _write_pair_atomic(canonical: Path, runtime: Path, content: str) -> None:
    """尽力以文件组方式替换；第二步失败时回滚第一步。"""
    token = uuid.uuid4().hex
    payload = content.encode("utf-8")
    pairs = []
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


def ensure_dcr_params_files(user_id: int, *, template_dir: Path | None = None) -> DcrParamsDocument:
    """初始化权威镜像；已有未知/损坏参数绝不静默覆盖。调用方须持用户锁。"""
    canonical = canonical_params_path(user_id)
    runtime = params_path(user_id, DCR_3D)
    if canonical.is_file():
        current = _read_document(canonical)
        if not runtime.is_file() or sha256_file(runtime) != current.sha256:
            _copy_atomic(canonical, runtime)
        return current
    if runtime.is_file():
        current = _read_document(runtime)
        _copy_atomic(runtime, canonical)
        return current
    default_path = program_template_dir(DCR_3D, template_dir) / DCR_PARAMS_FILE
    validate_program_template(template_dir, DCR_3D)
    default = _read_document(default_path)
    _copy_atomic(default_path, canonical)
    _copy_atomic(default_path, runtime)
    return default


def save_current_document(
    user_id: int,
    document: dict,
    *,
    expected_sha256: str,
) -> DcrParamsDocument:
    """校验并同时替换权威镜像与 exe 目录副本。调用方须持用户锁。"""
    canonical = canonical_params_path(user_id)
    runtime = params_path(user_id, DCR_3D)
    if not canonical.is_file():
        raise DcrParamsError("当前 DCR 参数尚未初始化")
    current_hash = sha256_file(canonical)
    if expected_sha256.lower() != current_hash:
        raise DcrParamsStaleError(current_hash)
    content = serialize_params(document)
    _write_pair_atomic(canonical, runtime, content)
    return get_current_document(user_id)


def snapshot_current_to(user_id: int, destination: Path) -> DcrParamsDocument:
    """将当前权威参数原子复制到任务 staging；并以复制结果作为快照。"""
    canonical = canonical_params_path(user_id)
    if not canonical.is_file():
        raise DcrParamsError("当前 DCR 参数尚未初始化")
    _copy_atomic(canonical, destination)
    return _read_document(destination)


def restore_runtime_from_canonical(user_id: int) -> DcrParamsDocument:
    """任务终止后恢复 exe 目录当前参数。调用方须持用户锁。"""
    current = get_current_document(user_id)
    runtime = params_path(user_id, DCR_3D)
    _copy_atomic(canonical_params_path(user_id), runtime)
    if sha256_file(runtime) != current.sha256:
        raise DcrParamsError("恢复工作目录 model_DC.dat 后 SHA-256 不一致")
    return current
