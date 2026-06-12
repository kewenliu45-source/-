# 系统架构说明

## 项目目录树

```
inventory-warning-system/
├── app/                          # 应用主目录
│   ├── __init__.py               # 包初始化
│   ├── main.py                   # FastAPI 应用入口
│   ├── config.py                 # 配置管理
│   ├── routers/                  # API 路由层
│   │   ├── page_router.py        # 页面路由
│   │   ├── upload_router.py      # 数据上传和分析路由
│   │   └── tplus_oauth_router.py # T+ OAuth 授权路由
│   ├── services/                 # 业务逻辑层
│   │   └── warning_service.py    # 预警计算引擎
│   ├── data_sources/             # 数据源适配层
│   │   ├── base.py               # 数据源基类和标准字段定义
│   │   ├── excel_source.py       # Excel 数据处理
│   │   ├── database_source.py    # 数据库数据处理
│   │   └── tplus_openapi_source.py # T+ OpenAPI 数据处理
│   ├── notifications/            # 通知服务层
│   │   └── wechat.py             # 企业微信通知
│   ├── templates/                # Jinja2 HTML 模板
│   │   ├── index.html            # 首页（上传页面）
│   │   ├── result.html           # 分析结果页面
│   │   ├── error.html            # 错误页面
│   │   └── oauth_success.html    # OAuth 授权成功页面
│   └── static/                   # 静态资源
├── tests/                        # 单元测试
├── uploads/                      # 上传文件临时目录
├── outputs/                      # 输出文件目录
├── docs/                         # 文档目录
├── scripts/                      # 脚本工具
├── requirements.txt              # Python 依赖
├── .env.example                  # 环境变量示例
└── .gitignore                    # Git 忽略规则
```

## 目录职责说明

### app/
应用核心目录，包含所有业务代码。

### app/routers/ - API 路由层
**职责**：处理 HTTP 请求，调用业务逻辑，返回响应

| 文件 | 职责 |
|------|------|
| `page_router.py` | 页面路由，返回 HTML 页面 |
| `upload_router.py` | 数据上传、数据库分析、结果展示、Excel 导出 |
| `tplus_oauth_router.py` | T+ OAuth 授权回调、消息接收 |

### app/services/ - 业务逻辑层
**职责**：实现核心业务规则，与数据源和展示层解耦

| 文件 | 职责 |
|------|------|
| `warning_service.py` | 库存预警计算引擎，生成预警状态和调货建议 |

### app/data_sources/ - 数据源适配层
**职责**：对接不同数据源，将原始数据转换为标准格式

| 文件 | 职责 |
|------|------|
| `base.py` | 定义标准数据列、校验函数、三表合并逻辑（以销售为主） |
| `excel_source.py` | 解析 Excel 三表（自动检测表头），合并为标准数据 |
| `database_source.py` | 数据库连接和 SQL 查询，分发到 mock/tplus/SQL 模式 |
| `tplus_openapi_source.py` | T+ OpenAPI 客户端，获取库存和销售数据（以销售为主匹配库存） |

### app/notifications/ - 通知服务层
**职责**：向外部系统发送通知消息

| 文件 | 职责 |
|------|------|
| `wechat.py` | 企业微信机器人消息推送 |

### app/templates/ - 前端模板
**职责**：HTML 页面渲染

| 文件 | 职责 |
|------|------|
| `index.html` | 首页，数据上传表单 |
| `result.html` | 分析结果展示，预警明细和调货建议 |
| `error.html` | 错误信息展示 |
| `oauth_success.html` | OAuth 授权成功提示 |

## 核心文件职责

### app/main.py
**职责**：FastAPI 应用初始化和路由注册

**核心功能**：
- 创建 FastAPI 实例
- 挂载静态文件目录
- 注册路由（page_router, upload_router, tplus_oauth_router）

**代码位置**：`app/main.py:1-22`

---

### app/config.py
**职责**：集中管理所有配置项

**核心配置**：
- 目录配置：`UPLOAD_DIR`, `OUTPUT_DIR`
- 业务配置：`SAFE_DAYS`, `WARNING_WAREHOUSE_CODE`
- 数据源配置：`DATA_SOURCE`, `DB_TYPE`
- 数据库配置：`DB_HOST`, `DB_PORT`, `DB_NAME` 等
- T+ API 配置：`TPLUS_API_BASE_URL`, `TPLUS_APP_KEY` 等
- 企业微信配置：`WECHAT_WEBHOOK`

**代码位置**：`app/config.py:1-92`

---

### app/services/warning_service.py
**职责**：库存预警核心计算引擎

**核心函数**：
- `analyze_standard_data(df)` - 主分析函数

