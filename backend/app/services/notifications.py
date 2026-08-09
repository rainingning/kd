"""站内通知写入助手。"""
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Notification, Task


def notify(session: AsyncSession, task: Task, type_: str, message: str) -> None:
    session.add(Notification(user_id=task.user_id, task_id=task.id, type=type_, message=message))
