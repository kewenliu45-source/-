import pandas as pd
import numpy as np

from app.config import SAFE_DAYS, WARNING_WAREHOUSE_CODE
from app.data_sources.base import ensure_standard_columns, build_standard_data_from_frames

# ========= 通用清洗 =========

def clean_columns(df):
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.replace("\n", "", regex=False)
        .str.replace(" ", "", regex=False)
    )
    return df


def clean_code(value):
    if pd.isna(value):
        return ""

    s = str(value).strip()
    # Excel 中编码列若为纯数字会被读成浮点数（如 1001.0），只去除这种尾缀
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except ValueError:
            pass
    return s


def clean_size(value):
    if pd.isna(value):
        return ""

    value = str(value).strip()

    value = value.replace("码", "")

    return value


# ========= 销售表 =========

def build_sales_standard_df(sales_file):

    # 先读取前几行，检测表头位置
    preview = pd.read_excel(sales_file, header=None, nrows=10)

    # 查找包含 "存货编码" 的行作为表头
    header_row = 0
    for i, row in preview.iterrows():
        row_str = " ".join(str(v) for v in row.values if pd.notna(v))
        if "存货编码" in row_str:
            header_row = i
            break

    # 读取时指定字符串列，避免数字被自动转换
    sales_df = pd.read_excel(
        sales_file,
        header=header_row,
        dtype={"存货编码": str, "尺码": str, "仓库编码": str}
    )

    sales_df = clean_columns(sales_df)

    # 填充 NaN 值，避免 groupby 时丢失数据
    for col in ["存货", "仓库", "销售单位"]:
        if col in sales_df.columns:
            sales_df[col] = sales_df[col].fillna("")

    sales_df["存货编码"] = sales_df["存货编码"].apply(clean_code)

    sales_df["尺码"] = sales_df["尺码"].apply(clean_size)

    sales_df["数量"] = pd.to_numeric(
        sales_df["数量"],
        errors="coerce"
    ).fillna(0)

    # 按仓库筛选（与库存表保持一致）
    # 处理仓库编码格式：6.0 -> 6 -> 006
    if WARNING_WAREHOUSE_CODE and "仓库编码" in sales_df.columns:
        sales_df["仓库编码"] = pd.to_numeric(sales_df["仓库编码"], errors="coerce")
        sales_df = sales_df[sales_df["仓库编码"].notna()]
        sales_df["仓库编码"] = sales_df["仓库编码"].astype(int).astype(str).str.zfill(3)
        sales_df = sales_df[sales_df["仓库编码"] == WARNING_WAREHOUSE_CODE]

    # 只保留有销量
    sales_df = sales_df[sales_df["数量"] > 0]

    sales_standard_df = (
        sales_df
        .groupby(
            ["存货编码", "存货", "尺码"],
            as_index=False
        )["数量"]
        .sum()
    )

    sales_standard_df = sales_standard_df.rename(
        columns={
            "数量": "近7天销量"
        }
    )

    sales_standard_df["日均销量"] = (
        sales_standard_df["近7天销量"] / SAFE_DAYS
    )

    return sales_standard_df


# ========= 近1年销售表（高库存预警用）=========

def build_annual_sales_standard_df(annual_sales_file):
    """解析近1年销售表，输出高库存预警所需的年度销售数据。

    复用现有销售表解析逻辑：自动识别表头、清洗编码/尺码、仓库筛选、聚合。

    Returns:
        DataFrame 列: 存货编码, 存货, 尺码, 近365天销量, 年日均销量
    """
    # 先读取前几行，检测表头位置
    preview = pd.read_excel(annual_sales_file, header=None, nrows=10)

    # 查找包含 "存货编码" 的行作为表头
    header_row = 0
    for i, row in preview.iterrows():
        row_str = " ".join(str(v) for v in row.values if pd.notna(v))
        if "存货编码" in row_str:
            header_row = i
            break

    # 读取时指定字符串列，避免数字被自动转换
    df = pd.read_excel(
        annual_sales_file,
        header=header_row,
        dtype={"存货编码": str, "尺码": str, "仓库编码": str},
    )

    df = clean_columns(df)

    # 填充 NaN 值，避免 groupby 时丢失数据
    for col in ["存货", "仓库", "销售单位"]:
        if col in df.columns:
            df[col] = df[col].fillna("")

    df["存货编码"] = df["存货编码"].apply(clean_code)
    df["尺码"] = df["尺码"].apply(clean_size)

    df["数量"] = pd.to_numeric(df["数量"], errors="coerce").fillna(0)

    # 按仓库筛选
    if WARNING_WAREHOUSE_CODE and "仓库编码" in df.columns:
        df["仓库编码"] = pd.to_numeric(df["仓库编码"], errors="coerce")
        df = df[df["仓库编码"].notna()]
        df["仓库编码"] = df["仓库编码"].astype(int).astype(str).str.zfill(3)
        df = df[df["仓库编码"] == WARNING_WAREHOUSE_CODE]

    # 只保留有销量
    df = df[df["数量"] > 0]

    result = (
        df
        .groupby(["存货编码", "存货", "尺码"], as_index=False)["数量"]
        .sum()
    )

    result = result.rename(columns={"数量": "近365天销量"})
    result["年日均销量"] = (result["近365天销量"] / 365).round(2)

    return result


