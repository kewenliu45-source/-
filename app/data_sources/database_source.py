from urllib.parse import quote_plus

import pandas as pd

from app.config import (
    DB_HOST,
    DB_NAME,
    DB_PASSWORD,
    DB_PORT,
    DB_TYPE,
    DB_USER,
    DB_ODBC_DRIVER,
    DATABASE_URL,
    SAFE_DAYS,
    WARNING_WAREHOUSE_CODE,
)
from app.data_sources.base import ensure_standard_columns
from app.data_sources.excel_source import clean_code, clean_size


def build_database_url() -> str:
    if DATABASE_URL:
        return DATABASE_URL

    if not all([DB_TYPE, DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
        raise ValueError("数据库连接配置不完整，请检查 DB_TYPE、DB_HOST、DB_PORT、DB_NAME、DB_USER、DB_PASSWORD")

    user = quote_plus(DB_USER)
    password = quote_plus(DB_PASSWORD)
    host = DB_HOST
    database = quote_plus(DB_NAME)

    if DB_TYPE == "mysql":
        return f"mysql+pymysql://{user}:{password}@{host}:{DB_PORT}/{database}?charset=utf8mb4"

    if DB_TYPE == "postgresql":
        return f"postgresql+psycopg2://{user}:{password}@{host}:{DB_PORT}/{database}"

    if DB_TYPE == "sqlserver":
        driver = quote_plus(DB_ODBC_DRIVER)
        return (
            f"mssql+pyodbc://{user}:{password}@{host}:{DB_PORT}/{database}"
            f"?driver={driver}"
        )

    if DB_TYPE == "oracle":
        return f"oracle+oracledb://{user}:{password}@{host}:{DB_PORT}/?service_name={database}"

    raise ValueError(f"暂不支持的数据库类型：{DB_TYPE}")


def build_mock_standard_data() -> pd.DataFrame:
    data = [
        {
            "存货编码": "SKU001",
            "存货": "测试商品A",
            "尺码": "M",
            "近7天销量": 35,
            "日均销量": 5,
            "仓库编码": "WH001",
            "仓库": "本地仓",
            "当前现存量": 8,
            "当前可用量": 4,
            "总部库存": 60,
        },
        {
            "存货编码": "SKU002",
            "存货": "测试商品B",
            "尺码": "L",
            "近7天销量": 21,
            "日均销量": 3,
            "仓库编码": "WH001",
            "仓库": "本地仓",
            "当前现存量": 0,
            "当前可用量": 0,
            "总部库存": 18,
        },
        {
            "存货编码": "SKU003",
            "存货": "测试商品C",
            "尺码": "XL",
            "近7天销量": 14,
            "日均销量": 2,
            "仓库编码": "WH002",
            "仓库": "门店仓",
            "当前现存量": 30,
            "当前可用量": 26,
            "总部库存": 10,
        },
    ]

    return ensure_standard_columns(pd.DataFrame(data))


def read_sql_dataframe(sql: str, engine) -> pd.DataFrame:
    return pd.read_sql_query(sql, engine)


def build_standard_data_from_database() -> pd.DataFrame:
    if DB_TYPE == "mock":
        return build_mock_standard_data()

    if DB_TYPE in {"tplus", "openapi", "chanjet"}:
        from app.data_sources.tplus_openapi_source import build_standard_data_from_tplus_openapi

        return build_standard_data_from_tplus_openapi()

    try:
        from sqlalchemy import create_engine, text
    except ImportError as exc:
        raise RuntimeError("缺少数据库依赖，请先安装 sqlalchemy 和对应数据库驱动") from exc

    engine = create_engine(build_database_url())

    # 这些 SQL 是对接模板。到客户现场后，需要根据真实表名、字段名和口径调整。
    inventory_sql = """
        SELECT
            warehouse_code AS 仓库编码,
            warehouse_name AS 仓库,
            sku_code AS 存货编码,
            sku_name AS 存货,
            size_name AS 尺码,
            current_qty AS 当前现存量,
            available_qty AS 当前可用量
        FROM inventory
        WHERE warehouse_code = :warning_warehouse_code
    """

    if DB_TYPE == "sqlserver":
        sales_date_filter = f"business_date >= DATEADD(day, -{SAFE_DAYS}, GETDATE())"
    else:
        sales_date_filter = f"business_date >= CURRENT_DATE - INTERVAL '{SAFE_DAYS} day'"

    sales_sql = f"""
        SELECT
            sku_code AS 存货编码,
            sku_name AS 存货,
            size_name AS 尺码,
            SUM(quantity) AS 近{SAFE_DAYS}天销量
        FROM sales
        WHERE {sales_date_filter}
        GROUP BY sku_code, sku_name, size_name
    """

    hq_sql = """
        SELECT
            sku_code AS 存货编码,
            size_name AS 尺码,
            SUM(available_qty) AS 总部库存
        FROM hq_inventory
        GROUP BY sku_code, size_name
    """

    inventory_df = pd.read_sql_query(
        text(inventory_sql),
        engine,
        params={"warning_warehouse_code": WARNING_WAREHOUSE_CODE},
    )
    sales_df = read_sql_dataframe(sales_sql, engine)
    hq_df = read_sql_dataframe(hq_sql, engine)

    return build_standard_data_from_frames(inventory_df, sales_df, hq_df)


def build_standard_data_from_frames(
    inventory_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    hq_df: pd.DataFrame,
) -> pd.DataFrame:
    for df in [inventory_df, sales_df, hq_df]:
        df.columns = df.columns.astype(str).str.strip()

    inventory_df["存货编码"] = inventory_df["存货编码"].apply(clean_code)
    inventory_df["尺码"] = inventory_df["尺码"].apply(clean_size)
    if WARNING_WAREHOUSE_CODE and "仓库编码" in inventory_df.columns:
        inventory_df = inventory_df[
            inventory_df["仓库编码"].astype(str).str.strip() == WARNING_WAREHOUSE_CODE
        ].copy()
    inventory_df["当前现存量"] = pd.to_numeric(inventory_df["当前现存量"], errors="coerce").fillna(0)
    inventory_df["当前可用量"] = pd.to_numeric(inventory_df["当前可用量"], errors="coerce").fillna(0)

    sales_df["存货编码"] = sales_df["存货编码"].apply(clean_code)
    sales_df["尺码"] = sales_df["尺码"].apply(clean_size)
    sales_df["近7天销量"] = pd.to_numeric(sales_df[f"近{SAFE_DAYS}天销量"], errors="coerce").fillna(0)
    sales_df["日均销量"] = sales_df["近7天销量"] / SAFE_DAYS

    hq_df["存货编码"] = hq_df["存货编码"].apply(clean_code)
    hq_df["尺码"] = hq_df["尺码"].apply(clean_size)
    hq_df["总部库存"] = pd.to_numeric(hq_df["总部库存"], errors="coerce").fillna(0)

    inventory_group_df = (
        inventory_df
        .groupby(["存货编码", "尺码"], as_index=False)
        .agg({
            "当前现存量": "sum",
            "当前可用量": "sum",
            "仓库编码": "first",
            "仓库": "first",
            "存货": "first",
        })
    )

    standard_df = sales_df.merge(
        inventory_group_df,
        on=["存货编码", "尺码"],
        how="left",
        suffixes=("", "_库存"),
    )

    if "存货_库存" in standard_df.columns:
        standard_df["存货"] = standard_df["存货"].fillna(standard_df["存货_库存"])
        standard_df = standard_df.drop(columns=["存货_库存"])

    hq_group_df = (
        hq_df
        .groupby(["存货编码", "尺码"], as_index=False)["总部库存"]
        .sum()
    )

    standard_df = standard_df.merge(hq_group_df, on=["存货编码", "尺码"], how="left")

    standard_df["仓库编码"] = standard_df["仓库编码"].fillna("")
    standard_df["仓库"] = standard_df["仓库"].fillna("")
    standard_df["当前现存量"] = standard_df["当前现存量"].fillna(0)
    standard_df["当前可用量"] = standard_df["当前可用量"].fillna(0)
    standard_df["总部库存"] = standard_df["总部库存"].fillna(0)

    return ensure_standard_columns(standard_df)
