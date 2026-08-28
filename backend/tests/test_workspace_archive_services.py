"""固定用户工作区、暂存和归档基础服务单元测试（无需数据库）。"""
import importlib.util
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

from app.config import REPO_ROOT, settings
from app.scheduler.runner import build_argv
from app.services import workspace as workspace_service
from app.services.archive import (
    archive_task_files, archive_version, remove_temporary_archives,
)
from app.services.dcr_params import get_current_document, save_current_document
from app.services.program_params import (
    get_current_document as get_source_current_document,
    save_current_document as save_source_current_document,
)
from app.services.program_template import ProgramTemplateError, sha256_file, validate_program_template
from app.services.result_zip import ensure_result_zip
from app.services.staging import (
    UploadTooLargeError,
    create_staging,
    write_staged_upload,
    write_staging_metadata,
)
from app.services.storage import (
    MESH_FILE,
    PARAMS_FILE,
    RESULT_DIR,
    TASK_META_FILE,
    archive_dir,
    canonical_params_path,
    mesh_path,
    params_path,
    result_dir,
    staging_dir,
    user_root,
)
from app.services.workspace import (
    WorkspaceError,
    check_workspace,
    initialize_workspace,
    prepare_task_workspace,
    sync_program_files,
)


def _make_template(root: Path, *, version: str = "1.2.3") -> Path:
    root.mkdir()
    for program_key, executable in {
        "dcr_3d": "DCR_3D.exe",
        "be_fetd": "BE_FETD.exe",
        "fdem3d_frequency_domain": "FDEM3D_Frequency_Domain.exe",
    }.items():
        directory = root / "programs" / program_key
        directory.mkdir(parents=True)
        exe = directory / executable
        dll = directory / "libiomp5md.dll"
        exe.write_bytes(b"fake-exe-v1")
        dll.write_bytes(b"fake-dll-v1")
        parameter_sha256 = {}
        if program_key == "dcr_3d":
            path = directory / "model_DC.dat"
            shutil.copy2(REPO_ROOT / "docs" / "model_DC.dat", path)
            parameter_sha256[path.name] = sha256_file(path)
        else:
            for filename in ("GroundedWireSource.dat", "LoopSource.dat"):
                path = directory / filename
                shutil.copy2(REPO_ROOT / "docs" / program_key / filename, path)
                parameter_sha256[filename] = sha256_file(path)
        (directory / "program-manifest.json").write_text(json.dumps({
            "program_key": program_key,
            "version": version,
            "exe": executable,
            "dll": dll.name,
            "exe_sha256": sha256_file(exe),
            "dll_sha256": sha256_file(dll),
            "parameter_sha256": parameter_sha256,
        }), encoding="utf-8")
    return root


def test_program_template_validation(tmp_path):
    template = _make_template(tmp_path / "template")
    manifest = validate_program_template(template)
    assert manifest.version == "1.2.3"
    assert manifest.exe == "DCR_3D.exe"

    (template / "programs" / "dcr_3d" / "DCR_3D.exe").write_bytes(b"tampered")
    with pytest.raises(ProgramTemplateError, match="SHA-256"):
        validate_program_template(template)


