"""BE/FDEM 当前参数迁移分类与不可覆盖规则。"""
import importlib.util
from pathlib import Path

from app.em_param_schema import parse_parameter_bytes
from app.services.storage import canonical_program_param_path, params_path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "migrate_source_real_params.py"
SPEC = importlib.util.spec_from_file_location("migrate_source_real_params", SCRIPT)
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_known_placeholder_is_backed_up_and_seeded(workspace_env):
    user_id = 801
    runtime = params_path(user_id, "be_fetd", "GroundedWireSource.dat")
    runtime.parent.mkdir(parents=True)
    runtime.write_text("# old\nsource_type = grounded_wire\n", encoding="utf-8")
    actions, error = migration.migrate_file(
        user_id, "be_fetd", "grounded_wire", "GroundedWireSource.dat",
        execute=True, stamp="test-stamp",
    )
    assert error is None
    canonical = canonical_program_param_path(user_id, "be_fetd", "GroundedWireSource.dat")
    parse_parameter_bytes("be_fetd", "grounded_wire", canonical.read_bytes())
    assert runtime.read_bytes() == canonical.read_bytes()
    backup = workspace_env / str(user_id) / ".workspace-state" / "migration-backups" / "test-stamp"
    assert any(backup.iterdir())
    assert any("seed real default" in action for action in actions)


def test_valid_runtime_is_adopted_without_rewriting(workspace_env):
    user_id = 802
    runtime = params_path(user_id, "fdem3d_frequency_domain", "LoopSource.dat")
    runtime.parent.mkdir(parents=True)
    default = Path(__file__).resolve().parents[2] / "docs" / "fdem3d_frequency_domain" / "LoopSource.dat"
    payload = default.read_bytes()
    runtime.write_bytes(payload)
    actions, error = migration.migrate_file(
        user_id, "fdem3d_frequency_domain", "loop", "LoopSource.dat",
        execute=True, stamp="test-stamp",
    )
    assert error is None
    canonical = canonical_program_param_path(user_id, "fdem3d_frequency_domain", "LoopSource.dat")
    assert canonical.read_bytes() == payload
    assert runtime.read_bytes() == payload
    assert any("adopt real runtime" in action for action in actions)


def test_unknown_invalid_file_is_preserved(workspace_env):
    user_id = 803
    runtime = params_path(user_id, "be_fetd", "LoopSource.dat")
    runtime.parent.mkdir(parents=True)
    payload = b"unknown-invalid-binary\xff\x00"
    runtime.write_bytes(payload)
    _, error = migration.migrate_file(
        user_id, "be_fetd", "loop", "LoopSource.dat",
        execute=True, stamp="test-stamp",
    )
    assert error is not None
    assert runtime.read_bytes() == payload
    assert not canonical_program_param_path(user_id, "be_fetd", "LoopSource.dat").exists()
