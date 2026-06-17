import pandas as pd
import numpy as np

from app.config import WARNING_WAREHOUSE_CODE


def _normalize_warehouse_code(value) -> str:
    """统一仓库编码格式，避免 6 / 006 / 006.0 匹配不一致。"""
    if pd.isna(value):
        return ""
    code = str(value).strip()
    if code.endswith(".0"):
        try:
            code = str(int(float(code)))
        except ValueError:
            pass
    if WARNING_WAREHOUSE_CODE and WARNING_WAREHOUSE_CODE.isdigit() and code.isdigit():
        return code.zfill(len(WARNING_WAREHOUSE_CODE))
    return code


def analyze_standard_data(df: pd.DataFrame) -> pd.DataFrame:
    result_df = df.copy()

    for column in ["日均销量", "当前可用量", "总部库存"]:
        result_df[column] = pd.to_numeric(
            result_df[column],
            errors="coerce"
        ).fillna(0)

    # 兼容：近90天销量缺失时默认 0
    if "近90天销量" not in result_df.columns:
        result_df["近90天销量"] = 0
    result_df["近90天销量"] = pd.to_numeric(result_df["近90天销量"], errors="coerce").fillna(0)

    # 兼容：当前现存量缺失时用当前可用量兜底
    if "当前现存量" not in result_df.columns:
        result_df["当前现存量"] = result_df["当前可用量"]
    result_df["当前现存量"] = pd.to_numeric(result_df["当前现存量"], errors="coerce").fillna(0)

    # 兼容：近7天销量缺失时用日均销量*7兜底，否则默认 0
    if "近7天销量" not in result_df.columns:
        result_df["近7天销量"] = result_df["日均销量"] * 7
    result_df["近7天销量"] = pd.to_numeric(result_df["近7天销量"], errors="coerce").fillna(0)

    # 可售天数（无销量时用 inf 保证排序正确，最终展示前替换为显示值）
    result_df["可售天数"] = float("inf")
    has_sales = result_df["日均销量"] > 0
    result_df.loc[has_sales, "可售天数"] = (
        result_df.loc[has_sales, "当前可用量"]
        / result_df.loc[has_sales, "日均销量"]
    )

    # 目标库存（7天安全库存）
    result_df["目标库存"] = result_df["日均销量"] * 7

    # 建议调货量
    result_df["建议调货量"] = (
        result_df["目标库存"] - result_df["当前可用量"]
    )

    result_df["建议调货量"] = (
        result_df["建议调货量"]
        .clip(lower=0)
        .round(0)
    )

    # 总部可调数量
    result_df["总部可调数量"] = np.minimum(
        result_df["总部库存"],
        result_df["建议调货量"]
    )

    # 预警状态
    # 优先级：红色 > 橙色缺码 > 黄色 > 正常
    # 红色：当前可用量 <= 0 且 近7天销量 > 0
    # 橙色缺码：当前现存量 <= 0 且 近90天销量 > 0（且不满足红色）
    # 黄色：当前可用量 > 0 且 近7天销量 > 0 且 可售天数 < 7
    def get_warning_status(row):
        available = row["当前可用量"]
        sales_7 = row["近7天销量"]
        stock = row["当前现存量"]
        sales_90 = row["近90天销量"]

        # 红色：有需求但完全无可用库存
        if available <= 0 and sales_7 > 0:
            return "红色预警"

        # 橙色缺码：本地无现货，但近90天有销售记录
        if stock <= 0 and sales_90 > 0:
            return "橙色缺码"

        # 黄色：有库存但可售天数不足
        if available > 0 and sales_7 > 0 and row["可售天数"] < 7:
            return "黄色预警"

        return "正常"

    result_df["预警状态"] = result_df.apply(
        get_warning_status,
        axis=1
    )

    # 调货建议
    def get_transfer_advice(row):
        try:
            suggest_qty = int(float(row["建议调货量"]))
            hq_available_qty = int(float(row["总部可调数量"]))
        except (ValueError, TypeError):
            suggest_qty = 0
            hq_available_qty = 0

        if row["预警状态"] == "红色预警":
            action = "建议立即调货"

        elif row["预警状态"] == "橙色缺码":
            action = "缺码待补"

        elif row["预警状态"] == "黄色预警":
            action = "建议尽快调货"

        else:
            return "-"

        if hq_available_qty <= 0:
            return f"{action} {suggest_qty} 件；总部暂无可调库存"

        if hq_available_qty < suggest_qty:
            shortage_qty = suggest_qty - hq_available_qty
            return f"{action} {suggest_qty} 件；总部可调 {hq_available_qty} 件，仍缺 {shortage_qty} 件"

        return f"{action} {suggest_qty} 件；总部可满足"

    result_df["调货建议"] = result_df.apply(
        get_transfer_advice,
        axis=1
    )

    # 排序
    warning_order = {
        "红色预警": 0,
        "橙色缺码": 1,
        "黄色预警": 2,
        "正常": 3,
    }

    result_df["排序"] = result_df["预警状态"].map(warning_order)

    result_df = result_df.sort_values(
        by=["排序", "可售天数"]
    )

    result_df = result_df.drop(columns=["排序"])

    # 数值美化（inf 替换为显示值后再 round）
    result_df["可售天数"] = result_df["可售天数"].replace(float("inf"), 999).round(1)
    result_df["日均销量"] = result_df["日均销量"].round(1)

    return result_df


