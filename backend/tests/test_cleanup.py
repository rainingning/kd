"""T7.1 定时清理测试（需要测试数据库）。"""
import asyncio
from datetime import timedelta

from sqlalchemy import select

from app.models import Notification, SystemConfig, Task, TaskStatus, utcnow
from app.scheduler.cleanup import cleanup_expired_tasks
from app.scheduler.dispatcher import dispatch_once


async def test_cleanup_removes_expired(client, auth_headers, submit_task, db_session, storage_tmp):
    headers = await auth_headers("gina", "gina@example.com")
    old_id = (await submit_task(headers)).json()["id"]
    new_id = (await submit_task(headers)).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)

    # old 任务的完成时间改到 40 天前（超过默认 30 天保留期）
    old = await db_session.get(Task, old_id)
    old_dir = storage_tmp / old.storage_dir
    assert old_dir.exists()
    old.finished_at = utcnow() - timedelta(days=40)
    await db_session.commit()

    deleted, freed = await cleanup_expired_tasks()
    assert deleted == 1
    assert freed > 0
    assert not old_dir.exists()
    # 记录与级联通知一并删除
    assert await db_session.scalar(select(Task).where(Task.id == old_id)) is None
    assert await db_session.scalar(select(Notification).where(Notification.task_id == old_id)) is None
    # 未过期任务不受影响
    new = await db_session.get(Task, new_id)
    await db_session.refresh(new)
    assert (storage_tmp / new.storage_dir).exists()


async def test_cleanup_keeps_active_tasks(client, auth_headers, submit_task, db_session, storage_tmp):
    headers = await auth_headers("gina", "gina@example.com")
    task_id = (await submit_task(headers)).json()["id"]

    # 排队 40 天的任务、运行 40 天的任务都不能清
    task = await db_session.get(Task, task_id)
    task.queued_at = utcnow() - timedelta(days=40)
    db_session.add(Task(user_id=task.user_id, status=TaskStatus.RUNNING, params={},
                        storage_dir=None, started_at=utcnow() - timedelta(days=40)))
    await db_session.commit()

    deleted, _ = await cleanup_expired_tasks()
    assert deleted == 0
    assert await db_session.scalar(select(Task).where(Task.id == task_id)) is not None


async def test_cleanup_respects_retention_config(client, auth_headers, submit_task,
                                                 db_session, storage_tmp):
    headers = await auth_headers("gina", "gina@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)

    task = await db_session.get(Task, task_id)
    task.finished_at = utcnow() - timedelta(days=40)
    await db_session.commit()

    # 保留期调大到 60 天 → 40 天的任务不清
    db_session.add(SystemConfig(key="retention_days", value="60"))
    await db_session.commit()
    deleted, _ = await cleanup_expired_tasks()
    assert deleted == 0
