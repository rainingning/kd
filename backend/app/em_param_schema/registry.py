"""按 program_key/source_type 选择真实参数 schema 的注册表。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import be_fetd, fdem3d_frequency_domain as fdem
from .common import UnsupportedParameterSchemaError


@dataclass(frozen=True)
class ParameterSchema:
    program_key: str
    source_type: str
    schema_version: str
    encoding: str
    filename: str
    _parse_bytes: Callable[[str, bytes], dict]
    _validate: Callable[[str, dict], dict]
    _serialize: Callable[[str, dict], bytes]

    def parse_bytes(self, payload: bytes) -> dict:
        return self._parse_bytes(self.source_type, payload)

    def validate(self, document: dict) -> dict:
        return self._validate(self.source_type, document)

    def serialize(self, document: dict) -> bytes:
        return self._serialize(self.source_type, document)


_REGISTRY: dict[tuple[str, str], ParameterSchema] = {}
for module in (be_fetd, fdem):
    for source_type, version in module.SCHEMA_VERSIONS.items():
        filename = "GroundedWireSource.dat" if source_type == "grounded_wire" else "LoopSource.dat"
        item = ParameterSchema(
            program_key=module.PROGRAM_KEY,
            source_type=source_type,
            schema_version=version,
            encoding=module.ENCODING,
            filename=filename,
            _parse_bytes=module.parse_bytes,
            _validate=module.validate,
            _serialize=module.serialize,
        )
        _REGISTRY[(item.program_key, item.source_type)] = item


def get_schema(program_key: str, source_type: str) -> ParameterSchema:
    try:
        return _REGISTRY[(program_key, source_type)]
    except KeyError as exc:
        raise UnsupportedParameterSchemaError(
            f"未注册的参数 schema：program_key={program_key!r}, source_type={source_type!r}",
        ) from exc


def list_schemas() -> tuple[ParameterSchema, ...]:
    return tuple(_REGISTRY[key] for key in sorted(_REGISTRY))


def parse_bytes(program_key: str, source_type: str, payload: bytes) -> dict:
    return get_schema(program_key, source_type).parse_bytes(payload)


def validate(program_key: str, source_type: str, document: dict) -> dict:
    return get_schema(program_key, source_type).validate(document)


def serialize(program_key: str, source_type: str, document: dict) -> bytes:
    return get_schema(program_key, source_type).serialize(document)


def schema_version(program_key: str, source_type: str) -> str:
    return get_schema(program_key, source_type).schema_version
