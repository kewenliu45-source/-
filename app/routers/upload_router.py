from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import traceback

from app.data_sources.excel_source import build_standard_data
from app.services.warning_service import analyze_standard_data

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.post("/upload", response_class=HTMLResponse)
async def upload_files(
    request: Request,
    inventory_file: UploadFile = File(...),
    sales_file: UploadFile = File(...),
    hq_file: UploadFile = File(...)
):
    try:
        standard_df = build_standard_data(
            inventory_file.file,
            sales_file.file,
            hq_file.file
        )

        result = analyze_standard_data(standard_df)

        if isinstance(result, tuple):
            result_df = result[0]
        else:
            result_df = result

        records = result_df.to_dict(orient="records")

        red_count = int((result_df["预警状态"] == "红色预警").sum())
        yellow_count = int((result_df["预警状态"] == "黄色预警").sum())
        normal_count = int((result_df["预警状态"] == "正常").sum())

        suggest_total = int(result_df["建议调货量"].sum())
        hq_total = int(result_df["总部可调数量"].sum())

        summary = {
            "total": len(result_df),
            "red_count": red_count,
            "yellow_count": yellow_count,
            "normal_count": normal_count,
            "suggest_total": suggest_total,
            "hq_total": hq_total
        }

        return templates.TemplateResponse(
            request=request,
            name="result.html",
            context={
                "records": records,
                "preview_data": records,
                "summary": summary,
                "red_count": red_count,
                "yellow_count": yellow_count,
                "normal_count": normal_count,
                "suggest_total": suggest_total,
                "hq_total": hq_total,
                "output_filename": ""
            }
        )

    except Exception:
        error_msg = traceback.format_exc()
        print(error_msg)

        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "error": error_msg
            }
        )
