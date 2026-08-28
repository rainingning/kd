"""DCR_3D ``model_DC.dat`` 真实格式解析、校验与规范化序列化。"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.json"
SCHEMA_VERSION = "dcr-model-v1"
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_AIR_DOMAINS = 10_000
MAX_MATERIALS = 100_000
MAX_SOURCES = 10_000
MAX_TOTAL_OBSERVATIONS = 200_000
_INT_RE = re.compile(r"^[+-]?\d+$")


class ParamValidationError(ValueError):
    """参数失败；errors 使用前端可直接定位的 JSON 路径。"""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__(json.dumps(errors, ensure_ascii=False))


@dataclass(frozen=True)
class _Token:
    value: str
    line: int


@lru_cache
def get_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _number(value: Any, path: str, errors: dict[str, str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errors[path] = "应为数值"
        return None
    result = float(value)
    if not math.isfinite(result):
        errors[path] = "必须是有限数值"
        return None
    return result


def _integer(value: Any, path: str, errors: dict[str, str], *, minimum: int | None = None) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        errors[path] = "应为整数"
        return None
    if minimum is not None and value < minimum:
        errors[path] = f"不能小于 {minimum}"
        return None
    return value


def _point(value: Any, path: str, errors: dict[str, str]) -> dict[str, float] | None:
    if not isinstance(value, dict):
        errors[path] = "应为包含 x、y、z 的坐标对象"
        return None
    result: dict[str, float] = {}
    for axis in ("x", "y", "z"):
        number = _number(value.get(axis), f"{path}.{axis}", errors)
        if number is not None:
            result[axis] = number
    for key in value:
        if key not in {"x", "y", "z"}:
            errors[f"{path}.{key}"] = "未知字段"
    return result if len(result) == 3 else None


def _same_point(left: dict[str, float], right: dict[str, float]) -> bool:
    return all(left[axis] == right[axis] for axis in ("x", "y", "z"))


def _distance(left: dict[str, float], right: dict[str, float]) -> float:
    return math.sqrt(sum((left[axis] - right[axis]) ** 2 for axis in ("x", "y", "z")))


def validate_params_with_warnings(params: dict) -> tuple[dict, list[str]]:
    if not isinstance(params, dict):
        raise ParamValidationError({"$": "参数必须是对象"})
    errors: dict[str, str] = {}
    warnings: list[str] = []
    allowed = {"boundary_mode", "write_vtk", "air_domain_ids", "materials", "sources"}
    for key in params:
        if key not in allowed:
            errors[f"$.{key}"] = "未知字段"

    boundary = _integer(params.get("boundary_mode"), "$.boundary_mode", errors)
    if boundary is not None and boundary not in (1, 2):
        errors["$.boundary_mode"] = "只能为 1（Robin）或 2（零 Dirichlet）"
    write_vtk = params.get("write_vtk")
    if not isinstance(write_vtk, bool):
        errors["$.write_vtk"] = "应为布尔值"

    air_raw = params.get("air_domain_ids")
    air_ids: list[int] = []
    if not isinstance(air_raw, list):
        errors["$.air_domain_ids"] = "应为整数数组"
    else:
        if len(air_raw) > MAX_AIR_DOMAINS:
            errors["$.air_domain_ids"] = f"数量不能超过 {MAX_AIR_DOMAINS}"
        seen_air: set[int] = set()
        for index, value in enumerate(air_raw):
            item = _integer(value, f"$.air_domain_ids[{index}]", errors, minimum=1)
            if item is not None:
                if item in seen_air:
                    errors[f"$.air_domain_ids[{index}]"] = "空气域 ID 重复"
                else:
                    seen_air.add(item)
                    air_ids.append(item)

    materials_raw = params.get("materials")
    materials: list[dict] = []
    material_ids: set[int] = set()
    if not isinstance(materials_raw, list) or not materials_raw:
        errors["$.materials"] = "至少需要一行材料参数"
    elif len(materials_raw) > MAX_MATERIALS:
        errors["$.materials"] = f"数量不能超过 {MAX_MATERIALS}"
    else:
        material_fields = {"id", "rho_x", "rho_y", "rho_z", "alpha", "beta", "gamma"}
        for index, value in enumerate(materials_raw):
            path = f"$.materials[{index}]"
            if not isinstance(value, dict):
                errors[path] = "应为材料对象"
                continue
            for key in value:
                if key not in material_fields:
                    errors[f"{path}.{key}"] = "未知字段"
            domain_id = _integer(value.get("id"), f"{path}.id", errors, minimum=1)
            if domain_id is not None:
                if domain_id in material_ids:
                    errors[f"{path}.id"] = "材料 Domain ID 重复"
                else:
                    material_ids.add(domain_id)
            row: dict[str, Any] = {"id": domain_id}
            for name in ("rho_x", "rho_y", "rho_z"):
                number = _number(value.get(name), f"{path}.{name}", errors)
                if number is not None and number <= 0:
                    errors[f"{path}.{name}"] = "电阻率必须大于 0"
                row[name] = number
            for name in ("alpha", "beta", "gamma"):
                row[name] = _number(value.get(name), f"{path}.{name}", errors)
            if all(item is not None for item in row.values()):
                materials.append(row)
    for index, domain_id in enumerate(air_ids):
        if domain_id not in material_ids:
            errors[f"$.air_domain_ids[{index}]"] = "空气域 ID 必须在材料表中存在"

    sources_raw = params.get("sources")
    sources: list[dict] = []
    total_observations = 0
    if not isinstance(sources_raw, list) or not sources_raw:
        errors["$.sources"] = "至少需要一个 AB 供电源"
    elif len(sources_raw) > MAX_SOURCES:
        errors["$.sources"] = f"数量不能超过 {MAX_SOURCES}"
    else:
        source_fields = {"current", "a", "b", "observations"}
        observation_fields = {"m", "n", "geometry_mode", "custom_k"}
        for source_index, value in enumerate(sources_raw):
            source_path = f"$.sources[{source_index}]"
            if not isinstance(value, dict):
                errors[source_path] = "应为供电源对象"
                continue
            for key in value:
                if key not in source_fields:
                    errors[f"{source_path}.{key}"] = "未知字段"
            current = _number(value.get("current"), f"{source_path}.current", errors)
            if current is not None and current == 0:
                errors[f"{source_path}.current"] = "供电电流不能为 0"
            a = _point(value.get("a"), f"{source_path}.a", errors)
            b = _point(value.get("b"), f"{source_path}.b", errors)
            if a is not None and b is not None and _same_point(a, b):
                errors[f"{source_path}.b"] = "B 电极不能与 A 电极重合"
            observations_raw = value.get("observations")
            observations: list[dict] = []
            if not isinstance(observations_raw, list) or not observations_raw:
                errors[f"{source_path}.observations"] = "至少需要一组 MN 测量电极"
            else:
                total_observations += len(observations_raw)
                if total_observations > MAX_TOTAL_OBSERVATIONS:
                    errors["$.sources"] = f"MN 总数不能超过 {MAX_TOTAL_OBSERVATIONS}"
                for obs_index, observation in enumerate(observations_raw):
                    obs_path = f"{source_path}.observations[{obs_index}]"
                    if not isinstance(observation, dict):
                        errors[obs_path] = "应为 MN 观测对象"
                        continue
                    for key in observation:
                        if key not in observation_fields:
                            errors[f"{obs_path}.{key}"] = "未知字段"
                    m = _point(observation.get("m"), f"{obs_path}.m", errors)
                    n = _point(observation.get("n"), f"{obs_path}.n", errors)
                    mode = _integer(observation.get("geometry_mode"), f"{obs_path}.geometry_mode", errors)
                    if mode is not None and mode not in (0, 1, 2, 3):
                        errors[f"{obs_path}.geometry_mode"] = "只能为 0、1、2 或 3"
                    custom_k = _number(observation.get("custom_k"), f"{obs_path}.custom_k", errors)
                    if mode == 3 and custom_k == 0:
                        warnings.append(f"{obs_path}.custom_k 为 0，视电阻率也将为 0")
                    if m is not None and n is not None and _same_point(m, n):
                        errors[f"{obs_path}.n"] = "N 电极不能与 M 电极重合"
                    if mode in (1, 2) and a is not None and b is not None and m is not None and n is not None:
                        distances = [_distance(a, m), _distance(b, m), _distance(a, n), _distance(b, n)]
                        if any(distance == 0 for distance in distances):
                            errors[obs_path] = "自动几何因子模式下 M/N 不能与 A/B 重合"
                        else:
                            denominator = 1 / distances[0] - 1 / distances[1] - 1 / distances[2] + 1 / distances[3]
                            scale = sum(1 / distance for distance in distances)
                            if abs(denominator) <= max(scale * 1e-14, 1e-15):
                                errors[obs_path] = "电极组合导致几何因子奇异"
                    if m is not None and n is not None and mode in (0, 1, 2, 3) and custom_k is not None:
                        observations.append({"m": m, "n": n, "geometry_mode": mode, "custom_k": custom_k})
            if current is not None and a is not None and b is not None and observations:
                sources.append({"current": current, "a": a, "b": b, "observations": observations})

    if errors:
        raise ParamValidationError(errors)
    return {
        "boundary_mode": boundary,
        "write_vtk": write_vtk,
        "air_domain_ids": air_ids,
        "materials": materials,
        "sources": sources,
    }, warnings


def validate_params(params: dict) -> dict:
    normalized, _ = validate_params_with_warnings(params)
    return normalized


class _Cursor:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.offset = 0

    def _next(self, path: str) -> _Token:
        if self.offset >= len(self.tokens):
            raise ParamValidationError({path: "参数文件提前结束"})
        token = self.tokens[self.offset]
        self.offset += 1
        return token

    def integer(self, path: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
        token = self._next(path)
        if not _INT_RE.fullmatch(token.value):
            raise ParamValidationError({path: f"第 {token.line} 行应为整数，实际为 {token.value!r}"})
        value = int(token.value)
        if minimum is not None and value < minimum:
            raise ParamValidationError({path: f"不能小于 {minimum}"})
        if maximum is not None and value > maximum:
            raise ParamValidationError({path: f"不能超过 {maximum}"})
        return value

    def number(self, path: str) -> float:
        token = self._next(path)
        try:
            value = float(token.value.replace("D", "E").replace("d", "e"))
        except ValueError as exc:
            raise ParamValidationError({path: f"第 {token.line} 行不是有效数值：{token.value!r}"}) from exc
        if not math.isfinite(value):
            raise ParamValidationError({path: f"第 {token.line} 行必须是有限数值"})
        return value


def parse_params(content: str) -> dict:
    tokens: list[_Token] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        data = line.split("#", 1)[0]
        tokens.extend(_Token(value, line_number) for value in data.split())
    cursor = _Cursor(tokens)
    boundary_mode = cursor.integer("$.boundary_mode")
    write_flag = cursor.integer("$.write_vtk")
    if write_flag not in (0, 1):
        raise ParamValidationError({"$.write_vtk": "文件值只能为 0 或 1"})
    air_count = cursor.integer("$.air_domain_ids.count", minimum=0, maximum=MAX_AIR_DOMAINS)
    air_ids = [cursor.integer(f"$.air_domain_ids[{index}]", minimum=1) for index in range(air_count)]
    material_count = cursor.integer("$.materials.count", minimum=1, maximum=MAX_MATERIALS)
    materials = []
    for index in range(material_count):
        path = f"$.materials[{index}]"
        materials.append({
            "id": cursor.integer(f"{path}.id", minimum=1),
            "rho_x": cursor.number(f"{path}.rho_x"),
            "rho_y": cursor.number(f"{path}.rho_y"),
            "rho_z": cursor.number(f"{path}.rho_z"),
            "alpha": cursor.number(f"{path}.alpha"),
            "beta": cursor.number(f"{path}.beta"),
            "gamma": cursor.number(f"{path}.gamma"),
        })
    source_count = cursor.integer("$.sources.count", minimum=1, maximum=MAX_SOURCES)
    sources = []
    total_observations = 0
    for source_index in range(source_count):
        path = f"$.sources[{source_index}]"
        current = cursor.number(f"{path}.current")
        a = {axis: cursor.number(f"{path}.a.{axis}") for axis in ("x", "y", "z")}
        b = {axis: cursor.number(f"{path}.b.{axis}") for axis in ("x", "y", "z")}
        observation_count = cursor.integer(
            f"{path}.observations.count", minimum=1, maximum=MAX_TOTAL_OBSERVATIONS)
        total_observations += observation_count
        if total_observations > MAX_TOTAL_OBSERVATIONS:
            raise ParamValidationError({"$.sources": f"MN 总数不能超过 {MAX_TOTAL_OBSERVATIONS}"})
        observations = []
        for obs_index in range(observation_count):
            obs_path = f"{path}.observations[{obs_index}]"
            observations.append({
                "m": {axis: cursor.number(f"{obs_path}.m.{axis}") for axis in ("x", "y", "z")},
                "n": {axis: cursor.number(f"{obs_path}.n.{axis}") for axis in ("x", "y", "z")},
                "geometry_mode": cursor.integer(f"{obs_path}.geometry_mode"),
                "custom_k": cursor.number(f"{obs_path}.custom_k"),
            })
        sources.append({"current": current, "a": a, "b": b, "observations": observations})
    if cursor.offset != len(tokens):
        token = tokens[cursor.offset]
        raise ParamValidationError({"$": f"第 {token.line} 行存在多余参数：{token.value!r}"})
    return validate_params({
        "boundary_mode": boundary_mode,
        "write_vtk": bool(write_flag),
        "air_domain_ids": air_ids,
        "materials": materials,
        "sources": sources,
    })


def parse_params_bytes(content: bytes) -> dict:
    if not content:
        raise ParamValidationError({"$": "参数文件不能为空"})
    if len(content) > MAX_FILE_BYTES:
        raise ParamValidationError({"$": f"参数文件不能超过 {MAX_FILE_BYTES // 1024 // 1024} MiB"})
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParamValidationError({"$": "参数文件必须使用 UTF-8 编码"}) from exc
    return parse_params(text)


def _format_number(value: float) -> str:
    if value == 0:
        return "0.0"
    text = format(value, ".17g")
    if "e" not in text.lower() and "." not in text:
        text += ".0"
    return text


def _point_values(point: dict[str, float]) -> str:
    return " ".join(_format_number(point[axis]) for axis in ("x", "y", "z"))


def serialize_params(params: dict) -> str:
    model, _ = validate_params_with_warnings(params)
    lines = [
        "# DCR3D parameter file. Blank lines and text after # are ignored.",
        "",
        f"{model['boundary_mode']}                                  # artificial boundary: 1=Robin, 2=zero Dirichlet",
        f"{1 if model['write_vtk'] else 0}                                  # write nodal-potential VTK: 1=yes, 0=no",
        "",
        f"{len(model['air_domain_ids'])}" + (" " + " ".join(map(str, model["air_domain_ids"])) if model["air_domain_ids"] else "") + "    # number of air domain IDs, followed by the IDs",
        f"{len(model['materials'])}                                  # number of material parameter rows below",
        "# ID   rho_x   rho_y   rho_z   alpha   beta   gamma (ohm*m, degrees)",
    ]
    for row in model["materials"]:
        lines.append(" ".join([
            str(row["id"]), *(_format_number(row[name]) for name in (
                "rho_x", "rho_y", "rho_z", "alpha", "beta", "gamma")),
        ]))
    lines.extend(["", f"{len(model['sources'])}                                  # number of AB current-electrode pairs"])
    for source_index, source in enumerate(model["sources"], start=1):
        lines.extend([
            "",
            f"# Source {source_index}",
            f"{_format_number(source['current'])}                                # current I (A)",
            f"{_point_values(source['a'])}                # A electrode x y z (m)",
            f"{_point_values(source['b'])}                # B electrode x y z (m)",
            f"{len(source['observations'])}                                  # number of MN pairs for Source {source_index}",
            "# Mx My Mz   Nx Ny Nz   geometry_mode custom_K",
        ])
        for observation in source["observations"]:
            lines.append(
                f"{_point_values(observation['m'])}    {_point_values(observation['n'])}    "
                f"{observation['geometry_mode']}  {_format_number(observation['custom_k'])}"
            )
    return "\n".join(lines) + "\n"
