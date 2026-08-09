"""T5 任务查询、文件下载、站内通知测试（需要测试数据库）。"""
import asyncio
import json

from sqlalchemy import select

from app.models import Task, TaskStatus
from app.scheduler.dispatcher import dispatch_once


async def test_list_pagination_and_filter(client, auth_headers, submit_task, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    ids = [(await submit_task(headers)).json()["id"] for _ in range(3)]
    await client.post(f"/api/tasks/{ids[0]}/cancel", headers=headers)

    resp = await client.get("/api/tasks", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["total"] == 3

    resp = await client.get("/api/tasks?status=QUEUED", headers=headers)
    assert resp.json()["total"] == 2

    resp = await client.get("/api/tasks?status=CANCELED", headers=headers)
    assert resp.json()["total"] == 1

    resp = await client.get("/api/tasks?page_size=2&page=1", headers=headers)
    body = resp.json()
    assert body["total"] == 3 and len(body["items"]) == 2
    # 默认按提交时间倒序
    assert body["items"][0]["id"] == ids[2]


async def test_list_isolation(client, auth_headers, submit_task, storage_tmp):
    headers_a = await auth_headers("user_a", "a@example.com")
    headers_b = await auth_headers("user_b", "b@example.com")
    await submit_task(headers_a)
    resp = await client.get("/api/tasks", headers=headers_b)
    assert resp.json()["total"] == 0


async def test_detail_and_queue_position(client, auth_headers, submit_task, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    id1 = (await submit_task(headers)).json()["id"]
    id2 = (await submit_task(headers)).json()["id"]

    resp = await client.get(f"/api/tasks/{id1}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["queue_position"] == 0
    assert resp.json()["params"]["grid_size"] == 10

    resp = await client.get(f"/api/tasks/{id2}", headers=headers)
    assert resp.json()["queue_position"] == 1


async def test_detail_others_task_404(client, auth_headers, submit_task, storage_tmp):
    headers_a = await auth_headers("user_a", "a@example.com")
    headers_b = await auth_headers("user_b", "b@example.com")
    task_id = (await submit_task(headers_a)).json()["id"]
    resp = await client.get(f"/api/tasks/{task_id}", headers=headers_b)
    assert resp.status_code == 404


async def test_file_downloads(client, auth_headers, submit_task, db_session, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers, params={"grid_size": 7, "mock_sleep": 0})).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)
    assert (await db_session.get(Task, task_id)).status == TaskStatus.COMPLETED

    resp = await client.get(f"/api/tasks/{task_id}/files/result", headers=headers)
    assert resp.status_code == 200
    assert "mock computation result" in resp.text

    resp = await client.get(f"/api/tasks/{task_id}/files/stderr", headers=headers)
    assert resp.status_code == 200

    resp = await client.get(f"/api/tasks/{task_id}/files/input", headers=headers)
    assert resp.status_code == 200
    assert resp.content == b"1,2,3\n4,5,6\n"
    assert "data.csv" in resp.headers["content-disposition"]

    resp = await client.get(f"/api/tasks/{task_id}/files/params", headers=headers)
    assert resp.status_code == 200
    assert json.loads(resp.text)["grid_size"] == 7


async def test_file_not_ready_and_isolation(client, auth_headers, submit_task, storage_tmp):
    headers_a = await auth_headers("user_a", "a@example.com")
    headers_b = await auth_headers("user_b", "b@example.com")
    task_id = (await submit_task(headers_a)).json()["id"]

    # 任务还在排队，stdout 尚未生成
    resp = await client.get(f"/api/tasks/{task_id}/files/result", headers=headers_a)
    assert resp.status_code == 404
    # 他人任务不可下载
    resp = await client.get(f"/api/tasks/{task_id}/files/input", headers=headers_b)
    assert resp.status_code == 404
    # 未知文件类型
    resp = await client.get(f"/api/tasks/{task_id}/files/hack", headers=headers_a)
    assert resp.status_code == 404


async def test_notifications(client, auth_headers, submit_task, db_session, storage_tmp):
    headers = await auth_headers("erin", "erin@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    launched = await dispatch_once()
    await asyncio.gather(*launched)

    resp = await client.get("/api/notifications", headers=headers)
    body = resp.json()
    assert body["total"] == 1 and body["unread_count"] == 1
    assert body["items"][0]["type"] == "completed"
    assert str(task_id) in body["items"][0]["message"]

    resp = await client.post("/api/notifications/read", json={"ids": None}, headers=headers)
    assert resp.status_code == 200
    resp = await client.get("/api/notifications", headers=headers)
    assert resp.json()["unread_count"] == 0

    resp = await client.get("/api/notifications?unread_only=true", headers=headers)
    assert resp.json()["total"] == 0
