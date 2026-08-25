"""从不可变任务归档下载参数、输入、结果 ZIP 和运行日志。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import ArchiveStatus, Task, User
from ..services.result_zip import ResultZipError, ensure_result_zip
from ..services.storage import (
    MESH_DIR,
    MESH_FILE,
    PARAMS_FILE,
    STDERR_FILE,
    STDOUT_FILE,
    path_from_relative,
)

router = APIRouter(prefix="/api/tasks", tags=["files"])

_FILES = {
    "stderr": (Path(STDERR_FILE), STDERR_FILE),
    "stdout": (Path(STDOUT_FILE), STDOUT_FILE),
    "input": (Path(MESH_DIR) / MESH_FILE, None),
    "params": (Path(PARAMS_FILE), PARAMS_FILE),
}


def _safe_download_name(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    name = value.replace("\\", "/").split("/")[-1].strip()
    return name or fallback


@router.get("/{task_id}/files/{kind}")
async def download_file(
    task_id: int,
    kind: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if kind not in (*_FILES.keys(), "result"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未知文件类型")
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    if task.archive_status != ArchiveStatus.COMPLETED or not task.archive_dir:
        raise HTTPException(status.HTTP_409_CONFLICT, "任务尚未完成归档")

    try:
        archived = path_from_relative(task.archive_dir)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "任务归档路径无效") from exc

    if kind == "result":
        if not task.archive_version:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "任务缺少归档版本")
        try:
            path = await asyncio.to_thread(
                ensure_result_zip, task.id, task.archive_version, archived)
        except ResultZipError as exc:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc)) from exc
        return FileResponse(path, filename=f"task_{task.id}_Forward_data.zip")

    relative, download_name = _FILES[kind]
    if kind == "input":
        download_name = _safe_download_name(task.input_filename, MESH_FILE)
    path = archived / relative
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "归档文件不存在")
    return FileResponse(path, filename=download_name)
