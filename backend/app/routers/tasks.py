"""任务提交与取消（T4.1 / T4.4）。任务查询、文件下载见 P5。"""
import json
import logging
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import get_current_user
from ..models import Task, TaskStatus, User, utcnow
from ..param_schema import ParamValidationError, serialize_params, validate_params
from ..scheduler.runner import request_cancel
from ..schemas import TaskDetailResponse, TaskListResponse, TaskResponse
from ..services.config import get_int
from ..services.storage import task_dir

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

_CHUNK = 1024 * 1024


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def submit_task(
    params: str = Form(..., description="参数 JSON 字符串"),
    file: UploadFile = File(..., description="输入数据文件"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    try:
        raw_params = json.loads(params)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "params 不是合法的 JSON")
    try:
        normalized = validate_params(raw_params)
    except ParamValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=e.errors)

    queued_count = await session.scalar(
        select(func.count(Task.id)).where(Task.user_id == user.id, Task.status == TaskStatus.QUEUED))
    if (queued_count or 0) >= await get_int(session, "max_queued_per_user"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "排队任务数已达上限，请稍后再提交")

    task = Task(user_id=user.id, status=TaskStatus.QUEUED,
                params=normalized, input_filename=file.filename)
    session.add(task)
    await session.flush()  # 取 task.id 用于目录命名

    max_bytes = (await get_int(session, "max_upload_mb")) * 1024 * 1024
    tdir = task_dir(user.id, task.id)
    tdir.mkdir(parents=True, exist_ok=True)
    try:
        (tdir / "params.in").write_text(serialize_params(normalized), encoding="utf-8")
        size = 0
        with open(tdir / "input.dat", "wb") as f:
            while chunk := await file.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "文件超过大小上限")
                f.write(chunk)
    except Exception:
        shutil.rmtree(tdir, ignore_errors=True)
        await session.rollback()
        raise

    task.storage_dir = f"{user.id}/{task.id}"
    await session.commit()
    return task


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")

    if task.status == TaskStatus.QUEUED:
        task.status = TaskStatus.CANCELED
        task.error_message = "用户取消"
        task.finished_at = utcnow()
        await session.commit()
        return task

    if task.status == TaskStatus.RUNNING:
        if request_cancel(task_id, kind="user"):
            return task  # runner 负责落终态 CANCELED，前端轮询获取
        # 已分发但进程未注册的竞态窗口：直接置取消，runner 启动时发现状态非 RUNNING 会跳过
        task.status = TaskStatus.CANCELED
        task.error_message = "用户取消"
        task.finished_at = utcnow()
        await session.commit()
        return task

    raise HTTPException(status.HTTP_409_CONFLICT, "任务已结束，不能取消")


# ---- T5.1 任务列表与详情 ----

@router.get("", response_model=TaskListResponse)
async def list_tasks(
    status_filter: str | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Task).where(Task.user_id == user.id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter.upper())
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = await session.scalars(
        stmt.order_by(Task.queued_at.desc()).offset((page - 1) * page_size).limit(page_size))
    return TaskListResponse(total=total or 0, items=list(rows))


@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(
    task_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")

    detail = TaskDetailResponse.model_validate(task)
    if task.status == TaskStatus.QUEUED:
        detail.queue_position = await session.scalar(
            select(func.count(Task.id))
            .where(Task.status == TaskStatus.QUEUED, Task.queued_at < task.queued_at))
    return detail
