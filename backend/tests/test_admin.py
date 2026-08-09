"""T6 管理后台测试（需要测试数据库）。"""
import asyncio

from sqlalchemy import select

from app.models import AuditLog, Notification, NotificationType, Task, TaskStatus, User
from app.scheduler.dispatcher import dispatch_once


async def _task(db_session, task_id) -> Task:
    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)
    return task


# ---- 权限 ----

async def test_admin_required(client, auth_headers):
    assert (await client.get("/api/admin/dashboard")).status_code == 401
    headers = await auth_headers("norm", "norm@example.com")
    assert (await client.get("/api/admin/dashboard", headers=headers)).status_code == 403


# ---- T6.1 仪表盘 ----

async def test_dashboard(client, admin_headers, auth_headers, submit_task, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    await submit_task(headers)

    resp = await client.get("/api/admin/dashboard", headers=admin_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_users"] == 2  # admin + erin
    assert body["queued_tasks"] == 1
    assert body["running_tasks"] == 0
    assert body["active_users"] == 0
    assert 0 <= body["cpu_percent"] <= 100
    assert 0 < body["memory_percent"] <= 100
    assert 0 < body["disk_percent"] <= 100


# ---- T6.2 任务监控与终止 ----

async def test_running_and_queued_lists(client, admin_headers, auth_headers, submit_task,
                                        db_session, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers, params={"grid_size": 10, "mock_sleep": 30})).json()["id"]
    launched = await dispatch_once()
    await asyncio.sleep(0.3)

    resp = await client.get("/api/admin/tasks/running", headers=admin_headers)
    items = resp.json()
    assert len(items) == 1
    assert items[0]["id"] == task_id and items[0]["username"] == "erin"
    assert items[0]["started_at"] is not None

    resp = await client.post(f"/api/admin/tasks/{task_id}/kill", headers=admin_headers)
    assert resp.status_code == 200
    await asyncio.gather(*launched)

    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error_message == "被管理员终止"

    note = (await db_session.scalars(select(Notification))).first()
    assert note.type == NotificationType.KILLED

    logs = (await db_session.scalars(select(AuditLog))).all()
    assert any(log.action == "task.kill" for log in logs)

    resp = await client.get("/api/admin/tasks/running", headers=admin_headers)
    assert resp.json() == []


async def test_kill_queued_task(client, admin_headers, auth_headers, submit_task,
                                db_session, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers)).json()["id"]

    resp = await client.get("/api/admin/tasks/queued", headers=admin_headers)
    assert len(resp.json()) == 1

    resp = await client.post(f"/api/admin/tasks/{task_id}/kill", headers=admin_headers)
    assert resp.status_code == 200
    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error_message == "被管理员终止"


async def test_kill_finished_task_409(client, admin_headers, auth_headers, submit_task, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)
    resp = await client.post(f"/api/admin/tasks/{task_id}/kill", headers=admin_headers)
    assert resp.status_code == 409


# ---- T6.3 用户管理 ----

