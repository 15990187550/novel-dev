import os
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from novel_dev.api.routes import router
from novel_dev.api.config_routes import router as config_router

app = FastAPI()
app.include_router(router)
app.include_router(config_router)

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
    return FileResponse(os.path.join(SERVE_DIR, "index.html"))


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(os.path.join(SERVE_DIR, "index.html"))
