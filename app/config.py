import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(os.path.join(BASE_DIR, ".env"))
else:
    env_file = os.path.join(BASE_DIR, ".env")
    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(BASE_DIR, "outputs")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

SAFE_DAYS = 7

# 数据源配置：excel / database
DATA_SOURCE = os.getenv("DATA_SOURCE", "excel").strip().lower()

# 数据库配置。未连接客户 VPN 时可使用 DB_TYPE=mock 做本地流程测试。
DB_TYPE = os.getenv("DB_TYPE", "mock").strip().lower()
DB_HOST = os.getenv("DB_HOST", "").strip()
DB_PORT = os.getenv("DB_PORT", "").strip()
DB_NAME = os.getenv("DB_NAME", "").strip()
DB_USER = os.getenv("DB_USER", "").strip()
DB_PASSWORD = os.getenv("DB_PASSWORD", "").strip()
DB_ODBC_DRIVER = os.getenv("DB_ODBC_DRIVER", "SQL Server").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# 畅捷通 T+ OpenAPI 配置。
# appKey/appSecret 先使用占位符，正式部署时写入 .env。
TPLUS_API_BASE_URL = os.getenv("TPLUS_API_BASE_URL", "").strip().rstrip("/")
TPLUS_AUTH_BASE_URL = os.getenv("TPLUS_AUTH_BASE_URL", "https://openapi.chanjet.com").strip().rstrip("/")
TPLUS_AUTH_MODE = os.getenv("TPLUS_AUTH_MODE", "oauth").strip().lower()
TPLUS_APP_KEY = os.getenv("TPLUS_APP_KEY", "YOUR_APP_KEY").strip()
APP_SECRET = os.getenv("APP_SECRET", os.getenv("TPLUS_APP_SECRET", "YOUR_APP_SECRET")).strip()
TPLUS_APP_SECRET = APP_SECRET
CHANJET_MESSAGE_SECRET = os.getenv("CHANJET_MESSAGE_SECRET", "").strip()
TPLUS_REDIRECT_URI = os.getenv("TPLUS_REDIRECT_URI", "").strip()
TPLUS_CERTIFICATE = (
    os.getenv("TPLUS_CERTIFICATE", "").strip()
    or os.getenv("CHANJET_CERTIFICATE", "").strip()
)
TPLUS_APP_TICKET = os.getenv("TPLUS_APP_TICKET", "").strip()
TPLUS_ORG_ID = os.getenv("TPLUS_ORG_ID", "1240415177997138").strip()
TPLUS_TOKEN_CACHE_FILE = os.getenv(
    "TPLUS_TOKEN_CACHE_FILE",
    os.path.join(OUTPUT_DIR, "tplus_token_cache.json"),
).strip()
TPLUS_APP_TICKET_CACHE_FILE = os.getenv(
    "TPLUS_APP_TICKET_CACHE_FILE",
    os.path.join(OUTPUT_DIR, "tplus_app_ticket_cache.json"),
).strip()
TPLUS_RECENT_SALES_CACHE_FILE = os.getenv(
    "TPLUS_RECENT_SALES_CACHE_FILE",
    os.path.join(OUTPUT_DIR, "tplus_recent_sales_cache.json"),
).strip()
TPLUS_RECENT_SALES_CACHE_TTL_SECONDS = int(os.getenv("TPLUS_RECENT_SALES_CACHE_TTL_SECONDS", "1800"))
TPLUS_APP_TICKET_MAX_AGE_SECONDS = int(os.getenv("TPLUS_APP_TICKET_MAX_AGE_SECONDS", "1500"))
TPLUS_TOKEN_REFRESH_SKEW_SECONDS = int(os.getenv("TPLUS_TOKEN_REFRESH_SKEW_SECONDS", "43200"))
TPLUS_REQUEST_TIMEOUT = int(os.getenv("TPLUS_REQUEST_TIMEOUT", "20"))
TPLUS_RETRY_TIMES = int(os.getenv("TPLUS_RETRY_TIMES", "3"))
TPLUS_QUERY_PAGE_SIZE = int(os.getenv("TPLUS_QUERY_PAGE_SIZE", "200"))
TPLUS_INVENTORY_QUERY_ENDPOINT = os.getenv(
    "TPLUS_INVENTORY_QUERY_ENDPOINT",
    "/tplus/api/v2/inventory/Query",
).strip()
TPLUS_CURRENT_STOCK_QUERY_ENDPOINT = os.getenv(
    "TPLUS_CURRENT_STOCK_QUERY_ENDPOINT",
    "/tplus/api/v2/currentStock/Query",
).strip()
WARNING_WAREHOUSE_CODE = os.getenv("WARNING_WAREHOUSE_CODE", "006").strip()

# 企业微信机器人 Webhook
# 没有就先留空，不影响系统运行
WECHAT_WEBHOOK = ""
