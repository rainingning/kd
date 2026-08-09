"""Mock 计算程序（研发任务分解 T0.3）。

在真实 program.exe 就绪前，模拟其行为约定：
    program <参数文件路径> <数据文件路径>
- 参数文件为 JSON，可含字段：
    mock_sleep     : 模拟计算耗时秒数（默认 1）
    mock_exit_code : 进程退出码（默认 0）
- stdout 打印模拟计算结果；stderr 在失败时打印错误信息
- 退出码 0 = 成功，非 0 = 失败
"""
import json
import sys
import time


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: mock_program <params_file> <data_file>", file=sys.stderr)
        return 2

    params_path, data_path = sys.argv[1], sys.argv[2]

    with open(params_path, "r", encoding="utf-8") as f:
        params = json.load(f)
    with open(data_path, "rb") as f:
        data = f.read()

    sleep_sec = float(params.get("mock_sleep", 1))
    exit_code = int(params.get("mock_exit_code", 0))

    # 模拟计算耗时
    time.sleep(sleep_sec)

    if exit_code != 0:
        print(f"mock computation failed (exit_code={exit_code})", file=sys.stderr)
        return exit_code

    # 模拟结果输出到 stdout：对输入数据做确定性的简单汇总
    checksum = sum(data) % 1_000_000_007
    print("# mock computation result")
    print(f"input_bytes={len(data)}")
    print(f"input_checksum={checksum}")
    for key, value in sorted(params.items()):
        if not key.startswith("mock_"):
            print(f"param_{key}={value}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
