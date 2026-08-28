"""迁移 BE_FETD/FDEM3D 四个当前参数并只读识别历史归档。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app import db  # noqa: E402
from app.em_param_schema import (  # noqa: E402
    ParamValidationError,
    parse_parameter_bytes,
    schema_version_for,
)
from app.models import (  # noqa: E402
    ACTIVE_WORKSPACE_STATUSES,
    ArchiveStatus,
    Task,
    User,
    UserProgram,
    WorkspaceStatus,
)
from app.services.program_sync import sync_user_program  # noqa: E402
from app.services.program_template import (  # noqa: E402
    program_template_dir,
    validate_all_program_templates,
)
from app.services.programs import DCR_3D, get_program, list_programs  # noqa: E402
from app.services.storage import (  # noqa: E402
    canonical_program_param_path,
    params_path,
    path_from_relative,
    workspace_state_root,
)


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.migration-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _known_placeholder(payload: bytes) -> bool:
    text = payload.decode("utf-8", errors="ignore").lower()
    return "source_type = grounded_wire" in text or "source_type = loop" in text or text.startswith("default ")


def classify(path: Path, program_key: str, source_type: str) -> str:
    if not path.is_file():
        return "missing"
    payload = path.read_bytes()
    try:
        parse_parameter_bytes(program_key, source_type, payload)
        return "real"
    except ParamValidationError:
        return "legacy-placeholder" if _known_placeholder(payload) else "invalid"


def migrate_file(
    user_id: int,
    program_key: str,
    source_type: str,
    filename: str,
    *,
    execute: bool,
    stamp: str,
) -> tuple[list[str], str | None]:
    canonical = canonical_program_param_path(user_id, program_key, filename)
    runtime = params_path(user_id, program_key, filename)
    canonical_kind = classify(canonical, program_key, source_type)
    runtime_kind = classify(runtime, program_key, source_type)
    actions = [f"{program_key}/{filename}: canonical={canonical_kind} runtime={runtime_kind}"]
    backup = workspace_state_root(user_id) / "migration-backups" / stamp

    if canonical_kind == "real":
        if runtime_kind != "real" or _sha(runtime) != _sha(canonical):
            actions.append("restore runtime from authoritative canonical")
            if execute:
                if runtime.is_file() and runtime_kind != "missing":
                    _atomic_copy(runtime, backup / f"{program_key}-{filename}.runtime-before-restore")
                _atomic_copy(canonical, runtime)
        return actions, None
    if canonical_kind == "invalid":
        return actions, "权威镜像为未知无效格式，已保留，需人工修复"
    if canonical_kind == "missing" and runtime_kind == "real":
        actions.append("adopt real runtime as canonical")
        if execute:
            _atomic_copy(runtime, canonical)
        return actions, None
    if runtime_kind == "invalid":
        return actions, "工作目录文件为未知无效格式，已保留，需人工修复"

    for label, path, kind in (
        ("canonical", canonical, canonical_kind),
        ("runtime", runtime, runtime_kind),
    ):
        if kind == "legacy-placeholder":
            target = backup / f"{program_key}-{filename}.{label}.legacy"
            actions.append(f"backup {path} -> {target}")
            if execute:
                _atomic_copy(path, target)
    default = program_template_dir(program_key) / filename
    actions.append(f"seed real default -> canonical and runtime ({default})")
    if execute:
        _atomic_copy(default, canonical)
        _atomic_copy(default, runtime)
    return actions, None


async def migrate_archives(execute: bool) -> tuple[int, int]:
    """只读 archive；正式模式只回填数据库 Task 元数据。"""
    scanned = updated = 0
    async with db.async_session() as session:
        rows = list((await session.scalars(select(Task).where(
            Task.program_key.in_(["be_fetd", "fdem3d_frequency_domain"]),
            Task.archive_status == ArchiveStatus.COMPLETED,
            Task.archive_dir.is_not(None),
            Task.source_type.is_not(None),
        ))).all())
        for task in rows:
            scanned += 1
            try:
                choice = get_program(task.program_key).choice_by_source(task.source_type)
                path = path_from_relative(task.archive_dir) / choice.filename
                payload = path.read_bytes()
                before = _sha(path)
                document = parse_parameter_bytes(task.program_key, task.source_type, payload)
                after = _sha(path)
                if before != after:
                    raise RuntimeError("archive hash changed during read-only scan")
            except (OSError, ValueError, ParamValidationError):
                continue
            updated += 1
            print(f"task#{task.id}: loadable {task.program_key}/{task.source_type} sha={before[:12]}")
            if execute:
                task.params = document
                task.parameter_schema_version = schema_version_for(task.program_key)
                task.parameter_sha256 = before
        if execute:
            await session.commit()
    return scanned, updated


async def mark_failures(user_ids: set[int], message: str) -> None:
    if not user_ids:
        return
    async with db.async_session() as session:
        users = list((await session.scalars(select(User).where(User.id.in_(user_ids)))).all())
        programs = list((await session.scalars(select(UserProgram).where(
            UserProgram.user_id.in_(user_ids),
            UserProgram.program_key.in_(["be_fetd", "fdem3d_frequency_domain"]),
        ))).all())
        for user in users:
            user.workspace_status = WorkspaceStatus.ERROR
            user.workspace_error = message
        for program in programs:
            program.workspace_status = WorkspaceStatus.ERROR
            program.workspace_error = message
        await session.commit()


async def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 BE/FDEM 真实源参数")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backup-reference")
    parser.add_argument("--backup-checksum")
    args = parser.parse_args()
    if args.execute and (not args.backup_reference or not args.backup_checksum):
        parser.error("--execute 必须提供 --backup-reference 和 --backup-checksum")

    validate_all_program_templates()
    async with db.async_session() as session:
        active = await session.scalar(select(func.count(Task.id)).where(
            Task.status.in_(ACTIVE_WORKSPACE_STATUSES)))
        if active:
            print(f"REFUSED: {active} active tasks exist", file=sys.stderr)
            return 2
        user_ids = list((await session.scalars(select(User.id).order_by(User.id))).all())

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("MODE=EXECUTE" if args.execute else "MODE=DRY-RUN")
    failed_users: set[int] = set()
    for user_id in user_ids:
        for spec in list_programs():
            if spec.key == DCR_3D:
                continue
            for choice in spec.source_choices:
                actions, error = migrate_file(
                    user_id, spec.key, choice.source_type, choice.filename,
                    execute=args.execute, stamp=stamp,
                )
                for action in actions:
                    print(f"user#{user_id}: {action}")
                if error:
                    failed_users.add(user_id)
                    print(f"user#{user_id}: ERROR {error}", file=sys.stderr)
        if args.execute and user_id not in failed_users:
            result = await sync_user_program(user_id)
            if result.status != "synced":
                failed_users.add(user_id)
                print(f"user#{user_id}: sync failed: {result.error or result.status}", file=sys.stderr)

    scanned, loadable = await migrate_archives(args.execute)
    if args.execute:
        await mark_failures(failed_users, "BE/FDEM 真实参数迁移发现未知无效文件")
    print(f"users={len(user_ids)} failures={len(failed_users)} archives_scanned={scanned} archives_loadable={loadable}")
    return 0 if not failed_users else 3


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
