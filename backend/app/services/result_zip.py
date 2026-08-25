"""从不可变任务归档生成 Forward_data ZIP 缓存。"""
from __future__ import annotations

import os
import uuid
import zipfile
from pathlib import Path

from ..config import settings
from .storage import RESULT_DIR


class ResultZipError(RuntimeError):
    pass


def _safe_files(root: Path):
    resolved_root = root.resolve()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ResultZipError(f"结果目录不允许符号链接：{path}")
        if not path.is_file():
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ResultZipError(f"结果路径越界：{path}") from exc
        yield resolved, relative


def ensure_result_zip(task_id: int, archive_version: str, archive_root: Path) -> Path:
    results = archive_root / RESULT_DIR
    if not results.is_dir():
        raise ResultZipError("归档中不存在 Forward_data 目录")

    cache_root = settings.result_zip_cache_root
    cache_root.mkdir(parents=True, exist_ok=True)
    safe_version = "".join(
        c for c in archive_version if c.isalnum() or c in ("-", "_", "."))
    if safe_version != archive_version:
        raise ResultZipError("归档版本号包含非法字符")
    target = cache_root / f"task_{task_id}_{safe_version}.zip"
    if target.is_file():
        return target

    temporary = target.with_name(f".{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        with zipfile.ZipFile(
            temporary, mode="w", compression=zipfile.ZIP_DEFLATED, allowZip64=True,
        ) as archive:
            wrote_file = False
            for source, relative in _safe_files(results):
                wrote_file = True
                archive.write(source, (Path(RESULT_DIR) / relative).as_posix())
            if not wrote_file:
                archive.writestr(f"{RESULT_DIR}/", b"")
        os.replace(temporary, target)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        if isinstance(exc, ResultZipError):
            raise
        raise ResultZipError(f"结果 ZIP 生成失败：{exc}") from exc
    return target


def cached_zip_path(task_id: int, archive_version: str) -> Path:
    return settings.result_zip_cache_root / f"task_{task_id}_{archive_version}.zip"
