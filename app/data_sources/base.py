import pandas as pd


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
