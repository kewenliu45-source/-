import pandas as pd
import numpy as np


def analyze_standard_data(df: pd.DataFrame) -> pd.DataFrame:
    result_df = df.copy()

    # 日均销量
    result_df["日均销量"] = result_df["日均销量"].fillna(0)

    # 当前可用量
    result_df["当前可用量"] = result_df["当前可用量"].fillna(0)

    # 总部库存
    result_df["总部库存"] = result_df["总部库存"].fillna(0)

    # 可售天数
    result_df["可售天数"] = np.where(
        result_df["日均销量"] > 0,
        result_df["当前可用量"] / result_df["日均销量"],
        999
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
    def get_warning_status(row):
        if row["当前可用量"] <= 0:
            return "红色预警"

        elif row["可售天数"] < 7:
            return "黄色预警"

        else:
            return "正常"

    result_df["预警状态"] = result_df.apply(
        get_warning_status,
        axis=1
    )

    # 调货建议
    def get_transfer_advice(row):
        if row["预警状态"] == "红色预警":
            return f"建议立即调货 {int(row['总部可调数量'])} 件"

        elif row["预警状态"] == "黄色预警":
            return f"建议尽快调货 {int(row['总部可调数量'])} 件"

        return "-"

    result_df["调货建议"] = result_df.apply(
        get_transfer_advice,
        axis=1
    )

    # 排序
    warning_order = {
        "红色预警": 0,
        "黄色预警": 1,
        "正常": 2
    }

    result_df["排序"] = result_df["预警状态"].map(warning_order)

    result_df = result_df.sort_values(
        by=["排序", "可售天数"]
    )

    result_df = result_df.drop(columns=["排序"])

    # 数值美化
    result_df["可售天数"] = result_df["可售天数"].round(1)
    result_df["日均销量"] = result_df["日均销量"].round(1)

    return result_df