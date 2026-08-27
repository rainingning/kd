"""pytest 基座（T1.3）：独立测试库 fortran_platform_test。

数据库连接取自 .env（app.config.settings），仅将库名替换为 fortran_platform_test，
凭据不落入代码。数据库准备为惰性：只有使用 client / db_session 夹具的测试才会触发建库，
纯单元测试（如参数校验）无需数据库即可运行。
"""
import asyncio
import json

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.engine.url import make_url
from sqlalchemy.pool import NullPool

from app import db
from app.config import settings
from app.db import Base
from app.main import app
from app.models import EmailToken, TokenType

TEST_URL = make_url(settings.database_url).set(database="fortran_platform_test")


@pytest.fixture(scope="session")
def _prepare_database():
    """会话级：切换为 NullPool 并重建全部表。"""
    db.init_db(TEST_URL, poolclass=NullPool)

    async def _recreate():
        async with db.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_recreate())
    yield
    asyncio.run(db.engine.dispose())


@pytest.fixture
def _clean_tables(_prepare_database):
    """每个用库测试结束后清空所有表，保证用例隔离。"""
    yield

    async def _clean():
        async with db.engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())

    asyncio.run(_clean())


@pytest.fixture
def workspace_env(tmp_path, monkeypatch):
    """为涉及 API 的测试准备可信程序模板和隔离 storage。"""
    from app.services.program_template import sha256_file

    storage = tmp_path / "storage"
    template = tmp_path / "program-template"
    template.mkdir()
    exe = template / "DCR_3D.exe"
    dll = template / "libiomp5md.dll"
    exe.write_bytes(b"test-dcr3d-exe")
    dll.write_bytes(b"test-openmp-dll")
    (template / "program-manifest.json").write_text(json.dumps({
        "version": "test-1.0.0",
        "exe": exe.name,
        "dll": dll.name,
        "exe_sha256": sha256_file(exe),
        "dll_sha256": sha256_file(dll),
    }), encoding="utf-8")
    monkeypatch.setattr(settings, "storage_root", storage)
    monkeypatch.setattr(settings, "result_zip_cache_root", storage / ".zip-cache")
    monkeypatch.setattr(settings, "fortran_program_template_dir", template)
    return storage


@pytest_asyncio.fixture
async def client(_clean_tables, workspace_env):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def db_session(_clean_tables):
    async with db.async_session() as s:
        yield s


@pytest_asyncio.fixture
async def auth_headers(client, db_session):
    """工厂夹具：注册 → 验证 → 登录，返回带 token 的请求头。"""

    async def _make(username: str, email: str, password: str = "password123") -> dict:
        resp = await client.post("/api/auth/register",
                                 json={"username": username, "email": email, "password": password})
        assert resp.status_code == 201, resp.text
        rec = (await db_session.scalars(
            select(EmailToken).where(EmailToken.type == TokenType.VERIFY)
            .order_by(EmailToken.id.desc()))).first()
        resp = await client.get(f"/api/auth/verify?token={rec.token}")
        assert resp.status_code == 200, resp.text
        resp = await client.post("/api/auth/login", json={"username": username, "password": password})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['access_token']}"}

    return _make


@pytest.fixture
def storage_tmp(workspace_env):
    """任务文件写到临时目录，不污染仓库 storage/。"""
    return workspace_env


@pytest_asyncio.fixture
async def submit_task(client):
    """工厂夹具：提交一个任务（默认 Mock 立即成功）。"""
    import json as _json

    async def _submit(headers, params=None, data=b"1,2,3\n4,5,6\n", filename="data.csv"):
        params = params if params is not None else {"grid_size": 10, "mock_sleep": 0}
        return await client.post(
            "/api/tasks",
            data={"params": _json.dumps(params)},
            files={"file": (filename, data)},
            headers=headers,
        )

    return _submit


@pytest_asyncio.fixture
async def admin_headers(client, db_session):
    """直接建一个激活的管理员并登录，返回请求头。"""
    from app.models import User, UserRole, UserStatus
    from app.security import hash_password

    db_session.add(User(
        username="admin", email="admin@example.com",
        password_hash=hash_password("adminpass123"),
        role=UserRole.ADMIN, status=UserStatus.ACTIVE,
    ))
    await db_session.commit()
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "adminpass123"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
