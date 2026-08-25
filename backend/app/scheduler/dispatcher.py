"""FIFO 调度器（T4.2）与服务重启恢复（T4.5，FR-QUEUE-09）。

调度规则：
- 全局占用槽位数 < max_concurrent_tasks
- 同一用户固定工作区任何时刻只能被一个任务占用
- 等待队列按 queued_at FIFO；用户忙时跳过并继续选择其他用户
"""
import asyncio
import logging

from sqlalchemy import func, or_, select

from .. import db
from ..models import (
    ACTIVE_WORKSPACE_STATUSES, ArchiveStatus, Task, TaskStatus, User, utcnow,
)
from ..services.config import get_int
from ..services.program_sync import sync_pending_users_once
from . import state
from .runner import (
    _kill_process_tree, finalize_task, recover_task, run_task, terminate_orphan_processes,
)
from ..services.archive import remove_temporary_archives
from ..services.staging import remove_staging
from ..services.storage import archives_root, path_from_relative, staging_root
from .user_lock import try_lock_user_for_dispatch

logger = logging.getLogger(__name__)
_stop = asyncio.Event()


async def _sync_pending_programs() -> None:
    if state.program_sync_scan_running:
        return
    state.program_sync_scan_running = True
    try:
        await sync_pending_users_once()
    except Exception:
        logger.exception("延期程序同步扫描失败")
    finally:
        state.program_sync_scan_running = False


async def dispatch_once() -> list[asyncio.Task]:
    """扫描等待队列并按限额启动任务；返回 runner 协程任务列表（便于测试等待）。"""
    launched_ids: list[int] = []
    retry_ids: list[int] = []
    slot_statuses = (TaskStatus.PREPARING, TaskStatus.RUNNING, TaskStatus.ARCHIVING)
    async with db.async_session() as session:
        # 归档失败任务优先进入幂等重试；其用户仍保持逻辑占用状态。
        failed_archives = await session.scalars(
            select(Task)
            .where(
                Task.status == TaskStatus.ARCHIVE_FAILED,
                or_(Task.archive_retry_at.is_(None), Task.archive_retry_at <= utcnow()),
            )
            .order_by(Task.archive_retry_at.nullsfirst(), Task.queued_at)
            .with_for_update(skip_locked=True)
            .limit(10))
        for failed in failed_archives:
            failed.status = TaskStatus.ARCHIVING
            retry_ids.append(failed.id)

        max_concurrent = await get_int(session, "max_concurrent_tasks")

        occupied_total = await session.scalar(
            select(func.count(Task.id)).where(Task.status.in_(slot_statuses)))
        slots = max_concurrent - (occupied_total or 0)
        if slots <= 0:
            await session.commit()
            return [asyncio.create_task(recover_task(tid)) for tid in retry_ids]

        busy_users = set((await session.scalars(
            select(Task.user_id).where(Task.status.in_(ACTIVE_WORKSPACE_STATUSES))
        )).all())

        queued = await session.scalars(
            select(Task)
            .where(Task.status == TaskStatus.QUEUED)
            .order_by(Task.queued_at)
            .with_for_update(skip_locked=True)
            .limit(100))
        for task in queued:
            if slots <= 0:
                break
            if task.user_id in busy_users:
                continue
            if not await try_lock_user_for_dispatch(session, task.user_id):
                continue
            task.status = TaskStatus.PREPARING
            task.started_at = utcnow()
            busy_users.add(task.user_id)
            slots -= 1
            launched_ids.append(task.id)
        await session.commit()

    if launched_ids:
        logger.info("分发 %d 个任务: %s", len(launched_ids), launched_ids)
    return (
        [asyncio.create_task(recover_task(tid)) for tid in retry_ids]
        + [asyncio.create_task(run_task(tid)) for tid in launched_ids]
    )


