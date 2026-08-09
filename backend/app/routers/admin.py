"""管理后台 API（T6.1~T6.5，FR-ADMIN）。

仪表盘统计、任务监控与终止、用户管理、系统参数配置、审计日志。
全部接口要求管理员权限（路由级依赖 require_admin）。
"""
import secrets
import shutil

import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import require_admin
from ..models import (
    DEFAULT_CONFIG,
    AuditLog,
    NotificationType,
    SystemConfig,
    Task,
    TaskStatus,
    User,
    UserStatus,
    utcnow,
)
from ..scheduler.runner import request_cancel
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
from ..services.notifications import notify

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


# ---- T6.1 仪表盘 ----

@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(session: AsyncSession = Depends(get_session)):
    total_users = await session.scalar(select(func.count(User.id)))
    running_tasks = await session.scalar(
        select(func.count(Task.id)).where(Task.status == TaskStatus.RUNNING))
    queued_tasks = await session.scalar(
        select(func.count(Task.id)).where(Task.status == TaskStatus.QUEUED))
    active_users = await session.scalar(
        select(func.count(func.distinct(Task.user_id))).where(Task.status == TaskStatus.RUNNING))
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

async def _task_items(session: AsyncSession, status_: str) -> list[AdminTaskItem]:
    rows = (await session.execute(
        select(Task, User.username)
        .join(User, Task.user_id == User.id)
        .where(Task.status == status_)
        .order_by(Task.queued_at)
    )).all()
    return [
        AdminTaskItem(
            id=t.id, user_id=t.user_id, username=uname, status=t.status,
            input_filename=t.input_filename, queued_at=t.queued_at, started_at=t.started_at,
        )
        for t, uname in rows
    ]


@router.get("/tasks/running", response_model=list[AdminTaskItem])
async def list_running_tasks(session: AsyncSession = Depends(get_session)):
    return await _task_items(session, TaskStatus.RUNNING)


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
    if task is None or task.status not in (TaskStatus.QUEUED, TaskStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, "任务不在运行或排队中")

    if task.status == TaskStatus.RUNNING and request_cancel(task_id, kind="admin"):
        # runner 负责落终态 FAILED 并通知用户
        audit(session, admin.id, "task.kill", target=f"task#{task_id}", detail={"via": "process"})
        await session.commit()
        return {"detail": "已发送终止指令"}

    # QUEUED 或进程注册表竞态：直接落终态
    task.status = TaskStatus.FAILED
    task.error_message = "被管理员终止"
    task.finished_at = utcnow()
    notify(session, task, NotificationType.KILLED, f"任务 #{task.id} 已被管理员终止")
    audit(session, admin.id, "task.kill", target=f"task#{task_id}", detail={"via": "direct"})
    await session.commit()
    return {"detail": "已终止"}


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
    audit(session, admin.id, "user.create", target=user.username,
          detail={"user_id": user.id, "role": user.role})
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

    running = await session.scalar(
        select(func.count(Task.id))
        .where(Task.user_id == user_id, Task.status == TaskStatus.RUNNING))
    if running:
        raise HTTPException(status.HTTP_409_CONFLICT, "该用户有正在运行的任务，请先终止")

    await session.delete(target)  # DB 级联删除其任务/通知/模板/token 记录
    shutil.rmtree(settings.storage_root / str(user_id), ignore_errors=True)
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
    # 取消其排队中任务；运行中任务不动（FR-ADMIN-08）
    queued = await session.scalars(
        select(Task).where(Task.user_id == user_id, Task.status == TaskStatus.QUEUED))
    for t in queued:
        t.status = TaskStatus.CANCELED
        t.error_message = "账号被禁用"
        t.finished_at = utcnow()
    audit(session, admin.id, "user.disable", target=target.username, detail={"user_id": user_id})
    await session.commit()
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
        try:
            if float(value) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errors[key] = "必须为正数"
    if errors:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=errors)

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
