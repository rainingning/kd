"""子进程执行器（T4.3）：启动计算程序、超时控制、终态落库、站内通知。

执行约定（需求说明书 7.1）：program <参数文件> <数据文件>，stdout 为结果，退出码 0 成功。
命令模板见 config.fortran_command，含 {params} / {data} 占位符。
"""
import asyncio
import logging
import shlex
from decimal import Decimal
from pathlib import Path

from .. import db
from ..config import settings
from ..models import NotificationType, Task, TaskStatus, utcnow
from ..services.config import get_float
from ..services.notifications import notify
from ..services.storage import task_dir_from
from . import state
from .state import RunningEntry

logger = logging.getLogger(__name__)


def build_argv(params_path: Path, data_path: Path) -> list[str]:
    """按命令模板拼出 argv。posix=False 保留带引号的 Windows 路径，再去掉首尾引号。"""
    cmd = settings.fortran_command.format(params=f'"{params_path}"', data=f'"{data_path}"')
    return [token.strip('"') for token in shlex.split(cmd, posix=False)]


def request_cancel(task_id: int, kind: str) -> bool:
    """请求终止运行中的任务（kind: "user" / "admin"）。不在运行中返回 False。"""
    entry = state.running.get(task_id)
    if entry is None or entry.proc.returncode is not None:
        return False
    entry.cancel_kind = kind
    try:
        entry.proc.kill()
    except ProcessLookupError:
        pass
    return True


async def run_task(task_id: int) -> None:
    async with db.async_session() as session:
        task = await session.get(Task, task_id)
        if task is None or task.status != TaskStatus.RUNNING:
            return  # 分发后被取消等竞态，不启动

        task_dir = task_dir_from(task)
        argv = build_argv(task_dir / "params.in", task_dir / "input.dat")
        timeout_sec = (await get_float(session, "task_timeout_minutes")) * 60

        entry: RunningEntry | None = None
        timed_out = False
        start_error: str | None = None
        returncode: int | None = None

        with open(task_dir / "stdout.txt", "wb") as out_f, open(task_dir / "stderr.txt", "wb") as err_f:
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv, cwd=str(task_dir), stdout=out_f, stderr=err_f)
            except Exception as exc:
                logger.exception("任务 #%s 启动失败", task_id)
                start_error = f"任务启动失败：{exc}"
            else:
                entry = RunningEntry(proc=proc)
                state.running[task_id] = entry
                try:
                    await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
                    returncode = proc.returncode
                except asyncio.TimeoutError:
                    timed_out = True
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                finally:
                    state.running.pop(task_id, None)

        if state.shutting_down and task.status == TaskStatus.RUNNING:
            return  # 服务关停：保持 RUNNING，由下次启动的恢复逻辑标记（FR-QUEUE-09）

        finished = utcnow()
        task.finished_at = finished
        task.exit_code = returncode
        if task.started_at is not None:
            task.duration_sec = Decimal(f"{(finished - task.started_at).total_seconds():.3f}")

        if start_error is not None:
            task.status = TaskStatus.FAILED
            task.error_message = start_error
            notify(session, task, NotificationType.FAILED, f"任务 #{task.id} 失败：{start_error}")
        elif entry is not None and entry.cancel_kind == "user":
            task.status = TaskStatus.CANCELED
            task.error_message = "用户取消"
        elif entry is not None and entry.cancel_kind == "admin":
            task.status = TaskStatus.FAILED
            task.error_message = "被管理员终止"
            notify(session, task, NotificationType.KILLED, f"任务 #{task.id} 已被管理员终止")
        elif timed_out:
            task.status = TaskStatus.FAILED
            task.error_message = f"运行超时（超过 {timeout_sec / 60:g} 分钟）"
            notify(session, task, NotificationType.FAILED, f"任务 #{task.id} 失败：{task.error_message}")
        elif returncode == 0:
            task.status = TaskStatus.COMPLETED
            notify(session, task, NotificationType.COMPLETED, f"任务 #{task.id} 已完成")
        else:
            task.status = TaskStatus.FAILED
            task.error_message = f"程序异常退出（退出码 {returncode}）"
            notify(session, task, NotificationType.FAILED, f"任务 #{task.id} 失败：{task.error_message}")
        await session.commit()