async def dispatch_loop(interval: float = 1.0) -> None:
    logger.info("任务调度器已启动")
    while not _stop.is_set():
        try:
            await _sync_pending_programs()
            await dispatch_once()
        except Exception:
            logger.exception("调度周期异常")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def reconcile_storage() -> dict[str, int]:
    """启动期核对进程、临时归档和 staging；未知目录只告警不删除。"""
    async with db.async_session() as session:
        user_ids = list((await session.scalars(select(User.id).order_by(User.id))).all())
        tasks = list((await session.scalars(select(Task))).all())

    known_staging: dict[int, set[str]] = {user_id: set() for user_id in user_ids}
    known_archives: dict[int, set[str]] = {user_id: set() for user_id in user_ids}
    missing_queued: list[int] = []
    removable_staging = []
    for task in tasks:
        if task.archive_dir:
            try:
                known_archives.setdefault(task.user_id, set()).add(
                    str(path_from_relative(task.archive_dir).resolve()))
            except ValueError:
                logger.error("任务 #%s 归档路径无效：%s", task.id, task.archive_dir)
        if not task.staging_dir:
            if task.status == TaskStatus.QUEUED:
                missing_queued.append(task.id)
            continue
        try:
            stage = path_from_relative(task.staging_dir)
        except ValueError:
            if task.status == TaskStatus.QUEUED:
                missing_queued.append(task.id)
            continue
        known_staging.setdefault(task.user_id, set()).add(str(stage.resolve()))
        if task.status == TaskStatus.QUEUED and not stage.is_dir():
            missing_queued.append(task.id)
        elif task.archive_status == ArchiveStatus.COMPLETED and stage.exists():
            removable_staging.append(stage)

    orphan_processes = 0
    temporary_archives = 0
    orphan_staging = 0
    orphan_archives = 0
    for user_id in user_ids:
        orphan_processes += await asyncio.to_thread(terminate_orphan_processes, user_id)
        try:
            temporary_archives += await asyncio.to_thread(remove_temporary_archives, user_id)
        except OSError:
            logger.exception("用户 #%s 临时归档清理失败", user_id)
        root = staging_root(user_id)
        if root.is_dir():
            known = known_staging.get(user_id, set())
            for path in root.iterdir():
                if path.is_dir() and str(path.resolve()) not in known:
                    orphan_staging += 1
                    logger.warning("发现无法确认归属的暂存目录，不自动删除：%s", path)
        archive_root = archives_root(user_id)
        if archive_root.is_dir():
            known = known_archives.get(user_id, set())
            for path in archive_root.iterdir():
                if (path.is_dir() and not path.name.startswith(".tmp_")
                        and str(path.resolve()) not in known):
                    orphan_archives += 1
                    logger.warning("发现无法确认归属的正式归档，不自动删除：%s", path)

    for stage in removable_staging:
        try:
            await asyncio.to_thread(remove_staging, stage)
        except OSError:
            logger.exception("已归档任务的暂存目录清理失败：%s", stage)

    for task_id in missing_queued:
        await finalize_task(
            task_id,
            final_status=TaskStatus.FAILED,
            reason="服务启动检查发现任务暂存区缺失或路径无效",
            workspace_was_used=False,
        )

    summary = {
        "orphan_processes": orphan_processes,
        "temporary_archives": temporary_archives,
        "orphan_staging": orphan_staging,
        "orphan_archives": orphan_archives,
        "missing_queued": len(missing_queued),
        "removed_staging": len(removable_staging),
    }
    logger.info("启动存储对账完成：%s", summary)
    return summary


async def recover_interrupted_tasks() -> int:
    """服务启动时保护并归档中断现场，归档成功前不恢复该用户调度。"""
    await reconcile_storage()
    async with db.async_session() as session:
        ids = list((await session.scalars(
            select(Task.id).where(Task.status.in_(ACTIVE_WORKSPACE_STATUSES))
            .order_by(Task.queued_at)
        )).all())
    for task_id in ids:
        await recover_task(task_id)
    return len(ids)


async def shutdown_scheduler() -> None:
    """服务关停：停止分发并杀掉子进程；任务保持 RUNNING，由下次启动的恢复逻辑标记。"""
    state.shutting_down = True
    _stop.set()
    for entry in list(state.running.values()):
        _kill_process_tree(entry.proc.pid)
