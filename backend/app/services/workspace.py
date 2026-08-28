"""用户多程序固定工作区创建、自检、程序同步和任务准备。"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from .program_template import (
    ProgramManifest,
    ProgramTemplateError,
    program_template_dir,
    sha256_file,
    validate_all_program_templates,
    validate_program_template,
)
from .programs import DCR_3D, PROGRAM_DLL, get_program, list_programs
from .storage import (
    ARCHIVES_DIR,
    STAGING_DIR,
    archives_root,
    mesh_dir,
    mesh_path,
    params_path,
    program_dll_path,
    program_exe_path,
    program_root,
    programs_root,
    result_dir,
    staging_root,
    user_root,
)

logger = logging.getLogger(__name__)


class WorkspaceError(RuntimeError):
    pass


class ManifestBundle(dict[str, ProgramManifest]):
    """三程序清单集合；兼容旧代码读取 DCR 的标量属性。"""

    def __getattr__(self, name: str):
        dcr = self[DCR_3D]
        try:
            return getattr(dcr, name)
        except AttributeError as exc:
            raise AttributeError(name) from exc


@dataclass(frozen=True)
class WorkspaceCheck:
    ready: bool
    errors: tuple[str, ...]
    program_key: str = DCR_3D
    program_version: str | None = None
    exe_sha256: str | None = None
    dll_sha256: str | None = None
    runtime_file_hashes: dict[str, str] = field(default_factory=dict)


def _atomic_copy(source: Path, destination: Path, expected_sha256: str | None = None) -> None:
    if not source.is_file():
        raise WorkspaceError(f"源文件不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        if expected_sha256 is not None and sha256_file(temporary) != expected_sha256:
            raise WorkspaceError(f"复制后的 {destination.name} SHA-256 不一致")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def sync_program_files(
    user_id: int,
    *,
    program_key: str = DCR_3D,
    template_dir: Path | None = None,
    manifest: ProgramManifest | None = None,
) -> ProgramManifest:
    """原子替换一个程序的完整运行文件组；失败恢复旧文件。"""
    spec = get_program(program_key)
    manifest = manifest or validate_program_template(template_dir, program_key)
    source_root = program_template_dir(program_key, template_dir)
    target = program_root(user_id, program_key)
    target.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    files = [spec.executable, PROGRAM_DLL]
    if spec.parameter_mode == "upload":
        files.extend(spec.parameter_files)
    pairs = [
        (source_root / filename, target / filename, manifest.runtime_file_hashes[filename])
        for filename in files
    ]
    staged: list[tuple[Path, Path, Path]] = []
    installed: set[Path] = set()
    try:
        for source, destination, expected in pairs:
            temporary = target / f".{destination.name}.sync-{token}"
            backup = target / f".{destination.name}.backup-{token}"
            shutil.copy2(source, temporary)
            if sha256_file(temporary) != expected:
                raise WorkspaceError(f"复制后的 {destination.name} SHA-256 不一致")
            staged.append((temporary, destination, backup))
        for temporary, destination, backup in staged:
            if destination.exists():
                os.replace(destination, backup)
            os.replace(temporary, destination)
            installed.add(destination)
    except Exception:
        for temporary, destination, backup in reversed(staged):
            temporary.unlink(missing_ok=True)
            if backup.exists():
                destination.unlink(missing_ok=True)
                os.replace(backup, destination)
            elif destination in installed:
                destination.unlink(missing_ok=True)
        raise
    finally:
        for temporary, _, backup in staged:
            temporary.unlink(missing_ok=True)
            backup.unlink(missing_ok=True)
    return manifest


def initialize_workspace(
    user_id: int,
    *,
    template_dir: Path | None = None,
) -> dict[str, ProgramManifest]:
    """幂等初始化用户的三个程序目录；新用户失败时补偿删除。"""
    root = user_root(user_id)
    created_root = not root.exists()
    try:
        root.mkdir(parents=True, exist_ok=True)
        programs_root(user_id).mkdir(parents=True, exist_ok=True)
        staging_root(user_id).mkdir(parents=True, exist_ok=True)
        archives_root(user_id).mkdir(parents=True, exist_ok=True)
        manifests = ManifestBundle(validate_all_program_templates(template_dir))
        for spec in list_programs():
            mesh_dir(user_id, spec.key).mkdir(parents=True, exist_ok=True)
            result_dir(user_id, spec.key).mkdir(parents=True, exist_ok=True)
            sync_program_files(
                user_id, program_key=spec.key, template_dir=template_dir,
                manifest=manifests[spec.key])
        logger.info("用户 #%s 多程序工作区初始化完成：root=%s", user_id, root)
        return manifests
    except (OSError, ProgramTemplateError, WorkspaceError) as exc:
        if created_root:
            shutil.rmtree(root, ignore_errors=True)
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError(f"用户工作区初始化失败：{exc}") from exc


def check_workspace(
    user_id: int,
    *,
    program_key: str = DCR_3D,
    expected_version: str | None = None,
    expected_exe_sha256: str | None = None,
    expected_dll_sha256: str | None = None,
    expected_runtime_file_hashes: dict[str, str] | None = None,
) -> WorkspaceCheck:
    spec = get_program(program_key)
    root = program_root(user_id, program_key)
    errors: list[str] = []
    writable_directories = [root, mesh_dir(user_id, program_key), result_dir(user_id, program_key)]
    for directory in writable_directories:
        if not directory.is_dir():
            errors.append(f"缺少目录：{directory}")
            continue
        probe = directory / f".workspace-check-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"")
        except OSError as exc:
            errors.append(f"目录不可写：{directory}：{exc}")
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"检查临时文件无法删除：{probe}：{exc}")

    exe = program_exe_path(user_id, program_key)
    dll = program_dll_path(user_id, program_key)
    actual: dict[str, str] = {}
    for path in (exe, dll):
        if path.is_file():
            actual[path.name] = sha256_file(path)
        else:
            errors.append(f"缺少文件：{path.name}")
    for filename in spec.parameter_files if spec.parameter_mode == "upload" else ():
        path = params_path(user_id, program_key, filename)
        if path.is_file():
            actual[filename] = sha256_file(path)
        else:
            errors.append(f"缺少文件：{filename}")

    if expected_exe_sha256 and actual.get(spec.executable) != expected_exe_sha256:
        errors.append(f"{spec.executable} SHA-256 不一致")
    if expected_dll_sha256 and actual.get(PROGRAM_DLL) != expected_dll_sha256:
        errors.append(f"{PROGRAM_DLL} SHA-256 不一致")
    for filename, expected in (expected_runtime_file_hashes or {}).items():
        if actual.get(filename) != expected:
            errors.append(f"{filename} SHA-256 不一致")

    result = WorkspaceCheck(
        ready=not errors,
        errors=tuple(errors),
        program_key=program_key,
        program_version=expected_version,
        exe_sha256=actual.get(spec.executable),
        dll_sha256=actual.get(PROGRAM_DLL),
        runtime_file_hashes=actual,
    )
    if not result.ready:
        logger.warning("用户 #%s/%s 工作区检查失败：%s", user_id, program_key, "；".join(errors))
    return result


def check_all_workspaces(user_id: int) -> dict[str, WorkspaceCheck]:
    return {spec.key: check_workspace(user_id, program_key=spec.key) for spec in list_programs()}


def prepare_task_workspace(
    user_id: int,
    staging: Path,
    *,
    program_key: str = DCR_3D,
    expected_exe_sha256: str,
    expected_dll_sha256: str,
) -> dict[str, str]:
    """覆盖选中程序输入并重建空结果目录，返回实际参数文件 hashes。"""
    spec = get_program(program_key)
    check = check_workspace(
        user_id, program_key=program_key,
        expected_exe_sha256=expected_exe_sha256,
        expected_dll_sha256=expected_dll_sha256,
    )
    if not check.ready:
        raise WorkspaceError("；".join(check.errors))
    staged_mesh = staging / "mesh.mphtxt"
    if not staged_mesh.is_file():
        raise WorkspaceError("任务暂存区缺少 mesh.mphtxt")
    for filename in spec.parameter_files:
        source = staging / filename
        if not source.is_file():
            raise WorkspaceError(f"任务暂存区缺少 {filename}")
        _atomic_copy(source, params_path(user_id, program_key, filename))
    _atomic_copy(staged_mesh, mesh_path(user_id, program_key))

    output = result_dir(user_id, program_key)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=False)
    return {
        filename: sha256_file(params_path(user_id, program_key, filename))
        for filename in spec.parameter_files
    }


def remove_workspace(user_id: int) -> None:
    root = user_root(user_id)
    if root.exists():
        shutil.rmtree(root)
