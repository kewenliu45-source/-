import pyodbc

from app.config import (
    DB_HOST,
    DB_NAME,
    DB_ODBC_DRIVER,
    DB_PASSWORD,
    DB_PORT,
    DB_USER,
)


def main():
    connection_string = (
        f"DRIVER={{{DB_ODBC_DRIVER}}};"
        f"SERVER={DB_HOST},{DB_PORT};"
        f"DATABASE={DB_NAME};"
        f"UID={DB_USER};"
        f"PWD={DB_PASSWORD};"
        "Connection Timeout=5;"
    )

    with pyodbc.connect(connection_string) as connection:
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        print("数据库连接成功，测试查询结果：", cursor.fetchone()[0])


if __name__ == "__main__":
    main()
