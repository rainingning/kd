"""用户程序版本同步与运行中延期处理。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import func, select

from .. import db
from ..models import (
    ACTIVE_WORKSPACE_STATUSES, AuditLog, Task, User, WorkspaceStatus, utcnow,
)
from ..scheduler.user_lock import try_user_workspace_lock
from .program_template import ProgramTemplateError, validate_program_template
from .workspace import WorkspaceError, initialize_workspace

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgramSyncResult:
    user_id: int
    status: str  # synced / deferred / failed / missing
    version: str | None = None
    error: str | None = None


async def _set_deferred(user_id: int, reason: str) -> ProgramSyncResult:
    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        user.program_sync_pending = True
        user.workspace_error = reason
        session.add(AuditLog(
            admin_id=None,
            action="program.sync.deferred",
            target=f"user#{user_id}",
            detail={"user_id": user_id, "old_version": user.program_version, "error": reason},
        ))
        await session.commit()
        logger.warning("用户 #%s 程序同步延期：%s", user_id, reason)
        return ProgramSyncResult(
            user_id, "deferred", version=user.program_version, error=reason)


async def sync_program_for_locked_user(user_id: int) -> ProgramSyncResult:
    """调用方已持有用户工作区锁时执行文件同步。"""
    try:
        manifest = await asyncio.to_thread(validate_program_template)
    except ProgramTemplateError as exc:
        return await _record_failure(user_id, str(exc))

    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        user.workspace_status = WorkspaceStatus.SYNCING
        await session.commit()

    try:
        await asyncio.to_thread(initialize_workspace, user_id)
    except (OSError, ProgramTemplateError, WorkspaceError) as exc:
        return await _record_failure(user_id, str(exc))

    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        old_version = user.program_version
        old_exe_sha256 = user.exe_sha256
        old_dll_sha256 = user.dll_sha256
        user.workspace_status = WorkspaceStatus.READY
        user.workspace_error = None
        user.program_version = manifest.version
        user.exe_sha256 = manifest.exe_sha256
        user.dll_sha256 = manifest.dll_sha256
        user.program_synced_at = utcnow()
        user.program_sync_pending = False
        session.add(AuditLog(
            admin_id=None,
            action="program.sync.succeeded",
            target=f"user#{user_id}",
            detail={
                "user_id": user_id,
                "old_version": old_version,
                "new_version": manifest.version,
                "old_exe_sha256": old_exe_sha256,
                "new_exe_sha256": manifest.exe_sha256,
                "old_dll_sha256": old_dll_sha256,
                "new_dll_sha256": manifest.dll_sha256,
            },
        ))
        await session.commit()
    logger.info(
        "用户 #%s 程序同步成功：version=%s exe=%s dll=%s",
        user_id, manifest.version, manifest.exe_sha256, manifest.dll_sha256,
    )
    return ProgramSyncResult(user_id, "synced", version=manifest.version)


async def _record_failure(user_id: int, error: str) -> ProgramSyncResult:
    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is not None:
            user.workspace_status = WorkspaceStatus.ERROR
            user.workspace_error = error
            user.program_sync_pending = True
            session.add(AuditLog(
                admin_id=None,
                action="program.sync.failed",
                target=f"user#{user_id}",
                detail={"user_id": user_id, "old_version": user.program_version, "error": error},
            ))
            await session.commit()
            version = user.program_version
        else:
            version = None
    logger.error("用户 #%s 程序同步失败：%s", user_id, error)
    return ProgramSyncResult(user_id, "failed", version=version, error=error)


async def sync_user_program(user_id: int) -> ProgramSyncResult:
    """空闲用户立即同步；运行/准备/归档中的用户记录为延期。"""
    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        active = await session.scalar(select(func.count(Task.id)).where(
            Task.user_id == user_id,
            Task.status.in_(ACTIVE_WORKSPACE_STATUSES),
        ))
    if active:
        return await _set_deferred(user_id, "用户工作区正在执行或归档，程序同步已延期")

    async with try_user_workspace_lock(user_id) as acquired:
        if not acquired:
            return await _set_deferred(user_id, "用户工作区锁忙，程序同步已延期")
        # 获取锁后再次检查，关闭检查与锁之间的竞态窗口。
        async with db.async_session() as session:
            active = await session.scalar(select(func.count(Task.id)).where(
                Task.user_id == user_id,
                Task.status.in_(ACTIVE_WORKSPACE_STATUSES),
            ))
        if active:
            return await _set_deferred(user_id, "用户工作区正在执行或归档，程序同步已延期")
        return await sync_program_for_locked_user(user_id)


async def sync_pending_users_once(limit: int = 10) -> list[ProgramSyncResult]:
    async with db.async_session() as session:
        ids = list((await session.scalars(
            select(User.id)
            .where(User.program_sync_pending.is_(True))
            .order_by(User.id)
            .limit(limit)
        )).all())
    results: list[ProgramSyncResult] = []
    for user_id in ids:
        results.append(await sync_user_program(user_id))
    return results
