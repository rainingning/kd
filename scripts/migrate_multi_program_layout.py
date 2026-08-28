"""将旧 DCR 根工作区迁入 programs/dcr_3d，并初始化三个程序。

默认 dry-run；执行时必须声明外部数据库/storage 备份引用及校验值。
Alembic 必须先升级到最新版本。
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import func, select  # noqa: E402

from app import db  # noqa: E402
from app.models import ACTIVE_WORKSPACE_STATUSES, Task, User  # noqa: E402
from app.services.program_sync import sync_user_program  # noqa: E402
from app.services.program_template import validate_all_program_templates  # noqa: E402
from app.services.storage import program_root, user_root  # noqa: E402

LEGACY_RUNTIME_NAMES = (
    "DCR_3D.exe",
    "libiomp5md.dll",
    "model_DC.dat",
    "mesh",
    "Forward_data",
)


def migrate_user_files(user_id: int, execute: bool) -> list[str]:
    root = user_root(user_id)
    target = program_root(user_id, "dcr_3d")
    actions: list[str] = []
    for name in LEGACY_RUNTIME_NAMES:
        source = root / name
        destination = target / name
        if not source.exists():
            continue
        if destination.exists():
            actions.append(f"SKIP {source}: target already exists")
            continue
        actions.append(f"MOVE {source} -> {destination}")
        if execute:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
    return actions


async def main() -> int:
    parser = argparse.ArgumentParser(description="迁移三科学计算程序工作区布局")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--backup-reference")
    parser.add_argument("--backup-checksum")
    args = parser.parse_args()
    if args.execute and (not args.backup_reference or not args.backup_checksum):
        parser.error("--execute 必须同时提供 --backup-reference 和 --backup-checksum")

    validate_all_program_templates()
    async with db.async_session() as session:
        active = await session.scalar(select(func.count(Task.id)).where(
            Task.status.in_(ACTIVE_WORKSPACE_STATUSES)))
        if active:
            print(f"REFUSED: {active} active tasks exist", file=sys.stderr)
            return 2
        user_ids = list((await session.scalars(select(User.id).order_by(User.id))).all())

    print("MODE=EXECUTE" if args.execute else "MODE=DRY-RUN")
    if args.execute:
        print(f"BACKUP={args.backup_reference} CHECKSUM={args.backup_checksum}")
    for user_id in user_ids:
        for action in migrate_user_files(user_id, args.execute):
            print(f"user#{user_id}: {action}")
        if args.execute:
            result = await sync_user_program(user_id)
            if result.status != "synced":
                print(f"FAILED user#{user_id}: {result.error or result.status}", file=sys.stderr)
                return 3
            print(f"user#{user_id}: initialized all programs")
    print(f"users={len(user_ids)} completed")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(asyncio.run(main()))
