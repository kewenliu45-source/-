# AI 代码阅读指南

本指南帮助 AI（Codex / Claude Code / Cursor）快速理解项目，减少重复遍历仓库的 Token 消耗。

## 项目概览

**项目名称**：智能库存预警系统

**技术栈**：FastAPI + Pandas + Jinja2

**核心功能**：分析库存数据，识别缺货风险，生成调货建议

## 快速入门

### 必读文件（按顺序）

1. `PROJECT_GUIDE.md` - 项目总体说明
2. `BUSINESS_LOGIC.md` - 业务规则详解
3. `ARCHITECTURE.md` - 系统架构
4. `DATA_FLOW.md` - 数据流说明
5. `FILE_INDEX.md` - 文件索引
6. `FUNCTION_INDEX.md` - 函数索引
7. `API_FLOW.md` - API 流程
8. `KNOWN_ISSUES.md` - 已知问题
9. `CODEBASE_MAP.md` - 代码库地图

### 核心代码文件（按重要性）

1. `app/services/warning_service.py` - 预警计算引擎
2. `app/data_sources/base.py` - 标准数据层定义和三表合并逻辑
3. `app/data_sources/excel_source.py` - Excel 数据处理（自动检测表头）
4. `app/routers/upload_router.py` - 路由、业务流程和 Excel 导出
5. `app/data_sources/database_source.py` - 数据库数据处理
6. `app/data_sources/tplus_openapi_source.py` - T+ API 对接（以销售为主）
7. `app/config.py` - 配置管理

## 场景指南

### 如果要修改预警逻辑

**优先阅读**：
1. `app/services/warning_service.py` - 预警计算核心
2. `BUSINESS_LOGIC.md` - 预警规则说明

**关键函数**：
- `analyze_standard_data()` - 主分析函数
- `get_warning_status()` - 预警状态判断
- `get_transfer_advice()` - 调货建议生成

**关键配置**：
- `SAFE_DAYS` - 安全库存天数（默认 7）
- `WARNING_WAREHOUSE_CODE` - 预警仓库编码（默认 006)

**注意事项**：
- 预警规则硬编码在 `get_warning_status()` 中
- 可售天数计算依赖日均销量，注意除零处理
- 排序规则在 `analyze_standard_data()` 末尾

---

### 如果要修改数据库逻辑

**优先阅读**：
1. `app/data_sources/database_source.py` - 数据库数据处理
2. `app/config.py` - 数据库配置
3. `DATA_FLOW.md` - 数据流说明

**关键函数**：
- `build_database_url()` - 构建连接字符串
- `build_standard_data_from_database()` - 主入口函数（分发到 mock/tplus/SQL）
- `build_standard_data_from_frames()` - DataFrame 合并（在 base.py 中）

