"""管理后台 API（T6.1~T6.5，FR-ADMIN）。

仪表盘统计、任务监控与终止、用户管理、系统参数配置、审计日志。
全部接口要求管理员权限（路由级依赖 require_admin）。
"""
import asyncio
import math
import secrets

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import db
from ..config import settings
from ..db import get_session
from ..deps import require_admin
from ..models import (
    ACTIVE_WORKSPACE_STATUSES,
    DEFAULT_CONFIG,
    AuditLog,
    SystemConfig,
    Task,
    TaskStatus,
    User,
    UserProgram,
    UserStatus,
    WorkspaceStatus,
    utcnow,
)
from ..scheduler.runner import finalize_task, recover_task, request_cancel
from ..schemas import (
    AdminTaskItem,
    AdminUserCreate,
    AdminUserUpdate,
    AuditLogListResponse,
    AuditLogResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    DashboardResponse,
    ResetPasswordResponse,
    UserListResponse,
    UserResponse,
)
from ..security import hash_password
from ..services.audit import audit
from ..services.config import get_config_map
from ..services.program_sync import sync_user_program
from ..services.program_template import (
    ProgramTemplateError, validate_all_program_templates, validate_program_template,
)
from ..services.programs import list_programs
from ..services.workspace import (
    WorkspaceError, check_all_workspaces, check_workspace, initialize_workspace, remove_workspace,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---- T6.1 仪表盘 ----

@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(session: AsyncSession = Depends(get_session)):
    total_users = await session.scalar(select(func.count(User.id)))
    monitored_statuses = (TaskStatus.PREPARING, TaskStatus.RUNNING, TaskStatus.ARCHIVING)
    running_tasks = await session.scalar(
        select(func.count(Task.id)).where(Task.status.in_(monitored_statuses)))
    queued_tasks = await session.scalar(
        select(func.count(Task.id)).where(Task.status == TaskStatus.QUEUED))
    active_users = await session.scalar(
        select(func.count(func.distinct(Task.user_id))).where(
            Task.status.in_(monitored_statuses)))
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage(str(settings.storage_root.resolve()))
    return DashboardResponse(
        total_users=total_users or 0,
        active_users=active_users or 0,
        running_tasks=running_tasks or 0,
        queued_tasks=queued_tasks or 0,
        cpu_percent=psutil.cpu_percent(interval=None),
        memory_percent=mem.percent,
        disk_percent=disk.percent,
    )


# ---- T6.2 任务监控与终止 ----

async def _task_items(session: AsyncSession, statuses: str | tuple[str, ...]) -> list[AdminTaskItem]:
    status_filter = (
        Task.status.in_(statuses) if isinstance(statuses, tuple)
        else Task.status == statuses
    )
    rows = (await session.execute(
        select(Task, User.username)
        .join(User, Task.user_id == User.id)
        .where(status_filter)
        .order_by(Task.queued_at)
    )).all()
    return [
        AdminTaskItem(
            id=t.id, user_id=t.user_id, username=uname, status=t.status,
            program_key=t.program_key, source_type=t.source_type,
            stdin_choice=t.stdin_choice, input_filename=t.input_filename,
            parameter_filename=t.parameter_filename,
            queued_at=t.queued_at, started_at=t.started_at,
        )
        for t, uname in rows
    ]


@router.get("/tasks/running", response_model=list[AdminTaskItem])
async def list_running_tasks(session: AsyncSession = Depends(get_session)):
    return await _task_items(session, (
        TaskStatus.PREPARING, TaskStatus.RUNNING, TaskStatus.ARCHIVING,
    ))


@router.get("/tasks/queued", response_model=list[AdminTaskItem])
async def list_queued_tasks(session: AsyncSession = Depends(get_session)):
    return await _task_items(session, TaskStatus.QUEUED)


@router.post("/tasks/{task_id}/kill")
async def kill_task(
    task_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if task is None or task.status not in (
        TaskStatus.QUEUED, TaskStatus.PREPARING, TaskStatus.RUNNING,
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "任务不在准备、运行或排队中")

    if task.status in (TaskStatus.PREPARING, TaskStatus.RUNNING):
        process_signaled = request_cancel(task_id, kind="admin")
        # 无论进程是否已注册，runner 都会在启动前竞态检查或进程退出后归档。
        audit(session, admin.id, "task.kill", target=f"task#{task_id}", detail={
            "via": "process" if process_signaled else "prelaunch_request",
        })
        await session.commit()
        return {"detail": "已记录终止指令"}

    # 排队任务从 staging 直接归档，不触碰用户固定工作区。
    audit(session, admin.id, "task.kill", target=f"task#{task_id}", detail={"via": "queued"})
    await session.commit()
    archived = await finalize_task(
        task_id,
        final_status=TaskStatus.FAILED,
        reason="被管理员终止",
        workspace_was_used=False,
    )
    if not archived:
        return {"detail": "任务已终止，但归档失败，等待管理员重试"}
    return {"detail": "已终止并归档"}


# ---- T6.3 用户管理 ----

@router.get("/users", response_model=UserListResponse)
async def list_users(
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(User)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.email.ilike(like)))
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(
        stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return UserListResponse(total=total or 0, items=list(rows))


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: AdminUserCreate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    dup = await session.scalar(
        select(User.id).where(or_(User.username == body.username, User.email == body.email)))
    if dup is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名或邮箱已被占用")
    user = User(
        username=body.username, email=body.email,
        password_hash=hash_password(body.password),
        role=body.role, status=UserStatus.ACTIVE,  # 管理员创建的用户直接激活
    )
    session.add(user)
    await session.flush()
    try:
        manifests = await asyncio.to_thread(initialize_workspace, user.id)
    except WorkspaceError as exc:
        await session.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"用户工作区初始化失败：{exc}",
        ) from exc
    user.workspace_status = WorkspaceStatus.READY
    user.workspace_error = None
    for program_key, manifest in manifests.items():
        session.add(UserProgram(
            user_id=user.id,
            program_key=program_key,
            workspace_status=WorkspaceStatus.READY,
            program_version=manifest.version,
            exe_sha256=manifest.exe_sha256,
            dll_sha256=manifest.dll_sha256,
            runtime_file_hashes=manifest.runtime_file_hashes,
            program_synced_at=utcnow(),
        ))
    dcr = manifests["dcr_3d"]
    user.program_version = dcr.version
    user.exe_sha256 = dcr.exe_sha256
    user.dll_sha256 = dcr.dll_sha256
    user.program_synced_at = utcnow()
    audit(session, admin.id, "user.create", target=user.username,
          detail={"user_id": user.id, "role": user.role,
                  "program_versions": {key: value.version for key, value in manifests.items()}})
    await session.commit()
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    body: AdminUserUpdate,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    changes: dict = {}
    if body.role is not None and body.role != target.role:
        if target.id == admin.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能修改自己的角色")
        changes["role"] = body.role
    if body.username is not None and body.username != target.username:
        dup = await session.scalar(select(User.id).where(User.username == body.username))
        if dup is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被占用")
        changes["username"] = body.username
    if body.email is not None and body.email != target.email:
        dup = await session.scalar(select(User.id).where(User.email == body.email))
        if dup is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "邮箱已被占用")
        changes["email"] = body.email

    for field, value in changes.items():
        setattr(target, field, value)
    if changes:
        audit(session, admin.id, "user.update", target=target.username,
              detail={"user_id": target.id, "changes": changes})
        await session.commit()
    return target


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己")

    active = await session.scalar(
        select(func.count(Task.id))
        .where(Task.user_id == user_id, Task.status.in_(ACTIVE_WORKSPACE_STATUSES)))
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户工作区正在被任务占用，请稍后删除")

    try:
        await asyncio.to_thread(remove_workspace, user_id)
    except OSError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"用户工作区删除失败：{exc}",
        ) from exc
    await session.delete(target)  # DB 级联删除其任务/通知/模板/token 记录
    audit(session, admin.id, "user.delete", target=target.username, detail={"user_id": user_id})
    await session.commit()