# ========= 库存表 =========

def build_inventory_standard_df(inventory_file):

    # 先读取前几行，检测表头位置
    preview = pd.read_excel(inventory_file, header=None, nrows=10)

    # 查找包含 "存货编码" 的行作为表头
    header_row = 0
    for i, row in preview.iterrows():
        row_str = " ".join(str(v) for v in row.values if pd.notna(v))
        if "存货编码" in row_str:
            header_row = i
            break

    # 读取时指定字符串列，避免数字被自动转换
    inventory_df = pd.read_excel(
        inventory_file,
        header=header_row,
        dtype={"存货编码": str, "尺码": str, "仓库编码": str}
    )

    inventory_df = clean_columns(inventory_df)

    inventory_df["存货编码"] = inventory_df["存货编码"].apply(clean_code)

    inventory_df["尺码"] = inventory_df["尺码"].apply(clean_size)

    inventory_df["可用量(主)"] = pd.to_numeric(
        inventory_df["可用量(主)"],
        errors="coerce"
    ).fillna(0)

    inventory_df["现存量(主)"] = pd.to_numeric(
        inventory_df["现存量(主)"],
        errors="coerce"
    ).fillna(0)

    inventory_standard_df = inventory_df[
        [
            "仓库编码",
            "仓库",
            "存货编码",
            "存货",
            "尺码",
            "现存量(主)",
            "可用量(主)"
        ]
    ].copy()

    # 在途仓是数值字段，默认为 0（T+ 路径从 currentStock 提取，Excel 路径无此数据源）
    inventory_standard_df["在途仓"] = 0

    inventory_standard_df = inventory_standard_df.rename(
        columns={
            "现存量(主)": "当前现存量",
            "可用量(主)": "当前可用量"
        }
    )

    return inventory_standard_df


# ========= 总部二维库存表 =========

def build_hq_standard_df(hq_file):

    hq_df = pd.read_excel(hq_file, header=1)

    hq_df = clean_columns(hq_df)

    # 总部库存表存货编码取后11位，与销售表/库存表匹配
    def clean_hq_code(value):
        s = clean_code(value)
        if len(s) > 11:
            return s[-11:]
        return s

    hq_df["存货编码"] = hq_df["存货编码"].apply(clean_hq_code)

    id_cols = [
        "检索号",
        "存货编码",
        "存货名称",
        "存货等级",
        "款式类别"
    ]

    id_cols = [c for c in id_cols if c in hq_df.columns]

    size_cols = [
        c for c in hq_df.columns
        if c not in id_cols
    ]

    hq_long_df = hq_df.melt(
        id_vars=id_cols,
        value_vars=size_cols,
        var_name="尺码",
        value_name="总部库存"
    )

    hq_long_df["尺码"] = hq_long_df["尺码"].apply(clean_size)

    hq_long_df["总部库存"] = pd.to_numeric(
        hq_long_df["总部库存"],
        errors="coerce"
    ).fillna(0)

    # 过滤掉存货编码为空的行（如"总计"行）
    hq_long_df = hq_long_df[
        (hq_long_df["总部库存"] > 0) &
        (hq_long_df["存货编码"].astype(str).str.strip() != "")
    ]

    hq_standard_df = (
        hq_long_df
        .groupby(
            ["存货编码", "尺码"],
            as_index=False
        )["总部库存"]
        .sum()
    )

    return hq_standard_df


# ========= 在途库存表（未发货）=========

