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


# ========= 构建标准数据层 =========

def build_standard_data(
    inventory_file,
    sales_file,
    hq_file=None
):
    """
    从 Excel 文件构建标准数据。

    Args:
        inventory_file: 库存表文件对象
        sales_file: 销售表文件对象
        hq_file: 总部库存表文件对象，可选

    Returns:
        标准 DataFrame
    """
    sales_df = build_sales_standard_df(sales_file)
    inventory_df = build_inventory_standard_df(inventory_file)
    hq_df = build_hq_standard_df(hq_file) if hq_file else None

    # Excel 入口已在各 build_*_df 函数中清洗过，标记 already_cleaned=True
    return build_standard_data_from_frames(inventory_df, sales_df, hq_df, already_cleaned=True)
