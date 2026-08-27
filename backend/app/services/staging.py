"""排队任务暂存区文件写入。"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Protocol

from .storage import (
    MESH_FILE,
    PARAMS_FILE,
    STDERR_FILE,
    STDOUT_FILE,
    TASK_META_FILE,
    relative_to_storage,
    staging_dir,
)

_CHUNK = 1024 * 1024


class AsyncReadable(Protocol):
    async def read(self, size: int = -1) -> bytes: ...


class UploadTooLargeError(ValueError):
    pass


def _temporary_for(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp-{uuid.uuid4().hex}")


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = _temporary_for(path)
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def create_staging(user_id: int, task_id: int, params_content: str) -> Path:
    directory = staging_dir(user_id, task_id)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        atomic_write_text(directory / PARAMS_FILE, params_content)
        (directory / STDOUT_FILE).touch()
        (directory / STDERR_FILE).touch()
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    return directory


async def write_staged_upload(
    directory: Path,
    source: AsyncReadable,
    *,
    max_bytes: int,
) -> int:
    destination = directory / MESH_FILE
    temporary = _temporary_for(destination)
    size = 0
    try:
        with temporary.open("wb") as stream:
            while chunk := await source.read(_CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLargeError("文件超过大小上限")
                stream.write(chunk)
        os.replace(temporary, destination)
        return size
    finally:
        temporary.unlink(missing_ok=True)


def write_staging_metadata(directory: Path, metadata: dict[str, Any]) -> None:
    atomic_write_json(directory / TASK_META_FILE, metadata)


def remove_staging(directory: Path) -> None:
    if directory.exists():
        shutil.rmtree(directory)


def staging_relative(user_id: int, task_id: int) -> str:
    return relative_to_storage(staging_dir(user_id, task_id))
