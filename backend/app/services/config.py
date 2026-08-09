"""系统配置读取（system_config 表 + 默认值回退）。"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import DEFAULT_CONFIG, SystemConfig


async def get_config_map(session: AsyncSession) -> dict[str, str]:
    rows = await session.scalars(select(SystemConfig))
    merged = dict(DEFAULT_CONFIG)
    merged.update({row.key: row.value for row in rows})
    return merged


async def get_int(session: AsyncSession, key: str) -> int:
    return int((await get_config_map(session))[key])


async def get_float(session: AsyncSession, key: str) -> float:
    return float((await get_config_map(session))[key])


async def ensure_defaults(session: AsyncSession) -> None:
    """补齐缺失的默认配置项（启动时与测试种子使用）。"""
    existing = set((await session.scalars(select(SystemConfig.key))).all())
    for key, value in DEFAULT_CONFIG.items():
        if key not in existing:
            session.add(SystemConfig(key=key, value=value))
    await session.flush()
