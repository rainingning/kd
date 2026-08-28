"""FDEM3D_Frequency_Domain 两类真实参数文件 schema（UTF-8）。"""
from __future__ import annotations

from typing import Any

from .common import (
    MAX_FILE_BYTES,
    MAX_GEOMETRY_ITEMS,
    MAX_MATERIALS,
    MAX_RECEIVERS,
    ParameterValidationError,
    TokenCursor,
    format_number,
    integer,
    material_line,
    number,
    point,
    point_line,
    same_point,
    validate_air_and_materials,
    validate_receivers,
)

PROGRAM_KEY = "fdem3d_frequency_domain"
GROUNDED_WIRE = "grounded_wire"
LOOP = "loop"
ENCODING = "utf-8"
SCHEMA_VERSION = "fdem3d-frequency-source-v1"
SCHEMA_VERSIONS = {
    GROUNDED_WIRE: SCHEMA_VERSION,
    LOOP: SCHEMA_VERSION,
}


def _decode(payload: bytes) -> str:
    if len(payload) > MAX_FILE_BYTES:
        raise ParameterValidationError({"$": f"文件不能超过 {MAX_FILE_BYTES} 字节"})
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParameterValidationError({"$": "FDEM 参数文件必须为 UTF-8 编码"}) from exc


def parse_bytes(source_type: str, payload: bytes) -> dict:
    cursor = TokenCursor(_decode(payload))
    frequency = {
        "count": cursor.integer("$.frequency.count"),
        "min_hz": cursor.number("$.frequency.min_hz"),
        "max_hz": cursor.number("$.frequency.max_hz"),
    }
    solver = {
        "mode": cursor.integer("$.solver.mode"),
        "rk_dimension": cursor.integer("$.solver.rk_dimension"),
    }
    if source_type == GROUNDED_WIRE:
        geometry_count = cursor.count("$.source.segments", minimum=1, maximum=MAX_GEOMETRY_ITEMS)
        turns = None
    elif source_type == LOOP:
        geometry_count = cursor.count("$.source.vertices", minimum=3, maximum=MAX_GEOMETRY_ITEMS)
        turns = cursor.integer("$.source.turns")
    else:
        raise ValueError(f"FDEM 不支持参数类型：{source_type}")
    current = cursor.number("$.source.current")
    air_count = cursor.count("$.air_domain_ids", minimum=0, maximum=10_000)
    air_domain_ids = [cursor.integer(f"$.air_domain_ids[{index}]") for index in range(air_count)]
    material_count = cursor.count("$.materials", minimum=1, maximum=MAX_MATERIALS)
    materials = []
    for index in range(material_count):
        path = f"$.materials[{index}]"
        materials.append({
            "id": cursor.integer(f"{path}.id"),
            "rho_x": cursor.number(f"{path}.rho_x"),
            "rho_y": cursor.number(f"{path}.rho_y"),
            "rho_z": cursor.number(f"{path}.rho_z"),
            "alpha": cursor.number(f"{path}.alpha"),
            "beta": cursor.number(f"{path}.beta"),
            "gamma": cursor.number(f"{path}.gamma"),
            "mu_r": cursor.number(f"{path}.mu_r"),
        })
    source: dict[str, Any] = {"type": source_type, "current": current}
    document: dict[str, Any] = {
        "frequency": frequency,
        "solver": solver,
        "source": source,
        "air_domain_ids": air_domain_ids,
        "materials": materials,
    }
    if source_type == GROUNDED_WIRE:
        source["segments"] = [{
            "start": cursor.point(f"$.source.segments[{index}].start"),
            "end": cursor.point(f"$.source.segments[{index}].end"),
        } for index in range(geometry_count)]
    else:
        source["turns"] = turns
        source["vertices"] = [cursor.point(f"$.source.vertices[{index}]") for index in range(geometry_count)]
    receiver_count = cursor.count("$.receivers", minimum=1, maximum=MAX_RECEIVERS)
    document["receivers"] = [cursor.point(f"$.receivers[{index}]") for index in range(receiver_count)]
    cursor.finish()
    return validate(source_type, document)