def test_initialize_and_check_workspace(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    template = _make_template(tmp_path / "template")
    monkeypatch.setattr(settings, "storage_root", storage)

    manifest = initialize_workspace(42, template_dir=template)
    root = user_root(42)
    dcr_root = root / "programs" / "dcr_3d"
    assert (dcr_root / "DCR_3D.exe").read_bytes() == b"fake-exe-v1"
    assert (dcr_root / "libiomp5md.dll").read_bytes() == b"fake-dll-v1"
    assert (dcr_root / "mesh").is_dir()
    assert (dcr_root / "Forward_data").is_dir()
    assert (root / "staging").is_dir()
    assert (root / "archives").is_dir()
    assert (root / "programs" / "be_fetd" / "GroundedWireSource.dat").is_file()
    assert (root / "programs" / "fdem3d_frequency_domain" / "LoopSource.dat").is_file()

    check = check_workspace(
        42,
        expected_version=manifest.version,
        expected_exe_sha256=manifest.exe_sha256,
        expected_dll_sha256=manifest.dll_sha256,
    )
    assert check.ready
    assert check.errors == ()


def test_program_sync_preserves_user_saved_dcr_params(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    template = _make_template(tmp_path / "template")
    monkeypatch.setattr(settings, "storage_root", storage)
    initialize_workspace(43, template_dir=template)
    current = get_current_document(43)
    changed = json.loads(json.dumps(current.document))
    changed["materials"][0]["rho_x"] = 777.0
    saved = save_current_document(43, changed, expected_sha256=current.sha256)

    initialize_workspace(43, template_dir=template)
    after = get_current_document(43)
    assert after.sha256 == saved.sha256
    assert after.document["materials"][0]["rho_x"] == 777.0
    assert params_path(43).read_bytes() == canonical_params_path(43).read_bytes()


def test_program_sync_preserves_source_params(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    template = _make_template(tmp_path / "template")
    monkeypatch.setattr(settings, "storage_root", storage)
    initialize_workspace(44, template_dir=template)
    current = get_source_current_document(44, "be_fetd", "loop")
    changed = json.loads(json.dumps(current.document))
    changed["source"]["current"] = 9.5
    saved = save_source_current_document(
        44, "be_fetd", "loop", changed, expected_sha256=current.sha256)

    initialize_workspace(44, template_dir=template)
    after = get_source_current_document(44, "be_fetd", "loop")
    assert after.sha256 == saved.sha256
    assert after.document["source"]["current"] == 9.5
    assert params_path(44, "be_fetd", "LoopSource.dat").read_bytes() == (
        storage / "44" / ".workspace-state" / "be_fetd" / "LoopSource.dat"
    ).read_bytes()


def test_program_pair_sync_rolls_back_on_second_replace_failure(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    template = _make_template(tmp_path / "template")
    monkeypatch.setattr(settings, "storage_root", storage)
    initialize_workspace(9, template_dir=template)

    dcr_template = template / "programs" / "dcr_3d"
    exe = dcr_template / "DCR_3D.exe"
    dll = dcr_template / "libiomp5md.dll"
    exe.write_bytes(b"fake-exe-v2")
    dll.write_bytes(b"fake-dll-v2")
    (dcr_template / "program-manifest.json").write_text(json.dumps({
        "program_key": "dcr_3d",
        "version": "2.0.0",
        "exe": exe.name,
        "dll": dll.name,
        "exe_sha256": sha256_file(exe),
        "dll_sha256": sha256_file(dll),
        "parameter_sha256": {
            "model_DC.dat": sha256_file(dcr_template / "model_DC.dat"),
        },
    }), encoding="utf-8")

    real_replace = workspace_service.os.replace
    failed = False

    def flaky_replace(source, destination):
        nonlocal failed
        source = Path(source)
        destination = Path(destination)
        if (not failed and destination.name == "libiomp5md.dll"
                and ".sync-" in source.name):
            failed = True
            raise OSError("simulated DLL replace failure")
        return real_replace(source, destination)

    monkeypatch.setattr(workspace_service.os, "replace", flaky_replace)
    with pytest.raises(OSError, match="simulated"):
        sync_program_files(9, template_dir=template)

    dcr_root = user_root(9) / "programs" / "dcr_3d"
    assert (dcr_root / "DCR_3D.exe").read_bytes() == b"fake-exe-v1"
    assert (dcr_root / "libiomp5md.dll").read_bytes() == b"fake-dll-v1"


def test_prepare_fixed_workspace_clears_old_results(tmp_path, monkeypatch):
    storage = tmp_path / "storage"
    template = _make_template(tmp_path / "template")
    monkeypatch.setattr(settings, "storage_root", storage)
    manifest = initialize_workspace(8, template_dir=template)
    stage = create_staging(8, 21, "new-model\n")
    (stage / MESH_FILE).write_bytes(b"new-mesh")
    (result_dir(8) / "old.txt").write_text("old", encoding="utf-8")

    prepare_task_workspace(
        8,
        stage,
        expected_exe_sha256=manifest.exe_sha256,
        expected_dll_sha256=manifest.dll_sha256,
    )

    assert params_path(8).read_text() == "new-model\n"
    assert mesh_path(8).read_bytes() == b"new-mesh"
    assert result_dir(8).is_dir()
    assert list(result_dir(8).iterdir()) == []


class _Upload:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    async def read(self, size=-1):
        if self.offset >= len(self.data):
            return b""
        end = len(self.data) if size < 0 else min(len(self.data), self.offset + size)
        chunk = self.data[self.offset:end]
        self.offset = end
        return chunk


async def test_staging_upload_and_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    directory = create_staging(7, 11, '{"grid_size": 10}\n')
    size = await write_staged_upload(directory, _Upload(b"mesh-data"), max_bytes=100)
    write_staging_metadata(directory, {"task_id": 11})
    assert size == 9
    assert (directory / PARAMS_FILE).is_file()
    assert (directory / MESH_FILE).read_bytes() == b"mesh-data"
    assert json.loads((directory / TASK_META_FILE).read_text())["task_id"] == 11

    other = create_staging(7, 12, "{}\n")
    with pytest.raises(UploadTooLargeError):
        await write_staged_upload(other, _Upload(b"too-large"), max_bytes=3)
    assert not (other / MESH_FILE).exists()


def test_archive_publishes_immutable_version(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(settings, "result_zip_cache_root", tmp_path / "zip-cache")
    uid, task_id = 5, 99
    stage = create_staging(uid, task_id, "model\n")
    (stage / MESH_FILE).write_bytes(b"queued-mesh")
    (stage / "stdout.txt").write_text("out", encoding="utf-8")
    (stage / "stderr.txt").write_text("err", encoding="utf-8")

    params_path(uid).parent.mkdir(parents=True, exist_ok=True)
    params_path(uid).write_text("active-model\n", encoding="utf-8")
    mesh_path(uid).parent.mkdir(parents=True, exist_ok=True)
    mesh_path(uid).write_bytes(b"active-mesh")
    result_dir(uid).mkdir(parents=True, exist_ok=True)
    (result_dir(uid) / "a.txt").write_text("A", encoding="utf-8")
    (result_dir(uid) / "nested").mkdir()
    (result_dir(uid) / "nested" / "b.bin").write_bytes(b"BB")

    archived = archive_task_files(
        user_id=uid,
        task_id=task_id,
        staging=stage,
        metadata={"task_id": task_id, "status": "COMPLETED"},
        workspace_was_used=True,
    )
    target = archive_dir(uid, archived.version)
    assert target.is_dir()
    assert (target / PARAMS_FILE).read_text() == "model\n"
    assert (target / "mesh" / MESH_FILE).read_bytes() == b"active-mesh"
    assert (target / RESULT_DIR / "nested" / "b.bin").read_bytes() == b"BB"
    assert archived.result_file_count == 2
    assert archived.result_size_bytes == 3
    assert json.loads((target / TASK_META_FILE).read_text())["archive_version"] == archived.version

    zip_path = ensure_result_zip(task_id, archived.version, target)
    with zipfile.ZipFile(zip_path) as bundle:
        assert sorted(bundle.namelist()) == [
            "Forward_data/a.txt", "Forward_data/nested/b.bin"]
        assert bundle.read("Forward_data/nested/b.bin") == b"BB"

    # 相同版本重复归档为幂等读取，不创建第二个目录。
    repeated = archive_task_files(
        user_id=uid,
        task_id=task_id,
        staging=stage,
        metadata={"task_id": task_id},
        workspace_was_used=True,
        version=archived.version,
    )
    assert repeated == archived

    # 覆盖活动工作区不能改变历史归档。
    params_path(uid).write_text("next-model\n", encoding="utf-8")
    assert (target / PARAMS_FILE).read_text() == "model\n"


def test_remove_only_temporary_archives(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    root = user_root(3) / "archives"
    (root / ".tmp_7_deadbeef").mkdir(parents=True)
    (root / "20260808T153012.345Z_task7").mkdir()
    assert remove_temporary_archives(3) == 1
    assert not (root / ".tmp_7_deadbeef").exists()
    assert (root / "20260808T153012.345Z_task7").exists()


def test_archive_version_is_utc_and_unique_by_task():
    from datetime import datetime, timezone

    instant = datetime(2026, 8, 8, 15, 30, 12, 345678, tzinfo=timezone.utc)
    assert archive_version(123, instant) == "20260808T153012.345Z_task123"


def test_runner_builds_no_argument_commands(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "storage_root", tmp_path / "storage")
    monkeypatch.setattr(settings, "execution_mode", "dcr3d")
    assert build_argv(17) == [str(user_root(17) / "programs" / "dcr_3d" / "DCR_3D.exe")]
    assert build_argv(17, "be_fetd") == [
        str(user_root(17) / "programs" / "be_fetd" / "BE_FETD.exe")
    ]

    monkeypatch.setattr(settings, "execution_mode", "mock")
    monkeypatch.setattr(
        settings,
        "mock_fortran_command",
        f'"{sys.executable}" "{REPO_ROOT / "mock" / "mock_fortran_solver.py"}"',
    )
    argv = build_argv(17)
    assert argv == [sys.executable, str(REPO_ROOT / "mock" / "mock_fortran_solver.py")]
    assert all("model_DC.dat" not in value and "mesh.mphtxt" not in value for value in argv)


def test_fixed_path_mock(tmp_path, monkeypatch):
    workspace = tmp_path / "dcr_3d"
    (workspace / "mesh").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "docs" / "model_DC.dat", workspace / PARAMS_FILE)
    (workspace / "mesh" / MESH_FILE).write_bytes(b"mesh")
    monkeypatch.chdir(workspace)
    monkeypatch.setattr(sys, "argv", ["mock_fortran_solver.py"])

    source = REPO_ROOT / "mock" / "mock_fortran_solver.py"
    spec = importlib.util.spec_from_file_location("mock_dcr3d_test", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.main() == 0
    assert (workspace / RESULT_DIR / "summary.txt").is_file()
    assert (workspace / RESULT_DIR / "details" / "parameters.json").is_file()
