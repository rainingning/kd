"""T4 任务核心测试：提交、调度、执行、超时、取消、并发限额、FIFO、重启恢复。

需要测试数据库；计算程序使用 Mock（config.fortran_command 默认指向 mock_program.py）。
"""
import asyncio
import json

import pytest
from sqlalchemy import func, select

from app.config import settings
from app.models import Notification, NotificationType, SystemConfig, Task, TaskStatus
from app.scheduler.dispatcher import dispatch_once, recover_interrupted_tasks


@pytest.fixture
def storage_tmp(tmp_path, monkeypatch):
    """任务文件写到临时目录，不污染仓库 storage/。"""
    monkeypatch.setattr(settings, "storage_root", tmp_path)
    return tmp_path


async def _set_config(db_session, key, value):
    db_session.add(SystemConfig(key=key, value=str(value)))
    await db_session.commit()


async def _submit(client, headers, params=None, data=b"1,2,3\n4,5,6\n", filename="data.csv"):
    params = params if params is not None else {"grid_size": 10, "mock_sleep": 0}
    return await client.post(
        "/api/tasks",
        data={"params": json.dumps(params)},
        files={"file": (filename, data)},
        headers=headers,
    )


async def _task(db_session, task_id) -> Task:
    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)  # 防止身份映射缓存到旧状态
    return task


# ---- T4.1 提交 ----

async def test_submit_success(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    resp = await _submit(client, headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "QUEUED"
    assert body["input_filename"] == "data.csv"
    assert body["params"]["grid_size"] == 10

    tdirs = list(storage_tmp.glob("*/*"))
    assert len(tdirs) == 1
    assert json.loads((tdirs[0] / "params.in").read_text())["grid_size"] == 10
    assert (tdirs[0] / "input.dat").read_bytes() == b"1,2,3\n4,5,6\n"


async def test_submit_invalid_params(client, auth_headers, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    resp = await _submit(client, headers, params={"grid_size": -1})
    assert resp.status_code == 422
    assert "grid_size" in resp.json()["detail"]


async def test_submit_bad_json(client, auth_headers, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    resp = await client.post("/api/tasks", data={"params": "not-json"},
                             files={"file": ("a.csv", b"x")}, headers=headers)
    assert resp.status_code == 400


async def test_queued_limit(client, auth_headers, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    for _ in range(3):
        assert (await _submit(client, headers)).status_code == 201
    resp = await _submit(client, headers)
    assert resp.status_code == 429


async def test_upload_size_limit(client, auth_headers, db_session, storage_tmp):
    await _set_config(db_session, "max_upload_mb", 1)
    headers = await auth_headers("dave", "dave@example.com")
    big = b"x" * (2 * 1024 * 1024)
    resp = await _submit(client, headers, data=big)
    assert resp.status_code == 413
    # 任务未残留
    assert await db_session.scalar(select(func.count(Task.id))) == 0
    assert list(storage_tmp.glob("*/*")) == []


# ---- T4.2/T4.3 调度与执行 ----

async def test_dispatch_and_run_success(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers)).json()["id"]

    launched = await dispatch_once()
    assert len(launched) == 1
    await asyncio.gather(*launched)

    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.COMPLETED
    assert task.exit_code == 0
    assert task.started_at is not None and task.finished_at is not None
    assert float(task.duration_sec) >= 0

    tdir = storage_tmp / task.storage_dir
    assert "mock computation result" in (tdir / "stdout.txt").read_text()

    note = (await db_session.scalars(select(Notification))).first()
    assert note.type == NotificationType.COMPLETED


async def test_run_failure_nonzero_exit(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers,
                             params={"grid_size": 10, "mock_sleep": 0, "mock_exit_code": 1})).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)

    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.exit_code == 1
    assert "退出码" in task.error_message
    tdir = storage_tmp / task.storage_dir
    assert "failed" in (tdir / "stderr.txt").read_text()

    note = (await db_session.scalars(select(Notification))).first()
    assert note.type == NotificationType.FAILED


async def test_run_timeout(client, auth_headers, db_session, storage_tmp):
    await _set_config(db_session, "task_timeout_minutes", 0.02)  # 1.2 秒
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers,
                             params={"grid_size": 10, "mock_sleep": 30})).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)

    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert "超时" in task.error_message


