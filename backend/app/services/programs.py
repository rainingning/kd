"""固定科学计算程序注册表。

程序路径、文件名和 stdin 映射只允许由本模块定义，禁止接受客户端路径。
"""
from __future__ import annotations

from dataclasses import dataclass

DCR_3D = "dcr_3d"
BE_FETD = "be_fetd"
FDEM3D_FREQUENCY_DOMAIN = "fdem3d_frequency_domain"

GROUNDED_WIRE = "grounded_wire"
LOOP_SOURCE = "loop"
GROUNDED_WIRE_FILE = "GroundedWireSource.dat"
LOOP_SOURCE_FILE = "LoopSource.dat"
PROGRAM_DLL = "libiomp5md.dll"
DCR_PARAMS_FILE = "model_DC.dat"
MESH_DIR = "mesh"
MESH_FILE = "mesh.mphtxt"
RESULT_DIR = "Forward_data"


@dataclass(frozen=True)
class SourceChoice:
    source_type: str
    stdin_choice: int
    filename: str
    label: str


@dataclass(frozen=True)
class ProgramSpec:
    key: str
    display_name: str
    directory_name: str
    executable: str
    parameter_mode: str
    source_choices: tuple[SourceChoice, ...] = ()

    @property
    def requires_stdin(self) -> bool:
        return bool(self.source_choices)

    @property
    def parameter_files(self) -> tuple[str, ...]:
        if self.parameter_mode == "structured":
            return (DCR_PARAMS_FILE,)
        return tuple(choice.filename for choice in self.source_choices)

    def choice_by_value(self, value: int) -> SourceChoice:
        for choice in self.source_choices:
            if choice.stdin_choice == value:
                return choice
        raise ValueError(f"程序 {self.key} 不支持参数选择 {value}")

    def choice_by_source(self, source_type: str) -> SourceChoice:
        for choice in self.source_choices:
            if choice.source_type == source_type:
                return choice
        raise ValueError(f"程序 {self.key} 不支持参数类型 {source_type}")


_SOURCE_CHOICES = (
    SourceChoice(GROUNDED_WIRE, 1, GROUNDED_WIRE_FILE, "接地导线源"),
    SourceChoice(LOOP_SOURCE, 2, LOOP_SOURCE_FILE, "回线源"),
)

PROGRAMS: dict[str, ProgramSpec] = {
    DCR_3D: ProgramSpec(
        key=DCR_3D,
        display_name="DCR_3D",
        directory_name=DCR_3D,
        executable="DCR_3D.exe",
        parameter_mode="structured",
    ),
    BE_FETD: ProgramSpec(
        key=BE_FETD,
        display_name="BE_FETD",
        directory_name=BE_FETD,
        executable="BE_FETD.exe",
        parameter_mode="upload",
        source_choices=_SOURCE_CHOICES,
    ),
    FDEM3D_FREQUENCY_DOMAIN: ProgramSpec(
        key=FDEM3D_FREQUENCY_DOMAIN,
        display_name="FDEM3D_Frequency_Domain",
        directory_name=FDEM3D_FREQUENCY_DOMAIN,
        executable="FDEM3D_Frequency_Domain.exe",
        parameter_mode="upload",
        source_choices=_SOURCE_CHOICES,
    ),
}


def get_program(program_key: str) -> ProgramSpec:
    try:
        return PROGRAMS[program_key]
    except KeyError as exc:
        raise ValueError(f"不支持的科学计算程序：{program_key}") from exc


def list_programs() -> tuple[ProgramSpec, ...]:
    return tuple(PROGRAMS.values())
