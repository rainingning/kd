"""DCR 当前参数、历史版本和任务快照一致性测试。"""
import asyncio
from copy import deepcopy
from pathlib import Path

from sqlalchemy import select

from app.models import Task, User
from app.param_schema import SCHEMA_VERSION, parse_params
from app.scheduler.dispatcher import dispatch_once
from app.scheduler.user_lock import try_user_workspace_lock
from app.services.storage import canonical_params_path, params_path

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "model_DC.dat"


async def _user_id(db_session, username: str) -> int:
    return await db_session.scalar(select(User.id).where(User.username == username))


async def test_current_upload_save_download_and_stale_revision(
    client, auth_headers, db_session, storage_tmp,
):
    headers = await auth_headers("dcr_editor", "dcr-editor@example.com")
    user_id = await _user_id(db_session, "dcr_editor")

    current = await client.get("/api/dcr-params/current", headers=headers)
    assert current.status_code == 200
    body = current.json()
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["document"]["boundary_mode"] == 1
    assert canonical_params_path(user_id).is_file()
    assert params_path(user_id).read_bytes() == canonical_params_path(user_id).read_bytes()

    uploaded = await client.post(
        "/api/dcr-params/parse",
        files={"file": ("my_model.dat", SAMPLE.read_bytes(), "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code == 200
    document = uploaded.json()["document"]
    document["boundary_mode"] = 2
    saved = await client.put(
        "/api/dcr-params/current",
        json={"document": document, "expected_sha256": body["sha256"]},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["sha256"] != body["sha256"]
    assert parse_params(params_path(user_id).read_text())["boundary_mode"] == 2

    stale = await client.put(
        "/api/dcr-params/current",
        json={"document": document, "expected_sha256": body["sha256"]},
        headers=headers,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_revision"

    download = await client.get("/api/dcr-params/current/file", headers=headers)
    assert download.status_code == 200
    assert parse_params(download.text)["boundary_mode"] == 2


async def test_upload_validation_and_workspace_busy(
    client, auth_headers, db_session, storage_tmp,
):
    headers = await auth_headers("dcr_busy", "dcr-busy@example.com")
    user_id = await _user_id(db_session, "dcr_busy")
    bad = await client.post(
        "/api/dcr-params/parse",
        files={"file": ("bad.dat", b"1\n", "text/plain")},
        headers=headers,
    )
    assert bad.status_code == 422
    wrong_extension = await client.post(
        "/api/dcr-params/parse",
        files={"file": ("bad.txt", SAMPLE.read_bytes())},
        headers=headers,
    )
    assert wrong_extension.status_code == 422

    current = (await client.get("/api/dcr-params/current", headers=headers)).json()
    async with try_user_workspace_lock(user_id) as acquired:
        assert acquired
        response = await client.put(
            "/api/dcr-params/current",
            json={"document": current["document"], "expected_sha256": current["sha256"]},
            headers=headers,
        )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workspace_busy"


async def test_queued_snapshot_is_immutable_and_runtime_restores_latest_current(
    client, auth_headers, db_session, storage_tmp,
):
    headers = await auth_headers("dcr_snapshot", "dcr-snapshot@example.com")
    user_id = await _user_id(db_session, "dcr_snapshot")
    initial = (await client.get("/api/dcr-params/current", headers=headers)).json()

    submitted = await client.post(
        "/api/tasks",
        data={"params": "{}", "program_key": "dcr_3d", "dcr_parameter_sha256": initial["sha256"]},
        files={"file": ("mesh.mphtxt", b"mesh")},
        headers=headers,
    )
    assert submitted.status_code == 201, submitted.text
    task_id = submitted.json()["id"]

    edited = deepcopy(initial["document"])
    edited["materials"][0]["rho_x"] = 321.0
    saved = await client.put(
        "/api/dcr-params/current",
        json={"document": edited, "expected_sha256": initial["sha256"]},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    latest_hash = saved.json()["sha256"]

    await asyncio.gather(*(await dispatch_once()))
    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)
    archive = storage_tmp / task.archive_dir
    archived_model = parse_params((archive / "model_DC.dat").read_text())
    assert archived_model["materials"][0]["rho_x"] == initial["document"]["materials"][0]["rho_x"]
    assert parse_params(params_path(user_id).read_text())["materials"][0]["rho_x"] == 321.0
    assert canonical_params_path(user_id).read_bytes() == params_path(user_id).read_bytes()
    assert task.parameter_sha256 == initial["sha256"]
    assert task.parameter_schema_version == SCHEMA_VERSION

    versions = await client.get("/api/dcr-params/versions", headers=headers)
    assert versions.status_code == 200
    assert versions.json()["items"][0]["task_id"] == task_id
    assert versions.json()["items"][0]["loadable"] is True
    loaded = await client.get(f"/api/dcr-params/versions/{task_id}", headers=headers)
    assert loaded.status_code == 200
    assert loaded.json()["document"] == initial["document"]
    assert loaded.json()["sha256"] == initial["sha256"]
    assert saved.json()["sha256"] == latest_hash


async def test_archived_version_is_owner_scoped(client, auth_headers, db_session, storage_tmp):
    headers_a = await auth_headers("dcr_owner_a", "dcr-owner-a@example.com")
    headers_b = await auth_headers("dcr_owner_b", "dcr-owner-b@example.com")
    current = (await client.get("/api/dcr-params/current", headers=headers_a)).json()
    submitted = await client.post(
        "/api/tasks",
        data={"params": "{}", "dcr_parameter_sha256": current["sha256"]},
        files={"file": ("mesh.mphtxt", b"mesh")}, headers=headers_a,
    )
    task_id = submitted.json()["id"]
    await asyncio.gather(*(await dispatch_once()))
    assert (await client.get(f"/api/dcr-params/versions/{task_id}", headers=headers_b)).status_code == 404
