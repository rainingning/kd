"""DCR 真实 model_DC.dat 解析、校验与序列化单元测试。"""
from copy import deepcopy
from pathlib import Path

import pytest

from app.param_schema import (
    SCHEMA_VERSION,
    ParamValidationError,
    get_schema,
    parse_params,
    parse_params_bytes,
    serialize_params,
    validate_params,
)

SAMPLE = Path(__file__).resolve().parents[2] / "docs" / "model_DC.dat"


def sample_model() -> dict:
    return parse_params(SAMPLE.read_text(encoding="utf-8"))


def test_real_sample_and_canonical_roundtrip():
    model = sample_model()
    assert model["boundary_mode"] == 1
    assert model["write_vtk"] is True
    assert model["air_domain_ids"] == [2, 4]
    assert len(model["materials"]) == 4
    assert [len(source["observations"]) for source in model["sources"]] == [4, 3, 2]
    assert parse_params(serialize_params(model)) == model


def test_comments_blank_lines_bom_and_fortran_d_exponent():
    text = SAMPLE.read_text(encoding="utf-8").replace("100.0", "1.0D+2", 1)
    model = parse_params_bytes(("\ufeff# extra\n\n" + text).encode("utf-8"))
    assert model["materials"][0]["rho_x"] == 100.0


@pytest.mark.parametrize("mutation,path", [
    (lambda text: "\n".join(text.splitlines()[:-1]), "$.sources[2].observations[1]"),
    (lambda text: text + "\n999\n", "$"),
    (lambda text: text.replace("2 2 4", "3 2 4", 1), "$"),
])
def test_parse_rejects_truncation_trailing_and_count_mismatch(mutation, path):
    with pytest.raises(ParamValidationError) as exc:
        parse_params(mutation(SAMPLE.read_text(encoding="utf-8")))
    assert any(key.startswith(path) for key in exc.value.errors)


@pytest.mark.parametrize("field,mutate", [
    ("$.boundary_mode", lambda m: m.update(boundary_mode=3)),
    ("$.write_vtk", lambda m: m.update(write_vtk=1)),
    ("$.materials[0].rho_x", lambda m: m["materials"][0].update(rho_x=0)),
    ("$.materials[1].id", lambda m: m["materials"][1].update(id=1)),
    ("$.sources[0].current", lambda m: m["sources"][0].update(current=0)),
    ("$.sources[0].observations[0].geometry_mode", lambda m: m["sources"][0]["observations"][0].update(geometry_mode=9)),
])
def test_domain_validation_paths(field, mutate):
    model = deepcopy(sample_model())
    mutate(model)
    with pytest.raises(ParamValidationError) as exc:
        validate_params(model)
    assert field in exc.value.errors


def test_air_domain_must_exist_in_material_table():
    model = deepcopy(sample_model())
    model["air_domain_ids"].append(99)
    with pytest.raises(ParamValidationError) as exc:
        validate_params(model)
    assert exc.value.errors["$.air_domain_ids[2]"]


def test_non_finite_number_rejected():
    model = deepcopy(sample_model())
    model["materials"][0]["rho_x"] = float("nan")
    with pytest.raises(ParamValidationError) as exc:
        validate_params(model)
    assert "有限" in exc.value.errors["$.materials[0].rho_x"]


def test_schema_identifies_real_format():
    schema = get_schema()
    assert schema["schema_version"] == SCHEMA_VERSION
    assert schema["format"] == "model_DC.dat"
