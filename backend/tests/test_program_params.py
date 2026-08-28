"""BE/FDEM 当前参数、任务快照与历史只读 API。"""
import asyncio
import copy
import hashlib
import sys

import pytest
from sqlalchemy import select

from app.models import ArchiveStatus, Task, TaskStatus, User
from app.scheduler.dispatcher import dispatch_once
from app.scheduler import runner as runner_service
from app.em_param_schema import parse_parameter_bytes, schema_version_for
from app.services.storage import canonical_program_param_path, params_path, path_from_relative


CASES = [
    ("be_fetd", "grounded_wire", 1, "GroundedWireSource.dat"),
    ("be_fetd", "loop", 2, "LoopSource.dat"),
    ("fdem3d_frequency_domain", "grounded_wire", 1, "GroundedWireSource.dat"),
    ("fdem3d_frequency_domain", "loop", 2, "LoopSource.dat"),
]


@pytest.mark.parametrize("program_key,source_type,choice,filename", CASES)
async def test_current_default_upload_and_save(
    client, auth_headers, storage_tmp,
    program_key, source_type, choice, filename,
):
    headers = await auth_headers(
        f"params_{program_key[:5]}_{choice}", f"params-{program_key[:5]}-{choice}@example.com")
    base = f"/api/program-params/{program_key}/{source_type}"
    current = (await client.get(f"{base}/current", headers=headers)).json()
    assert current["filename"] == filename
    assert current["schema_version"] == schema_version_for(program_key)
    default = (await client.get(f"{base}/default", headers=headers)).json()
    assert default["document"] == current["document"]

    original = (await client.get(f"{base}/current/file", headers=headers)).content
    parsed = (await client.post(
        f"{base}/parse", headers=headers,
        files={"file": (filename, original, "application/octet-stream")},
    )).json()
    assert parsed["document"] == current["document"]

    changed = copy.deepcopy(parsed["document"])
    changed["source"]["current"] = 2.5 + choice
    saved_response = await client.put(
        f"{base}/current", headers=headers,
        json={"document": changed, "expected_sha256": current["sha256"]},
    )
    assert saved_response.status_code == 200, saved_response.text
    saved = saved_response.json()
    assert saved["document"]["source"]["current"] == 2.5 + choice
    assert saved["sha256"] != current["sha256"]

    downloaded = await client.get(f"{base}/current/file", headers=headers)
    assert downloaded.status_code == 200
    assert parse_parameter_bytes(program_key, source_type, downloaded.content) == saved["document"]