async def test_user_crud_flow(client, admin_headers, db_session):
    # 创建（管理员创建的用户直接激活，可立即登录）
    resp = await client.post("/api/admin/users", json={
        "username": "frank", "email": "frank@example.com", "password": "password123"},
        headers=admin_headers)
    assert resp.status_code == 201
    user_id = resp.json()["id"]
    assert resp.json()["status"] == "active"
    resp = await client.post("/api/auth/login", json={"username": "frank", "password": "password123"})
    assert resp.status_code == 200

    # 列表 + 搜索
    resp = await client.get("/api/admin/users?keyword=fra", headers=admin_headers)
    assert resp.json()["total"] == 1
    resp = await client.get("/api/admin/users", headers=admin_headers)
    assert resp.json()["total"] == 2

    # 重名冲突
    resp = await client.post("/api/admin/users", json={
        "username": "frank", "email": "x@example.com", "password": "password123"},
        headers=admin_headers)
    assert resp.status_code == 409

    # 编辑
    resp = await client.put(f"/api/admin/users/{user_id}", json={"username": "frank2"},
                            headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "frank2"

    # 重置密码
    resp = await client.post(f"/api/admin/users/{user_id}/reset-password", headers=admin_headers)
    assert resp.status_code == 200
    temp = resp.json()["temporary_password"]
    assert (await client.post("/api/auth/login",
                              json={"username": "frank2", "password": "password123"})).status_code == 401
    assert (await client.post("/api/auth/login",
                              json={"username": "frank2", "password": temp})).status_code == 200

    # 删除
    resp = await client.delete(f"/api/admin/users/{user_id}", headers=admin_headers)
    assert resp.status_code == 204
    assert (await db_session.get(User, user_id)) is None


async def test_disable_cancels_queued_and_blocks_login(client, admin_headers, auth_headers,
                                                       submit_task, db_session, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    erin_id = (await db_session.scalar(select(User.id).where(User.username == "erin")))

    resp = await client.post(f"/api/admin/users/{erin_id}/disable", headers=admin_headers)
    assert resp.status_code == 200

    # 排队任务被取消，登录被拒
    assert (await _task(db_session, task_id)).status == TaskStatus.CANCELED
    resp = await client.post("/api/auth/login", json={"username": "erin", "password": "password123"})
    assert resp.status_code == 403

    # 启用后恢复
    resp = await client.post(f"/api/admin/users/{erin_id}/enable", headers=admin_headers)
    assert resp.status_code == 200
    resp = await client.post("/api/auth/login", json={"username": "erin", "password": "password123"})
    assert resp.status_code == 200


async def test_admin_self_protection(client, admin_headers, db_session):
    admin_id = await db_session.scalar(select(User.id).where(User.username == "admin"))
    assert (await client.delete(f"/api/admin/users/{admin_id}", headers=admin_headers)).status_code == 400
    assert (await client.post(f"/api/admin/users/{admin_id}/disable",
                              headers=admin_headers)).status_code == 400
    assert (await client.put(f"/api/admin/users/{admin_id}", json={"role": "user"},
                             headers=admin_headers)).status_code == 400


async def test_delete_user_removes_files(client, admin_headers, auth_headers, submit_task,
                                         db_session, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)
    task = await _task(db_session, task_id)
    tdir = storage_tmp / task.storage_dir
    assert tdir.exists()

    erin_id = await db_session.scalar(select(User.id).where(User.username == "erin"))
    resp = await client.delete(f"/api/admin/users/{erin_id}", headers=admin_headers)
    assert resp.status_code == 204
    assert not tdir.exists()
    # 任务记录级联删除（用查询而非 get，绕过身份映射缓存）
    assert await db_session.scalar(select(Task).where(Task.id == task_id)) is None


# ---- T6.4 系统参数配置 ----

async def test_config_update_takes_effect(client, admin_headers, auth_headers, submit_task,
                                          db_session, storage_tmp):
    resp = await client.get("/api/admin/config", headers=admin_headers)
    assert resp.json()["config"]["max_concurrent_tasks"] == "50"

    resp = await client.put("/api/admin/config",
                            json={"config": {"max_concurrent_tasks": "1"}}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["config"]["max_concurrent_tasks"] == "1"

    # 调度器下一周期即按新值执行
    headers = await auth_headers("erin", "erin@example.com")
    await submit_task(headers)
    await submit_task(headers)
    launched = await dispatch_once()
    assert len(launched) == 1
    await asyncio.gather(*launched)

    # 非法配置
    resp = await client.put("/api/admin/config", json={"config": {"bogus": "1"}}, headers=admin_headers)
    assert resp.status_code == 422
    resp = await client.put("/api/admin/config",
                            json={"config": {"max_concurrent_tasks": "abc"}}, headers=admin_headers)
    assert resp.status_code == 422


# ---- T6.5 审计日志 ----

async def test_audit_logs(client, admin_headers):
    await client.post("/api/admin/users", json={
        "username": "frank", "email": "frank@example.com", "password": "password123"},
        headers=admin_headers)

    resp = await client.get("/api/admin/audit-logs", headers=admin_headers)
    body = resp.json()
    assert body["total"] >= 1
    assert body["items"][0]["action"] == "user.create"
    assert body["items"][0]["admin_username"] == "admin"
    assert body["items"][0]["target"] == "frank"

    resp = await client.get("/api/admin/audit-logs?action=user.create", headers=admin_headers)
    assert resp.json()["total"] == 1
    resp = await client.get("/api/admin/audit-logs?action=task.kill", headers=admin_headers)
    assert resp.json()["total"] == 0
