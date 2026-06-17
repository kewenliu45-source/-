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
from app.data_sources.base import ensure_standard_columns, build_standard_data_from_frames
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
            "近90天销量": 300,
            "仓库编码": "WH001",
            "仓库": "本地仓",
            "当前现存量": 8,
            "当前可用量": 4,
            "总部库存": 60,
            "在途仓": "",
            "在途（未发货）": 0,
        },
        {
            "存货编码": "SKU002",
            "存货": "测试商品B",
            "尺码": "L",
            "近7天销量": 21,
            "日均销量": 3,
            "近90天销量": 180,
            "仓库编码": "WH001",
            "仓库": "本地仓",
            "当前现存量": 0,
            "当前可用量": 0,
            "总部库存": 18,
            "在途仓": "",
            "在途（未发货）": 0,
        },
        {
            "存货编码": "SKU003",
            "存货": "测试商品C",
            "尺码": "XL",
            "近7天销量": 14,
            "日均销量": 2,
            "近90天销量": 120,
            "仓库编码": "WH002",
            "仓库": "门店仓",
            "当前现存量": 30,
            "当前可用量": 26,
            "总部库存": 10,
            "在途仓": "",
            "在途（未发货）": 0,
        },
    ]

    return ensure_standard_columns(pd.DataFrame(data))


def read_sql_dataframe(sql: str, engine) -> pd.DataFrame:
    return pd.read_sql_query(sql, engine)


def build_standard_data_from_database(
    hq_df: pd.DataFrame | None = None,
    transit_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if DB_TYPE == "mock":
        return build_mock_standard_data()

    if DB_TYPE in {"tplus", "openapi", "chanjet"}:
        from app.data_sources.tplus_openapi_source import build_standard_data_from_tplus_openapi

        return build_standard_data_from_tplus_openapi(hq_df=hq_df, transit_df=transit_df)

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
            SUM(quantity) AS 近7天销量
        FROM sales
        WHERE {sales_date_filter}
          AND warehouse_code = :warning_warehouse_code
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
    sales_df = pd.read_sql_query(
        text(sales_sql),
        engine,
        params={"warning_warehouse_code": WARNING_WAREHOUSE_CODE},
    )
    hq_df = read_sql_dataframe(hq_sql, engine)

    return build_standard_data_from_frames(inventory_df, sales_df, hq_df)

