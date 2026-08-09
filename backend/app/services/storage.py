"""任务文件存储路径助手。"""
from pathlib import Path

from ..config import settings


def task_dir(user_id: int, task_id: int) -> Path:
    return settings.storage_root / str(user_id) / str(task_id)


def task_dir_from(task) -> Path:
    return settings.storage_root / task.storage_dir
