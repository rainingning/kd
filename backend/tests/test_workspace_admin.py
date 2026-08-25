"""用户工作区、程序同步和归档重试管理 API 测试。"""
import asyncio

from sqlalchemy import select

from app.models import Task, TaskStatus, User
from app.scheduler.dispatcher import dispatch_once, reconcile_storage
from app.services.program_sync import sync_pending_users_once
from app.routers import tasks as tasks_router
from app.services.archive import ArchiveError


async def test_program_template_user_sync_and_workspace_check(
    client, admin_headers, auth_headers, db_session, storage_tmp,
):
    await auth_headers("workspace_user", "workspace@example.com")
    user_id = await db_session.scalar(
        select(User.id).where(User.username == "workspace_user"))

    response = await client.get("/api/admin/program-template", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["version"] == "test-1.0.0"

    response = await client.post(
        f"/api/admin/users/{user_id}/program-sync", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "synced"

    response = await client.post(
        f"/api/admin/users/{user_id}/workspace-check", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["ready"] is True
    assert response.json()["errors"] == []

    response = await client.get("/api/admin/program-sync/status", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["synced"] >= 1
    assert body["deferred"] == 0


async def test_batch_program_sync_initializes_all_users(
    client, admin_headers, auth_headers, storage_tmp,
):
    await auth_headers("sync_user", "sync@example.com")
    response = await client.post("/api/admin/program-sync", headers=admin_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert body["synced"] == 2
    assert body["failed"] == 0
    assert body["deferred"] == 0


async def test_running_user_program_sync_is_deferred_and_retried(
    client, admin_headers, auth_headers, submit_task, db_session, storage_tmp,
):
    headers = await auth_headers("deferred_user", "deferred@example.com")
    user_id = await db_session.scalar(
        select(User.id).where(User.username == "deferred_user"))
    task_id = (await submit_task(
        headers, params={"grid_size": 10, "mock_sleep": 30})).json()["id"]
    launched = await dispatch_once()
    await asyncio.sleep(0.3)

    response = await client.post(
        f"/api/admin/users/{user_id}/program-sync", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "deferred"

    status_response = await client.get(
        "/api/admin/program-sync/status", headers=admin_headers)
    assert status_response.json()["deferred"] == 1

    await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
    await asyncio.gather(*launched)
    results = await sync_pending_users_once()
    assert any(result.user_id == user_id and result.status == "synced" for result in results)


async def test_archive_failure_list_and_manual_retry(
    client, admin_headers, auth_headers, submit_task, db_session, monkeypatch, storage_tmp,
):
    headers = await auth_headers("archive_user", "archive@example.com")
    task_id = (await submit_task(headers)).json()["id"]

    real_archive = tasks_router.archive_task_files

    def fail_archive(*args, **kwargs):
        raise ArchiveError("simulated archive disk failure")

    monkeypatch.setattr(tasks_router, "archive_task_files", fail_archive)
    response = await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == TaskStatus.ARCHIVE_FAILED
    assert response.json()["terminal_status"] == TaskStatus.CANCELED
    assert response.json()["archive_retry_count"] == 1
    assert response.json()["archive_retry_at"] is not None

    response = await client.get("/api/admin/tasks/archive-failures", headers=admin_headers)
    assert response.status_code == 200
    failures = response.json()
    assert len(failures) == 1
    assert failures[0]["id"] == task_id
    assert failures[0]["archive_retry_count"] == 1

    monkeypatch.setattr(tasks_router, "archive_task_files", real_archive)
    response = await client.post(
        f"/api/admin/tasks/{task_id}/archive-retry", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["status"] == TaskStatus.CANCELED
    assert response.json()["archive_status"] == "COMPLETED"

    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)
    assert task.status == TaskStatus.CANCELED
    assert task.archive_dir
    assert (storage_tmp / task.archive_dir / "task.json").is_file()


async def test_startup_reconciliation_preserves_unknown_directories_and_marks_missing_staging(
    client, auth_headers, submit_task, db_session, storage_tmp,
):
    headers = await auth_headers("reconcile_user", "reconcile@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    task = await db_session.get(Task, task_id)
    user_root = storage_tmp / str(task.user_id)
    stage = storage_tmp / task.staging_dir
    for path in stage.iterdir():
        if path.is_file():
            path.unlink()
    stage.rmdir()

    unknown_stage = user_root / "staging" / "orphan-unknown"
    unknown_archive = user_root / "archives" / "orphan-unknown"
    temporary_archive = user_root / "archives" / ".tmp_99_deadbeef"
    unknown_stage.mkdir()
    unknown_archive.mkdir()
    temporary_archive.mkdir()

    summary = await reconcile_storage()
    assert summary["missing_queued"] == 1
    assert summary["orphan_staging"] == 1
    assert summary["orphan_archives"] == 1
    assert summary["temporary_archives"] == 1
    assert unknown_stage.exists()
    assert unknown_archive.exists()
    assert not temporary_archive.exists()

    await db_session.refresh(task)
    assert task.status == TaskStatus.ARCHIVE_FAILED
    assert task.terminal_status == TaskStatus.FAILED
    assert task.archive_error


async def test_single_user_runtime_limit_is_immutable(client, admin_headers):
    response = await client.put(
        "/api/admin/config",
        json={"config": {"max_running_per_user": "2"}},
        headers=admin_headers,
    )
    assert response.status_code == 422
