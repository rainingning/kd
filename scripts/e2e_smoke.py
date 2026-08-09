"""端到端冒烟 + 并发验证脚本（研发任务分解 T9.2）。

前提：后端服务已启动（scripts\\start_backend.bat 或 uvicorn），使用 .env 指向的开发库。
脚本会：
  1. 健康检查
  2. 确保管理员存在（没有则创建 admin / admin123456）
  3. 注册并激活测试用户（直接读库取验证 token——仅限开发联调，生产不可用）
  4. 完整流程：提交任务 → 轮询到完成 → 下载结果文件 → 站内通知
  5. 并发验证：放宽单用户限额后提交 60 个任务，全程采样仪表盘，
     断言运行数不超过上限（默认 50），且 60 个任务最终全部完成
  6. 恢复限额配置

用法：.venv/Scripts/python scripts/e2e_smoke.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.db import async_session  # noqa: E402
from app.models import EmailToken, TokenType, User, UserRole, UserStatus  # noqa: E402
from app.security import hash_password  # noqa: E402

BASE = "http://127.0.0.1:8000"
ADMIN_PASSWORD = "admin123456"


async def ensure_admin(client: httpx.AsyncClient) -> dict:
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    if resp.status_code != 200:
        async with async_session() as session:
            exists = await session.scalar(select(User.id).where(User.username == "admin"))
            if exists is None:
                session.add(User(username="admin", email="admin@example.com",
                                 password_hash=hash_password(ADMIN_PASSWORD),
                                 role=UserRole.ADMIN, status=UserStatus.ACTIVE))
                await session.commit()
                print("[setup] 创建管理员 admin")
        resp = await client.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
        resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def create_verified_user(client: httpx.AsyncClient, username: str) -> dict:
    email = f"{username}@example.com"
    resp = await client.post("/api/auth/register",
                             json={"username": username, "email": email, "password": "password123"})
    assert resp.status_code == 201, resp.text
    async with async_session() as session:
        rec = await session.scalar(
            select(EmailToken).where(EmailToken.type == TokenType.VERIFY)
            .order_by(EmailToken.id.desc()))
        token = rec.token
    resp = await client.get(f"/api/auth/verify?token={token}")
    assert resp.status_code == 200, resp.text
    resp = await client.post("/api/auth/login", json={"username": username, "password": "password123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def submit(client: httpx.AsyncClient, headers: dict, params: dict) -> int:
    resp = await client.post(
        "/api/tasks",
        data={"params": json.dumps(params)},
        files={"file": ("data.csv", b"1,2,3\n4,5,6\n")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def wait_terminal(client: httpx.AsyncClient, headers: dict, task_id: int) -> dict:
    for _ in range(300):
        resp = await client.get(f"/api/tasks/{task_id}", headers=headers)
        body = resp.json()
        if body["status"] in ("COMPLETED", "FAILED", "CANCELED"):
            return body
        await asyncio.sleep(0.5)
    raise TimeoutError(f"任务 {task_id} 长时间未结束")


async def main() -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        resp = await client.get("/api/health")
        assert resp.status_code == 200, "后端未启动？"
        print("[1/6] 健康检查通过")

        admin = await ensure_admin(client)
        username = f"e2e_{int(time.time())}"
        headers = await create_verified_user(client, username)
        print(f"[2/6] 测试用户 {username} 注册激活完成")

        # 单任务完整流程
        task_id = await submit(client, headers, {"grid_size": 10, "mock_sleep": 0.2})
        body = await wait_terminal(client, headers, task_id)
        assert body["status"] == "COMPLETED", body
        resp = await client.get(f"/api/tasks/{task_id}/files/result", headers=headers)
        assert "mock computation result" in resp.text
        resp = await client.get("/api/notifications", headers=headers)
        assert resp.json()["total"] >= 1
        print(f"[3/6] 单任务流程通过（任务 #{task_id}，结果下载与通知正常）")

        # 并发验证：放宽单用户限额，提交 60 个任务
        await client.put("/api/admin/config", json={"config": {
            "max_queued_per_user": "60", "max_running_per_user": "60"}}, headers=admin)
        resp = await client.get("/api/admin/config", headers=admin)
        max_concurrent = int(resp.json()["config"]["max_concurrent_tasks"])

        task_ids = [await submit(client, headers, {"grid_size": 10, "mock_sleep": 0.5})
                    for _ in range(60)]
        print(f"[4/6] 已提交 60 个任务（并发上限 {max_concurrent}），等待全部完成...")

        max_running_seen = 0
        pending = set(task_ids)
        while pending:
            resp = await client.get("/api/admin/dashboard", headers=admin)
            max_running_seen = max(max_running_seen, resp.json()["running_tasks"])
            done = set()
            for tid in pending:
                resp = await client.get(f"/api/tasks/{tid}", headers=headers)
                if resp.json()["status"] in ("COMPLETED", "FAILED", "CANCELED"):
                    done.add(tid)
            pending -= done
            await asyncio.sleep(0.2)

        statuses = []
        for tid in task_ids:
            resp = await client.get(f"/api/tasks/{tid}", headers=headers)
            statuses.append(resp.json()["status"])
        assert all(s == "COMPLETED" for s in statuses), f"存在未完成任务: {statuses.count('COMPLETED')}/60"
        print(f"[5/6] 60 个任务全部完成；采样到的最大同时运行数 = {max_running_seen}（上限 {max_concurrent}）")
        assert max_running_seen <= max_concurrent, "并发超限！"

        # 恢复限额
        await client.put("/api/admin/config", json={"config": {
            "max_queued_per_user": "3", "max_running_per_user": "3"}}, headers=admin)
        print("[6/6] 配置已恢复")

    print("\nE2E 冒烟验证全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