def build_intransit_standard_df(transit_file):
    """
    解析在途库存表（宽表格式），输出标准长表。

    在途表格式与总部二维表类似：
    - 表头行包含 '货号/尺码' 和各尺码列
    - 每行是一个 SKU，各尺码列的值为在途数量

    只输出在途数量，不输出仓库信息（在途仓来自本地库存表）。

    返回列: 存货编码, 尺码, 在途（未发货）
    """
    # 自动检测表头行
    preview = pd.read_excel(transit_file, header=None, nrows=15)
    header_row = 0
    for i, row in preview.iterrows():
        row_str = " ".join(str(v) for v in row.values if pd.notna(v))
        if "货号/尺码" in row_str or "存货编码" in row_str:
            header_row = i
            break

    transit_df = pd.read_excel(transit_file, header=header_row)
    transit_df = clean_columns(transit_df)

    # 识别编码列
    code_col = None
    for candidate in ["货号/尺码", "存货编码", "编码"]:
        if candidate in transit_df.columns:
            code_col = candidate
            break
    if code_col is None:
        raise ValueError("在途库存表中未找到编码列（货号/尺码 或 存货编码）")

    # 识别非尺码列（排除这些后，剩下的都是尺码列）
    id_cols = {code_col, "K", "合计", "中/小学/幼儿园", "吊牌价", "备注", "单价", "金额",
               "仓库", "仓库名称", "仓库编码", "在途仓"}
    id_cols = id_cols & set(transit_df.columns)
    size_cols = [c for c in transit_df.columns if c not in id_cols]

    # 如果没有尺码列，尝试按 存货编码+尺码 的长表格式处理
    if not size_cols:
        if "尺码" in transit_df.columns and "在途（未发货）" in transit_df.columns:
            result = transit_df[["存货编码", "尺码", "在途（未发货）"]].copy()
            result["存货编码"] = result["存货编码"].apply(clean_code)
            result["尺码"] = result["尺码"].apply(clean_size)
            result["在途（未发货）"] = pd.to_numeric(result["在途（未发货）"], errors="coerce").fillna(0)
            return result
        raise ValueError("在途库存表中未识别到尺码列")

    # 宽表 → 长表
    transit_df = transit_df.rename(columns={code_col: "存货编码"})

    long_df = transit_df.melt(
        id_vars=["存货编码"],
        value_vars=size_cols,
        var_name="尺码",
        value_name="在途（未发货）",
    )

    long_df["存货编码"] = long_df["存货编码"].apply(clean_code)
    long_df["尺码"] = long_df["尺码"].apply(clean_size)
    long_df["在途（未发货）"] = pd.to_numeric(long_df["在途（未发货）"], errors="coerce").fillna(0)

    # 过滤掉数量为 0 或编码为空的行
    long_df = long_df[
        (long_df["在途（未发货）"] > 0) &
        (long_df["存货编码"].astype(str).str.strip() != "")
    ]

    # 聚合：只输出 存货编码、尺码、在途（未发货）
    result = (
        long_df
        .groupby(["存货编码", "尺码"], as_index=False)["在途（未发货）"]
        .sum()
    )

    return result


# ========= 构建标准数据层 =========

def build_standard_data(
    inventory_file,
    sales_file,
    transit_file=None,
    hq_file=None,
):
    """
    从 Excel 文件构建标准数据（四表合一）。

    Args:
        inventory_file: 本地库存表文件对象
        sales_file: 近期销售表文件对象
        transit_file: 在途库存表文件对象（未发货），可选
        hq_file: 总部库存表文件对象，可选

    Returns:
        (标准 DataFrame, 警告信息列表)
    """
    from app.data_sources.tplus_openapi_source import query_90day_sales

    warnings = []

    sales_df = build_sales_standard_df(sales_file)
    inventory_df = build_inventory_standard_df(inventory_file)
    transit_df = build_intransit_standard_df(transit_file) if transit_file else None
    hq_df = build_hq_standard_df(hq_file) if hq_file else None

    # 近90天销量从 T+ API 实时获取
    sales_90_df = None
    try:
        sales_90_df = query_90day_sales()
        import logging
        logging.getLogger(__name__).warning(
            "近90天销量查询结果: 行数=%s, 列=%s",
            len(sales_90_df) if sales_90_df is not None else "None",
            list(sales_90_df.columns) if sales_90_df is not None else "N/A",
        )
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("近90天销量查询失败，降级为0: %s", exc)
        warnings.append("T+ 近90天销量获取失败，本次未计算橙色缺码预警，仅完成红黄绿库存预警。")

    # Excel 入口已在各 build_*_df 函数中清洗过，标记 already_cleaned=True
    standard_df = build_standard_data_from_frames(
        inventory_df, sales_df, hq_df,
        already_cleaned=True,
        transit_df=transit_df,
        sales_90_df=sales_90_df,
    )
    return standard_df, warnings
