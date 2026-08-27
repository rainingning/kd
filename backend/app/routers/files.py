"""从不可变任务归档下载参数、输入、结果 ZIP 和运行日志。"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import ArchiveStatus, Task, User
from ..services.programs import (
    DCR_3D, DCR_PARAMS_FILE, GROUNDED_WIRE_FILE, LOOP_SOURCE_FILE,
    MESH_DIR, MESH_FILE,
)
from ..services.result_zip import ResultZipError, ensure_result_zip
from ..services.storage import STDERR_FILE, STDOUT_FILE, path_from_relative

router = APIRouter(prefix="/api/tasks", tags=["files"])

_STATIC_FILES = {
    "stderr": (Path(STDERR_FILE), STDERR_FILE),
    "stdout": (Path(STDOUT_FILE), STDOUT_FILE),
    "input": (Path(MESH_DIR) / MESH_FILE, None),
}
_PARAMETER_KINDS = {
    "grounded-params": GROUNDED_WIRE_FILE,
    "loop-params": LOOP_SOURCE_FILE,
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
    allowed = (*_STATIC_FILES.keys(), *_PARAMETER_KINDS.keys(), "params", "result")
    if kind not in allowed:
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
        return FileResponse(
            path, filename=f"task_{task.id}_{task.program_key}_Forward_data.zip")

    if kind in _STATIC_FILES:
        relative, download_name = _STATIC_FILES[kind]
        if kind == "input":
            download_name = _safe_download_name(task.input_filename, MESH_FILE)
    elif kind == "params":
        filename = DCR_PARAMS_FILE if task.program_key == DCR_3D else task.parameter_filename
        if not filename:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "任务没有所选参数文件")
        relative, download_name = Path(filename), filename
    else:
        if task.program_key == DCR_3D:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "DCR_3D 不包含该参数文件")
        filename = _PARAMETER_KINDS[kind]
        relative, download_name = Path(filename), filename

    path = archived / relative
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "归档文件不存在")
    return FileResponse(path, filename=download_name)
