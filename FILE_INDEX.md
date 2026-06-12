# 文件索引

## 核心文件

### app/main.py
**作用**：FastAPI 应用入口，初始化应用和注册路由

**重要等级**：★★★★★

**核心函数**：
- `chanjet_check_file()` - T+ 畅捷通校验文件接口

**被哪些模块调用**：
- uvicorn 启动时加载

---

### app/config.py
**作用**：集中管理所有配置项，从环境变量和 .env 文件读取

**重要等级**：★★★★★

**核心变量**：
- `BASE_DIR` - 项目根目录
- `UPLOAD_DIR` - 上传目录
- `OUTPUT_DIR` - 输出目录
- `SAFE_DAYS` - 安全库存天数（默认7）
- `DATA_SOURCE` - 数据源类型
- `DB_TYPE` - 数据库类型
- `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` - 数据库连接
- `TPLUS_API_BASE_URL` - T+ API 地址
- `TPLUS_APP_KEY`, `TPLUS_APP_SECRET` - T+ 应用凭证
- `TPLUS_ORG_ID` - T+ 组织 ID
- `WARNING_WAREHOUSE_CODE` - 预警仓库编码（默认006）
- `WECHAT_WEBHOOK` - 企业微信 Webhook

**被哪些模块调用**：
- 所有需要配置的模块

---

### app/services/warning_service.py
**作用**：库存预警核心计算引擎

**重要等级**：★★★★★

**核心函数**：
- `analyze_standard_data(df)` - 主分析函数

**被哪些模块调用**：
- `app/routers/upload_router.py:render_analysis_result()`

---

### app/routers/upload_router.py
**作用**：数据上传、分析入口和 Excel 导出

**重要等级**：★★★★★

**核心函数**：
- `upload_files()` - Excel 文件上传处理
- `analyze_from_database()` - 数据库分析处理（支持可选的总部库存表上传）
- `render_analysis_result()` - 统一结果渲染
- `build_result_context()` - 构建模板上下文
- `export_sales_table()` - 导出近7天销售表（GET /export/sales）
- `export_inventory_table()` - 导出库存表（GET /export/inventory）
- `get_database_data_source_name()` - 获取数据源名称
- `get_user_facing_error()` - 错误信息转换

**被哪些模块调用**：
- `app/main.py` - 路由注册

---

### app/routers/page_router.py
**作用**：页面路由，返回首页 HTML

**重要等级**：★★★☆☆

**核心函数**：
- `index()` - 首页路由

**被哪些模块调用**：
- `app/main.py` - 路由注册

---

### app/routers/tplus_oauth_router.py
**作用**：T+ OAuth 授权和消息回调处理

**重要等级**：★★★★☆

**核心函数**：
- `tplus_message_callback()` - 消息回调处理
- `tplus_oauth_callback()` - OAuth 授权回调
- `decrypt_chanjet_message()` - 消息解密
- `save_chanjet_certificate()` - 保存证书

**被哪些模块调用**：
- `app/main.py` - 路由注册

---

### app/data_sources/base.py
**作用**：定义数据标准层，包含标准字段列表、校验函数和三表合并逻辑

**重要等级**：★★★★★

**核心内容**：
- `STANDARD_COLUMNS` - 标准字段列表
- `ensure_standard_columns(df)` - 校验和规范化
- `build_standard_data_from_frames()` - 三表合并（以销售为主，LEFT JOIN 库存）
- `_ensure_clean_code_size()` - 编码和尺码清洗

**被哪些模块调用**：
- `app/data_sources/excel_source.py`
- `app/data_sources/database_source.py`
- `app/data_sources/tplus_openapi_source.py`

---

### app/data_sources/excel_source.py
**作用**：Excel 数据解析和标准化，处理三表合并

**重要等级**：★★★★★

**核心函数**：
- `build_sales_standard_df(sales_file)` - 销售表解析（自动检测表头，仓库编码格式统一）
- `build_inventory_standard_df(inventory_file)` - 库存表解析（自动检测表头）
- `build_hq_standard_df(hq_file)` - 总部库存表解析（存货编码取后11位）
- `build_standard_data(inventory_file, sales_file, hq_file)` - 三表合并
- `clean_columns(df)` - 列名清洗
- `clean_code(value)` - 编码清洗
- `clean_size(value)` - 尺码清洗

**被哪些模块调用**：
- `app/routers/upload_router.py:upload_files()`
- `app/data_sources/database_source.py` - 引用 clean_code, clean_size

---

### app/data_sources/database_source.py
**作用**：数据库数据查询和标准化，分发到不同数据源模式

**重要等级**：★★★★☆

**核心函数**：
- `build_database_url()` - 构建数据库连接 URL
- `build_standard_data_from_database()` - 主入口函数（分发到 mock/tplus/SQL）
- `build_mock_standard_data()` - 模拟数据生成
- `read_sql_dataframe(sql, engine)` - SQL 查询封装

**被哪些模块调用**：
- `app/routers/upload_router.py:analyze_from_database()`

