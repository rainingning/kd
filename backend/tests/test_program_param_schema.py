"""BE_FETD/FDEM3D 真实参数 schema 与 registry 单元测试。"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.em_param_schema import (
    MAX_FILE_BYTES,
    SCHEMA_VERSIONS,
    ParamValidationError,
    ParameterValidationError,
    UnsupportedParameterSchemaError,
    get_schema,
    list_schemas,
    parse_bytes,
    parse_parameter_bytes,
    schema_version,
    schema_version_for,
    serialize,
    serialize_parameter,
    validate,
    validate_parameter,
    validate_parameter_with_warnings,
)

DOCS = Path(__file__).resolve().parents[2] / "docs"
CASES = (
    ("be_fetd", "grounded_wire", DOCS / "be_fetd" / "GroundedWireSource.dat", "gb18030"),
    ("be_fetd", "loop", DOCS / "be_fetd" / "LoopSource.dat", "gb18030"),
    (
        "fdem3d_frequency_domain",
        "grounded_wire",
        DOCS / "fdem3d_frequency_domain" / "GroundedWireSource.dat",
        "utf-8",
    ),
    (
        "fdem3d_frequency_domain",
        "loop",
        DOCS / "fdem3d_frequency_domain" / "LoopSource.dat",
        "utf-8",
    ),
)


def _load(program_key: str, source_type: str) -> dict:
    path = next(item[2] for item in CASES if item[:2] == (program_key, source_type))
    return parse_bytes(program_key, source_type, path.read_bytes())


@pytest.mark.parametrize("program_key,source_type,path,encoding", CASES)
def test_real_sample_golden_and_canonical_roundtrip(program_key, source_type, path, encoding):
    document = parse_bytes(program_key, source_type, path.read_bytes())
    assert len(document["materials"]) == 4
    assert document["air_domain_ids"] == [2, 4]
    assert len(document["receivers"]) == 1
    assert document["source"]["type"] == source_type
    assert document["source"]["current"] == 1.0
    if source_type == "grounded_wire":
        assert len(document["source"]["segments"]) == 1
        assert document["source"]["segments"][0]["start"] == {"x": -25.0, "y": -25.0, "z": 0.0}
    else:
        assert document["source"]["turns"] == 1
        assert len(document["source"]["vertices"]) == 4

    canonical = serialize(program_key, source_type, document)
    canonical.decode(encoding)
    assert parse_bytes(program_key, source_type, canonical) == document
    assert validate(program_key, source_type, document) == document


def test_be_canonical_keeps_fixed_fortran_header_positions():
    for source_type in ("grounded_wire", "loop"):
        payload = serialize("be_fetd", source_type, _load("be_fetd", source_type))
        lines = payload.decode("gb18030").splitlines()
        assert lines[0].startswith("# Backward-Euler")
        assert lines[2].startswith("#")
        source_numeric_lines = 2 if source_type == "grounded_wire" else 3
        model_header_index = 3 + source_numeric_lines
        assert lines[model_header_index].startswith("#")
        material_count = int(lines[model_header_index + 2])
        first_material = lines[model_header_index + 3].split()
        assert material_count == 4
        assert len(first_material) == 9
        assert not lines[model_header_index + 3].startswith("#")


@pytest.mark.parametrize("program_key,source_type,path,encoding", CASES)
def test_registry_metadata(program_key, source_type, path, encoding):
    item = get_schema(program_key, source_type)
    assert item.program_key == program_key
    assert item.source_type == source_type
    assert item.encoding == encoding
    assert item.filename == path.name
    assert item.schema_version == schema_version(program_key, source_type)
    assert item.schema_version.endswith("-v1")
    assert item.parse_bytes(path.read_bytes()) == parse_bytes(program_key, source_type, path.read_bytes())


def test_registry_lists_four_schemas_and_rejects_unknown_key():
    assert {(item.program_key, item.source_type) for item in list_schemas()} == {
        ("be_fetd", "grounded_wire"),
        ("be_fetd", "loop"),
        ("fdem3d_frequency_domain", "grounded_wire"),
        ("fdem3d_frequency_domain", "loop"),
    }
    with pytest.raises(UnsupportedParameterSchemaError):
        get_schema("unknown", "loop")


def test_stable_em_param_schema_facade_for_callers():
    payload = (DOCS / "be_fetd" / "GroundedWireSource.dat").read_bytes()
    document = parse_parameter_bytes("be_fetd", "grounded_wire", payload)
    normalized, warnings = validate_parameter_with_warnings("be_fetd", "grounded_wire", document)
    assert warnings == []
    assert normalized == document
    assert validate_parameter("be_fetd", "grounded_wire", document) == document
    assert MAX_FILE_BYTES > len(payload)
    assert SCHEMA_VERSIONS["be_fetd"] == schema_version_for("be_fetd")
    assert parse_parameter_bytes(
        "be_fetd", "grounded_wire", serialize_parameter("be_fetd", "grounded_wire", document),
    ) == document
    assert schema_version_for("be_fetd") == schema_version_for("be_fetd", "loop")
    assert ParamValidationError is ParameterValidationError


def test_be_serializes_gb18030_and_fdem_accepts_utf8_bom_and_d_exponent():
    be = _load("be_fetd", "loop")
    be_bytes = serialize("be_fetd", "loop", be)
    assert "模型参数" in be_bytes.decode("gb18030")
    with pytest.raises(UnicodeDecodeError):
        be_bytes.decode("utf-8")

    original = (DOCS / "fdem3d_frequency_domain" / "GroundedWireSource.dat").read_text(encoding="utf-8")
    payload = ("\ufeff\n# extra comment\n" + original.replace("1.0d4", "1.0D4")).encode("utf-8")
    parsed = parse_bytes("fdem3d_frequency_domain", "grounded_wire", payload)
    assert parsed["frequency"]["max_hz"] == 10_000.0


@pytest.mark.parametrize(
    "program_key,source_type,payload,path",
    [
        ("be_fetd", "grounded_wire", b"", "$.time_stepping.blocks"),
        ("fdem3d_frequency_domain", "loop", b"\xff", "$"),
    ],
)
def test_encoding_or_early_eof_errors_have_json_path(program_key, source_type, payload, path):
    with pytest.raises(ParameterValidationError) as caught:
        parse_bytes(program_key, source_type, payload)
    assert path in caught.value.errors


@pytest.mark.parametrize("program_key,source_type", [(item[0], item[1]) for item in CASES])
def test_parser_rejects_truncation_and_trailing_tokens(program_key, source_type):
    document = _load(program_key, source_type)
    canonical = serialize(program_key, source_type, document)
    encoding = get_schema(program_key, source_type).encoding
    text = canonical.decode(encoding)
    truncated = text.rsplit(maxsplit=1)[0].encode(encoding)
    with pytest.raises(ParameterValidationError) as caught:
        parse_bytes(program_key, source_type, truncated)
    assert "$.receivers[0].z" in caught.value.errors

    with pytest.raises(ParameterValidationError) as caught:
        parse_bytes(program_key, source_type, canonical + "\n999\n".encode(encoding))
    assert "$" in caught.value.errors
    assert "多余参数" in caught.value.errors["$"]


@pytest.mark.parametrize("program_key", ["be_fetd", "fdem3d_frequency_domain"])
def test_common_material_air_and_numeric_validation_paths(program_key):
    document = _load(program_key, "grounded_wire")
    document["air_domain_ids"] = [2, 2, 999]
    document["materials"][1]["id"] = document["materials"][0]["id"]
    document["materials"][0]["rho_x"] = 0
    document["materials"][0]["alpha"] = float("nan")
    with pytest.raises(ParameterValidationError) as caught:
        validate(program_key, "grounded_wire", document)
    errors = caught.value.errors
    assert "$.air_domain_ids[1]" in errors
    assert "$.air_domain_ids[2]" in errors
    assert "$.materials[1].id" in errors
    assert "$.materials[0].rho_x" in errors
    assert "$.materials[0].alpha" in errors


@pytest.mark.parametrize("program_key", ["be_fetd", "fdem3d_frequency_domain"])
def test_grounded_geometry_and_receiver_validation_paths(program_key):
    document = _load(program_key, "grounded_wire")
    document["source"]["current"] = 0
    document["source"]["segments"][0]["end"] = deepcopy(document["source"]["segments"][0]["start"])
    document["receivers"][0]["z"] = float("inf")
    document["unknown"] = 1
    with pytest.raises(ParameterValidationError) as caught:
        validate(program_key, "grounded_wire", document)
    errors = caught.value.errors
    assert "$.source.current" in errors
    assert "$.source.segments[0].end" in errors
    assert "$.receivers[0].z" in errors
    assert "$.unknown" in errors


@pytest.mark.parametrize("program_key", ["be_fetd", "fdem3d_frequency_domain"])
def test_loop_geometry_validation_paths(program_key):
    document = _load(program_key, "loop")
    document["source"]["turns"] = 0
    document["source"]["vertices"][1] = deepcopy(document["source"]["vertices"][0])
    with pytest.raises(ParameterValidationError) as caught:
        validate(program_key, "loop", document)
    assert "$.source.turns" in caught.value.errors
    assert "$.source.vertices[1]" in caught.value.errors


@pytest.mark.parametrize("program_key", ["be_fetd", "fdem3d_frequency_domain"])
def test_source_discriminator_must_match_registry_source_type(program_key):
    document = _load(program_key, "grounded_wire")
    document["source"]["type"] = "loop"
    with pytest.raises(ParameterValidationError) as caught:
        validate(program_key, "grounded_wire", document)
    assert "$.source.type" in caught.value.errors


def test_be_time_stepping_validation_paths():
    document = _load("be_fetd", "grounded_wire")
    document["time_stepping"] = {"blocks": 0, "steps_per_block": 0, "base_time_step": -1}
    with pytest.raises(ParameterValidationError) as caught:
        validate("be_fetd", "grounded_wire", document)
    assert set(caught.value.errors) >= {
        "$.time_stepping.blocks",
        "$.time_stepping.steps_per_block",
        "$.time_stepping.base_time_step",
    }


@pytest.mark.parametrize(
    "count,minimum,maximum,path",
    [
        (1, 1.0, 2.0, "$.frequency.max_hz"),
        (2, 2.0, 1.0, "$.frequency.max_hz"),
    ],
)
def test_fdem_frequency_rules(count, minimum, maximum, path):
    document = _load("fdem3d_frequency_domain", "grounded_wire")
    document["frequency"] = {"count": count, "min_hz": minimum, "max_hz": maximum}
    with pytest.raises(ParameterValidationError) as caught:
        validate("fdem3d_frequency_domain", "grounded_wire", document)
    assert path in caught.value.errors


def test_fdem_solver_rules():
    document = _load("fdem3d_frequency_domain", "grounded_wire")
    document["solver"] = {"mode": 3, "rk_dimension": 1}
    with pytest.raises(ParameterValidationError) as caught:
        validate("fdem3d_frequency_domain", "grounded_wire", document)
    assert "$.solver.mode" in caught.value.errors
    document["solver"] = {"mode": 2, "rk_dimension": 1}
    with pytest.raises(ParameterValidationError) as caught:
        validate("fdem3d_frequency_domain", "grounded_wire", document)
    assert "$.solver.rk_dimension" in caught.value.errors