def analyze_high_stock_data(
    inventory_df: pd.DataFrame,
    annual_sales_df: pd.DataFrame,
) -> pd.DataFrame:
    """高库存预警分析。

    以库存表为主表，按存货编码+尺码合并年度销售数据，
    计算预计消化库存天数，判断是否为高库存。

    Args:
        inventory_df: 库存数据，需包含 存货编码, 存货, 尺码, 当前现存量, 当前可用量
            可选列：仓库编码, 仓库（有仓库编码时按 WARNING_WAREHOUSE_CODE 筛选）
        annual_sales_df: 年度销售数据，需包含 存货编码, 尺码, 近365天销量

    Returns:
        包含高库存分析结果的 DataFrame
    """
    inv = inventory_df.copy()

    # 数值清洗
    for col in ["当前现存量", "当前可用量"]:
        if col in inv.columns:
            inv[col] = pd.to_numeric(inv[col], errors="coerce").fillna(0)

    # 仓库编码筛选
    if "仓库编码" in inv.columns and WARNING_WAREHOUSE_CODE:
        inv["仓库编码"] = inv["仓库编码"].apply(_normalize_warehouse_code)
        inv = inv[inv["仓库编码"] == WARNING_WAREHOUSE_CODE].copy()

    # 聚合库存（按存货编码+尺码去重）
    agg_dict = {"当前现存量": "sum", "当前可用量": "sum"}
    for col in ["仓库编码", "仓库", "存货"]:
        if col in inv.columns:
            agg_dict[col] = "first"
    inv = inv.groupby(["存货编码", "尺码"], as_index=False).agg(agg_dict)

    # 处理年度销售数据
    sales = annual_sales_df.copy()
    if "近365天销量" not in sales.columns:
        sales["近365天销量"] = 0
    sales["近365天销量"] = pd.to_numeric(sales["近365天销量"], errors="coerce").fillna(0)

    # 聚合年度销售（按存货编码+尺码汇总）
    sales_agg = sales.groupby(["存货编码", "尺码"], as_index=False)["近365天销量"].sum()

    # 合并
    result = inv.merge(sales_agg, on=["存货编码", "尺码"], how="left")
    result["近365天销量"] = result["近365天销量"].fillna(0)

    # 计算年日均销量
    result["年日均销量"] = (result["近365天销量"] / 365).round(2)

    # 计算预计消化库存天数
    result["预计消化库存天数"] = 999
    has_sales = result["年日均销量"] > 0
    result.loc[has_sales, "预计消化库存天数"] = (
        result.loc[has_sales, "当前可用量"] / result.loc[has_sales, "年日均销量"]
    ).round(1)

    # 判断预警状态
    result["预警状态"] = "正常"
    high_stock_mask = (result["当前可用量"] > 0) & (result["预计消化库存天数"] > 90)
    result.loc[high_stock_mask, "预警状态"] = "高库存预警"

    # 排序：高库存预警在前，按消化天数降序
    result["排序"] = (result["预警状态"] != "高库存预警").astype(int)
    result = result.sort_values(by=["排序", "预计消化库存天数"], ascending=[True, False])
    result = result.drop(columns=["排序"])

    return result
