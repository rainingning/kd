"""管理员操作审计（T6.5，FR-ADMIN-07）。"""
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AuditLog


def audit(session: AsyncSession, admin_id: int, action: str,
          target: str | None = None, detail: dict | None = None) -> None:
    session.add(AuditLog(admin_id=admin_id, action=action, target=target, detail=detail))
