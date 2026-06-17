import logging
import os
import time

from fastapi import APIRouter, UploadFile, File, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.templating import Jinja2Templates

from app.config import BASE_DIR, DB_TYPE, OUTPUT_DIR

logger = logging.getLogger(__name__)
from app.data_sources.database_source import build_standard_data_from_database
from app.data_sources.excel_source import build_standard_data
from app.services.warning_service import analyze_standard_data

router = APIRouter()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "app", "templates"))

# 最近一次分析结果的文件路径（模块级变量）
_latest_result_file: str | None = None


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


def build_result_context(result_df, data_source_name: str, warnings=None, output_filename=""):
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
        "在途仓",
        "在途（未发货）",
        "调货建议",
    ]
    transfer_columns = [column for column in transfer_columns if column in transfer_df.columns]
    transfer_records = transfer_df[transfer_columns].to_dict(orient="records")

    red_count = int((result_df["预警状态"] == "红色预警").sum())
    orange_count = int((result_df["预警状态"] == "橙色缺码").sum())
    yellow_count = int((result_df["预警状态"] == "黄色预警").sum())
    normal_count = int((result_df["预警状态"] == "正常").sum())

    suggest_total = int(result_df["建议调货量"].sum())
    hq_total = int(result_df["总部可调数量"].sum())

    summary = {
        "total": len(result_df),
        "red_count": red_count,
        "orange_count": orange_count,
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
        "orange_count": orange_count,
        "yellow_count": yellow_count,
        "normal_count": normal_count,
        "suggest_total": suggest_total,
        "hq_total": hq_total,
        "output_filename": output_filename,
        "warnings": warnings or [],
    }


def get_database_data_source_name() -> str:
    if DB_TYPE == "mock":
        return "模拟数据库"

    if DB_TYPE in {"tplus", "openapi", "chanjet"}:
        return "畅捷通 T+ OpenAPI"

    return "客户数据库"


def _save_result_excel(result_df, filepath: str):
    """保存预警结果为带颜色的 Excel 文件。"""
    from openpyxl import Workbook
    from openpyxl.styles import PatternFill, Font, Alignment, Border, Side

    # 预警状态对应的颜色（行背景色）
    STATUS_COLORS = {
        "红色预警": "FCA5A5",    # 浅红
        "橙色缺码": "FDBA74",    # 浅橙
        "黄色预警": "FDE68A",    # 浅黄
        "正常":     "BBF7D0",    # 浅绿
    }

    wb = Workbook()
    ws = wb.active
    ws.title = "预警结果"

    # 写表头
    columns = list(result_df.columns)
    header_fill = PatternFill(start_color="374151", end_color="374151", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    thin_border = Border(
        left=Side(style="thin", color="D1D5DB"),
        right=Side(style="thin", color="D1D5DB"),
        top=Side(style="thin", color="D1D5DB"),
        bottom=Side(style="thin", color="D1D5DB"),
    )

    for col_idx, col_name in enumerate(columns, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # 找到预警状态列的索引
    status_col_idx = columns.index("预警状态") if "预警状态" in columns else -1

    # 写数据行
    for row_idx, row in enumerate(result_df.itertuples(index=False), 2):
        status = row[status_col_idx] if status_col_idx >= 0 else ""
        row_color = STATUS_COLORS.get(str(status).strip(), "")
        row_fill = PatternFill(start_color=row_color, end_color=row_color, fill_type="solid") if row_color else None

        for col_idx, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col_idx, value=value)
            if row_fill:
                cell.fill = row_fill
            cell.alignment = Alignment(vertical="center")
            cell.border = thin_border

    # 表头也加边框
    for col_idx in range(1, len(columns) + 1):
        ws.cell(row=1, column=col_idx).border = thin_border

    # 自动调整列宽（取前100行的最大宽度）
    for col_idx, col_name in enumerate(columns, 1):
        max_len = len(str(col_name))
        for row_idx in range(2, min(102, ws.max_row + 1)):
            cell_val = ws.cell(row=row_idx, column=col_idx).value
            if cell_val:
                max_len = max(max_len, len(str(cell_val)))
        ws.column_dimensions[ws.cell(row=1, column=col_idx).column_letter].width = min(max_len + 4, 40)

    # 冻结首行
    ws.freeze_panes = "A2"

    wb.save(filepath)


def render_analysis_result(request: Request, standard_df, data_source_name: str, warnings=None):
    global _latest_result_file

    result = analyze_standard_data(standard_df)

    if isinstance(result, tuple):
        result_df = result[0]
    else:
        result_df = result

    # 保存分析结果为 Excel 文件，供下载（带预警颜色）
    try:
        filename = f"预警结果_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath = os.path.join(OUTPUT_DIR, filename)
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        _save_result_excel(result_df, filepath)
        _latest_result_file = filepath
    except Exception as exc:
        logger.warning("保存预警结果文件失败: %s", exc)
        filename = ""

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context=build_result_context(result_df, data_source_name, warnings=warnings, output_filename=filename),
    )


