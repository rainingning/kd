"""T3.1 参数校验与序列化单元测试（无需数据库）。"""
import json

import pytest

from app.param_schema import ParamValidationError, get_schema, serialize_params, validate_params


def test_validate_fills_defaults():
    out = validate_params({"grid_size": 100})
    assert out["grid_size"] == 100
    assert out["time_step"] == 0.01
    assert out["method"] == "explicit"
    assert out["enable_output"] is True
    assert out["mock_exit_code"] == 0


def test_missing_required():
    with pytest.raises(ParamValidationError) as exc:
        validate_params({})
    assert "grid_size" in exc.value.errors


def test_wrong_type():
    with pytest.raises(ParamValidationError) as exc:
        validate_params({"grid_size": "abc"})
    assert "grid_size" in exc.value.errors


def test_bool_not_accepted_as_int():
    with pytest.raises(ParamValidationError):
        validate_params({"grid_size": True})


def test_out_of_range():
    with pytest.raises(ParamValidationError) as exc:
        validate_params({"grid_size": 0})
    assert "grid_size" in exc.value.errors


def test_unknown_field_rejected():
    with pytest.raises(ParamValidationError) as exc:
        validate_params({"grid_size": 10, "bogus": 1})
    assert "bogus" in exc.value.errors


def test_enum_validation():
    with pytest.raises(ParamValidationError) as exc:
        validate_params({"grid_size": 10, "method": "other"})
    assert "method" in exc.value.errors


def test_float_coercion():
    out = validate_params({"grid_size": 10, "time_step": 1})
    assert out["time_step"] == 1.0
    assert isinstance(out["time_step"], float)


def test_serialize_roundtrip():
    params = validate_params({"grid_size": 32, "time_step": 0.5})
    text = serialize_params(params)
    assert json.loads(text) == params


def test_schema_has_format():
    assert get_schema()["format"] == "json"
