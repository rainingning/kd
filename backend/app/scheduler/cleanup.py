"""过期任务清理（T7.1，FR-CLEAN）：删除超过保留期的终态任务及其文件。

保留期由系统配置 retention_days 控制（默认 30 天），每日执行一次；
任务删除时其站内通知由 DB 级联一并删除。
"""
import asyncio
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select

from .. import db
from ..config import settings
from ..models import TERMINAL_STATUSES, Task, utcnow
from ..services.config import get_int

logger = logging.getLogger(__name__)
_stop = asyncio.Event()


def _dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


async def cleanup_expired_tasks() -> tuple[int, int]:
    """删除过期终态任务（文件 + DB 记录）。返回 (删除任务数, 释放字节数)。"""
    async with db.async_session() as session:
        retention_days = await get_int(session, "retention_days")
        cutoff = utcnow() - timedelta(days=retention_days)
        rows = await session.scalars(
            select(Task).where(
                Task.status.in_(TERMINAL_STATUSES),
                Task.finished_at.isnot(None),
                Task.finished_at < cutoff,
            ))
        tasks = list(rows)
        freed = 0
        for task in tasks:
            if task.storage_dir:
                tdir = settings.storage_root / task.storage_dir
                if tdir.is_dir():
                    freed += _dir_size(tdir)
                    shutil.rmtree(tdir, ignore_errors=True)
            await session.delete(task)
        await session.commit()
    if tasks:
        logger.info("清理过期任务 %d 个，释放 %.2f MB", len(tasks), freed / 1024 / 1024)
    return len(tasks), freed


async def cleanup_loop(interval_hours: float = 24.0) -> None:
    logger.info("定时清理已启动（每 %g 小时执行）", interval_hours)
    while not _stop.is_set():
        try:
            await cleanup_expired_tasks()
        except Exception:
            logger.exception("定时清理异常")
        try:
            await asyncio.wait_for(_stop.wait(), timeout=interval_hours * 3600)
        except asyncio.TimeoutError:
            pass


def stop_cleanup() -> None:
    _stop.set()
