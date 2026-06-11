import os

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={}
    )