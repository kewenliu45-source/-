from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.routers import page_router, tplus_oauth_router, upload_router

app = FastAPI(title="智能库存预警系统")

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/CHANJET_CHECK.txt", include_in_schema=False)
def chanjet_check_file():
    return FileResponse("app/static/CHANJET_CHECK.txt", media_type="text/plain")

app.include_router(page_router.router)
app.include_router(upload_router.router)
app.include_router(tplus_oauth_router.router)
