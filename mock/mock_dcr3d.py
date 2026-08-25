"""固定工作区版 DCR_3D Mock。

必须在用户根目录中无参数启动：
- 读取 ./model_DC.dat（开发期仍为 JSON）
- 读取 ./mesh/mesh.mphtxt
- 写入 ./Forward_data/ 下多个结果文件
- stdout/stderr 仅作为运行日志
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PARAMS_FILE = "model_DC.dat"
MESH_FILE = Path("mesh") / "mesh.mphtxt"
RESULT_DIR = Path("Forward_data")


def main() -> int:
    if len(sys.argv) != 1:
        print("DCR_3D mock does not accept command-line arguments", file=sys.stderr)
        return 2

    root = Path.cwd()
    params_path = root / PARAMS_FILE
    mesh_path = root / MESH_FILE
    if not params_path.is_file():
        print(f"missing parameter file: {PARAMS_FILE}", file=sys.stderr)
        return 3
    if not mesh_path.is_file():
        print(f"missing mesh file: {MESH_FILE.as_posix()}", file=sys.stderr)
        return 4

    try:
        params = json.loads(params_path.read_text(encoding="utf-8"))
        mesh = mesh_path.read_bytes()
    except Exception as exc:
        print(f"input read failed: {exc}", file=sys.stderr)
        return 5

    sleep_sec = float(params.get("mock_sleep", 1))
    exit_code = int(params.get("mock_exit_code", 0))
    time.sleep(sleep_sec)

    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    # 即使模拟失败也可留下部分结果，用于验证失败终态归档。
    summary = RESULT_DIR / "summary.txt"
    checksum = sum(mesh) % 1_000_000_007
    summary.write_text(
        "\n".join([
            "# mock DCR_3D result",
            f"input_bytes={len(mesh)}",
            f"input_checksum={checksum}",
            f"grid_size={params.get('grid_size', '')}",
            "",
        ]),
        encoding="utf-8",
    )
    detail_dir = RESULT_DIR / "details"
    detail_dir.mkdir(exist_ok=True)
    (detail_dir / "parameters.json").write_text(
        json.dumps(params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if exit_code != 0:
        print(f"mock DCR_3D failed (exit_code={exit_code})", file=sys.stderr)
        return exit_code

    print("mock DCR_3D completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
