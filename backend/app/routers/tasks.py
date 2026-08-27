"""任务提交与取消（T4.1 / T4.4）。任务查询、文件下载见 P5。"""
import asyncio
import json
import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import ArchiveStatus, Task, TaskStatus, User, WorkspaceStatus, utcnow
from ..param_schema import ParamValidationError, serialize_params, validate_params
from ..scheduler.runner import request_cancel
from ..scheduler.user_lock import lock_task_submission
from ..schemas import TaskDetailResponse, TaskListResponse, TaskResponse
from ..services.archive import ArchiveError, archive_task_files, archive_version
from ..services.config import get_int
from ..services.storage import path_from_relative
from ..services.staging import (
    UploadTooLargeError,
    create_staging,
    remove_staging,
    staging_relative,
    write_staged_upload,
    write_staging_metadata,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=e.errors)

    if user.workspace_status != WorkspaceStatus.READY:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "用户工作区尚未就绪，请联系管理员修复",
        )

    # 防止同一用户并发提交同时通过排队上限检查。
    await lock_task_submission(session, user.id)
    queued_count = await session.scalar(
        select(func.count(Task.id)).where(Task.user_id == user.id, Task.status == TaskStatus.QUEUED))
    if (queued_count or 0) >= await get_int(session, "max_queued_per_user"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "排队任务数已达上限，请稍后再提交")

    original_filename = (file.filename or "mesh.mphtxt").replace("\\", "/").split("/")[-1]
    task = Task(
        user_id=user.id,
        status=TaskStatus.QUEUED,
        archive_status=ArchiveStatus.PENDING,
        params=normalized,
        input_filename=original_filename,
        program_version=user.program_version,
        exe_sha256=user.exe_sha256,
        dll_sha256=user.dll_sha256,
    )
    session.add(task)
    await session.flush()  # 取 task.id 用于 staging 目录命名

    max_bytes = (await get_int(session, "max_upload_mb")) * 1024 * 1024
    stage = None
    try:
        stage = await asyncio.to_thread(
            create_staging, user.id, task.id, serialize_params(normalized))
        size = await write_staged_upload(stage, file, max_bytes=max_bytes)
        await asyncio.to_thread(write_staging_metadata, stage, {
            "task_id": task.id,
            "user_id": user.id,
            "original_input_filename": original_filename,
            "params": normalized,
            "queued_at": task.queued_at.isoformat() if task.queued_at else utcnow().isoformat(),
            "input_size_bytes": size,
        })
        task.staging_dir = staging_relative(user.id, task.id)
    except UploadTooLargeError as exc:
        if stage is not None:
            await asyncio.to_thread(remove_staging, stage)
        await session.rollback()
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, str(exc)) from exc
    except Exception:
        if stage is not None:
            await asyncio.to_thread(remove_staging, stage)
        await session.rollback()
        raise

    await session.commit()
    logger.info(
        "任务 #%s 暂存完成：user=%s input=%s bytes=%s staging=%s",
        task.id, user.id, original_filename, size, task.staging_dir,
    )
    return task


async def _archive_queued_task(
    task: Task,
    session: AsyncSession,
    *,
    final_status: str,
    reason: str,
) -> Task:
    """未进入固定工作区的排队任务从 staging 直接归档。"""
    stage = path_from_relative(task.staging_dir)
    task.status = TaskStatus.ARCHIVING
    task.archive_status = ArchiveStatus.ARCHIVING
    task.terminal_status = final_status
    task.workspace_was_used = False
    task.archive_version = task.archive_version or archive_version(task.id)
    task.error_message = reason
    finished = utcnow()
    await session.commit()
    try:
        archived = await asyncio.to_thread(
            archive_task_files,
            user_id=task.user_id,
            task_id=task.id,
            staging=stage,
            metadata={
                "task_id": task.id,
                "user_id": task.user_id,
                "original_input_filename": task.input_filename,
                "params": task.params,
                "status": final_status,
                "reason": reason,
                "exit_code": task.exit_code,
                "queued_at": task.queued_at.isoformat() if task.queued_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "finished_at": finished.isoformat(),
                "duration_sec": None,
                "program_version": task.program_version,
                "exe_sha256": task.exe_sha256,
                "dll_sha256": task.dll_sha256,
            },
            workspace_was_used=False,
            version=task.archive_version,
        )
    except ArchiveError as exc:
        task.status = TaskStatus.ARCHIVE_FAILED
        task.archive_status = ArchiveStatus.FAILED
        task.archive_error = str(exc)
        task.archive_retry_count = (task.archive_retry_count or 0) + 1
        delay = min(5 * (2 ** (task.archive_retry_count - 1)), 300)
        task.archive_retry_at = utcnow() + timedelta(seconds=delay)
        await session.commit()
        return task

    task.status = final_status
    task.archive_status = ArchiveStatus.COMPLETED
    task.archive_error = None
    task.archive_retry_at = None
    task.archive_version = archived.version
    task.archive_dir = archived.relative_dir
    task.archived_at = archived.archived_at
    task.result_file_count = archived.result_file_count
    task.result_size_bytes = archived.result_size_bytes
    task.finished_at = finished
    await session.commit()
    await asyncio.to_thread(remove_staging, stage)
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
        return await _archive_queued_task(
            task, session, final_status=TaskStatus.CANCELED, reason="用户取消")

    if task.status in (TaskStatus.PREPARING, TaskStatus.RUNNING):
        request_cancel(task_id, kind="user")
        return task  # runner 在启动前或进程退出后负责归档并落 CANCELED

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
