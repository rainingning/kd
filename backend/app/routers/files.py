"""任务文件下载（T5.2，FR-HIST-03）。"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import Task, User
from ..services.storage import task_dir_from

router = APIRouter(prefix="/api/tasks", tags=["files"])

# kind -> (磁盘文件名, 下载文件名)；input 的下载名取原始上传文件名
_FILES = {
    "result": ("stdout.txt", "stdout.txt"),
    "stderr": ("stderr.txt", "stderr.txt"),
    "input": ("input.dat", None),
    "params": ("params.in", "params.in"),
}


@router.get("/{task_id}/files/{kind}")
async def download_file(
    task_id: int,
    kind: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    if kind not in _FILES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未知文件类型")
    task = await session.get(Task, task_id)
    if task is None or task.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")

    filename, download_name = _FILES[kind]
    if kind == "input":
        download_name = task.input_filename or "input.dat"
    path = task_dir_from(task) / filename
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件不存在")
    return FileResponse(path, filename=download_name)
