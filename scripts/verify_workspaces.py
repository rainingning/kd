"""批量检查所有用户固定工作区，输出用户级 JSON 报告。"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import select  # noqa: E402

from app.db import async_session  # noqa: E402
from app.models import User  # noqa: E402
from app.services.workspace import check_workspace  # noqa: E402


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="检查所有用户工作区")
    parser.add_argument("--report", type=Path, help="可选 JSON 报告输出路径")
    args = parser.parse_args()

    async with async_session() as session:
        users = list((await session.scalars(select(User).order_by(User.id))).all())

    items = []
    for user in users:
        result = await asyncio.to_thread(
            check_workspace,
            user.id,
            expected_version=user.program_version,
            expected_exe_sha256=user.exe_sha256,
            expected_dll_sha256=user.dll_sha256,
        )
        items.append({
            "user_id": user.id,
            "username": user.username,
            "ready": result.ready,
            "errors": list(result.errors),
            "program_version": user.program_version,
            "exe_sha256": result.exe_sha256,
            "dll_sha256": result.dll_sha256,
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
