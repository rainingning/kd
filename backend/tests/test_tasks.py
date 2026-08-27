"""T4 任务核心测试：提交、调度、执行、超时、取消、并发限额、FIFO、重启恢复。

需要测试数据库；计算程序使用固定路径、无参数的 mock_dcr3d.py。
"""
import asyncio
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from app.models import Notification, NotificationType, SystemConfig, Task, TaskStatus, User
from app.scheduler import runner as runner_service
from app.scheduler.dispatcher import dispatch_once, recover_interrupted_tasks
from app.services.program_template import ProgramTemplateError
from app.services.storage import path_from_relative
from app.services.workspace import prepare_task_workspace


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

    stages = list(storage_tmp.glob("*/staging/*"))
    assert len(stages) == 1
    assert json.loads((stages[0] / "model_DC.dat").read_text())["grid_size"] == 10
    assert (stages[0] / "mesh.mphtxt").read_bytes() == b"1,2,3\n4,5,6\n"


@pytest.mark.parametrize("program_key,choice,selected_name", [
    ("be_fetd", 1, "GroundedWireSource.dat"),
    ("be_fetd", 2, "LoopSource.dat"),
    ("fdem3d_frequency_domain", 1, "GroundedWireSource.dat"),
    ("fdem3d_frequency_domain", 2, "LoopSource.dat"),
])
async def test_uploaded_parameter_program_stdin_and_archive(
    client, auth_headers, db_session, storage_tmp,
    program_key, choice, selected_name,
):
    headers = await auth_headers(f"u_{program_key[:8]}_{choice}", f"{program_key[:8]}-{choice}@example.com")
    payload = f"custom-{program_key}-{choice}\n".encode()
    resp = await client.post(
        "/api/tasks",
        data={"program_key": program_key, "params": "{}", "stdin_choice": str(choice)},
        files={
            "file": ("mesh.mphtxt", b"mesh-data"),
            "parameter_file": (selected_name, payload, "application/octet-stream"),
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["program_key"] == program_key
    assert body["stdin_choice"] == choice
    assert body["parameter_filename"] == selected_name

    launched = await dispatch_once()
    await asyncio.gather(*launched)
    task = await _task(db_session, body["id"])
    assert task.status == TaskStatus.COMPLETED
    archive = storage_tmp / task.archive_dir
    assert (archive / selected_name).read_bytes() == payload
    assert (archive / "GroundedWireSource.dat").is_file()
    assert (archive / "LoopSource.dat").is_file()
    assert f"choice {choice}" in (archive / "stdout.txt").read_text()
    metadata = json.loads((archive / "task.json").read_text(encoding="utf-8"))
    assert metadata["stdin_choice"] == choice
    assert set(metadata["runtime_file_hashes"]) == {
        "GroundedWireSource.dat", "LoopSource.dat",
    }


async def test_new_program_rejects_missing_or_invalid_choice(client, auth_headers, storage_tmp):
    headers = await auth_headers("invalid_choice", "invalid-choice@example.com")
    base_files = {"file": ("mesh.mphtxt", b"mesh")}
    missing = await client.post(
        "/api/tasks", data={"program_key": "be_fetd", "params": "{}"},
        files=base_files, headers=headers)
    assert missing.status_code == 422
    invalid = await client.post(
        "/api/tasks",
        data={"program_key": "be_fetd", "params": "{}", "stdin_choice": "3"},
        files={**base_files, "parameter_file": ("x.dat", b"x")}, headers=headers)
    assert invalid.status_code == 422


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
    assert list(storage_tmp.glob("*/staging/*")) == []


# ---- T4.2/T4.3 调度与执行 ----

async def test_low_disk_blocks_workspace_overwrite(
    client, auth_headers, submit_task, db_session, storage_tmp, monkeypatch,
):
    headers = await auth_headers("disk_user", "disk@example.com")
    task_id = (await submit_task(headers)).json()["id"]
    monkeypatch.setattr(
        runner_service.shutil,
        "disk_usage",
        lambda _path: SimpleNamespace(free=0),
    )

    launched = await dispatch_once()
    await asyncio.gather(*launched)
    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert "磁盘剩余空间不足" in task.error_message
    assert task.workspace_was_used is False
    assert task.archive_status == "COMPLETED"


async def test_invalid_program_template_blocks_task_start(
    client, auth_headers, submit_task, db_session, storage_tmp, monkeypatch,
):
    headers = await auth_headers("template_fail", "template-fail@example.com")
    task_id = (await submit_task(headers)).json()["id"]

    def invalid_template(*_args, **_kwargs):
        raise ProgramTemplateError("simulated template hash mismatch")

    monkeypatch.setattr(runner_service, "validate_program_template", invalid_template)
    await asyncio.gather(*(await dispatch_once()))
    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert "程序模板不可用" in task.error_message
    assert task.workspace_was_used is False
    assert task.archive_status == "COMPLETED"


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

    archive = storage_tmp / task.archive_dir
    assert "mock DCR_3D completed" in (archive / "stdout.txt").read_text()
    assert (archive / "Forward_data" / "summary.txt").is_file()
    assert task.archive_status == "COMPLETED"

    note = (await db_session.scalars(select(Notification))).first()
    assert note.type == NotificationType.COMPLETED


async def test_sequential_tasks_preserve_immutable_archives(
    client, auth_headers, db_session, storage_tmp,
):
    headers = await auth_headers("serial_user", "serial@example.com")
    first_id = (await _submit(client, headers, data=b"first-mesh")).json()["id"]
    await asyncio.gather(*(await dispatch_once()))
    first = await _task(db_session, first_id)
    first_archive = storage_tmp / first.archive_dir
    assert (first_archive / "mesh" / "mesh.mphtxt").read_bytes() == b"first-mesh"

    second_id = (await _submit(client, headers, data=b"second-mesh")).json()["id"]
    await asyncio.gather(*(await dispatch_once()))
    second = await _task(db_session, second_id)
    second_archive = storage_tmp / second.archive_dir

    assert first.status == TaskStatus.COMPLETED
    assert second.status == TaskStatus.COMPLETED
    assert first.archive_version != second.archive_version
    assert (first_archive / "mesh" / "mesh.mphtxt").read_bytes() == b"first-mesh"
    assert (second_archive / "mesh" / "mesh.mphtxt").read_bytes() == b"second-mesh"
    assert (
        storage_tmp / str(second.user_id) / "programs" / "dcr_3d" / "mesh" / "mesh.mphtxt"
    ).read_bytes() == b"second-mesh"


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
    archive = storage_tmp / task.archive_dir
    assert "failed" in (archive / "stderr.txt").read_text()
    assert task.archive_status == "COMPLETED"

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
    assert task.archive_status == "COMPLETED"
    archive = storage_tmp / task.archive_dir
    assert (archive / "mesh" / "mesh.mphtxt").is_file()
    metadata = json.loads((archive / "task.json").read_text(encoding="utf-8"))
    for key in (
        "queued_at", "started_at", "finished_at", "archived_at", "program_version",
        "exe_sha256", "dll_sha256", "archive_version", "result_file_count",
        "result_size_bytes",
    ):
        assert key in metadata


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
    assert (await _task(db_session, id1)).status in {
        TaskStatus.PREPARING, TaskStatus.RUNNING, TaskStatus.ARCHIVING, TaskStatus.COMPLETED,
    }
    assert (await _task(db_session, id2)).status == TaskStatus.QUEUED
    await asyncio.gather(*launched)

    launched = await dispatch_once()
    assert len(launched) == 1
    await asyncio.gather(*launched)
    assert (await _task(db_session, id1)).status == TaskStatus.COMPLETED
    assert (await _task(db_session, id2)).status == TaskStatus.COMPLETED


async def test_different_users_can_run_concurrently(
    client, auth_headers, db_session, storage_tmp,
):
    headers_a = await auth_headers("parallel_a", "parallel-a@example.com")
    headers_b = await auth_headers("parallel_b", "parallel-b@example.com")
    id_a = (await _submit(
        client, headers_a, params={"grid_size": 10, "mock_sleep": 0.2})).json()["id"]
    id_b = (await _submit(
        client, headers_b, params={"grid_size": 10, "mock_sleep": 0.2})).json()["id"]

    launched = await dispatch_once()
    assert len(launched) == 2
    await asyncio.gather(*launched)
    assert (await _task(db_session, id_a)).status == TaskStatus.COMPLETED
    assert (await _task(db_session, id_b)).status == TaskStatus.COMPLETED


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
    user = await db_session.get(User, task.user_id)
    prepare_task_workspace(
        user.id,
        path_from_relative(task.staging_dir),
        expected_exe_sha256=user.exe_sha256,
        expected_dll_sha256=user.dll_sha256,
    )
    task.status = TaskStatus.RUNNING
    task.program_version = user.program_version
    task.exe_sha256 = user.exe_sha256
    task.dll_sha256 = user.dll_sha256
    await db_session.commit()

    recovered = await recover_interrupted_tasks()
    assert recovered == 1
    task = await _task(db_session, task_id)
    assert task.status == TaskStatus.FAILED
    assert "重启" in task.error_message

    note = (await db_session.scalars(select(Notification))).first()
    assert note.type == NotificationType.FAILED
