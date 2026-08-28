"""BE_FETD 两类真实参数文件 schema（GB18030）。"""
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

PROGRAM_KEY = "be_fetd"
GROUNDED_WIRE = "grounded_wire"
LOOP = "loop"
ENCODING = "gb18030"
SCHEMA_VERSION = "be-fetd-params-v1"
SCHEMA_VERSIONS = {
    GROUNDED_WIRE: SCHEMA_VERSION,
    LOOP: SCHEMA_VERSION,
}


def _decode(payload: bytes) -> str:
    if len(payload) > MAX_FILE_BYTES:
        raise ParameterValidationError({"$": f"文件不能超过 {MAX_FILE_BYTES} 字节"})
    try:
        return payload.decode(ENCODING)
    except UnicodeDecodeError as exc:
        raise ParameterValidationError({"$": "BE_FETD 参数文件必须为 GB18030 编码"}) from exc


def parse_bytes(source_type: str, payload: bytes) -> dict:
    cursor = TokenCursor(_decode(payload))
    time_stepping = {
        "blocks": cursor.integer("$.time_stepping.blocks"),
        "steps_per_block": cursor.integer("$.time_stepping.steps_per_block"),
        "base_time_step": cursor.number("$.time_stepping.base_time_step"),
    }
    if source_type == GROUNDED_WIRE:
        geometry_count = cursor.count("$.source.segments", minimum=1, maximum=MAX_GEOMETRY_ITEMS)
        turns = None
    elif source_type == LOOP:
        geometry_count = cursor.count("$.source.vertices", minimum=3, maximum=MAX_GEOMETRY_ITEMS)
        turns = cursor.integer("$.source.turns")
    else:
        raise ValueError(f"BE_FETD 不支持参数类型：{source_type}")
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
            "epsilon_r": cursor.number(f"{path}.epsilon_r"),
        })
    source: dict[str, Any] = {"type": source_type, "current": current}
    document: dict[str, Any] = {
        "time_stepping": time_stepping,
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
        raise ValueError(f"BE_FETD 不支持参数类型：{source_type}")
    errors: dict[str, str] = {}
    allowed_fields = {"time_stepping", "source", "air_domain_ids", "materials", "receivers"}
    for key in document:
        if key not in allowed_fields:
            errors[f"$.{key}"] = "未知字段"

    time_raw = document.get("time_stepping")
    time_stepping: dict[str, int | float] = {}
    if not isinstance(time_raw, dict):
        errors["$.time_stepping"] = "应为时间推进参数对象"
    else:
        allowed = {"blocks", "steps_per_block", "base_time_step"}
        for key in time_raw:
            if key not in allowed:
                errors[f"$.time_stepping.{key}"] = "未知字段"
        blocks = integer(time_raw.get("blocks"), "$.time_stepping.blocks", errors, minimum=1)
        steps = integer(time_raw.get("steps_per_block"), "$.time_stepping.steps_per_block", errors, minimum=1)
        base = number(time_raw.get("base_time_step"), "$.time_stepping.base_time_step", errors, positive=True)
        if blocks is not None:
            time_stepping["blocks"] = blocks
        if steps is not None:
            time_stepping["steps_per_block"] = steps
        if base is not None:
            time_stepping["base_time_step"] = base
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
    air_ids, materials = validate_air_and_materials(document, errors, include_epsilon=True)
    receivers = validate_receivers(document, errors)

    normalized: dict[str, Any] = {
        "time_stepping": time_stepping,
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
    ts = value["time_stepping"]
    source = value["source"]
    lines = [
        "# Backward-Euler time stepping",
        f"{ts['blocks']} {ts['steps_per_block']} {format_number(ts['base_time_step'])}  # nblock nstep dt0(s)",
        "# 源信息",
    ]
    if source_type == GROUNDED_WIRE:
        lines.extend([str(len(source["segments"])), format_number(source["current"])])
    else:
        lines.extend([str(len(source["vertices"])), str(source["turns"]), format_number(source["current"])])
    air = value["air_domain_ids"]
    lines.extend([
        "# 模型参数",
        " ".join([str(len(air)), *(str(item) for item in air)]),
        str(len(value["materials"])),
        *(material_line(item, include_epsilon=True) for item in value["materials"]),
        "# 计算区域参数",
    ])
    if source_type == GROUNDED_WIRE:
        for segment in source["segments"]:
            lines.extend([point_line(segment["start"]), point_line(segment["end"])])
    else:
        lines.extend(point_line(vertex) for vertex in source["vertices"])
    lines.extend(["# 接收点", str(len(value["receivers"]))])
    lines.extend(point_line(receiver) for receiver in value["receivers"])
    return ("\n".join(lines) + "\n").encode(ENCODING)


def schema_version(source_type: str) -> str:
    try:
        return SCHEMA_VERSIONS[source_type]
    except KeyError as exc:
        raise ValueError(f"BE_FETD 不支持参数类型：{source_type}") from exc