@router.get("/download/{filename}")
async def download_result_file(filename: str):
    """下载分析结果 Excel 文件"""
    filepath = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(filepath):
        return HTMLResponse(content="文件不存在，请重新分析", status_code=404)
    return FileResponse(
        path=filepath,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=filename,
    )


@router.post("/upload", response_class=HTMLResponse)
async def upload_files(
    request: Request,
    inventory_file: UploadFile = File(...),
    sales_file: UploadFile = File(...),
    transit_file: UploadFile = File(...),
    hq_file: UploadFile = File(...),
):
    try:
        standard_df, warnings = build_standard_data(
            inventory_file.file,
            sales_file.file,
            transit_file.file if transit_file else None,
            hq_file.file if hq_file else None,
        )

        return render_analysis_result(request, standard_df, "Excel 上传", warnings=warnings)

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
async def analyze_from_database(
    request: Request,
    hq_file: UploadFile | None = File(None),
    transit_file: UploadFile | None = File(None),
):
    try:
        from app.data_sources.excel_source import build_hq_standard_df, build_intransit_standard_df

        hq_df = None
        if hq_file:
            hq_df = build_hq_standard_df(hq_file.file)
            if hq_df.empty:
                hq_df = None

        transit_df = None
        if transit_file:
            transit_df = build_intransit_standard_df(transit_file.file)
            if transit_df.empty:
                transit_df = None

        # 从数据库获取库存和销售数据（T+ 模式内部已走 build_standard_data_from_frames）
        standard_df = build_standard_data_from_database(hq_df=hq_df, transit_df=transit_df)

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


