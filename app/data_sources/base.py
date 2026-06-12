import pandas as pd

from app.config import SAFE_DAYS, WARNING_WAREHOUSE_CODE

STANDARD_COLUMNS = [
    "存货编码",
    "存货",
    "尺码",
    "近7天销量",
    "日均销量",
    "仓库编码",
    "仓库",
    "当前现存量",
    "当前可用量",
    "总部库存",
]


def ensure_standard_columns(df: pd.DataFrame) -> pd.DataFrame:
    missing_columns = [column for column in STANDARD_COLUMNS if column not in df.columns]
    if missing_columns:
        raise ValueError(f"标准数据缺少字段：{', '.join(missing_columns)}")

    return df[STANDARD_COLUMNS].copy()


def _clean_code(value) -> str:
    """清洗编码字段（处理 Excel 浮点数问题）"""
    if pd.isna(value):
        return ""
    s = str(value).strip()
    if s.endswith(".0"):
        try:
            return str(int(float(s)))
        except ValueError:
            pass
    return s


def _clean_size(value) -> str:
    """清洗尺码字段（去除"码"字）"""
    if pd.isna(value):
        return ""
    return str(value).strip().replace("码", "")


def _ensure_clean_code_size(df: pd.DataFrame) -> pd.DataFrame:
    """确保编码和尺码字段已清洗"""
    from app.data_sources.excel_source import clean_code, clean_size
    if "存货编码" in df.columns:
        df["存货编码"] = df["存货编码"].apply(clean_code)
    if "尺码" in df.columns:
        df["尺码"] = df["尺码"].apply(clean_size)
    return df


def build_standard_data_from_frames(
    inventory_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    hq_df: pd.DataFrame | None = None,
    already_cleaned: bool = False,
) -> pd.DataFrame:
    """
    将库存、销售、总部库存三个 DataFrame 合并为标准数据。

    Args:
        inventory_df: 库存数据，必须包含 存货编码, 尺码, 当前现存量, 当前可用量
        sales_df: 销售数据，必须包含 存货编码, 尺码, 近7天销量
        hq_df: 总部库存数据，可选，包含 存货编码, 尺码, 总部库存
        already_cleaned: 如果为 True，跳过编码/尺码清洗（Excel 入口已清洗）

    Returns:
        标准 DataFrame
    """
    # 校验必要字段
    required_inventory_cols = {"存货编码", "尺码", "当前现存量", "当前可用量"}
    missing_inv = required_inventory_cols - set(inventory_df.columns)
    if missing_inv:
        raise ValueError(f"库存数据缺少必要字段：{', '.join(missing_inv)}")

    required_sales_cols = {"存货编码", "尺码", "近7天销量"}
    missing_sales = required_sales_cols - set(sales_df.columns)
    if missing_sales:
        raise ValueError(f"销售数据缺少必要字段：{', '.join(missing_sales)}")

    # 1. 清洗销售数据（如未清洗过）
    if not already_cleaned:
        sales_df = _ensure_clean_code_size(sales_df)
    sales_df["近7天销量"] = pd.to_numeric(sales_df["近7天销量"], errors="coerce").fillna(0)

    # 2. 筛选近7天销量 > 0
    sales_df = sales_df[sales_df["近7天销量"] > 0]

    # 3. 计算日均销量
    sales_df["日均销量"] = sales_df["近7天销量"] / SAFE_DAYS

    # 4. 清洗库存数据（如未清洗过）
    if not already_cleaned:
        inventory_df = _ensure_clean_code_size(inventory_df)

    # 仓库筛选
    if WARNING_WAREHOUSE_CODE and "仓库编码" in inventory_df.columns:
        inventory_df = inventory_df[
            inventory_df["仓库编码"].astype(str).str.strip() == WARNING_WAREHOUSE_CODE
        ]

    inventory_df["当前现存量"] = pd.to_numeric(inventory_df["当前现存量"], errors="coerce").fillna(0)
    inventory_df["当前可用量"] = pd.to_numeric(inventory_df["当前可用量"], errors="coerce").fillna(0)

    # 5. 聚合库存数据
    agg_dict = {"当前现存量": "sum", "当前可用量": "sum"}
    for col in ["仓库编码", "仓库", "存货"]:
        if col in inventory_df.columns:
            agg_dict[col] = "first"

    inventory_group_df = (
        inventory_df
        .groupby(["存货编码", "尺码"], as_index=False)
        .agg(agg_dict)
    )

    # 6. 合并销售 + 库存
    standard_df = sales_df.merge(
        inventory_group_df,
        on=["存货编码", "尺码"],
        how="left",
        suffixes=("", "_库存"),
    )

    # 商品名补全
    if "存货_库存" in standard_df.columns:
        standard_df["存货"] = standard_df["存货"].fillna(standard_df["存货_库存"])
        standard_df = standard_df.drop(columns=["存货_库存"])

    # 7. 合并总部库存（如有）
    if hq_df is not None and not hq_df.empty:
        if not already_cleaned:
            hq_df = _ensure_clean_code_size(hq_df)
        hq_df["总部库存"] = pd.to_numeric(hq_df["总部库存"], errors="coerce").fillna(0)

        hq_group_df = (
            hq_df
            .groupby(["存货编码", "尺码"], as_index=False)["总部库存"]
            .sum()
        )
        standard_df = standard_df.merge(hq_group_df, on=["存货编码", "尺码"], how="left")

    # 8. fillna
    for col in ["仓库编码", "仓库"]:
        if col in standard_df.columns:
            standard_df[col] = standard_df[col].fillna("")
    for col in ["当前现存量", "当前可用量", "总部库存"]:
        standard_df[col] = standard_df.get(col, 0)
        if standard_df[col].isna().any():
            standard_df[col] = standard_df[col].fillna(0)

    # 9. ensure_standard_columns()
    return ensure_standard_columns(standard_df)
