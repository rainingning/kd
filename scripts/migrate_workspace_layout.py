"""旧任务历史清理及用户固定工作区初始化。

默认仅 dry-run：
    .venv/Scripts/python scripts/migrate_workspace_layout.py

确认已停止服务并完成 DB/storage 双备份后执行：
    .venv/Scripts/python scripts/migrate_workspace_layout.py \
        --execute --backup-reference "D:/backup/2026-08-08" \
        --backup-checksum "backup-manifest-sha256"

必须先执行 `alembic upgrade head`。脚本不会删除用户、参数模板和审计日志。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import psutil  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db import async_session  # noqa: E402
from app.models import (  # noqa: E402
    ACTIVE_WORKSPACE_STATUSES,
    AuditLog,
    Notification,
    Task,
    User,
    WorkspaceStatus,
    utcnow,
)
from app.services.workspace import (  # noqa: E402
    WorkspaceError, check_workspace, initialize_workspace,
)


def _legacy_task_dirs(user_ids: list[int]) -> list[Path]:
    paths: list[Path] = []
    for user_id in user_ids:
        root = settings.storage_root / str(user_id)
        if not root.is_dir():
            continue
        # 旧结构为 storage/{user_id}/{task_id}/，task_id 是纯数字。
        paths.extend(path for path in root.iterdir() if path.is_dir() and path.name.isdigit())
    return paths


def _stage_legacy_directories(paths: list[Path]) -> list[tuple[Path, Path]]:
    """先在同一文件系统原子改名；任一步失败则恢复已改名目录。"""
    staged: list[tuple[Path, Path]] = []
    try:
        for original in paths:
            tombstone = original.with_name(
                f".legacy-task-{original.name}-{uuid.uuid4().hex}")
            original.rename(tombstone)
            staged.append((original, tombstone))
    except OSError:
        for original, tombstone in reversed(staged):
            if tombstone.exists() and not original.exists():
                tombstone.rename(original)
        raise
    return staged


def _restore_staged_directories(staged: list[tuple[Path, Path]]) -> None:
    for original, tombstone in reversed(staged):
        if tombstone.exists() and not original.exists():
            tombstone.rename(original)


def _delete_staged_directories(staged: list[tuple[Path, Path]]) -> tuple[list[str], list[dict]]:
    removed: list[str] = []
    failures: list[dict] = []
    for original, tombstone in staged:
        try:
            shutil.rmtree(tombstone)
            removed.append(str(original))
        except OSError as exc:
            failures.append({
                "path": str(original),
                "tombstone": str(tombstone),
                "error": str(exc),
            })
    return removed, failures


def _running_compute_processes() -> list[dict]:
    root = settings.storage_root.resolve()
    matches: list[dict] = []
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(process.info.get("name") or "").lower()
            command = [str(item) for item in (process.info.get("cmdline") or [])]
            is_compute = name == "dcr_3d.exe" or any(
                Path(item).name.lower() == "mock_dcr3d.py" for item in command)
            if not is_compute:
                continue
            cwd = Path(process.cwd()).resolve()
            if cwd == root or cwd.is_relative_to(root):
                matches.append({"pid": process.pid, "name": name, "cwd": str(cwd)})
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError, ValueError):
            continue
    return matches


async def collect_plan() -> dict:
    async with async_session() as session:
        user_ids = list((await session.scalars(select(User.id).order_by(User.id))).all())
        task_count = int(await session.scalar(select(func.count(Task.id))) or 0)
        notification_count = int(await session.scalar(
            select(func.count(Notification.id)).where(Notification.task_id.isnot(None))) or 0)
        active_count = int(await session.scalar(select(func.count(Task.id)).where(
            Task.status.in_(ACTIVE_WORKSPACE_STATUSES))) or 0)
    old_dirs = await asyncio.to_thread(_legacy_task_dirs, user_ids)
    running_processes = await asyncio.to_thread(_running_compute_processes)
    return {
        "users": user_ids,
        "task_count": task_count,
        "notification_count": notification_count,
        "active_task_count": active_count,
        "running_compute_processes": running_processes,
        "legacy_task_dirs": [str(path) for path in old_dirs],
    }


async def execute_migration(plan: dict, backup_reference: str, backup_checksum: str) -> dict:
    if plan["active_task_count"]:
        raise RuntimeError("仍有准备、运行或归档中的任务，拒绝迁移")
    if plan["running_compute_processes"]:
        raise RuntimeError(
            f"仍有 {len(plan['running_compute_processes'])} 个计算进程，拒绝迁移")

    report = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "backup_reference": backup_reference,
        "backup_checksum": backup_checksum,
        "plan": plan,
        "removed_task_dirs": [],
        "directory_failures": [],
        "initialized_users": [],
        "user_failures": [],
    }

    # 先原子改名隔离旧目录。数据库事务失败时可原名恢复，避免 DB/文件单边清理。
    old_dirs = [Path(value) for value in plan["legacy_task_dirs"]]
    try:
        staged_dirs = await asyncio.to_thread(_stage_legacy_directories, old_dirs)
    except OSError as exc:
        raise RuntimeError(f"旧任务目录预清理失败，数据库尚未修改：{exc}") from exc

    # 仅清理任务通知；无 task_id 的平台通知不属于旧任务历史。
    try:
        async with async_session() as session:
            await session.execute(delete(Notification).where(Notification.task_id.isnot(None)))
            await session.execute(delete(Task))
            session.add(AuditLog(
                admin_id=None,
                action="migration.clear_legacy_tasks",
                target="all_tasks",
                detail={
                    "backup_reference": backup_reference,
                    "backup_checksum": backup_checksum,
                    "task_count": plan["task_count"],
                    "notification_count": plan["notification_count"],
                },
            ))
            await session.commit()
    except Exception:
        await asyncio.to_thread(_restore_staged_directories, staged_dirs)
        raise

    removed, failures = await asyncio.to_thread(_delete_staged_directories, staged_dirs)
    report["removed_task_dirs"] = removed
    report["directory_failures"] = failures

    for user_id in plan["users"]:
        try:
            manifest = await asyncio.to_thread(initialize_workspace, user_id)
            check = await asyncio.to_thread(
                check_workspace,
                user_id,
                expected_version=manifest.version,
                expected_exe_sha256=manifest.exe_sha256,
                expected_dll_sha256=manifest.dll_sha256,
            )
            if not check.ready:
                raise WorkspaceError("；".join(check.errors))
            async with async_session() as session:
                user = await session.get(User, user_id)
                if user is None:
                    raise RuntimeError("用户记录在迁移过程中消失")
                user.workspace_status = WorkspaceStatus.READY
                user.workspace_error = None
                user.program_version = manifest.version
                user.exe_sha256 = manifest.exe_sha256
                user.dll_sha256 = manifest.dll_sha256
                user.program_synced_at = utcnow()
                user.program_sync_pending = False
                await session.commit()
            report["initialized_users"].append(user_id)
        except (OSError, RuntimeError, WorkspaceError) as exc:
            report["user_failures"].append({"user_id": user_id, "error": str(exc)})
            async with async_session() as session:
                user = await session.get(User, user_id)
                if user is not None:
                    user.workspace_status = WorkspaceStatus.ERROR
                    user.workspace_error = str(exc)
                    await session.commit()

    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["success"] = not report["directory_failures"] and not report["user_failures"]
    return report


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="迁移为用户固定工作区并清空旧任务历史")
    parser.add_argument("--execute", action="store_true", help="实际执行；未指定时仅 dry-run")
    parser.add_argument("--backup-reference", help="DB 和 storage 双备份的位置/编号")
    parser.add_argument("--backup-checksum", help="双备份清单文件或备份集的校验值")
    parser.add_argument("--report", type=Path, help="JSON 报告输出路径")
    args = parser.parse_args()

    plan = await collect_plan()
    if not args.execute:
        print(json.dumps({"mode": "dry-run", **plan}, ensure_ascii=False, indent=2))
        return 0
    if not args.backup_reference or not args.backup_reference.strip():
        print("错误：实际执行必须通过 --backup-reference 提供已完成的双备份位置/编号")
        return 2
    if not args.backup_checksum or not args.backup_checksum.strip():
        print("错误：实际执行必须通过 --backup-checksum 提供备份校验值")
        return 2

    try:
        report = await execute_migration(
            plan,
            args.backup_reference.strip(),
            args.backup_checksum.strip(),
        )
    except Exception as exc:
        report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "backup_reference": args.backup_reference.strip(),
            "backup_checksum": args.backup_checksum.strip(),
            "plan": plan,
            "success": False,
            "fatal_error": str(exc),
        }
    report_path = args.report or Path(
        f"workspace-migration-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"迁移报告：{report_path.resolve()}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
