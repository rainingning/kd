"""多科学计算程序模板清单与完整性校验。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import settings
from ..em_param_schema import ParamValidationError as EmParamValidationError, parse_parameter_bytes
from .programs import DCR_3D, PROGRAM_DLL, ProgramSpec, get_program, list_programs

MANIFEST_FILE = "program-manifest.json"
_COPY_CHUNK = 1024 * 1024


class ProgramTemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProgramManifest:
    program_key: str
    version: str
    exe: str
    dll: str
    exe_sha256: str
    dll_sha256: str
    parameter_sha256: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "program_key": self.program_key,
            "version": self.version,
            "exe": self.exe,
            "dll": self.dll,
            "exe_sha256": self.exe_sha256,
            "dll_sha256": self.dll_sha256,
            "parameter_sha256": dict(self.parameter_sha256),
        }

    @property
    def runtime_file_hashes(self) -> dict[str, str]:
        return {
            self.exe: self.exe_sha256,
            self.dll: self.dll_sha256,
            **self.parameter_sha256,
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_COPY_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _required_string(data: dict, key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ProgramTemplateError(f"程序模板清单缺少有效字段：{key}")
    return value.strip()


def _valid_sha256(field_name: str, value: str) -> str:
    normalized = value.strip().lower()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        raise ProgramTemplateError(f"{field_name} 不是有效 SHA-256")
    return normalized


def program_template_dir(
    program_key: str,
    template_dir: Path | None = None,
) -> Path:
    root = (template_dir or settings.fortran_program_template_dir).resolve()
    nested = root / "programs" / get_program(program_key).directory_name
    # 单程序旧部署在迁移前仍可读取 DCR 根清单。
    if program_key == DCR_3D and not nested.exists() and (root / MANIFEST_FILE).is_file():
        return root
    return nested


def load_program_manifest(
    template_dir: Path | None = None,
    program_key: str = DCR_3D,
) -> ProgramManifest:
    spec = get_program(program_key)
    root = program_template_dir(program_key, template_dir)
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.is_file():
        raise ProgramTemplateError(f"程序模板清单不存在：{manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgramTemplateError(f"程序模板清单无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise ProgramTemplateError("程序模板清单必须是 JSON 对象")

    declared_key = data.get("program_key", program_key)
    if declared_key != program_key:
        raise ProgramTemplateError(
            f"模板程序标识不匹配：期望 {program_key}，实际 {declared_key}")
    manifest = ProgramManifest(
        program_key=program_key,
        version=_required_string(data, "version"),
        exe=_required_string(data, "exe"),
        dll=_required_string(data, "dll"),
        exe_sha256=_valid_sha256("exe_sha256", _required_string(data, "exe_sha256")),
        dll_sha256=_valid_sha256("dll_sha256", _required_string(data, "dll_sha256")),
        parameter_sha256={
            str(name): _valid_sha256(f"parameter_sha256.{name}", str(value))
            for name, value in (data.get("parameter_sha256") or {}).items()
        },
    )
    if manifest.exe != spec.executable or manifest.dll != PROGRAM_DLL:
        raise ProgramTemplateError(
            f"{program_key} 模板文件名必须为 {spec.executable} 和 {PROGRAM_DLL}")
    expected_parameters = set(spec.parameter_files)
    if set(manifest.parameter_sha256) != expected_parameters:
        raise ProgramTemplateError(
            f"{program_key} 默认参数文件必须为：{', '.join(sorted(expected_parameters)) or '无'}")
    return manifest


def _validate_files(root: Path, spec: ProgramSpec, manifest: ProgramManifest) -> None:
    for filename, expected in manifest.runtime_file_hashes.items():
        path = root / filename
        if not path.is_file():
            raise ProgramTemplateError(f"{spec.key} 程序模板缺少 {filename}")
        if sha256_file(path) != expected:
            raise ProgramTemplateError(f"{spec.key}/{filename} SHA-256 与清单不一致")
    if spec.parameter_mode == "source-structured":
        for choice in spec.source_choices:
            try:
                parse_parameter_bytes(
                    spec.key,
                    choice.source_type,
                    (root / choice.filename).read_bytes(),
                )
            except (OSError, EmParamValidationError) as exc:
                raise ProgramTemplateError(
                    f"{spec.key}/{choice.filename} 真实参数无效：{exc}") from exc


def validate_program_template(
    template_dir: Path | None = None,
    program_key: str = DCR_3D,
) -> ProgramManifest:
    spec = get_program(program_key)
    root = program_template_dir(program_key, template_dir)
    manifest = load_program_manifest(template_dir, program_key)
    _validate_files(root, spec, manifest)
    return manifest


def validate_all_program_templates(
    template_dir: Path | None = None,
) -> dict[str, ProgramManifest]:
    return {
        spec.key: validate_program_template(template_dir, spec.key)
        for spec in list_programs()
    }