---

### app/data_sources/tplus_openapi_source.py
**作用**：畅捷通 T+ OpenAPI 客户端，获取库存和销售数据

**重要等级**：★★★★★

**核心类**：
- `TPlusOpenAPIClient` - T+ API 客户端类

**核心函数**：
- `build_standard_data_from_tplus_openapi()` - 主入口函数
- `test_inventory_query()` - 存货查询测试
- `test_find_sale_delivery_list()` - 销售单列表测试
- `_build_inventory_master_df(records)` - 存货档案 DataFrame 构建
- `_build_current_stock_df(records)` - 现存量 DataFrame 构建
- `_extract_sale_delivery_sales_rows()` - 销售单明细提取
- `_build_recent_sales_summary_df()` - 近期销售汇总

**被哪些模块调用**：
- `app/data_sources/database_source.py:build_standard_data_from_database()`
- `app/routers/tplus_oauth_router.py` - TPlusOpenAPIClient, _extract_app_ticket

---

### app/notifications/wechat.py
**作用**：企业微信机器人消息推送

**重要等级**：★★★☆☆

**核心函数**：
- `send_wechat_message(content)` - 发送文本消息
- `build_warning_message(red_list, yellow_list)` - 构建预警消息
- `build_daily_summary_message(summary)` - 构建每日汇总消息

**被哪些模块调用**：
- 暂无直接调用（预留接口）

## 模板文件

### app/templates/index.html
**作用**：首页，数据上传表单

**重要等级**：★★★★☆

**功能**：
- Excel 三表上传表单
- 数据库分析按钮
- 使用说明展示

**被哪些模块调用**：
- `app/routers/page_router.py:index()`

---

### app/templates/result.html
**作用**：分析结果展示页面

**重要等级**：★★★★★

**功能**：
- 统计卡片（总数、红色预警、黄色预警、正常、建议调货总量）
- 调货建议表格
- 预警明细表格
- 筛选功能（前端）

**被哪些模块调用**：
- `app/routers/upload_router.py:render_analysis_result()`

---

### app/templates/error.html
**作用**：错误信息展示页面

**重要等级**：★★★☆☆

**被哪些模块调用**：
- `app/routers/upload_router.py:upload_files()`
- `app/routers/upload_router.py:analyze_from_database()`

---

### app/templates/oauth_success.html
**作用**：OAuth 授权成功提示页面

**重要等级**：★★☆☆☆

**被哪些模块调用**：
- `app/routers/tplus_oauth_router.py:tplus_oauth_callback()`

## 测试文件

### tests/test_warning_service.py
**作用**：预警服务单元测试

**重要等级**：★★★☆☆

**测试内容**：
- 零销量时可售天数计算（不除零）

---

### tests/test_upload_router_errors.py
**作用**：上传路由错误处理测试

**重要等级**：★★★☆☆

**测试内容**：
- T+ 内部连接失败错误信息
- T+ 超时错误信息

---

### tests/test_tplus_message_crypto.py
**作用**：T+ 消息加解密测试

**重要等级**：★★☆☆☆

---

### tests/test_tplus_request_errors.py
**作用**：T+ 请求错误处理测试

**重要等级**：★★☆☆☆

---

### tests/test_tplus_sales_warehouse.py
**作用**：T+ 销售仓库筛选测试

**重要等级**：★★☆☆☆

## 配置文件

### requirements.txt
**作用**：Python 依赖包列表

**重要等级**：★★★★☆

**依赖包**：
- fastapi, uvicorn - Web 框架
- pandas, openpyxl - 数据处理
- python-multipart, jinja2 - 文件上传和模板
- requests - HTTP 请求
- sqlalchemy, pyodbc - 数据库
- python-dotenv - 环境变量
- pycryptodome - 加解密

---

### .env.example
**作用**：环境变量配置示例

**重要等级**：★★★★☆

---

### .gitignore
**作用**：Git 忽略规则

**重要等级**：★★☆☆☆

## 文档文件

### README.md
**作用**：项目简介和快速开始

**重要等级**：★★☆☆☆

---

### 项目代码和文件结构.txt
**作用**：早期项目结构说明

**重要等级**：★☆☆☆☆（可能已过时）

## 目录说明

### uploads/
**作用**：上传文件临时存储目录

**重要等级**：★★★☆☆

---

### outputs/
**作用**：输出文件和缓存存储目录

**重要等级**：★★★☆☆

**存储内容**：
- `tplus_token_cache.json` - T+ Token 缓存
- `tplus_app_ticket_cache.json` - T+ AppTicket 缓存
- `tplus_recent_sales_cache.json` - T+ 销售数据缓存

---

### docs/
**作用**：文档目录

**重要等级**：★★☆☆☆

---

### scripts/
**作用**：脚本工具目录

**重要等级**：★★☆☆☆

---

### app/static/
**作用**：静态资源目录（CSS、JS、图片）

**重要等级**：★★★☆☆