# ---- T4.4 取消 ----

async def test_cancel_queued(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers)).json()["id"]
    resp = await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
    assert resp.status_code == 200
    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.CANCELED


async def test_cancel_running(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers,
                             params={"grid_size": 10, "mock_sleep": 30})).json()["id"]
    launched = await dispatch_once()
    await asyncio.sleep(0.3)  # 等进程起来
    resp = await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
    assert resp.status_code == 200
    await asyncio.gather(*launched)

    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.CANCELED
    assert task.error_message == "用户取消"


async def test_cancel_finished_conflict(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers)).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)
    resp = await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
    assert resp.status_code == 409


async def test_cancel_others_task_404(client, auth_headers, storage_tmp):
    headers_a = await auth_headers("user_a", "a@example.com")
    headers_b = await auth_headers("user_b", "b@example.com")
    task_id = (await _submit(client, headers_a)).json()["id"]
    resp = await client.post(f"/api/tasks/{task_id}/cancel", headers=headers_b)
    assert resp.status_code == 404


# ---- T4.2 并发限额与 FIFO ----

async def test_global_concurrent_limit(client, auth_headers, db_session, storage_tmp):
    await _set_config(db_session, "max_concurrent_tasks", 1)
    headers = await auth_headers("dave", "dave@example.com")
    id1 = (await _submit(client, headers)).json()["id"]
    id2 = (await _submit(client, headers)).json()["id"]

    launched = await dispatch_once()
    assert len(launched) == 1
    assert (await _task(db_session, id1)).status == TaskStatus.RUNNING
    assert (await _task(db_session, id2)).status == TaskStatus.QUEUED
    await asyncio.gather(*launched)

    launched = await dispatch_once()
    assert len(launched) == 1
    await asyncio.gather(*launched)
    assert (await _task(db_session, id1)).status == TaskStatus.COMPLETED
    assert (await _task(db_session, id2)).status == TaskStatus.COMPLETED


async def test_per_user_running_limit(client, auth_headers, db_session, storage_tmp):
    await _set_config(db_session, "max_running_per_user", 1)
    headers = await auth_headers("dave", "dave@example.com")
    await _submit(client, headers)
    await _submit(client, headers)

    launched = await dispatch_once()
    assert len(launched) == 1
    await asyncio.gather(*launched)
    launched = await dispatch_once()
    assert len(launched) == 1
    await asyncio.gather(*launched)


async def test_fifo_order(client, auth_headers, db_session, storage_tmp):
    await _set_config(db_session, "max_concurrent_tasks", 1)
    headers = await auth_headers("dave", "dave@example.com")
    ids = [(await _submit(client, headers)).json()["id"] for _ in range(3)]

    for _ in range(3):
        launched = await dispatch_once()
        await asyncio.gather(*launched)

    tasks = [(await _task(db_session, i)) for i in ids]
    started = [t.started_at for t in tasks]
    assert started == sorted(started)
    assert all(t.status == TaskStatus.COMPLETED for t in tasks)


# ---- T4.5 重启恢复 ----

async def test_restart_recovery(client, auth_headers, db_session, storage_tmp):
    headers = await auth_headers("dave", "dave@example.com")
    task_id = (await _submit(client, headers)).json()["id"]
    # 模拟服务崩溃时残留的 RUNNING 任务
    task = await _task(db_session, task_id)
    task.status = TaskStatus.RUNNING
    await db_session.commit()

    recovered = await recover_interrupted_tasks()
    assert recovered == 1
    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert "重启" in task.error_message

    note = (await db_session.scalars(select(Notification))).first()
    assert note.type == NotificationType.FAILED
