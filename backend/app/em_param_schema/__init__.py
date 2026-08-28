"""BE_FETD/FDEM3D 真实参数 schema 的稳定调用入口。

注册表键为 ``(program_key, source_type)``；所有参数错误均通过
:class:`ParamValidationError.errors` 暴露 JSON path。
"""
from __future__ import annotations

from . import be_fetd, fdem3d_frequency_domain
from .common import (
    MAX_FILE_BYTES,
    ParameterValidationError,
    UnsupportedParameterSchemaError,
)
from .registry import ParameterSchema, get_schema, list_schemas

ParamValidationError = ParameterValidationError
SCHEMA_VERSIONS = {
    be_fetd.PROGRAM_KEY: be_fetd.SCHEMA_VERSION,
    fdem3d_frequency_domain.PROGRAM_KEY: fdem3d_frequency_domain.SCHEMA_VERSION,
}


def get_parameter_schema(program_key: str, source_type: str) -> ParameterSchema:
    return get_schema(program_key, source_type)


def parse_parameter_bytes(program_key: str, source_type: str, payload: bytes) -> dict:
    return get_schema(program_key, source_type).parse_bytes(payload)


def validate_parameter(program_key: str, source_type: str, document: dict) -> dict:
    return get_schema(program_key, source_type).validate(document)


def validate_parameter_with_warnings(
    program_key: str,
    source_type: str,
    document: dict,
) -> tuple[dict, list[str]]:
    """校验并返回规范 DTO；当前 schema 没有非阻断 warning。"""
    return validate_parameter(program_key, source_type, document), []


def serialize_parameter(program_key: str, source_type: str, document: dict) -> bytes:
    return get_schema(program_key, source_type).serialize(document)


def schema_version_for(program_key: str, source_type: str | None = None) -> str:
    try:
        program_version = SCHEMA_VERSIONS[program_key]
    except KeyError as exc:
        raise UnsupportedParameterSchemaError(
            f"未注册的参数 schema：program_key={program_key!r}",
        ) from exc
    if source_type is not None:
        item_version = get_schema(program_key, source_type).schema_version
        if item_version != program_version:
            raise UnsupportedParameterSchemaError(
                f"schema 版本注册不一致：program_key={program_key!r}, source_type={source_type!r}",
            )
    return program_version


# 简名保留给只需要 registry 操作的调用方。
parse_bytes = parse_parameter_bytes
validate = validate_parameter
serialize = serialize_parameter
schema_version = schema_version_for

__all__ = [
    "MAX_FILE_BYTES",
    "ParamValidationError",
    "ParameterSchema",
    "ParameterValidationError",
    "SCHEMA_VERSIONS",
    "UnsupportedParameterSchemaError",
    "get_parameter_schema",
    "get_schema",
    "list_schemas",
    "parse_bytes",
    "parse_parameter_bytes",
    "schema_version",
    "schema_version_for",
    "serialize",
    "serialize_parameter",
    "validate",
    "validate_parameter",
    "validate_parameter_with_warnings",
]