@router.get("/export/sales")
async def export_sales_table():
    """导出近7天销售表（006仓库）- 表头与原始 Excel 一致"""
    try:
        import io
        import pandas as pd
        from datetime import datetime, timedelta
        from app.config import SAFE_DAYS, WARNING_WAREHOUSE_CODE

        # 定义完整的表头列
        full_columns = [
            "单据日期", "创建时间", "单据编号", "业务类型", "票据类型",
            "客户编码", "客户", "部门编码", "部门", "业务员编码", "业务员",
            "送货人编码", "送货人", "送货日期", "发货人编码", "发货人",
            "结算客户编码", "结算客户", "收款到期日", "收款方式", "运输方式",
            "现结金额", "抹零", "单据状态", "整单结款状态",
            "存货编码", "存货", "规格型号", "尺码", "仓库编码", "仓库", "销售单位", "数量"
        ]

        if DB_TYPE == "mock":
            data = [
                {
                    "单据日期": datetime.now().strftime("%Y-%m-%d"),
                    "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "单据编号": "MOCK001", "业务类型": "销售", "票据类型": "",
                    "客户编码": "C001", "客户": "测试客户", "部门编码": "D01", "部门": "销售部",
                    "业务员编码": "S01", "业务员": "张三", "送货人编码": "", "送货人": "",
                    "送货日期": "", "发货人编码": "", "发货人": "",
                    "结算客户编码": "C001", "结算客户": "测试客户", "收款到期日": "", "收款方式": "",
                    "运输方式": "", "现结金额": 0, "抹零": 0, "单据状态": "已完成", "整单结款状态": "",
                    "存货编码": "SKU001", "存货": "测试商品A", "规格型号": "", "尺码": "M",
                    "仓库编码": "006", "仓库": "销售一库", "销售单位": "件", "数量": 35
                },
                {
                    "单据日期": datetime.now().strftime("%Y-%m-%d"),
                    "创建时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "单据编号": "MOCK002", "业务类型": "销售", "票据类型": "",
                    "客户编码": "C002", "客户": "测试客户2", "部门编码": "D01", "部门": "销售部",
                    "业务员编码": "S02", "业务员": "李四", "送货人编码": "", "送货人": "",
                    "送货日期": "", "发货人编码": "", "发货人": "",
                    "结算客户编码": "C002", "结算客户": "测试客户2", "收款到期日": "", "收款方式": "",
                    "运输方式": "", "现结金额": 0, "抹零": 0, "单据状态": "已完成", "整单结款状态": "",
                    "存货编码": "SKU002", "存货": "测试商品B", "规格型号": "", "尺码": "L",
                    "仓库编码": "006", "仓库": "销售一库", "销售单位": "件", "数量": 21
                },
            ]
            df = pd.DataFrame(data)
        elif DB_TYPE in {"tplus", "openapi", "chanjet"}:
            # T+ 模式：使用缓存的销售数据
            from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
            client = TPlusOpenAPIClient()
            df = client.query_recent_sale_delivery_sales(days=SAFE_DAYS)
            # 重命名列以匹配 Excel 格式
            df = df.rename(columns={"近7天销量": "数量"})
            # 添加缺失的列
            if "存货" not in df.columns:
                df["存货"] = ""
            df["仓库编码"] = WARNING_WAREHOUSE_CODE
            df["仓库"] = "销售一库"
            df["销售单位"] = "件"
        else:
            from sqlalchemy import create_engine, text
            from app.data_sources.database_source import build_database_url

            engine = create_engine(build_database_url())

            if DB_TYPE == "sqlserver":
                sales_date_filter = f"business_date >= DATEADD(day, -{SAFE_DAYS}, GETDATE())"
            else:
                sales_date_filter = f"business_date >= CURRENT_DATE - INTERVAL '{SAFE_DAYS} day'"

            sales_sql = f"""
                SELECT
                    business_date AS 单据日期,
                    create_time AS 创建时间,
                    voucher_code AS 单据编号,
                    business_type AS 业务类型,
                    invoice_type AS 票据类型,
                    customer_code AS 客户编码,
                    customer_name AS 客户,
                    department_code AS 部门编码,
                    department_name AS 部门,
                    salesperson_code AS 业务员编码,
                    salesperson_name AS 业务员,
                    delivery_person_code AS 送货人编码,
                    delivery_person_name AS 送货人,
                    delivery_date AS 送货日期,
                    shipper_code AS 发货人编码,
                    shipper_name AS 发货人,
                    settlement_customer_code AS 结算客户编码,
                    settlement_customer_name AS 结算客户,
                    payment_due_date AS 收款到期日,
                    payment_method AS 收款方式,
                    shipping_method AS 运输方式,
                    cash_amount AS 现结金额,
                    rounding AS 抹零,
                    voucher_status AS 单据状态,
                    payment_status AS 整单结款状态,
                    sku_code AS 存货编码,
                    sku_name AS 存货,
                    specification AS 规格型号,
                    size_name AS 尺码,
                    warehouse_code AS 仓库编码,
                    warehouse_name AS 仓库,
                    sales_unit AS 销售单位,
                    SUM(quantity) AS 数量
                FROM sales
                WHERE {sales_date_filter}
                  AND warehouse_code = :warning_warehouse_code
                GROUP BY business_date, create_time, voucher_code, business_type, invoice_type,
                         customer_code, customer_name, department_code, department_name,
                         salesperson_code, salesperson_name, delivery_person_code, delivery_person_name,
                         delivery_date, shipper_code, shipper_name, settlement_customer_code,
                         settlement_customer_name, payment_due_date, payment_method, shipping_method,
                         cash_amount, rounding, voucher_status, payment_status,
                         sku_code, sku_name, specification, size_name, warehouse_code, warehouse_name, sales_unit
                ORDER BY business_date DESC
            """

            df = pd.read_sql_query(
                text(sales_sql),
                engine,
                params={"warning_warehouse_code": WARNING_WAREHOUSE_CODE},
            )

        # 添加缺失的列
        for col in full_columns:
            if col not in df.columns:
                df[col] = ""

        # 确保列顺序与原始 Excel 一致
        df = df[full_columns]

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='近7天销售表', index=False)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=sales_report.xlsx"}
        )

    except Exception as exc:
        logger.exception("导出销售表失败")
        return HTMLResponse(content=f"导出失败: {str(exc)}", status_code=500)


