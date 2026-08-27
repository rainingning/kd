"""用户固定工作区创建、自检、程序同步和删除。"""
from __future__ import annotations

import logging
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .program_template import ProgramManifest, ProgramTemplateError, sha256_file, validate_program_template
from .storage import (
    ARCHIVES_DIR,
    MESH_DIR,
    MESH_FILE,
    PARAMS_FILE,
    PROGRAM_DLL,
    PROGRAM_EXE,
    RESULT_DIR,
    STAGING_DIR,
    archives_root,
    mesh_dir,
    mesh_path,
    params_path,
    result_dir,
    staging_root,
    user_root,
)

logger = logging.getLogger(__name__)


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkspaceCheck:
    ready: bool
    errors: tuple[str, ...]
    program_version: str | None = None
    exe_sha256: str | None = None
    dll_sha256: str | None = None


def _atomic_copy(
    source: Path,
    destination: Path,
    expected_sha256: str | None = None,
) -> None:
    if not source.is_file():
        raise WorkspaceError(f"源文件不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        if expected_sha256 is not None:
            actual = sha256_file(temporary)
            if actual != expected_sha256:
                raise WorkspaceError(
                    f"复制后的 {destination.name} SHA-256 不一致")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def sync_program_files(
    user_id: int,
    *,
    template_dir: Path | None = None,
    manifest: ProgramManifest | None = None,
) -> ProgramManifest:
    """先校验两个临时文件，再成对替换；任一替换失败则恢复旧版本。"""
    root = (template_dir or settings.fortran_program_template_dir).resolve()
    manifest = manifest or validate_program_template(root)
    target = user_root(user_id)
    target.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    pairs = [
        (root / manifest.exe, target / PROGRAM_EXE, manifest.exe_sha256),
        (root / manifest.dll, target / PROGRAM_DLL, manifest.dll_sha256),
    ]
    staged: list[tuple[Path, Path, Path]] = []  # temporary, destination, backup
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
        # 逆序恢复，确保不会留下 exe/dll 混合版本。
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
) -> ProgramManifest:
    """幂等初始化用户目录。新目录失败时执行补偿删除。"""
    root = user_root(user_id)
    created_root = not root.exists()
    try:
        root.mkdir(parents=True, exist_ok=True)
        for directory in (
            mesh_dir(user_id),
            result_dir(user_id),
            staging_root(user_id),
            archives_root(user_id),
        ):
            directory.mkdir(parents=True, exist_ok=True)
        manifest = sync_program_files(user_id, template_dir=template_dir)
        logger.info(
            "用户 #%s 工作区初始化完成：root=%s version=%s exe=%s dll=%s",
            user_id, root, manifest.version, manifest.exe_sha256, manifest.dll_sha256,
        )
        return manifest
    except (OSError, ProgramTemplateError, WorkspaceError) as exc:
        if created_root:
            shutil.rmtree(root, ignore_errors=True)
        if isinstance(exc, WorkspaceError):
            raise
        raise WorkspaceError(f"用户工作区初始化失败：{exc}") from exc


def check_workspace(
    user_id: int,
    *,
    expected_version: str | None = None,
    expected_exe_sha256: str | None = None,
    expected_dll_sha256: str | None = None,
) -> WorkspaceCheck:
    root = user_root(user_id)
    errors: list[str] = []
    writable_directories = [root]
    for name in (MESH_DIR, RESULT_DIR, STAGING_DIR, ARCHIVES_DIR):
        directory = root / name
        if not directory.is_dir():
            errors.append(f"缺少目录：{name}")
        else:
            writable_directories.append(directory)

    for directory in writable_directories:
        probe = directory / f".workspace-check-{uuid.uuid4().hex}"
        try:
            probe.write_bytes(b"")
        except OSError as exc:
            errors.append(f"目录不可写：{directory.name or directory}：{exc}")
        finally:
            try:
                probe.unlink(missing_ok=True)
            except OSError as exc:
                errors.append(f"工作区检查临时文件无法删除：{probe}：{exc}")

    archive_root = root / ARCHIVES_DIR
    if archive_root.is_dir():
        temporary_archives = list(archive_root.glob(".tmp_*"))
        if temporary_archives:
            errors.append(f"存在 {len(temporary_archives)} 个临时归档残留")

    exe = root / PROGRAM_EXE
    dll = root / PROGRAM_DLL
    actual_exe = sha256_file(exe) if exe.is_file() else None
    actual_dll = sha256_file(dll) if dll.is_file() else None
    if actual_exe is None:
        errors.append(f"缺少文件：{PROGRAM_EXE}")
    if actual_dll is None:
        errors.append(f"缺少文件：{PROGRAM_DLL}")
    if expected_exe_sha256 and actual_exe != expected_exe_sha256:
        errors.append(f"{PROGRAM_EXE} SHA-256 不一致")
    if expected_dll_sha256 and actual_dll != expected_dll_sha256:
        errors.append(f"{PROGRAM_DLL} SHA-256 不一致")

    result = WorkspaceCheck(
        ready=not errors,
        errors=tuple(errors),
        program_version=expected_version,
        exe_sha256=actual_exe,
        dll_sha256=actual_dll,
    )
    if result.ready:
        logger.info("用户 #%s 工作区检查通过", user_id)
    else:
        logger.warning("用户 #%s 工作区检查失败：%s", user_id, "；".join(result.errors))
    return result


def prepare_task_workspace(
    user_id: int,
    staging: Path,
    *,
    expected_exe_sha256: str,
    expected_dll_sha256: str,
) -> None:
    """将任务暂存输入原子覆盖到固定工作区，并重建空结果目录。"""
    check = check_workspace(
        user_id,
        expected_exe_sha256=expected_exe_sha256,
        expected_dll_sha256=expected_dll_sha256,
    )
    if not check.ready:
        raise WorkspaceError("；".join(check.errors))

    staged_params = staging / PARAMS_FILE
    staged_mesh = staging / MESH_FILE
    if not staged_params.is_file() or not staged_mesh.is_file():
        raise WorkspaceError("任务暂存区缺少 model_DC.dat 或 mesh.mphtxt")

    _atomic_copy(staged_params, params_path(user_id))
    _atomic_copy(staged_mesh, mesh_path(user_id))

    output = result_dir(user_id)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True, exist_ok=False)


def remove_workspace(user_id: int) -> None:
    """删除用户根目录；失败必须抛出，禁止静默丢失索引。"""
    root = user_root(user_id)
    if root.exists():
        shutil.rmtree(root)
