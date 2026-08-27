"""任务版本归档：临时目录完成后原子发布。"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .storage import (
    MESH_DIR,
    MESH_FILE,
    PARAMS_FILE,
    RESULT_DIR,
    STDERR_FILE,
    STDOUT_FILE,
    TASK_META_FILE,
    archive_dir,
    archives_root,
    mesh_path,
    params_path,
    relative_to_storage,
    result_dir,
)


class ArchiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArchiveResult:
    version: str
    relative_dir: str
    archived_at: datetime
    result_file_count: int
    result_size_bytes: int


def archive_version(task_id: int, archived_at: datetime | None = None) -> str:
    instant = archived_at or datetime.now(timezone.utc)
    instant = instant.astimezone(timezone.utc)
    stamp = instant.strftime("%Y%m%dT%H%M%S") + f".{instant.microsecond // 1000:03d}Z"
    return f"{stamp}_task{task_id}"


def _copy_required(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ArchiveError(f"归档源文件不存在：{source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_optional(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination)
    else:
        destination.touch()


def _result_stats(directory: Path) -> tuple[int, int]:
    count = 0
    size = 0
    for path in directory.rglob("*"):
        if path.is_file():
            count += 1
            size += path.stat().st_size
    return count, size


def remove_temporary_archives(user_id: int) -> int:
    """用户锁内清理未发布的临时归档目录。正式归档目录永不删除。"""
    root = archives_root(user_id)
    if not root.is_dir():
        return 0
    removed = 0
    for path in root.glob(".tmp_*"):
        if path.is_dir():
            shutil.rmtree(path)
            removed += 1
    return removed


def archive_task_files(
    *,
    user_id: int,
    task_id: int,
    staging: Path,
    metadata: dict[str, Any],
    workspace_was_used: bool,
    archived_at: datetime | None = None,
    version: str | None = None,
) -> ArchiveResult:
    """归档任务文件。

    运行过的任务从固定工作区取参数/输入/Forward_data；未运行的排队取消任务
    从 staging 取参数/输入，并生成空 Forward_data。
    """
    instant = (archived_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    version = version or archive_version(task_id, instant)
    root = archives_root(user_id)
    root.mkdir(parents=True, exist_ok=True)
    destination = archive_dir(user_id, version)
    if destination.exists():
        try:
            existing = json.loads((destination / TASK_META_FILE).read_text(encoding="utf-8"))
            if existing.get("task_id") != task_id:
                raise ArchiveError(f"归档版本冲突：{version}")
            existing_time = datetime.fromisoformat(existing["archived_at"])
            return ArchiveResult(
                version=version,
                relative_dir=relative_to_storage(destination),
                archived_at=existing_time,
                result_file_count=int(existing["result_file_count"]),
                result_size_bytes=int(existing["result_size_bytes"]),
            )
        except ArchiveError:
            raise
        except Exception as exc:
            raise ArchiveError(f"已有归档不完整：{version}：{exc}") from exc
    temporary = root / f".tmp_{task_id}_{uuid.uuid4().hex}"

    try:
        temporary.mkdir(parents=False, exist_ok=False)
        if workspace_was_used:
            params_source = params_path(user_id)
            mesh_source = mesh_path(user_id)
        else:
            params_source = staging / PARAMS_FILE
            mesh_source = staging / MESH_FILE

        _copy_required(params_source, temporary / PARAMS_FILE)
        _copy_required(mesh_source, temporary / MESH_DIR / MESH_FILE)
        _copy_optional(staging / STDOUT_FILE, temporary / STDOUT_FILE)
        _copy_optional(staging / STDERR_FILE, temporary / STDERR_FILE)

        archived_results = temporary / RESULT_DIR
        if workspace_was_used and result_dir(user_id).is_dir():
            shutil.copytree(result_dir(user_id), archived_results)
        else:
            archived_results.mkdir(parents=True, exist_ok=True)
        result_count, result_size = _result_stats(archived_results)

        task_metadata = dict(metadata)
        task_metadata.update({
            "archive_version": version,
            "archived_at": instant.isoformat(),
            "result_file_count": result_count,
            "result_size_bytes": result_size,
        })
        (temporary / TASK_META_FILE).write_text(
            json.dumps(task_metadata, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temporary, destination)
    except Exception as exc:
        shutil.rmtree(temporary, ignore_errors=True)
        if isinstance(exc, ArchiveError):
            raise
        raise ArchiveError(f"任务 #{task_id} 归档失败：{exc}") from exc

    return ArchiveResult(
        version=version,
        relative_dir=relative_to_storage(destination),
        archived_at=instant,
        result_file_count=result_count,
        result_size_bytes=result_size,
    )
