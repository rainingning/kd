"""按 DATABASE_URL 凭据创建隔离测试库 fortran_platform_test（已存在则跳过）。"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import asyncpg  # noqa: E402
from sqlalchemy.engine.url import make_url  # noqa: E402

from app.config import settings  # noqa: E402


async def main() -> None:
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
            "SELECT 1 FROM pg_database WHERE datname = $1",
            "fortran_platform_test",
        )
        if not exists:
            await connection.execute(
                "CREATE DATABASE fortran_platform_test TEMPLATE template0")
            print("test database created")
        else:
            print("test database already exists")
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
