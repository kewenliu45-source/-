from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import page_router, upload_router

app = FastAPI(title="智能库存预警系统")

app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(page_router.router)
app.include_router(upload_router.router)