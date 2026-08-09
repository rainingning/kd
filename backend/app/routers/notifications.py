"""站内通知（T5.3，FR-NOTIFY）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import get_current_user
from ..models import Notification, User
from ..schemas import MarkReadRequest, NotificationListResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    base = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        base = base.where(Notification.read.is_(False))
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    unread = await session.scalar(
        select(func.count(Notification.id))
        .where(Notification.user_id == user.id, Notification.read.is_(False)))
    rows = await session.scalars(
        base.order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size).limit(page_size))
    return NotificationListResponse(total=total or 0, unread_count=unread or 0, items=list(rows))


@router.post("/read")
async def mark_read(
    body: MarkReadRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = (update(Notification)
            .values(read=True)
            .where(Notification.user_id == user.id, Notification.read.is_(False)))
    if body.ids is not None:
        stmt = stmt.where(Notification.id.in_(body.ids))
    await session.execute(stmt)
    await session.commit()
    return {"detail": "已标记为已读"}
