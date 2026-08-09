"""调度器进程内运行态。"""
import asyncio
from dataclasses import dataclass


@dataclass
class RunningEntry:
    proc: asyncio.subprocess.Process
    cancel_kind: str | None = None  # "user" / "admin"


# task_id -> 运行中进程
running: dict[int, RunningEntry] = {}

# 服务关停中：runner 不再落终态，保持 RUNNING 交给下次启动的恢复逻辑
shutting_down: bool = False
