import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.routers import page_router, tplus_oauth_router, upload_router

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_BASE_DIR, "static")

app = FastAPI(title="智能库存预警系统")

app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/CHANJET_CHECK.txt", include_in_schema=False)
def chanjet_check_file():
    return FileResponse(os.path.join(_STATIC_DIR, "CHANJET_CHECK.txt"), media_type="text/plain")

app.include_router(page_router.router)
app.include_router(upload_router.router)
app.include_router(tplus_oauth_router.router)