async def test_stale_revision_preserves_newer_current(client, auth_headers, storage_tmp):
    headers = await auth_headers("em_stale", "em-stale@example.com")
    base = "/api/program-params/be_fetd/grounded_wire"
    current = (await client.get(f"{base}/current", headers=headers)).json()
    first = copy.deepcopy(current["document"])
    first["source"]["current"] = 3.0
    saved = (await client.put(
        f"{base}/current", headers=headers,
        json={"document": first, "expected_sha256": current["sha256"]},
    )).json()
    stale = copy.deepcopy(current["document"])
    stale["source"]["current"] = 4.0
    response = await client.put(
        f"{base}/current", headers=headers,
        json={"document": stale, "expected_sha256": current["sha256"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "stale_revision"
    assert (await client.get(f"{base}/current", headers=headers)).json()["sha256"] == saved["sha256"]


async def test_queued_task_snapshot_isolated_and_archive_copy_on_write(
    client, auth_headers, db_session, storage_tmp,
):
    headers = await auth_headers("em_snapshot", "em-snapshot@example.com")
    program_key, source_type, choice, filename = CASES[3]
    base = f"/api/program-params/{program_key}/{source_type}"
    initial = (await client.get(f"{base}/current", headers=headers)).json()
    submitted_doc = copy.deepcopy(initial["document"])
    submitted_doc["source"]["current"] = 6.0
    submitted = (await client.put(
        f"{base}/current", headers=headers,
        json={"document": submitted_doc, "expected_sha256": initial["sha256"]},
    )).json()
    response = await client.post(
        "/api/tasks", headers=headers,
        data={
            "program_key": program_key,
            "params": "{}",
            "stdin_choice": str(choice),
            "parameter_sha256": submitted["sha256"],
        },
        files={"file": ("mesh.mphtxt", b"mesh-em-snapshot")},
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    task = await db_session.get(Task, task_id)
    stage_file = path_from_relative(task.staging_dir) / filename
    stage_hash = hashlib.sha256(stage_file.read_bytes()).hexdigest()
    assert stage_hash == submitted["sha256"]

    newer_doc = copy.deepcopy(submitted["document"])
    newer_doc["source"]["current"] = 7.0
    newer = (await client.put(
        f"{base}/current", headers=headers,
        json={"document": newer_doc, "expected_sha256": submitted["sha256"]},
    )).json()
    assert hashlib.sha256(stage_file.read_bytes()).hexdigest() == stage_hash

    launched = await dispatch_once()
    await asyncio.gather(*launched)
    await db_session.refresh(task)
    assert task.status == TaskStatus.COMPLETED
    archive_file = path_from_relative(task.archive_dir) / filename
    before = hashlib.sha256(archive_file.read_bytes()).hexdigest()
    assert before == stage_hash
    current_canonical = canonical_program_param_path(task.user_id, program_key, filename)
    current_runtime = current_canonical.parents[2] / "programs" / program_key / filename
    assert hashlib.sha256(current_canonical.read_bytes()).hexdigest() == newer["sha256"]
    assert current_runtime.read_bytes() == current_canonical.read_bytes()

    versions = (await client.get(f"{base}/versions", headers=headers)).json()
    assert versions["items"][0]["task_id"] == task_id
    assert versions["items"][0]["loadable"] is True
    historical = (await client.get(f"{base}/versions/{task_id}", headers=headers)).json()
    assert historical["document"]["source"]["current"] == 6.0
    copied_doc = copy.deepcopy(historical["document"])
    copied_doc["source"]["current"] = 8.0
    copied = await client.put(
        f"{base}/current", headers=headers,
        json={
            "document": copied_doc,
            "expected_sha256": newer["sha256"],
            "source_task_id": task_id,
        },
    )
    assert copied.status_code == 200, copied.text
    assert hashlib.sha256(archive_file.read_bytes()).hexdigest() == before


async def test_history_ownership_and_busy_save(
    client, auth_headers, db_session, storage_tmp,
):
    headers_a = await auth_headers("em_owner_a", "em-owner-a@example.com")
    headers_b = await auth_headers("em_owner_b", "em-owner-b@example.com")
    base = "/api/program-params/be_fetd/loop"
    current = (await client.get(f"{base}/current", headers=headers_a)).json()
    owner = await db_session.scalar(select(User).where(User.email == "em-owner-a@example.com"))
    task = Task(
        user_id=owner.id,
        status=TaskStatus.RUNNING,
        archive_status=ArchiveStatus.PENDING,
        program_key="be_fetd",
        source_type="loop",
        stdin_choice=2,
        params=current["document"],
    )
    db_session.add(task)
    await db_session.commit()
    response = await client.put(
        f"{base}/current", headers=headers_a,
        json={"document": current["document"], "expected_sha256": current["sha256"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "workspace_busy"
    assert (await client.get(f"{base}/versions/999999", headers=headers_b)).status_code == 404


async def test_source_task_cancel_restores_both_current_files(
    client, auth_headers, db_session, storage_tmp, monkeypatch,
):
    monkeypatch.setattr(runner_service, "build_argv", lambda *_: [
        sys.executable, "-c", "import time;time.sleep(30)",
    ])
    headers = await auth_headers("em_cancel", "em-cancel@example.com")
    program_key = "be_fetd"
    current = (await client.get(
        "/api/program-params/be_fetd/grounded_wire/current", headers=headers,
    )).json()
    response = await client.post(
        "/api/tasks", headers=headers,
        data={
            "program_key": program_key,
            "params": "{}",
            "stdin_choice": "1",
            "parameter_sha256": current["sha256"],
        },
        files={"file": ("mesh.mphtxt", b"mesh-cancel")},
    )
    assert response.status_code == 201, response.text
    task_id = response.json()["id"]
    launched = await dispatch_once()
    await asyncio.sleep(0.3)
    assert (await client.post(f"/api/tasks/{task_id}/cancel", headers=headers)).status_code == 200
    await asyncio.gather(*launched)
    task = await db_session.get(Task, task_id)
    assert task.status == TaskStatus.CANCELED
    for filename in ("GroundedWireSource.dat", "LoopSource.dat"):
        assert params_path(task.user_id, program_key, filename).read_bytes() == (
            canonical_program_param_path(task.user_id, program_key, filename).read_bytes()
        )
