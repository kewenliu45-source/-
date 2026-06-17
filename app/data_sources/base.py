import pandas as pd

from app.config import SAFE_DAYS, WARNING_WAREHOUSE_CODE

STANDARD_COLUMNS = [
    "存货编码",
    "存货",
    "尺码",
    "近7天销量",
    "日均销量",
    "近90天销量",
    "仓库编码",
    "仓库",
    "当前现存量",
    "当前可用量",
    "总部库存",
    "在途仓",
    "在途（未发货）",
]

KEY_COLUMNS = ["存货编码", "尺码"]


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


def _require_columns(df: pd.DataFrame, required_columns: set[str], data_name: str) -> None:
    missing_columns = required_columns - set(df.columns)
    if missing_columns:
        raise ValueError(f"{data_name}缺少必要字段：{', '.join(sorted(missing_columns))}")


def _normalize_warehouse_code(value) -> str:
    """统一仓库编码格式，避免 6 / 006 / 006.0 匹配不一致。"""
    code = _clean_code(value)
    if WARNING_WAREHOUSE_CODE and WARNING_WAREHOUSE_CODE.isdigit() and code.isdigit():
        return code.zfill(len(WARNING_WAREHOUSE_CODE))
    return code


def _aggregate_sales_df(sales_df: pd.DataFrame) -> pd.DataFrame:
    agg_dict = {"近7天销量": "sum"}
    if "存货" in sales_df.columns:
        agg_dict["存货"] = "first"

    result = sales_df.groupby(KEY_COLUMNS, as_index=False).agg(agg_dict)
    result["日均销量"] = result["近7天销量"] / SAFE_DAYS
    return result


def _sum_optional_df(
    df: pd.DataFrame,
    value_column: str,
    data_name: str,
    already_cleaned: bool,
) -> pd.DataFrame:
    _require_columns(df, {"存货编码", "尺码", value_column}, data_name)
    if not already_cleaned:
        df = _ensure_clean_code_size(df)
    else:
        df = df.copy()
    df[value_column] = pd.to_numeric(df[value_column], errors="coerce").fillna(0)
    return df.groupby(KEY_COLUMNS, as_index=False)[value_column].sum()


