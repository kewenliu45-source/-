import pandas as pd
import numpy as np

from app.data_sources.base import ensure_standard_columns

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

    return str(value).replace(".0", "").strip()


def clean_size(value):
    if pd.isna(value):
        return ""

    value = str(value).strip()

    value = value.replace("码", "")

    return value


# ========= 销售表 =========

def build_sales_standard_df(sales_file):

    sales_df = pd.read_excel(sales_file, header=7)

    sales_df = clean_columns(sales_df)

    sales_df["存货编码"] = sales_df["存货编码"].apply(clean_code)

    sales_df["尺码"] = sales_df["尺码"].apply(clean_size)

    sales_df["数量"] = pd.to_numeric(
        sales_df["数量"],
        errors="coerce"
    ).fillna(0)

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
        sales_standard_df["近7天销量"] / 7
    )

    return sales_standard_df


# ========= 库存表 =========

def build_inventory_standard_df(inventory_file):

    inventory_df = pd.read_excel(inventory_file, header=6)

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

    hq_df["存货编码"] = hq_df["存货编码"].apply(clean_code)

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

    hq_long_df = hq_long_df[
        hq_long_df["总部库存"] > 0
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
    hq_file
):

    sales_df = build_sales_standard_df(sales_file)

    inventory_df = build_inventory_standard_df(inventory_file)

    hq_df = build_hq_standard_df(hq_file)

    # 聚合库存
    inventory_group_df = (
        inventory_df
        .groupby(
            ["存货编码", "尺码"],
            as_index=False
        )
        .agg({
            "当前现存量": "sum",
            "当前可用量": "sum",
            "仓库编码": "first",
            "仓库": "first",
            "存货": "first"
        })
    )

    # 销售 + 库存
    standard_df = sales_df.merge(
        inventory_group_df,
        on=["存货编码", "尺码"],
        how="left",
        suffixes=("", "_库存")
    )

    # 商品名补全
    if "存货_库存" in standard_df.columns:

        standard_df["存货"] = standard_df["存货"].fillna(
            standard_df["存货_库存"]
        )

        standard_df = standard_df.drop(
            columns=["存货_库存"]
        )

    # 合并总部库存
    standard_df = standard_df.merge(
        hq_df,
        on=["存货编码", "尺码"],
        how="left"
    )

    # 空值处理
    standard_df["当前现存量"] = (
        standard_df["当前现存量"]
        .fillna(0)
    )

    standard_df["当前可用量"] = (
        standard_df["当前可用量"]
        .fillna(0)
    )

    standard_df["总部库存"] = (
        standard_df["总部库存"]
        .fillna(0)
    )

    return ensure_standard_columns(standard_df)
