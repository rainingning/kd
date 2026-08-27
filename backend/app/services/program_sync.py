"""多程序版本同步与运行中延期处理。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select

from .. import db
from ..models import (
    ACTIVE_WORKSPACE_STATUSES, AuditLog, Task, User, UserProgram,
    WorkspaceStatus, utcnow,
)
from ..scheduler.user_lock import try_user_workspace_lock
from .program_template import ProgramTemplateError, validate_all_program_templates
from .programs import DCR_3D, list_programs
from .workspace import WorkspaceError, initialize_workspace

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProgramSyncResult:
    user_id: int
    status: str
    program_key: str = "all"
    version: str | None = None
    error: str | None = None
    items: tuple[dict, ...] = field(default_factory=tuple)


async def _set_deferred(user_id: int, reason: str) -> ProgramSyncResult:
    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        rows = list((await session.scalars(
            select(UserProgram).where(UserProgram.user_id == user_id)
        )).all())
        for row in rows:
            row.program_sync_pending = True
            row.workspace_error = reason
        user.program_sync_pending = True
        user.workspace_error = reason
        session.add(AuditLog(
            admin_id=None, action="program.sync.deferred", target=f"user#{user_id}",
            detail={"user_id": user_id, "error": reason},
        ))
        await session.commit()
    return ProgramSyncResult(user_id, "deferred", error=reason)


async def _record_failure(user_id: int, error: str) -> ProgramSyncResult:
    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        user.workspace_status = WorkspaceStatus.ERROR
        user.workspace_error = error
        user.program_sync_pending = True
        rows = list((await session.scalars(
            select(UserProgram).where(UserProgram.user_id == user_id)
        )).all())
        for row in rows:
            row.workspace_status = WorkspaceStatus.ERROR
            row.workspace_error = error
            row.program_sync_pending = True
        session.add(AuditLog(
            admin_id=None, action="program.sync.failed", target=f"user#{user_id}",
            detail={"user_id": user_id, "error": error},
        ))
        await session.commit()
    logger.error("用户 #%s 多程序同步失败：%s", user_id, error)
    return ProgramSyncResult(user_id, "failed", error=error)


async def sync_program_for_locked_user(user_id: int) -> ProgramSyncResult:
    """调用方已持有用户工作区锁时，同步三个程序并写入程序级状态。"""
    try:
        manifests = await asyncio.to_thread(validate_all_program_templates)
    except ProgramTemplateError as exc:
        return await _record_failure(user_id, str(exc))

    async with db.async_session() as session:
        user = await session.get(User, user_id)
        if user is None:
            return ProgramSyncResult(user_id, "missing", error="用户不存在")
        user.workspace_status = WorkspaceStatus.SYNCING
        rows = {
            row.program_key: row
            for row in (await session.scalars(
                select(UserProgram).where(UserProgram.user_id == user_id)
            )).all()
        }
        for spec in list_programs():
            row = rows.get(spec.key)
            if row is None:
                row = UserProgram(user_id=user_id, program_key=spec.key)
                session.add(row)
                rows[spec.key] = row
            row.workspace_status = WorkspaceStatus.SYNCING
        await session.commit()

    try:
        await asyncio.to_thread(initialize_workspace, user_id)
    except (OSError, ProgramTemplateError, WorkspaceError) as exc:
        return await _record_failure(user_id, str(exc))

    items: list[dict] = []
    async with db.async_session() as session:
        user = await session.get(User, user_id)
        rows = {
            row.program_key: row
            for row in (await session.scalars(
                select(UserProgram).where(UserProgram.user_id == user_id)
            )).all()
        }
        for spec in list_programs():
            manifest = manifests[spec.key]
            row = rows.get(spec.key)
            if row is None:
                row = UserProgram(user_id=user_id, program_key=spec.key)
                session.add(row)
            old_version = row.program_version
            row.workspace_status = WorkspaceStatus.READY
            row.workspace_error = None
            row.program_version = manifest.version
            row.exe_sha256 = manifest.exe_sha256
            row.dll_sha256 = manifest.dll_sha256
            row.runtime_file_hashes = manifest.runtime_file_hashes
            row.program_synced_at = utcnow()
            row.program_sync_pending = False
            items.append({
                "program_key": spec.key, "status": "synced",
                "old_version": old_version, "version": manifest.version,
            })
        dcr = manifests[DCR_3D]
        user.workspace_status = WorkspaceStatus.READY
        user.workspace_error = None
        user.program_sync_pending = False
        user.program_version = dcr.version
        user.exe_sha256 = dcr.exe_sha256
        user.dll_sha256 = dcr.dll_sha256
        user.program_synced_at = utcnow()
        session.add(AuditLog(
            admin_id=None, action="program.sync.succeeded", target=f"user#{user_id}",
            detail={"user_id": user_id, "programs": items},
        ))
        await session.commit()
    return ProgramSyncResult(user_id, "synced", items=tuple(items))


async def sync_user_program(user_id: int) -> ProgramSyncResult:
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
        return await sync_program_for_locked_user(user_id)


async def sync_pending_users_once(limit: int = 10) -> list[ProgramSyncResult]:
    async with db.async_session() as session:
        row_ids = list((await session.scalars(
            select(UserProgram.user_id)
            .where(UserProgram.program_sync_pending.is_(True))
            .distinct().order_by(UserProgram.user_id).limit(limit)
        )).all())
        legacy_ids = list((await session.scalars(
            select(User.id)
            .where(User.program_sync_pending.is_(True))
            .order_by(User.id).limit(limit)
        )).all())
    ids = list(dict.fromkeys([*row_ids, *legacy_ids]))[:limit]
    return [await sync_user_program(user_id) for user_id in ids]