def validate(source_type: str, document: dict) -> dict:
    if not isinstance(document, dict):
        raise ParameterValidationError({"$": "参数必须是对象"})
    if source_type not in SCHEMA_VERSIONS:
        raise ValueError(f"FDEM 不支持参数类型：{source_type}")
    errors: dict[str, str] = {}
    allowed_fields = {"frequency", "solver", "source", "air_domain_ids", "materials", "receivers"}
    for key in document:
        if key not in allowed_fields:
            errors[f"$.{key}"] = "未知字段"

    raw_frequency = document.get("frequency")
    frequency: dict[str, int | float] = {}
    if not isinstance(raw_frequency, dict):
        errors["$.frequency"] = "应为频率参数对象"
    else:
        for key in raw_frequency:
            if key not in {"count", "min_hz", "max_hz"}:
                errors[f"$.frequency.{key}"] = "未知字段"
        count = integer(raw_frequency.get("count"), "$.frequency.count", errors, minimum=1)
        minimum = number(raw_frequency.get("min_hz"), "$.frequency.min_hz", errors, positive=True)
        maximum = number(raw_frequency.get("max_hz"), "$.frequency.max_hz", errors, positive=True)
        if count is not None:
            frequency["count"] = count
        if minimum is not None:
            frequency["min_hz"] = minimum
        if maximum is not None:
            frequency["max_hz"] = maximum
        if count is not None and minimum is not None and maximum is not None:
            if count == 1 and minimum != maximum:
                errors["$.frequency.max_hz"] = "单频计算时必须等于最小频率"
            elif count > 1 and maximum <= minimum:
                errors["$.frequency.max_hz"] = "多频计算时必须大于最小频率"

    raw_solver = document.get("solver")
    solver: dict[str, int] = {}
    if not isinstance(raw_solver, dict):
        errors["$.solver"] = "应为求解器参数对象"
    else:
        for key in raw_solver:
            if key not in {"mode", "rk_dimension"}:
                errors[f"$.solver.{key}"] = "未知字段"
        mode = integer(raw_solver.get("mode"), "$.solver.mode", errors)
        dimension = integer(raw_solver.get("rk_dimension"), "$.solver.rk_dimension", errors, minimum=1)
        if mode is not None:
            if mode not in (1, 2):
                errors["$.solver.mode"] = "只能为 1（Direct）或 2（Rational Krylov）"
            solver["mode"] = mode
        if dimension is not None:
            if mode == 2 and dimension < 2:
                errors["$.solver.rk_dimension"] = "Rational Krylov 模式下至少为 2"
            solver["rk_dimension"] = dimension

    raw_source = document.get("source")
    source: dict[str, Any] = {"type": source_type}
    if not isinstance(raw_source, dict):
        errors["$.source"] = "应为源参数对象"
        raw_source = {}
    source_fields = {"type", "current", "segments"} if source_type == GROUNDED_WIRE else {"type", "current", "turns", "vertices"}
    for key in raw_source:
        if key not in source_fields:
            errors[f"$.source.{key}"] = "未知字段"
    if raw_source.get("type") != source_type:
        errors["$.source.type"] = f"必须与 source_type 一致并设为 {source_type}"
    current = number(raw_source.get("current"), "$.source.current", errors, nonzero=True)
    if current is not None:
        source["current"] = current
    air_ids, materials = validate_air_and_materials(document, errors, include_epsilon=False)
    receivers = validate_receivers(document, errors)
    normalized: dict[str, Any] = {
        "frequency": frequency,
        "solver": solver,
        "source": source,
        "air_domain_ids": air_ids,
        "materials": materials,
    }
    if source_type == GROUNDED_WIRE:
        raw_segments = raw_source.get("segments")
        segments = []
        if not isinstance(raw_segments, list) or not raw_segments:
            errors["$.source.segments"] = "至少需要一条接地导线线段"
        elif len(raw_segments) > MAX_GEOMETRY_ITEMS:
            errors["$.source.segments"] = f"数量不能超过 {MAX_GEOMETRY_ITEMS}"
        else:
            for index, raw in enumerate(raw_segments):
                path = f"$.source.segments[{index}]"
                if not isinstance(raw, dict):
                    errors[path] = "应为包含 start、end 的线段对象"
                    continue
                for key in raw:
                    if key not in {"start", "end"}:
                        errors[f"{path}.{key}"] = "未知字段"
                start = point(raw.get("start"), f"{path}.start", errors)
                end = point(raw.get("end"), f"{path}.end", errors)
                if start is not None and end is not None:
                    if same_point(start, end):
                        errors[f"{path}.end"] = "线段两个端点不能重合"
                    segments.append({"start": start, "end": end})
        source["segments"] = segments
    else:
        turns = integer(raw_source.get("turns"), "$.source.turns", errors, minimum=1)
        raw_vertices = raw_source.get("vertices")
        vertices: list[dict[str, float]] = []
        if not isinstance(raw_vertices, list) or len(raw_vertices) < 3:
            errors["$.source.vertices"] = "闭合回线至少需要 3 个顶点"
        elif len(raw_vertices) > MAX_GEOMETRY_ITEMS:
            errors["$.source.vertices"] = f"数量不能超过 {MAX_GEOMETRY_ITEMS}"
        else:
            for index, raw in enumerate(raw_vertices):
                parsed = point(raw, f"$.source.vertices[{index}]", errors)
                if parsed is not None:
                    vertices.append(parsed)
            if len(vertices) == len(raw_vertices):
                for index, vertex in enumerate(vertices):
                    if same_point(vertex, vertices[(index + 1) % len(vertices)]):
                        errors[f"$.source.vertices[{(index + 1) % len(vertices)}]"] = "相邻回线顶点不能重合"
        source["turns"] = turns
        source["vertices"] = vertices
    normalized["receivers"] = receivers
    if errors:
        raise ParameterValidationError(errors)
    return normalized


