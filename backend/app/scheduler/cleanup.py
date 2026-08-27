"""按保留期清理任务归档、暂存、ZIP 缓存及数据库记录。"""
import asyncio
import logging
import shutil
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select

from .. import db
from ..models import TERMINAL_STATUSES, Task, utcnow
from ..services.config import get_int
from ..services.result_zip import cached_zip_path
from ..services.storage import path_from_relative

logger = logging.getLogger(__name__)
_stop = asyncio.Event()


def _dir_size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _remove_path(path: Path) -> int:
    if not path.exists():
        return 0
    size = _dir_size(path)
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    return size


def _delete_task_files(task: Task) -> int:
    paths: list[Path] = []
    for relative in (task.archive_dir, task.staging_dir):
        if relative:
            paths.append(path_from_relative(relative))
    # 迁移兼容：尚未清空的旧任务目录。
    if task.storage_dir:
        paths.append(path_from_relative(task.storage_dir))
    if task.archive_version:
        paths.append(cached_zip_path(task.id, task.archive_version))

    freed = 0
    seen: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        freed += _remove_path(path)
    return freed


async def cleanup_expired_tasks() -> tuple[int, int]:
    """仅在文件清理成功后删除数据库任务记录。"""
    async with db.async_session() as session:
        retention_days = await get_int(session, "retention_days")
        cutoff = utcnow() - timedelta(days=retention_days)
        tasks = list((await session.scalars(
            select(Task).where(
                Task.status.in_(TERMINAL_STATUSES),
                Task.finished_at.isnot(None),
                Task.finished_at < cutoff,
                or_(Task.cleanup_retry_at.is_(None), Task.cleanup_retry_at <= utcnow()),
            )
        )).all())
        freed = 0
        deleted = 0
        for task in tasks:
            try:
                freed += await asyncio.to_thread(_delete_task_files, task)
            except (OSError, ValueError) as exc:
                logger.exception("任务 #%s 文件清理失败，保留数据库记录等待重试", task.id)
                task.cleanup_error = str(exc)
                task.cleanup_retry_count = (task.cleanup_retry_count or 0) + 1
                retry_hours = min(2 ** (task.cleanup_retry_count - 1), 24)
                task.cleanup_retry_at = utcnow() + timedelta(hours=retry_hours)
                continue
            await session.delete(task)
            deleted += 1
        await session.commit()
    if deleted:
        logger.info("清理过期任务 %d 个，释放 %.2f MB", deleted, freed / 1024 / 1024)
    return deleted, freed


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
