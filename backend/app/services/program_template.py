"""正式 Fortran 程序模板清单与完整性校验。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from ..config import settings
from .storage import PROGRAM_DLL, PROGRAM_EXE

MANIFEST_FILE = "program-manifest.json"
_COPY_CHUNK = 1024 * 1024


class ProgramTemplateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProgramManifest:
    version: str
    exe: str
    dll: str
    exe_sha256: str
    dll_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "exe": self.exe,
            "dll": self.dll,
            "exe_sha256": self.exe_sha256,
            "dll_sha256": self.dll_sha256,
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


def load_program_manifest(template_dir: Path | None = None) -> ProgramManifest:
    root = (template_dir or settings.fortran_program_template_dir).resolve()
    manifest_path = root / MANIFEST_FILE
    if not manifest_path.is_file():
        raise ProgramTemplateError(f"程序模板清单不存在：{manifest_path}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProgramTemplateError(f"程序模板清单无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise ProgramTemplateError("程序模板清单必须是 JSON 对象")

    manifest = ProgramManifest(
        version=_required_string(data, "version"),
        exe=_required_string(data, "exe"),
        dll=_required_string(data, "dll"),
        exe_sha256=_required_string(data, "exe_sha256").lower(),
        dll_sha256=_required_string(data, "dll_sha256").lower(),
    )
    if manifest.exe != PROGRAM_EXE or manifest.dll != PROGRAM_DLL:
        raise ProgramTemplateError(
            f"模板文件名必须为 {PROGRAM_EXE} 和 {PROGRAM_DLL}")
    for field_name, value in (
        ("exe_sha256", manifest.exe_sha256),
        ("dll_sha256", manifest.dll_sha256),
    ):
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ProgramTemplateError(f"{field_name} 不是有效 SHA-256")
    return manifest


def validate_program_template(template_dir: Path | None = None) -> ProgramManifest:
    root = (template_dir or settings.fortran_program_template_dir).resolve()
    manifest = load_program_manifest(root)
    exe_path = root / manifest.exe
    dll_path = root / manifest.dll
    if not exe_path.is_file():
        raise ProgramTemplateError(f"程序模板缺少 {manifest.exe}")
    if not dll_path.is_file():
        raise ProgramTemplateError(f"程序模板缺少 {manifest.dll}")

    actual_exe = sha256_file(exe_path)
    actual_dll = sha256_file(dll_path)
    if actual_exe != manifest.exe_sha256:
        raise ProgramTemplateError(f"{manifest.exe} SHA-256 与清单不一致")
    if actual_dll != manifest.dll_sha256:
        raise ProgramTemplateError(f"{manifest.dll} SHA-256 与清单不一致")
    return manifest
