"""用户固定工作区、任务暂存与归档路径助手。"""
from pathlib import Path

from ..config import settings

PROGRAM_EXE = "DCR_3D.exe"
PROGRAM_DLL = "libiomp5md.dll"
PARAMS_FILE = "model_DC.dat"
MESH_DIR = "mesh"
MESH_FILE = "mesh.mphtxt"
RESULT_DIR = "Forward_data"
STAGING_DIR = "staging"
ARCHIVES_DIR = "archives"
STDOUT_FILE = "stdout.txt"
STDERR_FILE = "stderr.txt"
TASK_META_FILE = "task.json"


def user_root(user_id: int) -> Path:
    return settings.storage_root / str(user_id)


def program_exe_path(user_id: int) -> Path:
    return user_root(user_id) / PROGRAM_EXE


def program_dll_path(user_id: int) -> Path:
    return user_root(user_id) / PROGRAM_DLL


def params_path(user_id: int) -> Path:
    return user_root(user_id) / PARAMS_FILE


def mesh_dir(user_id: int) -> Path:
    return user_root(user_id) / MESH_DIR


def mesh_path(user_id: int) -> Path:
    return mesh_dir(user_id) / MESH_FILE


def result_dir(user_id: int) -> Path:
    return user_root(user_id) / RESULT_DIR


def staging_root(user_id: int) -> Path:
    return user_root(user_id) / STAGING_DIR


def staging_dir(user_id: int, task_id: int) -> Path:
    return staging_root(user_id) / str(task_id)


def archives_root(user_id: int) -> Path:
    return user_root(user_id) / ARCHIVES_DIR


def archive_dir(user_id: int, version: str) -> Path:
    return archives_root(user_id) / version


def relative_to_storage(path: Path) -> str:
    """返回使用正斜杠的 storage 相对路径。"""
    return path.resolve().relative_to(settings.storage_root.resolve()).as_posix()


def path_from_relative(relative: str | None) -> Path:
    """安全解析数据库中的 storage 相对路径，拒绝越界路径。"""
    if not relative:
        raise ValueError("存储相对路径为空")
    root = settings.storage_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("存储路径越界") from exc
    return candidate


# ---- 旧任务目录兼容；完成切换并清空旧历史后删除 ----
def task_dir(user_id: int, task_id: int) -> Path:
    return user_root(user_id) / str(task_id)


def task_dir_from(task) -> Path:
    return path_from_relative(task.storage_dir)