@router.get("/export/inventory")
async def export_inventory_table():
    """导出库存表（006仓库）- 表头与原始 Excel 一致"""
    try:
        import io
        import pandas as pd
        from app.config import WARNING_WAREHOUSE_CODE

        if DB_TYPE == "mock":
            data = [
                {"仓库编码": "006", "仓库": "销售一库", "存货编码": "SKU001", "存货": "测试商品A", "规格型号": "", "主计量": "件", "尺码": "M", "现存量(主)": 8, "可用量(主)": 4},
                {"仓库编码": "006", "仓库": "销售一库", "存货编码": "SKU002", "存货": "测试商品B", "规格型号": "", "主计量": "件", "尺码": "L", "现存量(主)": 0, "可用量(主)": 0},
            ]
            df = pd.DataFrame(data)
        elif DB_TYPE in {"tplus", "openapi", "chanjet"}:
            # T+ 模式：从 T+ API 获取库存数据
            from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
            client = TPlusOpenAPIClient()
            stock_records = client.query_current_stock()

            # 转换为 DataFrame
            rows = []
            for item in stock_records:
                from app.data_sources.tplus_openapi_source import _field, _to_number, _first_dynamic_value
                from app.data_sources.excel_source import clean_code, clean_size

                warehouse_code = str(_field(item, "WarehouseCode", "warehouseCode", "WhCode", "whCode") or "")
                if WARNING_WAREHOUSE_CODE and warehouse_code != WARNING_WAREHOUSE_CODE:
                    continue

                rows.append({
                    "仓库编码": warehouse_code,
                    "仓库": str(_field(item, "WarehouseName", "warehouseName", "WhName", "whName") or ""),
                    "存货编码": clean_code(_field(item, "InventoryCode", "inventoryCode", "Code", "code", "InvCode")),
                    "存货": str(_field(item, "InventoryName", "inventoryName", "Name", "name", "InvName") or ""),
                    "规格型号": str(_field(item, "Specification", "specification", "Spec", "spec") or ""),
                    "主计量": str(_field(item, "Unit", "unit", "MainUnit", "mainUnit") or "件"),
                    "尺码": clean_size(_first_dynamic_value(item)),
                    "现存量(主)": _to_number(_field(item, "ExistingQuantity", "existingQuantity", "Quantity", "quantity")),
                    "可用量(主)": _to_number(_field(item, "AvailableQuantity", "availableQuantity", "AvailableQty", "availableQty")),
                })
            df = pd.DataFrame(rows)
        else:
            from sqlalchemy import create_engine, text
            from app.data_sources.database_source import build_database_url

            engine = create_engine(build_database_url())

            inventory_sql = """
                SELECT
                    warehouse_code AS 仓库编码,
                    warehouse_name AS 仓库,
                    sku_code AS 存货编码,
                    sku_name AS 存货,
                    specification AS 规格型号,
                    unit AS 主计量,
                    size_name AS 尺码,
                    current_qty AS "现存量(主)",
                    available_qty AS "可用量(主)"
                FROM inventory
                WHERE warehouse_code = :warning_warehouse_code
                ORDER BY sku_code
            """

            df = pd.read_sql_query(
                text(inventory_sql),
                engine,
                params={"warning_warehouse_code": WARNING_WAREHOUSE_CODE},
            )

        # 添加缺失的列
        for col in ["规格型号", "主计量"]:
            if col not in df.columns:
                df[col] = ""

        # 确保列顺序与原始 Excel 一致
        df = df[["仓库编码", "仓库", "存货编码", "存货", "规格型号", "主计量", "尺码", "现存量(主)", "可用量(主)"]]

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='库存表', index=False)
        output.seek(0)

        return StreamingResponse(
            output,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=inventory_report.xlsx"}
        )

    except Exception as exc:
        logger.exception("导出库存表失败")
        return HTMLResponse(content=f"导出失败: {str(exc)}", status_code=500)

