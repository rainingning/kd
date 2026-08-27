"""使用 DATABASE_URL 中的 PostgreSQL 凭据创建指定数据库（已存在则跳过）。"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import asyncpg  # noqa: E402
from sqlalchemy.engine.url import make_url  # noqa: E402

from app.config import settings  # noqa: E402


async def create_database(name: str) -> bool:
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]*", name):
        raise ValueError("数据库名称只能包含字母、数字和下划线，且不能以数字开头")
    url = make_url(settings.database_url)
    connection = await asyncpg.connect(
        user=url.username,
        password=url.password,
        host=url.host,
        port=url.port,
        database="postgres",
    )
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", name)
        if exists:
            return False
        await connection.execute(f'CREATE DATABASE "{name}" TEMPLATE template0')
        return True
    finally:
        await connection.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description="创建 PostgreSQL 数据库")
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    try:
        created = await create_database(args.name)
    except (ValueError, OSError, asyncpg.PostgresError) as exc:
        print(f"database creation failed: {exc}", file=sys.stderr)
        return 1
    print("database created" if created else "database already exists")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
