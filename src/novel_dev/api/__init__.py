import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from novel_dev.api.routes import router
from novel_dev.api.config_routes import router as config_router
from novel_dev.db.engine import async_session_maker
from novel_dev.services.log_service import log_service
from novel_dev.services.recovery_cleanup_service import RecoveryCleanupService


async def run_startup_recovery_cleanup() -> None:
    try:
        async with async_session_maker() as session:
            await RecoveryCleanupService(session).run_cleanup()
    except Exception as exc:
        log_service.add_log(
            "system",
            "RecoveryCleanup",
            f"启动恢复清理失败: {exc}",
            level="error",
            event="recovery.cleanup",
            status="startup_failed",
            node="recovery",
            task="startup_cleanup",
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    cleanup_task = asyncio.create_task(run_startup_recovery_cleanup())
    try:
        yield
    finally:
        if not cleanup_task.done():
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup_task


app = FastAPI(lifespan=lifespan)
app.include_router(router)
app.include_router(config_router)


@app.get("/healthz")
async def healthz():
    return {"ok": True}

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")
DIST_DIR = os.path.join(WEB_DIR, "dist")
SERVE_DIR = DIST_DIR if os.path.isdir(DIST_DIR) else WEB_DIR

static_dir = os.path.join(SERVE_DIR, "static")
if os.path.isdir(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve Vite assets from dist/assets/
assets_dir = os.path.join(SERVE_DIR, "assets")
if os.path.isdir(assets_dir):
    app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


@app.get("/")
async def serve_index():
    return FileResponse(
        os.path.join(SERVE_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(
        os.path.join(SERVE_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