**关键配置**：
- `DB_TYPE` - 数据库类型（mysql/postgresql/sqlserver/oracle/mock）
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` - 连接信息
- `DATABASE_URL` - 完整连接串（优先级高于分项配置)

**注意事项**：
- SQL 查询是模板，到客户现场需要调整表名和字段名
- 不同数据库的日期函数不同（如 SQL Server 用 DATEADD）
- Mock 模式用于本地测试，数据硬编码在 `build_mock_standard_data()`

---

### 如果要修改企业微信

**优先阅读**：
1. `app/notifications/wechat.py` - 企业微信通知
2. `app/config.py` - Webhook 配置

**关键函数**：
- `send_wechat_message()` - 发送消息
- `build_warning_message()` - 构建预警消息
- `build_daily_summary_message()` - 构建每日汇总

**关键配置**：
- `WECHAT_WEBHOOK` - 企业微信机器人 Webhook

**注意事项**：
- 当前 wechat.py 未被调用，需要在 result.html 或定时任务中集成
- 消息格式为纯文本，不支持 Markdown

---

### 如果要修改前端

**优先阅读**：
1. `app/templates/index.html` - 首页
2. `app/templates/result.html` - 结果页
3. `app/routers/page_router.py` - 页面路由
4. `app/routers/upload_router.py` - 数据渲染

**关键模板变量**（result.html）：
- `summary` - 统计汇总（total, red_count, yellow_count, normal_count, suggest_total）
- `preview_data` - 预警明细数据
- `transfer_records` - 调货建议数据

**注意事项**：
- 使用 Jinja2 模板引擎
- 静态资源在 `app/static/` 目录
- 筛选功能是纯前端，但 JavaScript 未实现
- "发送每日汇总"按钮对应的 API 未实现
- "下载Excel"按钮对应的 API 未实现（分析结果下载）
- 已实现的导出功能：`/export/sales` 和 `/export/inventory`

---

### 如果要对接新的数据源

**优先阅读**：
1. `app/data_sources/base.py` - 标准数据层定义
2. `app/data_sources/database_source.py` - 参考实现
3. `ARCHITECTURE.md` - 数据源适配层说明

**标准字段**：
```python
STANDARD_COLUMNS = [
    "存货编码", "存货", "尺码",
    "近7天销量", "日均销量",
    "仓库编码", "仓库",
    "当前现存量", "当前可用量",
    "总部库存",
]
```

**实现步骤**：
1. 创建 `app/data_sources/xxx_source.py`
2. 实现 `build_standard_data_from_xxx()` 函数
3. 返回 `ensure_standard_columns(df)` 校验后的 DataFrame
4. 在 `upload_router.py` 中添加路由
5. 在 `database_source.py` 中添加 DB_TYPE 分支（如适用）
6. 考虑添加导出功能（参考 `/export/sales` 和 `/export/inventory`）

---

### 如果要修改 T+ OpenAPI 对接

**优先阅读**：
1. `app/data_sources/tplus_openapi_source.py` - T+ API 客户端
2. `app/routers/tplus_oauth_router.py` - OAuth 授权
3. `app/config.py` - T+ 配置

**关键类**：
- `TPlusOpenAPIClient` - T+ API 客户端

**关键方法**：
- `get_access_token()` - 获取/刷新 Token
- `query_inventory()` - 查询存货档案
- `query_current_stock()` - 查询现存量
- `query_recent_sale_delivery_sales()` - 查询近期销售

**关键配置**：
- `TPLUS_API_BASE_URL` - API 地址
- `TPLUS_APP_KEY`, `TPLUS_APP_SECRET` - 应用凭证
- `TPLUS_ORG_ID` - 组织 ID
- `TPLUS_AUTH_MODE` - 认证模式（oauth/self_built)

**注意事项**：
- Token 缓存在 `outputs/tplus_token_cache.json`
- 销售数据缓存在 `outputs/tplus_recent_sales_cache.json`（TTL 1800秒）
- 总部库存当前硬编码为 0，需要扩展
- 并发查询使用 ThreadPoolExecutor
- 以销售为主的数据合并逻辑（sales LEFT JOIN stock）

## 代码导航技巧

### 查找函数定义
- 预警相关：`app/services/warning_service.py`
- 数据处理：`app/data_sources/*.py`
- 路由处理：`app/routers/*.py`
- 通知相关：`app/notifications/*.py`

### 查找配置项
- 所有配置：`app/config.py`
- 环境变量：`.env` 或 `.env.example`

### 查找模板
- HTML 模板：`app/templates/*.html`
- 静态资源：`app/static/`

### 查找测试
- 单元测试：`tests/*.py`

## 常见修改场景

### 场景 1: 修改安全库存天数

**修改位置**：
- `app/config.py:29` - `SAFE_DAYS = 7`
- 或 `.env` 文件中的 `SAFE_DAYS` 变量

**影响范围**：
- 目标库存计算：`warning_service.py:23`
- 日均销量计算：`excel_source.py:79`（硬编码 7，需同步修改)

---

### 场景 2: 修改预警阈值

**修改位置**：
- `app/services/warning_service.py:43-51` - `get_warning_status()`

**当前阈值**：
- 红色预警：当前可用量 ≤ 0
- 黄色预警：可售天数 < 7 天

---

### 场景 3: 添加新的预警级别

**修改位置**：
1. `app/services/warning_service.py:43-51` - 添加新条件
2. `app/services/warning_service.py:87-91` - 更新排序映射
3. `app/templates/result.html` - 添加新样式

---

### 场景 4: 修改调货建议逻辑

**修改位置**：
- `app/services/warning_service.py:59-80` - `get_transfer_advice()`

---

### 场景 5: 修改 Excel 表头行号

**修改位置**：
- `app/data_sources/excel_source.py:50-58` - sales_file 自动检测逻辑
- `app/data_sources/excel_source.py:121-129` - inventory_file 自动检测逻辑
- `app/data_sources/excel_source.py:180` - hq_file header=1（固定）

**当前实现**：自动检测表头位置，扫描前10行查找包含"存货编码"的行

---

### 场景 6: 修改仓库筛选逻辑

**修改位置**：
- `app/config.py:87` - `WARNING_WAREHOUSE_CODE`
- `app/data_sources/excel_source.py:85-89` - Excel 销售表筛选（含格式统一）
- `app/data_sources/base.py:102-105` - 通用库存筛选
- `app/data_sources/tplus_openapi_source.py:841-842` - T+ 现存量筛选
- `app/data_sources/tplus_openapi_source.py:959-962` - T+ 销售筛选

---

### 场景 7: 添加新的数据库类型支持

**修改位置**：
- `app/data_sources/database_source.py:21-49` - `build_database_url()`
- `app/data_sources/database_source.py:129-132` - 日期函数适配

---

### 场景 8: 修改导出功能

**修改位置**：
- `app/routers/upload_router.py:182-328` - `export_sales_table()` 导出销售表
- `app/routers/upload_router.py:331-422` - `export_inventory_table()` 导出库存表

**关键配置**：
- `WARNING_WAREHOUSE_CODE` - 筛选仓库
- `SAFE_DAYS` - 销售数据天数

**注意事项**：
- 导出功能支持三种模式：mock、tplus、数据库
- 列顺序与原始 Excel 一致
- 使用 StreamingResponse 返回文件

## 代码约定

### 命名规范
- 函数名：snake_case
- 类名：PascalCase
- 常量：UPPER_SNAKE_CASE
- 文件名：snake_case.py

### 注释风格
- 中文注释
- 关键逻辑有注释说明
- 函数有简要 docstring（部分)

### 错误处理
- 使用 try/except 捕获异常
- 用户友好的错误信息通过 `get_user_facing_error()` 转换
- 技术异常记录到日志

### 数据处理
- 使用 Pandas DataFrame 作为核心数据结构
- 所有数据源最终转换为标准 DataFrame
- 使用 `ensure_standard_columns()` 校验

## 废弃/未使用代码

### 已废弃
- `app/services/excel_service.py` - 已删除
- `app/services/upload_router.py` - 已删除
- `app/_init_.py` - 已删除（改为 `app/__init__.py`)

### 未使用
- `app/notifications/wechat.py` - 已实现但未调用
- `test_inventory_query()` - 调试函数
- `test_find_sale_delivery_list()` - 调试函数

### 未实现
- `POST /send-daily-summary` - 模板中引用但未实现
- `GET /download/{filename}` - 模板中引用但未实现（分析结果下载）

### 已实现的导出功能
- `GET /export/sales` - 导出近7天销售表
- `GET /export/inventory` - 导出库存表

## 依赖关系

### 外部依赖
- fastapi, uvicorn - Web 框架
- pandas, openpyxl - 数据处理
- python-multipart, jinja2 - 文件上传和模板
- requests - HTTP 请求
- sqlalchemy, pyodbc - 数据库
- python-dotenv - 环境变量
- pycryptodome - 加解密

### 内部依赖
```
upload_router.py
  ├── excel_source.py
  │     └── base.py (build_standard_data_from_frames)
  ├── database_source.py
  │     ├── base.py (build_standard_data_from_frames)
  │     ├── excel_source.py (clean_code, clean_size, build_hq_standard_df)
  │     └── tplus_openapi_source.py (条件)
  └── warning_service.py

tplus_oauth_router.py
  └── tplus_openapi_source.py
```

## 测试

### 测试文件
- `tests/test_warning_service.py` - 预警服务测试
- `tests/test_upload_router_errors.py` - 错误处理测试
- `tests/test_tplus_message_crypto.py` - 消息加解密测试
- `tests/test_tplus_request_errors.py` - 请求错误测试
- `tests/test_tplus_sales_warehouse.py` - 销售仓库测试

### 运行测试
```bash
python -m pytest tests/
```

## 部署

### 环境变量
复制 `.env.example` 为 `.env`，填写实际配置。

### 启动命令
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 依赖安装
```bash
pip install -r requirements.txt
```

## 注意事项

1. **不要修改 base.py 的 STANDARD_COLUMNS**，除非所有数据源同步更新
2. **不要硬编码敏感信息**，使用 .env 文件
3. **Excel 表头**现在自动检测，但仍需确保前10行包含"存货编码"
4. **T+ Token 有效期**需要关注，避免过期导致查询失败
5. **仓库筛选逻辑**已统一，但需注意 Excel 中仓库编码可能为浮点数
6. **总部库存**在 T+ 模式下默认为 0，需要扩展实现
7. **以销售为主的数据合并**：所有数据源都使用 sales LEFT JOIN inventory
8. **总部库存编码**：取后11位与销售表/库存表匹配
9. **数据类型安全**：使用 `pd.to_numeric(errors="coerce").fillna(0)` 和 `int(float(...))` + try/except
