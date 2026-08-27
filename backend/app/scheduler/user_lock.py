"""PostgreSQL advisory lock：保证同一用户固定工作区互斥。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db

# 不同用途使用不同 key 空间：工作区锁为长连接会话锁，提交配额锁为事务锁。
_WORKSPACE_LOCK_BASE = 4_918_564_000_000_000_000
_SUBMIT_LOCK_BASE = 4_918_565_000_000_000_000


def _lock_key(base: int, user_id: int) -> int:
    key = base + int(user_id)
    if key > 9_223_372_036_854_775_807:
        raise ValueError("user_id 超出 advisory lock 可用范围")
    return key


async def lock_task_submission(session: AsyncSession, user_id: int) -> None:
    """串行化同一用户的“检查排队上限 + 创建任务”事务。"""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": _lock_key(_SUBMIT_LOCK_BASE, user_id)},
    )


async def try_lock_user_for_dispatch(session: AsyncSession, user_id: int) -> bool:
    """调度事务短暂占用工作区锁，防止多调度器同时挑中同一用户。"""
    return bool(await session.scalar(
        text("SELECT pg_try_advisory_xact_lock(:key)"),
        {"key": _lock_key(_WORKSPACE_LOCK_BASE, user_id)},
    ))


@asynccontextmanager
async def try_user_workspace_lock(user_id: int) -> AsyncIterator[bool]:
    """使用专用数据库连接持有会话级用户锁，退出时可靠释放。"""
    async with db.engine.connect() as connection:
        key = _lock_key(_WORKSPACE_LOCK_BASE, user_id)
        acquired = bool(await connection.scalar(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": key}))
        try:
            yield acquired
        finally:
            if acquired:
                await connection.execute(
                    text("SELECT pg_advisory_unlock(:key)"), {"key": key})
