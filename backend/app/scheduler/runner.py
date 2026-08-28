"""固定用户工作区执行器：无参数启动、终态归档与中断恢复。"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import psutil
from sqlalchemy import select

from .. import db
from ..config import settings
from ..em_param_schema import ParamValidationError as EmParamValidationError
from ..models import (
    ArchiveStatus,
    NotificationType,
    Task,
    TaskStatus,
    User,
    UserProgram,
    WorkspaceStatus,
    utcnow,
)
from ..services.archive import (
    ArchiveError, archive_task_files, archive_version, remove_temporary_archives,
)
from ..services.config import get_float, get_int
from ..services.dcr_params import DcrParamsError, restore_runtime_from_canonical
from ..services.program_params import (
    ProgramParamsError,
    restore_runtime_from_canonical as restore_source_runtime_from_canonical,
)
from ..services.notifications import notify
from ..services.program_sync import sync_program_for_locked_user
from ..services.program_template import ProgramTemplateError, validate_program_template
from ..services.programs import DCR_3D, get_program, list_programs
from ..services.staging import remove_staging
from ..services.storage import (
    STDERR_FILE, path_from_relative, program_exe_path, program_root, user_root,
)
from ..services.workspace import WorkspaceError, prepare_task_workspace
from . import state
from .state import RunningEntry
from .user_lock import try_user_workspace_lock

logger = logging.getLogger(__name__)


def _split_configured_command(command: str) -> list[str]:
    """解析仅含普通参数和双引号路径的 Windows 命令，不经过 shell。"""
    if command.count('"') % 2:
        raise ValueError("Mock 命令包含未闭合的双引号")
    tokens = [quoted or bare for quoted, bare in re.findall(r'"([^"\\]*(?:\\.[^"\\]*)*)"|(\S+)', command)]
    if not tokens:
        raise ValueError("Mock 命令为空")
    return tokens


def build_argv(user_id: int, program_key: str = DCR_3D) -> list[str]:
    """构造无额外参数命令；正式模式只传所选用户程序 exe。"""
    mode = settings.execution_mode.strip().lower()
    if mode in {"dcr3d", "formal"}:
        return [str(program_exe_path(user_id, program_key))]
    if mode == "mock":
        command = getattr(settings, "mock_fortran_command", settings.mock_dcr3d_command)
        return _split_configured_command(command)
    raise ValueError(f"不支持的 EXECUTION_MODE：{settings.execution_mode}")


def terminate_orphan_processes(user_id: int) -> int:
    """终止仍绑定到该用户任一程序目录的正式或 Mock 进程。"""
    expected_roots = {
        program_root(user_id, spec.key).resolve() for spec in list_programs()
    }
    expected_exes = {
        program_exe_path(user_id, spec.key).resolve() for spec in list_programs()
    }
    mock_names = {"mock_dcr3d.py", "mock_fortran_solver.py"}
    matches: list[psutil.Process] = []
    for process in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            exe_value = process.info.get("exe")
            executable_matches = bool(
                exe_value and Path(exe_value).resolve() in expected_exes)
            command = [str(value) for value in (process.info.get("cmdline") or [])]
            mock_matches = any(Path(value).name.lower() in mock_names for value in command)
            if not executable_matches and not mock_matches:
                continue
            try:
                cwd_matches = Path(process.cwd()).resolve() in expected_roots
            except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
                cwd_matches = executable_matches
            if cwd_matches:
                process.terminate()
                matches.append(process)
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            continue
    _, alive = psutil.wait_procs(matches, timeout=5)
    for process in alive:
        try:
            process.kill()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass
    if alive:
        psutil.wait_procs(alive, timeout=5)
    return len(matches)


def _kill_process_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        processes = parent.children(recursive=True)
        processes.reverse()
        processes.append(parent)
        for process in processes:
            try:
                process.kill()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                pass
        psutil.wait_procs(processes, timeout=5)
    except psutil.NoSuchProcess:
        pass


def request_cancel(task_id: int, kind: str) -> bool:
    """记录取消请求，并在进程已注册时立即终止。"""
    state.cancel_requests[task_id] = kind
    entry = state.running.get(task_id)
    if entry is None or entry.proc.returncode is not None:
        return True
    entry.cancel_kind = kind
    _kill_process_tree(entry.proc.pid)
    return True


def _append_failure_log(staging: Path, reason: str) -> None:
    if not staging.is_dir():
        return
    stderr = staging / STDERR_FILE
    # Fortran 的原始 stderr 编码未知；已有内容时禁止追加 UTF-8 造成混合编码。
    if stderr.is_file() and stderr.stat().st_size:
        return
    stderr.write_text(f"[platform] {reason}\n", encoding="utf-8", newline="\n")


def _schedule_archive_retry(task: Task) -> None:
    task.archive_retry_count = (task.archive_retry_count or 0) + 1
    delay_seconds = min(5 * (2 ** (task.archive_retry_count - 1)), 300)
    task.archive_retry_at = utcnow() + timedelta(seconds=delay_seconds)


def _notification_for(final_status: str, reason: str | None) -> tuple[str, str] | None:
    if final_status == TaskStatus.COMPLETED:
        return NotificationType.COMPLETED, "已完成"
    if final_status == TaskStatus.FAILED:
        if reason == "被管理员终止":
            return NotificationType.KILLED, "已被管理员终止"
        return NotificationType.FAILED, f"失败：{reason or '未知错误'}"
    return None


async def finalize_task(
    task_id: int,
    *,
    final_status: str,
    reason: str | None,
    workspace_was_used: bool,
    exit_code: int | None = None,
) -> bool:
    """先持久化 ARCHIVING，再原子归档，最后落业务终态并通知。"""
    async with db.async_session() as session:
        task = await session.get(Task, task_id)
        if task is None:
            return False
        try:
            staging = path_from_relative(task.staging_dir)
        except ValueError as exc:
            task.status = TaskStatus.ARCHIVE_FAILED
            task.archive_status = ArchiveStatus.FAILED
            task.archive_error = str(exc)
            _schedule_archive_retry(task)
            await session.commit()
            return False

        if final_status == TaskStatus.FAILED and reason:
            try:
                await asyncio.to_thread(_append_failure_log, staging, reason)
            except OSError:
                logger.exception("任务 #%s 写入平台失败日志失败", task_id)

        finished = utcnow()
        task.status = TaskStatus.ARCHIVING
        task.archive_status = ArchiveStatus.ARCHIVING
        task.terminal_status = final_status
        task.archive_error = None
        task.archive_version = task.archive_version or archive_version(task.id)
        task.workspace_was_used = workspace_was_used
        task.exit_code = exit_code
        task.error_message = reason
        logger.info(
            "任务 #%s 开始归档：target=%s version=%s workspace_used=%s",
            task.id, final_status, task.archive_version, workspace_was_used,
        )
        if task.started_at is not None:
            task.duration_sec = Decimal(
                f"{(finished - task.started_at).total_seconds():.3f}")
        await session.commit()

        metadata = {
            "task_id": task.id,
            "user_id": task.user_id,
            "program_key": task.program_key,
            "source_type": task.source_type,
            "stdin_choice": task.stdin_choice,
            "parameter_filename": task.parameter_filename,
            "parameter_original_filename": task.parameter_original_filename,
            "parameter_sha256": task.parameter_sha256,
            "original_input_filename": task.input_filename,
            "params": task.params,
            "parameter_schema_version": task.parameter_schema_version,
            "status": final_status,
            "reason": reason,
            "exit_code": exit_code,
            "queued_at": task.queued_at.isoformat() if task.queued_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "finished_at": finished.isoformat(),
            "duration_sec": float(task.duration_sec) if task.duration_sec is not None else None,
            "program_version": task.program_version,
            "exe_sha256": task.exe_sha256,
            "dll_sha256": task.dll_sha256,
        }
        try:
            archived = await asyncio.to_thread(
                archive_task_files,
                user_id=task.user_id,
                task_id=task.id,
                program_key=task.program_key,
                staging=staging,
                metadata=metadata,
                workspace_was_used=workspace_was_used,
                version=task.archive_version,
            )
        except ArchiveError as exc:
            logger.exception("任务 #%s 归档失败", task.id)
            task.status = TaskStatus.ARCHIVE_FAILED
            task.archive_status = ArchiveStatus.FAILED
            task.archive_error = str(exc)
            _schedule_archive_retry(task)
            await session.commit()
            return False

        task.status = final_status
        task.archive_status = ArchiveStatus.COMPLETED
        task.archive_error = None
        task.archive_retry_at = None
        task.archive_version = archived.version
        task.archive_dir = archived.relative_dir
        task.archived_at = archived.archived_at
        task.result_file_count = archived.result_file_count
        task.result_size_bytes = archived.result_size_bytes
        task.runtime_file_hashes = archived.runtime_file_hashes
        task.finished_at = finished
        notification = _notification_for(final_status, reason)
        if notification is not None:
            kind, message = notification
            notify(session, task, kind, f"任务 #{task.id} {message}")
        await session.commit()
        logger.info(
            "任务 #%s 归档成功：status=%s archive=%s files=%s bytes=%s",
            task.id, final_status, archived.relative_dir,
            archived.result_file_count, archived.result_size_bytes,
        )

    try:
        await asyncio.to_thread(remove_staging, staging)
    except OSError:
        # 正式归档和数据库索引已完成；残留 staging 交由清理任务处理。
        logger.exception("任务 #%s 暂存目录清理失败", task_id)
    return True


async def _restore_program_current(
    user_id: int,
    program_key: str,
    task_id: int,
) -> str | None:
    """调用方持有用户锁；恢复程序当前参数，失败时阻断工作区。"""
    try:
        if program_key == DCR_3D:
            await asyncio.to_thread(restore_runtime_from_canonical, user_id)
        elif get_program(program_key).parameter_mode == "source-structured":
            await asyncio.to_thread(
                restore_source_runtime_from_canonical, user_id, program_key)
        return None
    except (
        DcrParamsError, ProgramParamsError, EmParamValidationError, OSError, ValueError,
    ) as exc:
        message = f"恢复 {get_program(program_key).display_name} 当前参数失败：{exc}"
        logger.exception("任务 #%s %s", task_id, message)
        async with db.async_session() as session:
            user = await session.get(User, user_id)
            installation = await session.scalar(select(UserProgram).where(
                UserProgram.user_id == user_id,
                UserProgram.program_key == program_key,
            ))
            if user is not None:
                user.workspace_status = WorkspaceStatus.ERROR
                user.workspace_error = message
            if installation is not None:
                installation.workspace_status = WorkspaceStatus.ERROR
                installation.workspace_error = message
            await session.commit()
        return message


async def _prepare(task_id: int) -> tuple[int, Path, str, int | None] | None:
    """准备所选程序固定工作区并将任务推进到 RUNNING。"""
    async with db.async_session() as session:
        task = await session.get(Task, task_id)
        if task is None or task.status != TaskStatus.PREPARING:
            return None
        user = await session.get(User, task.user_id)
        installation = await session.scalar(select(UserProgram).where(
            UserProgram.user_id == task.user_id,
            UserProgram.program_key == task.program_key,
        ))
        if user is None or installation is None:
            await finalize_task(
                task_id, final_status=TaskStatus.FAILED,
                reason="用户或程序安装记录不存在", workspace_was_used=False)
            return None
        try:
            staging = path_from_relative(task.staging_dir)
            if not installation.exe_sha256 or not installation.dll_sha256:
                raise WorkspaceError("用户程序版本或 SHA-256 未初始化")
            runtime_hashes = await asyncio.to_thread(
                prepare_task_workspace,
                user.id,
                staging,
                program_key=task.program_key,
                expected_exe_sha256=installation.exe_sha256,
                expected_dll_sha256=installation.dll_sha256,
            )
        except (OSError, ValueError, WorkspaceError) as exc:
            await session.rollback()
            if get_program(task.program_key).uses_current_params:
                await _restore_program_current(task.user_id, task.program_key, task.id)
            await finalize_task(
                task_id, final_status=TaskStatus.FAILED,
                reason=f"工作区准备失败：{exc}", workspace_was_used=False)
            return None

        task.program_version = installation.program_version
        task.exe_sha256 = installation.exe_sha256
        task.dll_sha256 = installation.dll_sha256
        task.runtime_file_hashes = runtime_hashes
        task.workspace_was_used = True
        task.status = TaskStatus.RUNNING
        await session.commit()
        logger.info(
            "任务 #%s 工作区准备完成：user=%s program=%s version=%s",
            task.id, task.user_id, task.program_key, task.program_version,
        )
        return task.user_id, staging, task.program_key, task.stdin_choice


async def run_task(task_id: int) -> None:
    async with db.async_session() as session:
        task = await session.get(Task, task_id)
        if task is None or task.status != TaskStatus.PREPARING:
            return
        user_id = task.user_id
        program_key = task.program_key

    async with try_user_workspace_lock(user_id) as acquired:
        if not acquired:
            # 程序同步或另一个 worker 先取得锁；放回队列等待下次调度。
            async with db.async_session() as session:
                task = await session.get(Task, task_id)
                if task is not None and task.status == TaskStatus.PREPARING:
                    task.status = TaskStatus.QUEUED
                    task.started_at = None
                    await session.commit()
            return

        try:
            await asyncio.to_thread(remove_temporary_archives, user_id)
        except OSError as exc:
            await finalize_task(
                task_id,
                final_status=TaskStatus.FAILED,
                reason=f"临时归档现场清理失败：{exc}",
                workspace_was_used=False,
            )
            return

        try:
            await asyncio.to_thread(
                validate_program_template, program_key=program_key)
        except ProgramTemplateError as exc:
            logger.error("任务 #%s 启动前程序模板校验失败：%s", task_id, exc)
            await finalize_task(
                task_id,
                final_status=TaskStatus.FAILED,
                reason=f"程序模板不可用：{exc}",
                workspace_was_used=False,
            )
            return

        async with db.async_session() as session:
            min_free_mb = await get_int(session, "min_free_disk_mb")
        free_bytes = await asyncio.to_thread(
            lambda: shutil.disk_usage(settings.storage_root).free)
        if free_bytes < min_free_mb * 1024 * 1024:
            reason = (
                f"磁盘剩余空间不足：{free_bytes / 1024 / 1024:.0f} MB，"
                f"安全阈值为 {min_free_mb} MB"
            )
            logger.error("任务 #%s %s", task_id, reason)
            await finalize_task(
                task_id,
                final_status=TaskStatus.FAILED,
                reason=reason,
                workspace_was_used=False,
            )
            return

        async with db.async_session() as session:
            user = await session.get(User, user_id)
            installation = await session.scalar(select(UserProgram).where(
                UserProgram.user_id == user_id,
                UserProgram.program_key == program_key,
            ))
            sync_pending = bool(
                (user and user.program_sync_pending)
                or (installation and installation.program_sync_pending)
            )
        if sync_pending:
            sync_result = await sync_program_for_locked_user(user_id)
            if sync_result.status != "synced":
                await finalize_task(
                    task_id,
                    final_status=TaskStatus.FAILED,
                    reason=f"程序同步失败：{sync_result.error or sync_result.status}",
                    workspace_was_used=False,
                )
                return

        prepared = await _prepare(task_id)
        if prepared is None:
            return
        user_id, staging, program_key, stdin_choice = prepared
        timeout_sec: float
        async with db.async_session() as session:
            timeout_sec = (await get_float(session, "task_timeout_minutes")) * 60

        pending_kind = state.cancel_requests.pop(task_id, None)
        entry: RunningEntry | None = None
        timed_out = False
        start_error: str | None = None
        returncode: int | None = None

        if pending_kind is None:
            spec = get_program(program_key)
            cwd = program_root(user_id, program_key)
            argv = build_argv(user_id, program_key)
            input_bytes = (
                f"{stdin_choice}\n".encode("ascii")
                if spec.requires_stdin else None
            )
            env = os.environ.copy()
            env["GFORTRAN_UNBUFFERED_ALL"] = "1"
            env["FORT_BUFFERED"] = "0"
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            with (staging / "stdout.txt").open("wb") as out_f, \
                    (staging / "stderr.txt").open("wb") as err_f:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *argv,
                        cwd=str(cwd),
                        stdin=(asyncio.subprocess.PIPE if spec.requires_stdin
                               else asyncio.subprocess.DEVNULL),
                        stdout=out_f,
                        stderr=err_f,
                        env=env,
                        creationflags=creationflags,
                    )
                except Exception as exc:
                    logger.exception("任务 #%s 启动失败", task_id)
                    start_error = f"任务启动失败：{exc}"
                else:
                    logger.info(
                        "任务 #%s 进程已启动：pid=%s program=%s cwd=%s argv=%s stdin_choice=%s",
                        task_id, proc.pid, program_key, cwd, argv, stdin_choice,
                    )
                    entry = RunningEntry(proc=proc)
                    state.running[task_id] = entry
                    raced_cancel = state.cancel_requests.pop(task_id, None)
                    if raced_cancel is not None:
                        entry.cancel_kind = raced_cancel
                        _kill_process_tree(proc.pid)
                    try:
                        await asyncio.wait_for(
                            proc.communicate(input=input_bytes), timeout=timeout_sec)
                        returncode = proc.returncode
                    except asyncio.TimeoutError:
                        timed_out = True
                        _kill_process_tree(proc.pid)
                        try:
                            await proc.communicate()
                        except (BrokenPipeError, ConnectionResetError):
                            await proc.wait()
                        returncode = proc.returncode
                    except (BrokenPipeError, ConnectionResetError) as exc:
                        await proc.wait()
                        returncode = proc.returncode
                        start_error = f"向程序标准输入写入参数选择失败：{exc}"
                    finally:
                        state.running.pop(task_id, None)
                        state.cancel_requests.pop(task_id, None)
                        logger.info(
                            "任务 #%s 进程退出：pid=%s exit_code=%s timeout=%s",
                            task_id, proc.pid, proc.returncode, timed_out,
                        )
        else:
            # 进程注册前收到取消请求，不再启动程序。
            entry = None

        if get_program(program_key).uses_current_params:
            restore_error = await _restore_program_current(user_id, program_key, task_id)
            if restore_error is not None:
                start_error = restore_error

        if state.shutting_down:
            return  # 保持 RUNNING，下一次启动保护并归档工作区现场。

        cancel_kind = pending_kind or (entry.cancel_kind if entry is not None else None)
        if cancel_kind == "user":
            final_status, reason = TaskStatus.CANCELED, "用户取消"
        elif cancel_kind == "admin":
            final_status, reason = TaskStatus.FAILED, "被管理员终止"
        elif start_error is not None:
            final_status, reason = TaskStatus.FAILED, start_error
        elif timed_out:
            final_status = TaskStatus.FAILED
            reason = f"运行超时（超过 {timeout_sec / 60:g} 分钟）"
        elif returncode == 0:
            final_status, reason = TaskStatus.COMPLETED, None
        else:
            final_status = TaskStatus.FAILED
            reason = f"程序异常退出（退出码 {returncode}）"

        await finalize_task(
            task_id,
            final_status=final_status,
            reason=reason,
            workspace_was_used=True,
            exit_code=returncode,
        )


async def recover_task(task_id: int) -> None:
    """恢复 PREPARING/RUNNING/ARCHIVING/ARCHIVE_FAILED 任务。"""
    async with db.async_session() as session:
        task = await session.get(Task, task_id)
        if task is None or task.status not in (
            TaskStatus.PREPARING,
            TaskStatus.RUNNING,
            TaskStatus.ARCHIVING,
            TaskStatus.ARCHIVE_FAILED,
        ):
            return
        user_id = task.user_id
        status_before = task.status
        final_status = task.terminal_status or TaskStatus.FAILED
        reason = task.error_message
        exit_code = task.exit_code

    async with try_user_workspace_lock(user_id) as acquired:
        if not acquired:
            logger.warning("任务 #%s 恢复时用户锁忙，留待下次重试", task_id)
            return
        try:
            await asyncio.to_thread(remove_temporary_archives, user_id)
        except OSError:
            logger.exception("恢复任务 #%s 时清理临时归档失败", task_id)
        terminated = await asyncio.to_thread(terminate_orphan_processes, user_id)
        if terminated:
            logger.warning("恢复任务 #%s 前终止了 %d 个孤儿计算进程", task_id, terminated)
        if status_before == TaskStatus.PREPARING:
            final_status = TaskStatus.FAILED
            reason = "服务重启中断（工作区准备阶段）"
            workspace_was_used = False
        elif status_before == TaskStatus.RUNNING:
            final_status = TaskStatus.FAILED
            reason = "服务重启中断"
            workspace_was_used = True
        else:
            workspace_was_used = task.workspace_was_used
        if get_program(task.program_key).uses_current_params and workspace_was_used:
            restore_error = await _restore_program_current(user_id, task.program_key, task_id)
            if restore_error is not None:
                final_status = TaskStatus.FAILED
                reason = restore_error if not reason else f"{reason}；{restore_error}"
        await finalize_task(
            task_id,
            final_status=final_status,
            reason=reason,
            workspace_was_used=workspace_was_used,
            exit_code=exit_code,
        )