def serialize(source_type: str, document: dict) -> bytes:
    value = validate(source_type, document)
    frequency = value["frequency"]
    solver = value["solver"]
    source = value["source"]
    lines = [
        "# Frequency-domain frequencies (Hz)",
        f"{frequency['count']} {format_number(frequency['min_hz'])} {format_number(frequency['max_hz'])}",
        "# Linear solver",
        f"{solver['mode']} {solver['rk_dimension']}",
    ]
    if source_type == GROUNDED_WIRE:
        lines.extend(["# Grounded electric source", str(len(source["segments"])), format_number(source["current"])])
    else:
        lines.extend(["# Closed polygonal loop source", str(len(source["vertices"])), str(source["turns"]), format_number(source["current"])])
    air = value["air_domain_ids"]
    lines.extend([
        "# Material model",
        " ".join([str(len(air)), *(str(item) for item in air)]),
        str(len(value["materials"])),
        "# ID rho_x rho_y rho_z alpha beta gamma mu_r",
        *(material_line(item, include_epsilon=False) for item in value["materials"]),
    ])
    if source_type == GROUNDED_WIRE:
        lines.append("# Wire endpoints; positive current follows endpoint 1 -> endpoint 2")
        for segment in source["segments"]:
            lines.extend([point_line(segment["start"]), point_line(segment["end"])])
    else:
        lines.append("# Loop vertices; positive current follows the listed order and closes last -> first")
        lines.extend(point_line(vertex) for vertex in source["vertices"])
    lines.extend(["# Receivers", str(len(value["receivers"]))])
    lines.extend(point_line(receiver) for receiver in value["receivers"])
    return ("\n".join(lines) + "\n").encode(ENCODING)


def schema_version(source_type: str) -> str:
    try:
        return SCHEMA_VERSIONS[source_type]
    except KeyError as exc:
        raise ValueError(f"FDEM 不支持参数类型：{source_type}") from exc
