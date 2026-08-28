"""用户多程序工作区、任务暂存与归档路径助手。"""
from pathlib import Path

from ..config import settings
from .programs import (
    DCR_3D,
    DCR_PARAMS_FILE,
    MESH_DIR,
    MESH_FILE,
    PROGRAM_DLL,
    RESULT_DIR,
    get_program,
)

# 兼容旧调用；新代码必须通过 program_key 解析实际程序。
PROGRAM_EXE = get_program(DCR_3D).executable
PARAMS_FILE = DCR_PARAMS_FILE
PROGRAMS_DIR = "programs"
STAGING_DIR = "staging"
ARCHIVES_DIR = "archives"
WORKSPACE_STATE_DIR = ".workspace-state"
STDOUT_FILE = "stdout.txt"
STDERR_FILE = "stderr.txt"
TASK_META_FILE = "task.json"
UPLOADED_PARAMETER_FILE = "uploaded_parameter.dat"


def user_root(user_id: int) -> Path:
    return settings.storage_root / str(user_id)


def programs_root(user_id: int) -> Path:
    return user_root(user_id) / PROGRAMS_DIR


def program_root(user_id: int, program_key: str = DCR_3D) -> Path:
    return programs_root(user_id) / get_program(program_key).directory_name


def program_exe_path(user_id: int, program_key: str = DCR_3D) -> Path:
    spec = get_program(program_key)
    return program_root(user_id, program_key) / spec.executable


def program_dll_path(user_id: int, program_key: str = DCR_3D) -> Path:
    return program_root(user_id, program_key) / PROGRAM_DLL


def params_path(
    user_id: int,
    program_key: str = DCR_3D,
    filename: str | None = None,
) -> Path:
    spec = get_program(program_key)
    selected = filename or spec.parameter_files[0]
    if selected not in spec.parameter_files:
        raise ValueError(f"程序 {program_key} 不允许参数文件 {selected}")
    return program_root(user_id, program_key) / selected


def mesh_dir(user_id: int, program_key: str = DCR_3D) -> Path:
    return program_root(user_id, program_key) / MESH_DIR


def mesh_path(user_id: int, program_key: str = DCR_3D) -> Path:
    return mesh_dir(user_id, program_key) / MESH_FILE


def result_dir(user_id: int, program_key: str = DCR_3D) -> Path:
    return program_root(user_id, program_key) / RESULT_DIR


def staging_root(user_id: int) -> Path:
    return user_root(user_id) / STAGING_DIR


def staging_dir(user_id: int, task_id: int) -> Path:
    return staging_root(user_id) / str(task_id)


def archives_root(user_id: int) -> Path:
    return user_root(user_id) / ARCHIVES_DIR


def workspace_state_root(user_id: int) -> Path:
    return user_root(user_id) / WORKSPACE_STATE_DIR


def canonical_program_param_path(user_id: int, program_key: str, filename: str) -> Path:
    """一个受控程序参数文件的内部权威镜像。"""
    spec = get_program(program_key)
    if filename not in spec.parameter_files:
        raise ValueError(f"程序 {program_key} 不允许参数文件 {filename}")
    return workspace_state_root(user_id) / program_key / filename


def canonical_params_path(user_id: int) -> Path:
    """DCR 当前参数镜像兼容入口。"""
    return canonical_program_param_path(user_id, DCR_3D, DCR_PARAMS_FILE)


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
