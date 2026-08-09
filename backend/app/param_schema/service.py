"""参数 Schema 加载、校验与序列化（T3.1）。

参数集合固定且已知，由 schema.json 描述：
- format: 序列化目标格式。当前为 "json"（供 Mock 程序使用）；
  待实验室提供真实参数文件格式后，在 serialize_params 中实现对应格式（需求说明书 7.2）。
- fields: 字段定义，含 name / type(int|float|bool|string|enum) / required / default / min / max / options / description
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"


class ParamValidationError(ValueError):
    """校验失败，errors 为 {字段名: 错误信息}。"""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(json.dumps(errors, ensure_ascii=False))


@lru_cache
def get_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validate_value(value: Any, field: dict) -> str | None:
    """返回错误信息；合法返回 None。"""
    ftype = field["type"]
    label = field.get("description") or field["name"]

    if ftype == "bool":
        if not isinstance(value, bool):
            return f"{label}：应为布尔值"
        return None
    if ftype == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            return f"{label}：应为整数"
    elif ftype == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return f"{label}：应为数值"
    elif ftype == "string":
        if not isinstance(value, str):
            return f"{label}：应为字符串"
        return None
    elif ftype == "enum":
        if value not in field["options"]:
            return f"{label}：应为 {'/'.join(map(str, field['options']))} 之一"
        return None
    else:
        return f"schema 错误：未知类型 {ftype}"

    if "min" in field and value < field["min"]:
        return f"{label}：不能小于 {field['min']}"
    if "max" in field and value > field["max"]:
        return f"{label}：不能大于 {field['max']}"
    return None


def _coerce(value: Any, field: dict) -> Any:
    if field["type"] == "float":
        return float(value)
    return value


def validate_params(params: dict) -> dict:
    """按 schema 校验并补全默认值，返回规范化参数；失败抛 ParamValidationError。"""
    if not isinstance(params, dict):
        raise ParamValidationError({"_": "参数必须是键值对象"})

    fields = {f["name"]: f for f in get_schema()["fields"]}
    errors: dict[str, str] = {}
    normalized: dict[str, Any] = {}

    for key in params:
        if key not in fields:
            errors[key] = "未知参数"

    for name, field in fields.items():
        if name in params:
            msg = _validate_value(params[name], field)
            if msg is None:
                normalized[name] = _coerce(params[name], field)
            else:
                errors[name] = msg
        elif field.get("required"):
            errors[name] = f"{field.get('description') or name}：缺少必填参数"
        elif "default" in field:
            normalized[name] = field["default"]

    if errors:
        raise ParamValidationError(errors)
    return normalized


def serialize_params(params: dict) -> str:
    """将（已校验的）参数序列化为计算程序参数文件内容。"""
    fmt = get_schema().get("format", "json")
    if fmt == "json":
        return json.dumps(params, indent=2, ensure_ascii=False) + "\n"
    # TODO(T0.1): 实验室提供真实参数文件格式后在此实现
    raise ValueError(f"未实现的参数文件格式: {fmt}")
