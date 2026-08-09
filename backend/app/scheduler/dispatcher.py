"""FIFO 调度器（T4.2）与服务重启恢复（T4.5，FR-QUEUE-09）。

调度规则（需求说明书 4.4）：
- 全局 RUNNING 数 < max_concurrent_tasks（默认 50，可配）
- 单用户 RUNNING 数 < max_running_per_user（默认 3，可配）
- 等待队列按 queued_at 严格 FIFO
"""
import asyncio
import logging

from sqlalchemy import func, select

from .. import db
from ..models import NotificationType, Task, TaskStatus, utcnow
from ..services.config import get_int
from ..services.notifications import notify
from . import state
from .runner import run_task

logger = logging.getLogger(__name__)
_stop = asyncio.Event()


async def dispatch_once() -> list[asyncio.Task]:
    """扫描等待队列并按限额启动任务；返回 runner 协程任务列表（便于测试等待）。"""
    launched_ids: list[int] = []
    async with db.async_session() as session:
        max_concurrent = await get_int(session, "max_concurrent_tasks")
        per_user_limit = await get_int(session, "max_running_per_user")

        running_total = await session.scalar(
            select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING))
        slots = max_concurrent - (running_total or 0)
        if slots <= 0:
            return []

        per_user = dict((await session.execute(
            select(Task.user_id, func.count())
            .where(Task.status == TaskStatus.RUNNING)
            .group_by(Task.user_id)
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
            if per_user.get(task.user_id, 0) >= per_user_limit:
                continue
            task.status = TaskStatus.RUNNING
            task.started_at = utcnow()
            per_user[task.user_id] = per_user.get(task.user_id, 0) + 1
            slots -= 1
            launched_ids.append(task.id)
        await session.commit()

    if launched_ids:
        logger.info("分发 %d 个任务: %s", len(launched_ids), launched_ids)
    return [asyncio.create_task(run_task(tid)) for tid in launched_ids]


async def dispatch_loop(interval: float = 1.0) -> None:
    logger.info("任务调度器已启动")
    while not _stop.is_set():
        try:
            await dispatch_once()
        except Exception:
            logger.exception("调度周期异常")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def recover_interrupted_tasks() -> int:
    """服务启动时调用：残留 RUNNING → FAILED（服务重启中断）并通知用户。"""
    async with db.async_session() as session:
        rows = await session.scalars(select(Task).where(Task.status == TaskStatus.RUNNING))
        tasks = list(rows)
        for t in tasks:
            t.status = TaskStatus.FAILED
            t.error_message = "服务重启中断"
            t.finished_at = utcnow()
            notify(session, t, NotificationType.FAILED, f"任务 #{t.id} 失败：服务重启中断")
        await session.commit()
    return len(tasks)


async def shutdown_scheduler() -> None:
    """服务关停：停止分发并杀掉子进程；任务保持 RUNNING，由下次启动的恢复逻辑标记。"""
    state.shutting_down = True
    _stop.set()
    for entry in list(state.running.values()):
        try:
            entry.proc.kill()
        except ProcessLookupError:
            pass