**计算逻辑**：
1. 可售天数 = 当前可用量 / 日均销量
2. 目标库存 = 日均销量 × 7
3. 建议调货量 = max(0, 目标库存 - 当前可用量)
4. 总部可调数量 = min(总部库存, 建议调货量)
5. 预警状态：红色（可用量≤0）、黄色（可售天数<7）、正常
6. 调货建议文本生成

**代码位置**：`app/services/warning_service.py:1-105`

---

### app/routers/upload_router.py
**职责**：数据上传、分析入口和 Excel 导出

**核心函数**：
- `upload_files()` - Excel 文件上传处理
- `analyze_from_database()` - 数据库分析处理（支持可选的总部库存表上传）
- `render_analysis_result()` - 统一结果渲染
- `build_result_context()` - 构建模板上下文
- `export_sales_table()` - 导出近7天销售表（GET /export/sales）
- `export_inventory_table()` - 导出库存表（GET /export/inventory）
- `get_database_data_source_name()` - 获取数据源显示名称
- `get_user_facing_error()` - 错误信息转换

**代码位置**：`app/routers/upload_router.py:1-423`

---

### app/data_sources/base.py
**职责**：定义数据标准层和三表合并逻辑

**核心内容**：
- `STANDARD_COLUMNS` - 标准字段列表
- `ensure_standard_columns(df)` - 校验和规范化
- `build_standard_data_from_frames()` - 三表合并（以销售为主，LEFT JOIN 库存）
- `_ensure_clean_code_size()` - 编码和尺码清洗

**标准字段**：
- 存货编码、存货、尺码
- 近7天销量、日均销量
- 仓库编码、仓库
- 当前现存量、当前可用量
- 总部库存

**合并逻辑**：
1. 销售数据作为主体
2. 按存货编码+尺码 LEFT JOIN 库存数据
3. 按存货编码+尺码 LEFT JOIN 总部库存数据
4. 筛选近7天销量 > 0 的记录
5. 按 WARNING_WAREHOUSE_CODE 筛选仓库

**代码位置**：`app/data_sources/base.py:1-159`

---

### app/data_sources/excel_source.py
**职责**：Excel 数据解析和标准化

**核心函数**：
- `build_sales_standard_df()` - 销售表解析（自动检测表头，仓库编码格式统一）
- `build_inventory_standard_df()` - 库存表解析（自动检测表头）
- `build_hq_standard_df()` - 总部库存表解析（二维转一维，存货编码取后11位）
- `build_standard_data()` - 三表合并（调用 base.py 的 `build_standard_data_from_frames`）

**数据清洗**：
- `clean_columns()` - 列名清洗
- `clean_code()` - 编码清洗（处理浮点数）
- `clean_size()` - 尺码清洗

**特殊处理**：
- 自动检测表头：扫描前10行查找包含"存货编码"的行
- 仓库编码统一：浮点数 → 整数 → 三位补零字符串（如 6.0 → "006"）
- 总部编码适配：取后11位与销售表/库存表匹配

**代码位置**：`app/data_sources/excel_source.py:1-264`

---

### app/data_sources/database_source.py
**职责**：数据库数据查询和标准化，分发到不同数据源模式

**核心函数**：
- `build_database_url()` - 构建数据库连接 URL
- `build_standard_data_from_database()` - 主入口函数（分发到 mock/tplus/SQL）
- `build_mock_standard_data()` - 模拟数据生成
- `read_sql_dataframe()` - SQL 查询封装

**支持数据库**：
- MySQL、PostgreSQL、SQL Server、Oracle
- Mock 模式（本地测试）
- T+ OpenAPI 模式（通过 tplus_openapi_source.py）

**合并逻辑**：委托给 `base.py` 的 `build_standard_data_from_frames()`

**代码位置**：`app/data_sources/database_source.py:1-169`

---

### app/data_sources/tplus_openapi_source.py
**职责**：畅捷通 T+ OpenAPI 对接

**核心类**：`TPlusOpenAPIClient`

**核心方法**：
- `get_access_token()` - 获取访问令牌（含缓存和自动刷新）
- `query_inventory()` - 查询存货档案
- `query_current_stock()` - 查询现存量
- `query_recent_sale_delivery_sales()` - 查询近期销售（含缓存和并发查询）
- `find_sale_delivery_list()` - 查询销售出库单列表
- `get_sale_delivery_detail()` - 获取销售出库单详情

**核心函数**：
- `build_standard_data_from_tplus_openapi()` - 主入口函数（以销售为主，LEFT JOIN 库存）

**合并逻辑**：
1. 销售数据作为主体
2. 按存货编码+尺码 LEFT JOIN 现存量数据
3. 按存货编码 LEFT JOIN 存货档案（补充存货名称）
4. 总部库存默认为 0

**代码位置**：`app/data_sources/tplus_openapi_source.py:1-1317`

---

### app/routers/tplus_oauth_router.py
**职责**：T+ OAuth 授权和消息回调

