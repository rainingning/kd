"""数据库引擎与会话（T1.1）。

engine / async_session 为模块级可重绑定对象：测试通过 init_db() 切换到测试库，
调度器等非请求路径代码通过 db.async_session() 获取会话。
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


engine = None
async_session: async_sessionmaker[AsyncSession] = None  # type: ignore[assignment]


def init_db(url: str, **engine_kwargs) -> None:
    global engine, async_session
    engine = create_async_engine(url, **engine_kwargs)
    async_session = async_sessionmaker(engine, expire_on_commit=False)


init_db(settings.database_url)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
