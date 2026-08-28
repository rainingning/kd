"""DCR_3D 当前 model_DC.dat 编辑、上传解析及历史归档加载 API。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import ACTIVE_WORKSPACE_STATUSES, ArchiveStatus, Task, User, UserProgram, WorkspaceStatus
from ..param_schema import (
    MAX_FILE_BYTES,
    SCHEMA_VERSION,
    ParamValidationError,
    parse_params_bytes,
    validate_params_with_warnings,
)
from ..schemas import DcrParamsSaveRequest
from ..scheduler.user_lock import try_user_workspace_lock
from ..services.dcr_params import (
    DcrParamsError,
    DcrParamsStaleError,
    get_current_document,
    get_default_document,
    save_current_document,
)
from ..services.program_template import sha256_file
from ..services.programs import DCR_3D, DCR_PARAMS_FILE
from ..services.storage import canonical_params_path, path_from_relative

router = APIRouter(prefix="/api/dcr-params", tags=["dcr-params"])
_CHUNK = 1024 * 1024


def _validation_422(exc: ParamValidationError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.errors)


async def _read_upload(source: UploadFile) -> bytes:
    original = (source.filename or "").replace("\\", "/").split("/")[-1]
    if not original.lower().endswith(".dat"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "参数文件必须是 .dat 文件")
    payload = bytearray()
    while chunk := await source.read(_CHUNK):
        payload.extend(chunk)
        if len(payload) > MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"参数文件不能超过 {MAX_FILE_BYTES // 1024 // 1024} MiB",
            )
    if not payload:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "参数文件不能为空")
    return bytes(payload)


@router.get("/current")
async def current_params(user: User = Depends(get_current_user)) -> dict:
    try:
        value = await asyncio.to_thread(get_current_document, user.id)
    except ParamValidationError as exc:
        raise _validation_422(exc) from exc
    except DcrParamsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return {**value.as_dict(), "source": "current"}


@router.get("/current/file")
async def download_current_params(user: User = Depends(get_current_user)):
    path = canonical_params_path(user.id)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "当前 DCR 参数不存在")
    return FileResponse(path, filename=DCR_PARAMS_FILE, media_type="text/plain; charset=utf-8")


@router.get("/default")
async def default_params(_: User = Depends(get_current_user)) -> dict:
    try:
        value = await asyncio.to_thread(get_default_document)
    except (DcrParamsError, ParamValidationError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"默认 DCR 参数不可用：{exc}") from exc
    return {**value.as_dict(), "source": "default"}


@router.post("/parse")
async def parse_uploaded_params(
    file: UploadFile = File(...),
    _: User = Depends(get_current_user),
) -> dict:
    payload = await _read_upload(file)
    try:
        document = await asyncio.to_thread(parse_params_bytes, payload)
        _, warnings = validate_params_with_warnings(document)
    except ParamValidationError as exc:
        raise _validation_422(exc) from exc
    return {
        "document": document,
        "sha256": None,
        "schema_version": SCHEMA_VERSION,
        "warnings": warnings,
        "source": "upload",
        "original_filename": (file.filename or DCR_PARAMS_FILE).replace("\\", "/").split("/")[-1],
    }


@router.put("/current")
async def update_current_params(
    body: DcrParamsSaveRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    installation = await session.scalar(select(UserProgram).where(
        UserProgram.user_id == user.id,
        UserProgram.program_key == DCR_3D,
    ))
    if installation is None or installation.workspace_status != WorkspaceStatus.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "DCR_3D 工作区尚未就绪")
    if body.source_task_id is not None:
        source = await session.get(Task, body.source_task_id)
        if (
            source is None or source.user_id != user.id or source.program_key != DCR_3D
            or source.archive_status != ArchiveStatus.COMPLETED
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "参数来源任务不存在或尚未完成归档")
    active = await session.scalar(select(func.count(Task.id)).where(
        Task.user_id == user.id,
        Task.status.in_(ACTIVE_WORKSPACE_STATUSES),
    ))
    if active:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"code": "workspace_busy", "message": "工作区正在运行或归档任务，请稍后保存"},
        )
    async with try_user_workspace_lock(user.id) as acquired:
        if not acquired:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"code": "workspace_busy", "message": "工作区锁忙，请稍后保存"},
            )
        try:
            value = await asyncio.to_thread(
                save_current_document,
                user.id,
                body.document,
                expected_sha256=body.expected_sha256,
            )
        except ParamValidationError as exc:
            raise _validation_422(exc) from exc
        except DcrParamsStaleError as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={
                    "code": "stale_revision",
                    "message": str(exc),
                    "current_sha256": exc.current_sha256,
                },
            ) from exc
        except (DcrParamsError, OSError) as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
    return {
        **value.as_dict(),
        "source": "current",
        "source_task_id": body.source_task_id,
    }


@router.get("/versions")
async def list_archived_versions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    condition = (
        Task.user_id == user.id,
        Task.program_key == DCR_3D,
        Task.archive_status == ArchiveStatus.COMPLETED,
        Task.archive_dir.is_not(None),
    )
    total = await session.scalar(select(func.count(Task.id)).where(*condition)) or 0
    rows = list((await session.scalars(
        select(Task).where(*condition)
        .order_by(Task.archived_at.desc(), Task.id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    )).all())
    return {
        "total": total,
        "items": [{
            "task_id": task.id,
            "archive_version": task.archive_version,
            "task_status": task.terminal_status or task.status,
            "archived_at": task.archived_at,
            "parameter_sha256": task.parameter_sha256
                or (task.runtime_file_hashes or {}).get(DCR_PARAMS_FILE),
            "schema_version": task.parameter_schema_version,
            "loadable": task.parameter_schema_version == SCHEMA_VERSION,
            "input_filename": task.input_filename,
        } for task in rows],
    }


@router.get("/versions/{task_id}")
async def archived_version(
    task_id: int,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    task = await session.get(Task, task_id)
    if (
        task is None or task.user_id != user.id or task.program_key != DCR_3D
        or task.archive_status != ArchiveStatus.COMPLETED or not task.archive_dir
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "DCR 参数历史版本不存在")
    try:
        root = path_from_relative(task.archive_dir)
        path = root / DCR_PARAMS_FILE
        payload = await asyncio.to_thread(path.read_bytes)
        document = await asyncio.to_thread(parse_params_bytes, payload)
        _, warnings = validate_params_with_warnings(document)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "历史归档缺少 model_DC.dat") from exc
    except ParamValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "incompatible_archive",
                "message": "该历史版本不是可加载的真实 DCR 参数格式，仍可从任务详情下载原文件",
                "errors": exc.errors,
            },
        ) from exc
    return {
        "document": document,
        "sha256": await asyncio.to_thread(sha256_file, path),
        "schema_version": SCHEMA_VERSION,
        "warnings": warnings,
        "source": "archive",
        "source_task_id": task.id,
        "archive_version": task.archive_version,
        "archived_at": task.archived_at,
    }
