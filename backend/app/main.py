"""FastAPI 入口（T1.1）。

lifespan：启动时做任务恢复（FR-QUEUE-09）并启动调度循环；关停时停止调度。
注意：API 测试（ASGITransport）不触发 lifespan，调度器由测试直接调用。
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import settings
from .routers import admin, auth, files, notifications, params, tasks, templates, users
from .db import async_session
from .scheduler.cleanup import cleanup_loop, stop_cleanup
from .scheduler.dispatcher import dispatch_loop, recover_interrupted_tasks, shutdown_scheduler
from .services.config import ensure_defaults
from .services.program_template import ProgramTemplateError, validate_all_program_templates

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_root.mkdir(parents=True, exist_ok=True)
    settings.result_zip_cache_root.mkdir(parents=True, exist_ok=True)
    try:
        await asyncio.to_thread(validate_all_program_templates)
    except ProgramTemplateError:
        logger.critical("正式程序模板自检失败，服务拒绝启动", exc_info=True)
        raise
    async with async_session() as session:
        await ensure_defaults(session)  # system_config 默认配置项
        await session.commit()
    recovered = await recover_interrupted_tasks()
    if recovered:
        logger.warning("服务重启：已检查并恢复/归档 %d 个中断任务", recovered)
    dispatcher = asyncio.create_task(dispatch_loop())
    cleaner = asyncio.create_task(cleanup_loop())
    yield
    await shutdown_scheduler()
    stop_cleanup()
    dispatcher.cancel()
    cleaner.cancel()


app = FastAPI(title="Fortran 科学计算平台", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(params.router)
app.include_router(templates.router)
app.include_router(tasks.router)
app.include_router(files.router)
app.include_router(notifications.router)
app.include_router(admin.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}


# ---- 生产模式：前端构建产物存在时由后端直接托管（单端口部署）----
# 所有 /api 路由已在上面注册，优先于本兜底路由；未命中的前端路由回退到 index.html。
from .config import REPO_ROOT  # noqa: E402

_dist = REPO_ROOT / "frontend" / "dist"
if _dist.is_dir():
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/") or full_path == "api":
            raise HTTPException(status_code=404)
        candidate = _dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
