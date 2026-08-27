"""批量检查所有用户的三个程序工作区，输出 JSON 报告。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import async_session  # noqa: E402
from app.models import User, UserProgram  # noqa: E402
from app.services.programs import list_programs  # noqa: E402
from app.services.workspace import check_workspace  # noqa: E402


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查所有用户的三个程序工作区")
    parser.add_argument("--report", type=Path, help="可选 JSON 报告输出路径")
    args = parser.parse_args()

    async with async_session() as session:
        users = list((await session.scalars(select(User).order_by(User.id))).all())
        installs = list((await session.scalars(select(UserProgram))).all())
    by_user = {(row.user_id, row.program_key): row for row in installs}

    items = []
    for user in users:
        programs = []
        for spec in list_programs():
            install = by_user.get((user.id, spec.key))
            result = await asyncio.to_thread(
                check_workspace,
                user.id,
                program_key=spec.key,
                expected_version=install.program_version if install else None,
                expected_exe_sha256=install.exe_sha256 if install else None,
                expected_dll_sha256=install.dll_sha256 if install else None,
            )
            programs.append({
                "program_key": spec.key,
                "ready": result.ready and install is not None,
                "errors": (["缺少程序安装记录"] if install is None else []) + list(result.errors),
                "program_version": install.program_version if install else None,
                "exe_sha256": result.exe_sha256,
                "dll_sha256": result.dll_sha256,
            })
        items.append({
            "user_id": user.id,
            "username": user.username,
            "ready": all(item["ready"] for item in programs),
            "programs": programs,
        })

    report = {
        "total": len(items),
        "ready": sum(1 for item in items if item["ready"]),
        "failed": sum(1 for item in items if not item["ready"]),
        "items": items,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
