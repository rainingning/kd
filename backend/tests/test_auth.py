"""T1.1/T1.3 冒烟测试 + T2 认证流程测试。"""
from sqlalchemy import select

from app.models import EmailToken, TokenType


async def test_health(client):
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def _register(client, username="alice", email="alice@example.com", password="password123"):
    return await client.post("/api/auth/register",
                             json={"username": username, "email": email, "password": password})


async def _login(client, username="alice", password="password123"):
    return await client.post("/api/auth/login", json={"username": username, "password": password})


async def test_register_verify_login_flow(client, db_session):
    # 注册
    resp = await _register(client)
    assert resp.status_code == 201

    # 未验证不能登录
    resp = await _login(client)
    assert resp.status_code == 403

    # 取出验证 token 完成验证
    rec = (await db_session.scalars(
        select(EmailToken).where(EmailToken.type == TokenType.VERIFY))).first()
    assert rec is not None
    resp = await client.get(f"/api/auth/verify?token={rec.token}")
    assert resp.status_code == 200

    # 验证后可登录
    resp = await _login(client)
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    # me
    resp = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"
    assert resp.json()["status"] == "active"


async def test_register_duplicate_conflict(client):
    await _register(client)
    resp = await client.post("/api/auth/register", json={
        "username": "alice", "email": "other@example.com", "password": "password123"})
    assert resp.status_code == 409


async def test_login_wrong_password(client):
    await _register(client)
    resp = await _login(client, password="wrong-password")
    assert resp.status_code == 401


async def test_forgot_and_reset_password(client, db_session):
    await _register(client)
    rec = (await db_session.scalars(select(EmailToken))).first()
    await client.get(f"/api/auth/verify?token={rec.token}")

    resp = await client.post("/api/auth/forgot-password", json={"email": "alice@example.com"})
    assert resp.status_code == 200
    # 不存在的邮箱也返回 200（不泄露注册状态）
    resp = await client.post("/api/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 200

    rec = (await db_session.scalars(
        select(EmailToken).where(EmailToken.type == TokenType.RESET))).first()
    assert rec is not None
    resp = await client.post("/api/auth/reset-password",
                             json={"token": rec.token, "new_password": "new-password-456"})
    assert resp.status_code == 200

    assert (await _login(client, password="password123")).status_code == 401
    assert (await _login(client, password="new-password-456")).status_code == 200


async def test_change_username_and_password(client, db_session):
    await _register(client)
    rec = (await db_session.scalars(select(EmailToken))).first()
    await client.get(f"/api/auth/verify?token={rec.token}")
    token = (await _login(client)).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put("/api/users/me", json={"username": "alice2"}, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice2"

    resp = await client.put("/api/users/me/password",
                            json={"old_password": "bad", "new_password": "new-password-456"},
                            headers=headers)
    assert resp.status_code == 400

    resp = await client.put("/api/users/me/password",
                            json={"old_password": "password123", "new_password": "new-password-456"},
                            headers=headers)
    assert resp.status_code == 200
    assert (await _login(client, username="alice2", password="new-password-456")).status_code == 200


async def test_me_requires_token(client):
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
