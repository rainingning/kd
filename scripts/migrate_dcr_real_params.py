"""将旧 DCR 占位 JSON 工作区迁移为真实 model_DC.dat；绝不修改 archives。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app import db  # noqa: E402
from app.models import ACTIVE_WORKSPACE_STATUSES, Task, User  # noqa: E402
from app.param_schema import ParamValidationError, parse_params_bytes  # noqa: E402
from app.services.dcr_params import ensure_dcr_params_files  # noqa: E402
from app.services.program_sync import sync_user_program  # noqa: E402
from app.services.program_template import program_template_dir, validate_all_program_templates  # noqa: E402
from app.services.programs import DCR_3D, DCR_PARAMS_FILE  # noqa: E402
from app.services.storage import canonical_params_path, params_path, workspace_state_root  # noqa: E402


def _is_legacy_json(payload: bytes) -> bool:
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(value, dict) and bool(
        set(value) & {"grid_size", "time_step", "method", "enable_output", "mock_sleep", "mock_exit_code"})


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.migration-{uuid.uuid4().hex}")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def classify(path: Path) -> str:
    if not path.is_file():
        return "missing"
    payload = path.read_bytes()
    try:
        parse_params_bytes(payload)
        return "real"
    except ParamValidationError:
        return "legacy-json" if _is_legacy_json(payload) else "invalid"


def migrate_user(user_id: int, execute: bool, stamp: str) -> tuple[list[str], str | None]:
    canonical = canonical_params_path(user_id)
    runtime = params_path(user_id)
    canonical_kind = classify(canonical)
    runtime_kind = classify(runtime)
    actions = [f"canonical={canonical_kind} runtime={runtime_kind}"]
    if "invalid" in {canonical_kind, runtime_kind}:
        return actions, "检测到未知或损坏格式，已保留原文件，需人工修复"
    if canonical_kind == "real":
        actions.append("restore runtime from canonical")
        if execute:
            ensure_dcr_params_files(user_id)
        return actions, None
    if canonical_kind == "missing" and runtime_kind == "real":
        actions.append("adopt real runtime as canonical")
        if execute:
            ensure_dcr_params_files(user_id)
        return actions, None

    # 剩余情况仅为 missing/legacy-json：备份旧文件并用可信默认参数初始化。
    backup = workspace_state_root(user_id) / "migration-backups" / stamp
    default = program_template_dir(DCR_3D) / DCR_PARAMS_FILE
    for label, path, kind in (("canonical", canonical, canonical_kind), ("runtime", runtime, runtime_kind)):
        if kind == "legacy-json":
            target = backup / f"{label}-{DCR_PARAMS_FILE}.legacy.json"
            actions.append(f"backup {path} -> {target}")
            if execute:
                _atomic_copy(path, target)
    actions.append(f"seed real default -> {canonical} and {runtime}")
    if execute:
        _atomic_copy(default, canonical)
        _atomic_copy(default, runtime)
        ensure_dcr_params_files(user_id)
    return actions, None


async def main() -> int:
    parser = argparse.ArgumentParser(description="迁移 DCR 真实 model_DC.dat 当前参数")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backup-reference")
    parser.add_argument("--backup-checksum")
    args = parser.parse_args()
    if args.execute and (not args.backup_reference or not args.backup_checksum):
        parser.error("--execute 必须提供 --backup-reference 和 --backup-checksum")

    validate_all_program_templates()
    async with db.async_session() as session:
        active = await session.scalar(select(func.count(Task.id)).where(Task.status.in_(ACTIVE_WORKSPACE_STATUSES)))
        if active:
            print(f"REFUSED: {active} active tasks exist", file=sys.stderr)
            return 2
        user_ids = list((await session.scalars(select(User.id).order_by(User.id))).all())

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print("MODE=EXECUTE" if args.execute else "MODE=DRY-RUN")
    failures = 0
    for user_id in user_ids:
        actions, error = migrate_user(user_id, args.execute, stamp)
        for action in actions:
            print(f"user#{user_id}: {action}")
        if error:
            failures += 1
            print(f"user#{user_id}: ERROR {error}", file=sys.stderr)
            continue
        if args.execute:
            result = await sync_user_program(user_id)
            if result.status != "synced":
                failures += 1
                print(f"user#{user_id}: sync failed: {result.error or result.status}", file=sys.stderr)
    print(f"users={len(user_ids)} failures={failures}")
    return 0 if failures == 0 else 3


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