@router.post("/users/{user_id}/reset-password", response_model=ResetPasswordResponse)
async def reset_user_password(
    user_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    temp_password = secrets.token_urlsafe(8)
    target.password_hash = hash_password(temp_password)
    audit(session, admin.id, "user.reset_password", target=target.username,
          detail={"user_id": user_id})
    await session.commit()
    return ResetPasswordResponse(temporary_password=temp_password)


@router.post("/users/{user_id}/disable", response_model=UserResponse)
async def disable_user(
    user_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if target.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己")

    target.status = UserStatus.DISABLED
    # 排队任务先保留 staging，提交事务后逐个执行取消归档；运行中任务不动。
    queued_ids = list((await session.scalars(
        select(Task.id).where(Task.user_id == user_id, Task.status == TaskStatus.QUEUED)
    )).all())
    audit(session, admin.id, "user.disable", target=target.username,
          detail={"user_id": user_id, "queued_tasks_to_archive": queued_ids})
    await session.commit()
    for task_id in queued_ids:
        await finalize_task(
            task_id,
            final_status=TaskStatus.CANCELED,
            reason="账号被禁用",
            workspace_was_used=False,
        )
    return target


@router.post("/users/{user_id}/enable", response_model=UserResponse)
async def enable_user(
    user_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    target.status = UserStatus.ACTIVE
    audit(session, admin.id, "user.enable", target=target.username, detail={"user_id": user_id})
    await session.commit()
    return target


# ---- 程序模板、用户工作区与归档运维 ----

@router.get("/program-template")
async def get_program_template_status(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    items = []
    for spec in list_programs():
        try:
            manifest = await asyncio.to_thread(
                validate_program_template, program_key=spec.key)
            items.append({"status": "ready", "name": spec.display_name, **manifest.as_dict()})
        except ProgramTemplateError as exc:
            items.append({
                "status": "error", "program_key": spec.key,
                "name": spec.display_name, "error": str(exc),
            })
    result = {
        "status": "ready" if all(item["status"] == "ready" for item in items) else "error",
        "programs": items,
    }
    # 一个发布周期内保留旧管理端读取的 DCR 顶层字段。
    dcr_item = next((item for item in items if item.get("program_key") == "dcr_3d"), None)
    if dcr_item and dcr_item["status"] == "ready":
        result.update({key: dcr_item[key] for key in (
            "version", "exe", "dll", "exe_sha256", "dll_sha256")})
    audit(session, admin.id, "program.template_check", detail=result)
    await session.commit()
    return result


@router.get("/program-sync/status")
async def get_program_sync_status(session: AsyncSession = Depends(get_session)):
    total_users = await session.scalar(select(func.count(User.id))) or 0
    rows = list((await session.scalars(select(UserProgram))).all())
    try:
        manifests = await asyncio.to_thread(validate_all_program_templates)
    except ProgramTemplateError:
        manifests = {}
    programs = []
    for spec in list_programs():
        subset = [row for row in rows if row.program_key == spec.key]
        manifest = manifests.get(spec.key)
        deferred = [row for row in subset if row.program_sync_pending
                    and row.workspace_error and "延期" in row.workspace_error]
        programs.append({
            "program_key": spec.key,
            "name": spec.display_name,
            "template_version": manifest.version if manifest else None,
            "total": total_users,
            "synced": sum(1 for row in subset if manifest
                          and row.program_version == manifest.version
                          and row.exe_sha256 == manifest.exe_sha256
                          and row.dll_sha256 == manifest.dll_sha256
                          and not row.program_sync_pending
                          and row.workspace_status == WorkspaceStatus.READY),
            "pending": sum(1 for row in subset if row.program_sync_pending and row not in deferred),
            "deferred": len(deferred),
            "failed": sum(1 for row in subset if row.workspace_status == WorkspaceStatus.ERROR),
            "syncing": sum(1 for row in subset if row.workspace_status == WorkspaceStatus.SYNCING),
        })
    ready_users = {
        user_id for user_id in {row.user_id for row in rows}
        if all(
            any(item.program_key == spec.key
                and item.workspace_status == WorkspaceStatus.READY
                and not item.program_sync_pending
                for item in rows if item.user_id == user_id)
            for spec in list_programs()
        )
    }
    deferred_users = {
        row.user_id for row in rows
        if row.program_sync_pending and row.workspace_error and "延期" in row.workspace_error
    }
    failed_users = {row.user_id for row in rows if row.workspace_status == WorkspaceStatus.ERROR}
    syncing_users = {row.user_id for row in rows if row.workspace_status == WorkspaceStatus.SYNCING}
    pending_users = {
        row.user_id for row in rows if row.program_sync_pending
    } - deferred_users - failed_users - syncing_users
    return {
        "total": total_users,
        "synced": len(ready_users),
        "pending": len(pending_users),
        "deferred": len(deferred_users),
        "failed": len(failed_users),
        "syncing": len(syncing_users),
        "programs": programs,
    }


@router.post("/program-sync")
async def sync_all_user_programs(
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    try:
        manifests = await asyncio.to_thread(validate_all_program_templates)
    except ProgramTemplateError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    user_ids = list((await session.scalars(select(User.id).order_by(User.id))).all())
    results = [await sync_user_program(user_id) for user_id in user_ids]
    summary = {
        "versions": {key: value.version for key, value in manifests.items()},
        "total": len(results),
        "synced": sum(1 for r in results if r.status == "synced"),
        "deferred": sum(1 for r in results if r.status == "deferred"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "items": [r.__dict__ for r in results],
    }
    audit(session, admin.id, "program.sync_all", detail={
        key: value for key, value in summary.items() if key != "items"})
    await session.commit()
    return summary


@router.post("/users/{user_id}/program-sync")
async def sync_one_user_program(
    user_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    result = await sync_user_program(user_id)
    if result.status == "missing":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    audit(session, admin.id, "program.sync_user", target=f"user#{user_id}",
          detail=result.__dict__)
    await session.commit()
    return result.__dict__


@router.post("/users/{user_id}/workspace-check")
async def check_one_user_workspace(
    user_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    checks = await asyncio.to_thread(check_all_workspaces, user_id)
    rows = {
        row.program_key: row
        for row in (await session.scalars(
            select(UserProgram).where(UserProgram.user_id == user_id)
        )).all()
    }
    items = []
    all_errors: list[str] = []
    for program_key, result in checks.items():
        row = rows.get(program_key)
        if row is not None:
            row.workspace_status = WorkspaceStatus.READY if result.ready else WorkspaceStatus.ERROR
            row.workspace_error = None if result.ready else "；".join(result.errors)
        all_errors.extend(f"{program_key}: {error}" for error in result.errors)
        items.append({
            "program_key": program_key,
            "ready": result.ready,
            "errors": list(result.errors),
            "exe_sha256": result.exe_sha256,
            "dll_sha256": result.dll_sha256,
        })
    ready = all(item["ready"] for item in items)
    target.workspace_status = WorkspaceStatus.READY if ready else WorkspaceStatus.ERROR
    target.workspace_error = None if ready else "；".join(all_errors)
    audit(session, admin.id, "workspace.check", target=f"user#{user_id}",
          detail={"ready": ready, "programs": items})
    await session.commit()
    return {"user_id": user_id, "ready": ready, "errors": all_errors, "programs": items}


@router.get("/tasks/archive-failures")
async def list_archive_failures(session: AsyncSession = Depends(get_session)):
    rows = list((await session.scalars(
        select(Task).where(Task.status == TaskStatus.ARCHIVE_FAILED)
        .order_by(Task.queued_at)
    )).all())
    return [{
        "id": task.id,
        "user_id": task.user_id,
        "archive_version": task.archive_version,
        "archive_error": task.archive_error,
        "archive_retry_count": task.archive_retry_count,
        "archive_retry_at": task.archive_retry_at,
        "terminal_status": task.terminal_status,
        "queued_at": task.queued_at,
    } for task in rows]


@router.post("/tasks/{task_id}/archive-retry")
async def retry_task_archive(
    task_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if task.status != TaskStatus.ARCHIVE_FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "任务不在归档失败状态")
    audit(session, admin.id, "archive.retry", target=f"task#{task_id}")
    await session.commit()
    await recover_task(task_id)
    async with db.async_session() as check_session:
        refreshed = await check_session.get(Task, task_id)
        return {
            "task_id": task_id,
            "status": refreshed.status,
            "archive_status": refreshed.archive_status,
            "archive_error": refreshed.archive_error,
        }


# ---- T6.4 系统参数配置 ----

@router.get("/config", response_model=ConfigResponse)
async def get_system_config(session: AsyncSession = Depends(get_session)):
    return ConfigResponse(config=await get_config_map(session))


@router.put("/config", response_model=ConfigResponse)
async def update_system_config(
    body: ConfigUpdateRequest,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
):
    errors: dict[str, str] = {}
    for key, value in body.config.items():
        if key not in DEFAULT_CONFIG:
            errors[key] = "未知配置项"
            continue
        if key == "max_running_per_user" and str(value) != "1":
            errors[key] = "固定工作区模式下单用户运行上限必须为 1"
            continue
        try:
            numeric = float(value)
            if not math.isfinite(numeric) or numeric <= 0 or not numeric.is_integer():
                raise ValueError
        except (TypeError, ValueError):
            errors[key] = "必须为正整数"
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=errors)

    for key, value in body.config.items():
        row = await session.get(SystemConfig, key)
        if row is not None:
            row.value = value
        else:
            session.add(SystemConfig(key=key, value=value))
    audit(session, admin.id, "config.update", detail=body.config)
    await session.commit()
    return ConfigResponse(config=await get_config_map(session))


# ---- T6.5 审计日志 ----

@router.get("/audit-logs", response_model=AuditLogListResponse)
async def list_audit_logs(
    action: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(AuditLog, User.username).join(User, AuditLog.admin_id == User.id, isouter=True)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    total = await session.scalar(
        select(func.count()).select_from(select(AuditLog.id).where(
            AuditLog.action == action if action else True).subquery()))
    rows = (await session.execute(
        stmt.order_by(AuditLog.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )).all()
    items = [
        AuditLogResponse(
            id=log.id, admin_id=log.admin_id, admin_username=uname,
            action=log.action, target=log.target, detail=log.detail, created_at=log.created_at,
        )
        for log, uname in rows
    ]
    return AuditLogListResponse(total=total or 0, items=items)
