"""BE/FDEM 参数 schema 的共享 token、数值与校验工具。"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_AIR_DOMAINS = 10_000
MAX_MATERIALS = 100_000
MAX_GEOMETRY_ITEMS = 100_000
MAX_RECEIVERS = 200_000
_INT_RE = re.compile(r"^[+-]?\d+$")


class ParameterValidationError(ValueError):
    """参数失败；``errors`` 的键均为 JSON path。"""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(json.dumps(errors, ensure_ascii=False))


class UnsupportedParameterSchemaError(ValueError):
    """program_key/source_type 没有注册 schema。"""


@dataclass(frozen=True)
class Token:
    value: str
    line: int


def tokenize(text: str) -> list[Token]:
    result: list[Token] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        effective = line.split("#", 1)[0].strip()
        result.extend(Token(part, line_number) for part in effective.split())
    return result


class TokenCursor:
    def __init__(self, text: str):
        self.tokens = tokenize(text)
        self.position = 0

    def _take(self, path: str) -> Token:
        if self.position >= len(self.tokens):
            raise ParameterValidationError({path: "文件提前结束，缺少参数"})
        token = self.tokens[self.position]
        self.position += 1
        return token

    def integer(self, path: str) -> int:
        token = self._take(path)
        if not _INT_RE.fullmatch(token.value):
            raise ParameterValidationError({path: f"第 {token.line} 行应为整数"})
        return int(token.value)

    def number(self, path: str) -> float:
        token = self._take(path)
        try:
            result = float(token.value.replace("D", "E").replace("d", "e"))
        except ValueError as exc:
            raise ParameterValidationError({path: f"第 {token.line} 行应为数值"}) from exc
        if not math.isfinite(result):
            raise ParameterValidationError({path: f"第 {token.line} 行必须是有限数值"})
        return result

    def point(self, path: str) -> dict[str, float]:
        return {axis: self.number(f"{path}.{axis}") for axis in ("x", "y", "z")}

    def count(self, path: str, *, minimum: int, maximum: int) -> int:
        value = self.integer(path)
        if value < minimum:
            raise ParameterValidationError({path: f"不能小于 {minimum}"})
        if value > maximum:
            raise ParameterValidationError({path: f"不能超过 {maximum}"})
        return value

    def finish(self) -> None:
        if self.position < len(self.tokens):
            token = self.tokens[self.position]
            raise ParameterValidationError({"$": f"第 {token.line} 行存在多余参数：{token.value}"})


def number(value: Any, path: str, errors: dict[str, str], *, positive: bool = False, nonzero: bool = False) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors[path] = "应为数值"
        return None
    result = float(value)
    if not math.isfinite(result):
        errors[path] = "必须是有限数值"
        return None
    if positive and result <= 0:
        errors[path] = "必须大于 0"
        return None
    if nonzero and result == 0:
        errors[path] = "不能为 0"
        return None
    return result


def integer(value: Any, path: str, errors: dict[str, str], *, minimum: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors[path] = "应为整数"
        return None
    if minimum is not None and value < minimum:
        errors[path] = f"不能小于 {minimum}"
        return None
    return value


def point(value: Any, path: str, errors: dict[str, str]) -> dict[str, float] | None:
    if not isinstance(value, dict):
        errors[path] = "应为包含 x、y、z 的坐标对象"
        return None
    result: dict[str, float] = {}
    allowed = {"x", "y", "z"}
    for key in value:
        if key not in allowed:
            errors[f"{path}.{key}"] = "未知字段"
    for axis in ("x", "y", "z"):
        parsed = number(value.get(axis), f"{path}.{axis}", errors)
        if parsed is not None:
            result[axis] = parsed
    return result if len(result) == 3 else None


def same_point(left: dict[str, float], right: dict[str, float]) -> bool:
    return all(left[axis] == right[axis] for axis in ("x", "y", "z"))


def validate_air_and_materials(
    document: dict,
    errors: dict[str, str],
    *,
    include_epsilon: bool,
) -> tuple[list[int], list[dict]]:
    air_raw = document.get("air_domain_ids")
    air_ids: list[int] = []
    air_id_paths: list[tuple[int, int]] = []
    if not isinstance(air_raw, list):
        errors["$.air_domain_ids"] = "应为整数数组"
    elif len(air_raw) > MAX_AIR_DOMAINS:
        errors["$.air_domain_ids"] = f"数量不能超过 {MAX_AIR_DOMAINS}"
    else:
        seen: set[int] = set()
        for index, value in enumerate(air_raw):
            item = integer(value, f"$.air_domain_ids[{index}]", errors, minimum=1)
            if item is not None:
                if item in seen:
                    errors[f"$.air_domain_ids[{index}]"] = "空气域 ID 重复"
                else:
                    seen.add(item)
                    air_ids.append(item)
                    air_id_paths.append((index, item))

    raw_materials = document.get("materials")
    materials: list[dict] = []
    material_ids: set[int] = set()
    if not isinstance(raw_materials, list) or not raw_materials:
        errors["$.materials"] = "至少需要一行材料参数"
    elif len(raw_materials) > MAX_MATERIALS:
        errors["$.materials"] = f"数量不能超过 {MAX_MATERIALS}"
    else:
        fields = {"id", "rho_x", "rho_y", "rho_z", "alpha", "beta", "gamma", "mu_r"}
        if include_epsilon:
            fields.add("epsilon_r")
        for index, raw in enumerate(raw_materials):
            path = f"$.materials[{index}]"
            if not isinstance(raw, dict):
                errors[path] = "应为材料对象"
                continue
            for key in raw:
                if key not in fields:
                    errors[f"{path}.{key}"] = "未知字段"
            item: dict[str, int | float] = {}
            domain_id = integer(raw.get("id"), f"{path}.id", errors, minimum=1)
            if domain_id is not None:
                if domain_id in material_ids:
                    errors[f"{path}.id"] = "材料 Domain ID 重复"
                else:
                    material_ids.add(domain_id)
                    item["id"] = domain_id
            for name in ("rho_x", "rho_y", "rho_z"):
                parsed = number(raw.get(name), f"{path}.{name}", errors, positive=True)
                if parsed is not None:
                    item[name] = parsed
            for name in ("alpha", "beta", "gamma"):
                parsed = number(raw.get(name), f"{path}.{name}", errors)
                if parsed is not None:
                    item[name] = parsed
            parsed_mu = number(raw.get("mu_r"), f"{path}.mu_r", errors, positive=True)
            if parsed_mu is not None:
                item["mu_r"] = parsed_mu
            if include_epsilon:
                parsed_epsilon = number(raw.get("epsilon_r"), f"{path}.epsilon_r", errors, positive=True)
                if parsed_epsilon is not None:
                    item["epsilon_r"] = parsed_epsilon
            if len(item) == len(fields):
                materials.append(item)
    for index, domain_id in air_id_paths:
        if domain_id not in material_ids:
            errors[f"$.air_domain_ids[{index}]"] = "空气域 ID 必须在材料表中定义"
    return air_ids, materials


def validate_receivers(document: dict, errors: dict[str, str]) -> list[dict[str, float]]:
    raw = document.get("receivers")
    receivers: list[dict[str, float]] = []
    if not isinstance(raw, list) or not raw:
        errors["$.receivers"] = "至少需要一个接收点"
    elif len(raw) > MAX_RECEIVERS:
        errors["$.receivers"] = f"数量不能超过 {MAX_RECEIVERS}"
    else:
        for index, value in enumerate(raw):
            parsed = point(value, f"$.receivers[{index}]", errors)
            if parsed is not None:
                receivers.append(parsed)
    return receivers


def format_number(value: int | float) -> str:
    result = format(float(value), ".15g")
    return "0" if result == "-0" else result


def point_line(value: dict[str, float]) -> str:
    return " ".join(format_number(value[axis]) for axis in ("x", "y", "z"))


def material_line(value: dict, *, include_epsilon: bool) -> str:
    fields = ["id", "rho_x", "rho_y", "rho_z", "alpha", "beta", "gamma", "mu_r"]
    if include_epsilon:
        fields.append("epsilon_r")
    return " ".join(str(value[name]) if name == "id" else format_number(value[name]) for name in fields)