**核心函数**：
- `tplus_message_callback()` - 消息回调处理
- `tplus_oauth_callback()` - OAuth 授权回调
- `decrypt_chanjet_message()` - 消息解密
- `save_chanjet_certificate()` - 保存证书

**代码位置**：`app/routers/tplus_oauth_router.py:1-146`

---

### app/notifications/wechat.py
**职责**：企业微信消息推送

**核心函数**：
- `send_wechat_message()` - 发送文本消息
- `build_warning_message()` - 构建预警消息
- `build_daily_summary_message()` - 构建每日汇总消息

**代码位置**：`app/notifications/wechat.py:1-66`

## 核心类职责

### TPlusOpenAPIClient
**所在文件**：`app/data_sources/tplus_openapi_source.py:63-678`

**职责**：封装 T+ OpenAPI 的所有交互

**主要方法**：

| 方法 | 职责 |
|------|------|
| `__init__()` | 初始化配置校验和 Session |
| `get_access_token()` | 获取/刷新访问令牌 |
| `exchange_code_for_token()` | OAuth 授权码换 Token |
| `refresh_access_token()` | 刷新访问令牌 |
| `generate_self_built_token()` | 自建应用获取 Token |
| `query_inventory()` | 查询存货档案 |
| `query_current_stock()` | 查询现存量 |
| `query_recent_sale_delivery_sales()` | 查询近期销售汇总 |
| `find_sale_delivery_list()` | 查询销售出库单列表 |
| `get_sale_delivery_detail()` | 获取销售出库单详情 |
| `save_app_ticket()` | 保存 appTicket |
| `_request()` | 通用 API 请求（含重试） |
| `_request_auth_token()` | Token 接口请求 |
| `_read_cached_token()` | 读取缓存 Token |
| `_write_cached_token()` | 写入缓存 Token |

## 核心函数职责

### 预警计算函数

#### analyze_standard_data(df)
**所在文件**：`app/services/warning_service.py:5-105`

**职责**：主分析函数，输入标准数据，输出含预警状态的结果

**输入**：标准 DataFrame（含 存货编码、日均销量、当前可用量、总部库存 等）

**输出**：增加 可售天数、目标库存、建议调货量、总部可调数量、预警状态、调货建议 列的 DataFrame

---

### 数据处理函数

#### build_standard_data(inventory_file, sales_file, hq_file)
**所在文件**：`app/data_sources/excel_source.py:242-264`

**职责**：Excel 三表合并为标准数据（调用 base.py 的合并函数，already_cleaned=True）

#### build_standard_data_from_database()
**所在文件**：`app/data_sources/database_source.py:99-168`

**职责**：从数据库获取标准数据（分发到 mock/tplus/SQL 模式）

#### build_standard_data_from_tplus_openapi()
**所在文件**：`app/data_sources/tplus_openapi_source.py:680-736`

**职责**：从 T+ API 获取标准数据（以销售为主，LEFT JOIN 库存）

#### build_standard_data_from_frames(inventory_df, sales_df, hq_df, already_cleaned)
**所在文件**：`app/data_sources/base.py:57-158`

**职责**：将库存、销售、总部库存三个 DataFrame 合并为标准数据（以销售为主）

---

### 数据校验函数

#### ensure_standard_columns(df)
**所在文件**：`app/data_sources/base.py:18-23`

**职责**：校验 DataFrame 是否包含所有标准列，缺失则抛异常

---

### 数据清洗函数

#### clean_code(value)
**所在文件**：`app/data_sources/excel_source.py:19-30`

**职责**：清洗编码字段（处理 Excel 浮点数问题）

#### clean_size(value)
**所在文件**：`app/data_sources/excel_source.py:33-41`

**职责**：清洗尺码字段（去除"码"字）

#### clean_columns(df)
**所在文件**：`app/data_sources/excel_source.py:8-16`

**职责**：清洗列名（去空格、换行符）

---

### 结果构建函数

#### build_result_context(result_df, data_source_name)
**所在文件**：`app/routers/upload_router.py:38-86`

**职责**：将分析结果转换为模板渲染所需的上下文数据

#### render_analysis_result(request, standard_df, data_source_name)
**所在文件**：`app/routers/upload_router.py:99-111`

**职责**：统一的结果渲染流程

---

### 错误处理函数

#### get_user_facing_error(exc)
**所在文件**：`app/routers/upload_router.py:19-35`

**职责**：将技术异常转换为用户友好的错误信息

---

### 通知函数

#### send_wechat_message(content)
**所在文件**：`app/notifications/wechat.py:5-24`

**职责**：发送企业微信消息

#### build_warning_message(red_list, yellow_list)
**所在文件**：`app/notifications/wechat.py:27-55`

**职责**：构建预警通知消息文本
