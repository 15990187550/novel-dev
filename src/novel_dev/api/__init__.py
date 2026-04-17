from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from novel_dev.api.routes import router
from novel_dev.api.config_routes import router as config_router

app = FastAPI()
app.include_router(router)
app.include_router(config_router)

WEB_DIR = os.path.join(os.path.dirname(__file__), "..", "web")

app.mount("/static", StaticFiles(directory=os.path.join(WEB_DIR, "static")), name="static")

@app.get("/")
async def serve_index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    if full_path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(os.path.join(WEB_DIR, "index.html"))
