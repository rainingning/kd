"""创建初始管理员账号（部署时使用，研发任务分解 T9.3）。

用法（在仓库根目录）：
    .venv/Scripts/python scripts/create_admin.py <用户名> <邮箱> [--password 密码]
密码省略时交互式输入。用户名或邮箱已存在则报错退出。
"""
import argparse
import asyncio
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from sqlalchemy import or_, select  # noqa: E402

from app.db import async_session  # noqa: E402
from app.models import User, UserRole, UserStatus, WorkspaceStatus, utcnow  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.services.workspace import WorkspaceError, initialize_workspace  # noqa: E402


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="创建管理员账号")
    parser.add_argument("username")
    parser.add_argument("email")
    parser.add_argument("--password")
    args = parser.parse_args()

    password = args.password or getpass.getpass("密码（至少 8 位）: ")
    if len(password) < 8:
        print("错误：密码至少 8 位")
        return 1

    async with async_session() as session:
        exists = await session.scalar(
            select(User.id).where(or_(User.username == args.username, User.email == args.email)))
        if exists is not None:
            print("错误：用户名或邮箱已存在")
            return 1
        user = User(
            username=args.username, email=args.email,
            password_hash=hash_password(password),
            role=UserRole.ADMIN, status=UserStatus.ACTIVE,
        )
        session.add(user)
        await session.flush()
        try:
            manifest = await asyncio.to_thread(initialize_workspace, user.id)
        except WorkspaceError as exc:
            await session.rollback()
            print(f"错误：用户工作区初始化失败：{exc}")
            return 1
        user.workspace_status = WorkspaceStatus.READY
        user.program_version = manifest.version
        user.exe_sha256 = manifest.exe_sha256
        user.dll_sha256 = manifest.dll_sha256
        user.program_synced_at = utcnow()
        await session.commit()
    print(f"管理员 {args.username} 创建成功")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
