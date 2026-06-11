import logging
import os

from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, DB_TYPE

logger = logging.getLogger(__name__)
from app.data_sources.database_source import build_standard_data_from_database
from app.data_sources.excel_source import build_standard_data
from app.services.warning_service import analyze_standard_data

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))


def get_user_facing_error(exc: Exception) -> str:
    message = str(exc)
    if "EXERROR0002" in message and "Connection refused" in message:
        return (
            "畅捷通已收到认证请求，但其内部无法连接当前 T+ 账套服务。"
            "请稍后重试；如果持续出现，请联系畅捷通技术支持，并提供错误码 "
            "EXERROR0002、组织 ID 和服务端日志中的 traceId。"
        )

    if "Read timed out" in message or ("接口在" in message and "秒内没有返回响应" in message):
        return (
            "调用畅捷通 T+ OpenAPI 超时。请先确认当前服务器能访问 openapi.chanjet.com，"
            "再根据现场网络和账套数据量调大 TPLUS_REQUEST_TIMEOUT，或调小 "
            "TPLUS_QUERY_PAGE_SIZE 后重试。"
        )

    return message


def build_result_context(result_df, data_source_name: str):
    records = result_df.to_dict(orient="records")
    transfer_df = result_df[result_df["建议调货量"] > 0].copy()
    transfer_columns = [
        "存货编码",
        "存货",
        "尺码",
        "仓库编码",
        "仓库",
        "近7天销量",
        "日均销量",
        "当前可用量",
        "可售天数",
        "建议调货量",
        "总部可调数量",
        "调货建议",
    ]
    transfer_columns = [column for column in transfer_columns if column in transfer_df.columns]
    transfer_records = transfer_df[transfer_columns].to_dict(orient="records")

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
        "hq_total": hq_total,
        "data_source_name": data_source_name,
    }

    return {
        "records": records,
        "preview_data": records,
        "transfer_records": transfer_records,
        "summary": summary,
        "red_count": red_count,
        "yellow_count": yellow_count,
        "normal_count": normal_count,
        "suggest_total": suggest_total,
        "hq_total": hq_total,
        "output_filename": "",
    }


def get_database_data_source_name() -> str:
    if DB_TYPE == "mock":
        return "模拟数据库"

    if DB_TYPE in {"tplus", "openapi", "chanjet"}:
        return "畅捷通 T+ OpenAPI"

    return "客户数据库"


def render_analysis_result(request: Request, standard_df, data_source_name: str):
    result = analyze_standard_data(standard_df)

    if isinstance(result, tuple):
        result_df = result[0]
    else:
        result_df = result

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context=build_result_context(result_df, data_source_name),
    )


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

        return render_analysis_result(request, standard_df, "Excel 上传")

    except Exception as exc:
        logger.exception("请求处理失败")

        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "error": get_user_facing_error(exc)
            }
        )


@router.post("/database-analysis", response_class=HTMLResponse)
async def analyze_from_database(request: Request):
    try:
        standard_df = build_standard_data_from_database()
        data_source_name = get_database_data_source_name()

        return render_analysis_result(request, standard_df, data_source_name)

    except Exception as exc:
        logger.exception("请求处理失败")

        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={
                "error": get_user_facing_error(exc)
            }
        )