def build_standard_data_from_frames(
    inventory_df: pd.DataFrame,
    sales_df: pd.DataFrame | None = None,
    hq_df: pd.DataFrame | None = None,
    already_cleaned: bool = False,
    transit_df: pd.DataFrame | None = None,
    sales_90_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    将库存、销售、总部库存、在途、近90天销售等 DataFrame 合并为标准数据。

    Args:
        inventory_df: 库存数据，必须包含 存货编码, 尺码, 当前现存量, 当前可用量
        sales_df: 销售数据，必须包含 存货编码, 尺码, 近7天销量。
            如果为 None，表示 inventory_df 已包含销售数据（T+ 预合并场景）。
        hq_df: 总部库存数据，可选，包含 存货编码, 尺码, 总部库存
        already_cleaned: 如果为 True，跳过编码/尺码清洗（Excel 入口已清洗）
        transit_df: 在途库存数据，可选，包含 存货编码, 尺码, 在途（未发货）；可选 在途仓
        sales_90_df: 近90天销售聚合数据，可选，包含 存货编码, 尺码, 近90天销量

    Returns:
        标准 DataFrame
    """
    required_inventory_cols = {"存货编码", "尺码", "当前现存量", "当前可用量"}
    _require_columns(inventory_df, required_inventory_cols, "库存数据")

    has_sales = sales_df is not None and not sales_df.empty
    if has_sales:
        required_sales_cols = {"存货编码", "尺码", "近7天销量"}
        _require_columns(sales_df, required_sales_cols, "销售数据")

    # 1. 清洗销售数据（如未清洗过）
    if has_sales:
        if not already_cleaned:
            sales_df = _ensure_clean_code_size(sales_df)
        else:
            sales_df = sales_df.copy()
        sales_df["近7天销量"] = pd.to_numeric(sales_df["近7天销量"], errors="coerce").fillna(0)

        # 2. 聚合并计算日均销量，避免销售明细一对多 merge 放大库存行
        sales_df = _aggregate_sales_df(sales_df)

    # 4. 清洗库存数据（如未清洗过）
    if not already_cleaned:
        inventory_df = _ensure_clean_code_size(inventory_df)
    else:
        inventory_df = inventory_df.copy()

    # 仓库筛选
    if WARNING_WAREHOUSE_CODE and "仓库编码" in inventory_df.columns:
        inventory_df["仓库编码"] = inventory_df["仓库编码"].apply(_normalize_warehouse_code)
        inventory_df = inventory_df[
            inventory_df["仓库编码"] == WARNING_WAREHOUSE_CODE
        ].copy()

    inventory_df["当前现存量"] = pd.to_numeric(inventory_df["当前现存量"], errors="coerce").fillna(0)
    inventory_df["当前可用量"] = pd.to_numeric(inventory_df["当前可用量"], errors="coerce").fillna(0)

    # 5. 聚合库存数据
    agg_dict = {"当前现存量": "sum", "当前可用量": "sum"}
    for col in ["仓库编码", "仓库", "存货"]:
        if col in inventory_df.columns:
            agg_dict[col] = "first"
    # 在途仓是数值字段，聚合时求和
    if "在途仓" in inventory_df.columns:
        inventory_df["在途仓"] = pd.to_numeric(inventory_df["在途仓"], errors="coerce").fillna(0)
        agg_dict["在途仓"] = "sum"
    # sales_df=None 时，inventory_df 已含销售数据，聚合时保留这些列
    if not has_sales:
        for col in ["近7天销量", "日均销量", "近90天销量", "在途（未发货）"]:
            if col in inventory_df.columns:
                agg_dict[col] = "sum"

    inventory_group_df = (
        inventory_df
        .groupby(["存货编码", "尺码"], as_index=False)
        .agg(agg_dict)
    )

    # 6. 合并库存 + 销售（以库存为主表，确保所有存货都保留）
    if has_sales:
        standard_df = inventory_group_df.merge(
            sales_df,
            on=["存货编码", "尺码"],
            how="left",
            suffixes=("", "_销售"),
        )

        # 商品名补全（优先用库存表的存货名，缺失时用销售表的）
        if "存货_销售" in standard_df.columns:
            standard_df["存货"] = standard_df["存货"].fillna(standard_df["存货_销售"])
            standard_df = standard_df.drop(columns=["存货_销售"])
    else:
        # sales_df 为 None：inventory_df 已包含销售数据（T+ 预合并场景）
        standard_df = inventory_group_df

    # 7. 合并总部库存（如有）
    if hq_df is not None and not hq_df.empty:
        hq_group_df = _sum_optional_df(hq_df, "总部库存", "总部库存数据", already_cleaned)
        standard_df = standard_df.merge(hq_group_df, on=["存货编码", "尺码"], how="left")

    # 7.5 合并近90天销量
    if sales_90_df is not None and not sales_90_df.empty:
        standard_df = standard_df.drop(columns=["近90天销量"], errors="ignore")
        sales_90_group = _sum_optional_df(sales_90_df, "近90天销量", "近90天销量数据", already_cleaned)
        standard_df = standard_df.merge(sales_90_group, on=["存货编码", "尺码"], how="left")

    # 7.6 合并在途库存
    if transit_df is not None and not transit_df.empty:
        # 在途（未发货）：来自人工 transit_df
        if "在途（未发货）" in transit_df.columns:
            standard_df = standard_df.drop(columns=["在途（未发货）"], errors="ignore")
            transit_group = _sum_optional_df(transit_df, "在途（未发货）", "在途库存数据", already_cleaned)
            standard_df = standard_df.merge(transit_group, on=["存货编码", "尺码"], how="left")
        # 在途仓：来自 transit_df 的数值列（如 T+ currentStock 在途仓数量）
        if "在途仓" in transit_df.columns:
            transit_warehouse_group = _sum_optional_df(transit_df, "在途仓", "在途仓数据", already_cleaned)
            # 合并：保留旧值，merge 新值后求和
            old_warehouse = standard_df["在途仓"].copy() if "在途仓" in standard_df.columns else 0
            standard_df = standard_df.drop(columns=["在途仓"], errors="ignore")
            standard_df = standard_df.merge(transit_warehouse_group, on=["存货编码", "尺码"], how="left")
            standard_df["在途仓"] = standard_df["在途仓"].fillna(0) + old_warehouse

    # 8. fillna
    for col in ["仓库编码", "仓库"]:
        if col in standard_df.columns:
            standard_df[col] = standard_df[col].fillna("")
    for col in ["近7天销量", "日均销量", "当前现存量", "当前可用量", "总部库存", "近90天销量", "在途仓", "在途（未发货）"]:
        if col not in standard_df.columns:
            standard_df[col] = 0
        else:
            standard_df[col] = pd.to_numeric(standard_df[col], errors="coerce").fillna(0)

    # 9. ensure_standard_columns()
    return ensure_standard_columns(standard_df)
