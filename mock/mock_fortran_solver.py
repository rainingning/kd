"""无参数多程序 Fortran Mock，通过 cwd 和 stdin 模拟真实程序。"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

MESH = Path("mesh") / "mesh.mphtxt"
RESULT = Path("Forward_data")
SOURCE_FILES = {
    "1": "GroundedWireSource.dat",
    "2": "LoopSource.dat",
}


def _write_result(program: str, mesh: bytes, details: dict) -> None:
    RESULT.mkdir(parents=True, exist_ok=True)
    nested = RESULT / "details"
    nested.mkdir(exist_ok=True)
    (RESULT / "summary.txt").write_text(
        "\n".join([
            f"# mock {program} result",
            f"input_bytes={len(mesh)}",
            f"input_checksum={sum(mesh) % 1_000_000_007}",
            f"stdin_choice={details.get('stdin_choice', '')}",
            f"parameter_file={details.get('parameter_file', '')}",
            "",
        ]),
        encoding="utf-8",
    )
    (nested / "parameters.json").write_text(
        json.dumps(details, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    if len(sys.argv) != 1:
        print("mock solver does not accept command-line arguments", file=sys.stderr)
        return 2
    root = Path.cwd()
    program = root.name
    mesh_path = root / MESH
    if not mesh_path.is_file():
        print(f"missing mesh file: {MESH.as_posix()}", file=sys.stderr)
        return 3
    mesh = mesh_path.read_bytes()

    if program == "dcr_3d":
        params_path = root / "model_DC.dat"
        if not params_path.is_file():
            print("missing parameter file: model_DC.dat", file=sys.stderr)
            return 4
        try:
            params = json.loads(params_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"input read failed: {exc}", file=sys.stderr)
            return 5
        time.sleep(float(params.get("mock_sleep", 0.1)))
        _write_result("DCR_3D", mesh, params)
        exit_code = int(params.get("mock_exit_code", 0))
        if exit_code:
            print(f"mock {program} failed (exit_code={exit_code})", file=sys.stderr)
            return exit_code
        print("mock DCR_3D completed")
        return 0

    if program not in {"be_fetd", "fdem3d_frequency_domain"}:
        print(f"unknown mock program cwd: {program}", file=sys.stderr)
        return 6
    missing = [name for name in SOURCE_FILES.values() if not (root / name).is_file()]
    if missing:
        print(f"missing parameter files: {', '.join(missing)}", file=sys.stderr)
        return 7
    choice = sys.stdin.readline().strip()
    selected = SOURCE_FILES.get(choice)
    if selected is None:
        print(f"invalid stdin choice: {choice!r}", file=sys.stderr)
        return 8
    payload = (root / selected).read_bytes()
    time.sleep(0.1)
    _write_result(program, mesh, {
        "stdin_choice": int(choice),
        "parameter_file": selected,
        "parameter_bytes": len(payload),
        "parameter_sha256": hashlib.sha256(payload).hexdigest(),
    })
    print(f"mock {program} completed with choice {choice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
