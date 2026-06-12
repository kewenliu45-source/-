# 函数索引

## 预警计算函数

### analyze_standard_data(df)
**所在文件**：`app/services/warning_service.py:5-105`

**作用**：主分析函数，输入标准数据，输出含预警状态和调货建议的结果

**输入**：
- `df`: DataFrame，必须包含标准字段（存货编码、日均销量、当前可用量、总部库存等）

**输出**：
- DataFrame，增加以下列：
  - 可售天数
  - 目标库存
  - 建议调货量
  - 总部可调数量
  - 预警状态（红色预警/黄色预警/正常）
  - 调货建议

**调用关系**：
- 调用方：`upload_router.py:render_analysis_result()`
- 调用：pandas, numpy 函数

---

### get_warning_status(row)
**所在文件**：`app/services/warning_service.py:43-51`

**作用**：根据当前可用量和可售天数判断预警状态

**输入**：
- `row`: Series，包含 当前可用量、可售天数

**输出**：
- 字符串："红色预警"/"黄色预警"/"正常"

**调用关系**：
- 调用方：`analyze_standard_data()` 内部 apply

---

### get_transfer_advice(row)
**所在文件**：`app/services/warning_service.py:59-83`

**作用**：生成调货建议文本（含安全类型转换）

**输入**：
- `row`: Series，包含 建议调货量、总部可调数量、预警状态

**输出**：
- 字符串：调货建议描述

**特殊处理**：
- 使用 `int(float(...))` 进行安全类型转换
- 使用 try/except 捕获 ValueError/TypeError

**调用关系**：
- 调用方：`analyze_standard_data()` 内部 apply

## 数据源函数

### build_standard_data(inventory_file, sales_file, hq_file)
**所在文件**：`app/data_sources/excel_source.py:242-264`

**作用**：Excel 三表合并为标准数据

**输入**：
- `inventory_file`: 库存表文件对象
- `sales_file`: 销售表文件对象
- `hq_file`: 总部库存表文件对象（可选）

**输出**：
- 标准 DataFrame

**调用关系**：
- 调用方：`upload_router.py:upload_files()`
- 调用：`build_sales_standard_df()`, `build_inventory_standard_df()`, `build_hq_standard_df()`, `base.py:build_standard_data_from_frames(already_cleaned=True)`

---

### build_sales_standard_df(sales_file)
**所在文件**：`app/data_sources/excel_source.py:47-113`

**作用**：解析销售表，计算近7天销量和日均销量

**输入**：
- `sales_file`: 销售表文件对象

**输出**：
- DataFrame，包含 存货编码、存货、尺码、近7天销量、日均销量

**特殊处理**：
- 自动检测表头位置（扫描前10行查找"存货编码"）
- 仓库编码格式统一：浮点数 → 整数 → 三位补零字符串
- 按 WARNING_WAREHOUSE_CODE 筛选仓库

**调用关系**：
- 调用方：`build_standard_data()`
- 调用：`clean_columns()`, `clean_code()`, `clean_size()`

---

### build_inventory_standard_df(inventory_file)
**所在文件**：`app/data_sources/excel_source.py:118-173`

**作用**：解析库存表，提取库存数据

**输入**：
- `inventory_file`: 库存表文件对象

**输出**：
- DataFrame，包含 仓库编码、仓库、存货编码、存货、尺码、当前现存量、当前可用量

**特殊处理**：
- 自动检测表头位置（扫描前10行查找"存货编码"）

**调用关系**：
- 调用方：`build_standard_data()`
- 调用：`clean_columns()`, `clean_code()`, `clean_size()`

---

### build_hq_standard_df(hq_file)
**所在文件**：`app/data_sources/excel_source.py:178-237`

**作用**：解析总部库存二维表，转换为一维格式

**输入**：
- `hq_file`: 总部库存表文件对象

**输出**：
- DataFrame，包含 存货编码、尺码、总部库存

**特殊处理**：
- 存货编码取后11位（`clean_hq_code`），与销售表/库存表匹配
- 过滤存货编码为空的行（如"总计"行）

**调用关系**：
- 调用方：`build_standard_data()`
- 调用：`clean_columns()`, `clean_code()`, `clean_size()`, pandas melt/groupby

---

### build_standard_data_from_database()
**所在文件**：`app/data_sources/database_source.py:99-168`

**作用**：从数据库获取标准数据（分发到 mock/tplus/SQL 模式）

**输入**：无（从 config 读取配置）

**输出**：
- 标准 DataFrame

**调用关系**：
- 调用方：`upload_router.py:analyze_from_database()`
- 调用：`build_mock_standard_data()`, `build_standard_data_from_tplus_openapi()`, `build_standard_data_from_frames()` (from base.py), `build_database_url()`

---

### build_mock_standard_data()
**所在文件**：`app/data_sources/database_source.py:52-92`

**作用**：生成模拟测试数据

**输入**：无

**输出**：
- 标准 DataFrame（3条测试数据）

**调用关系**：
- 调用方：`build_standard_data_from_database()` (DB_TYPE=mock)

---

### build_standard_data_from_frames(inventory_df, sales_df, hq_df, already_cleaned)
**所在文件**：`app/data_sources/base.py:57-158`

**作用**：将三个 DataFrame 合并为标准数据（以销售为主，LEFT JOIN 库存）

**输入**：
- `inventory_df`: 库存 DataFrame
- `sales_df`: 销售 DataFrame
- `hq_df`: 总部库存 DataFrame（可选）
- `already_cleaned`: bool，是否已清洗（Excel 入口为 True）

**输出**：
- 标准 DataFrame

**合并逻辑**：
1. 销售数据作为主体
2. 按存货编码+尺码 LEFT JOIN 库存数据
3. 按存货编码+尺码 LEFT JOIN 总部库存数据
4. 筛选近7天销量 > 0 的记录
5. 按 WARNING_WAREHOUSE_CODE 筛选仓库

**调用关系**：
- 调用方：`build_standard_data_from_database()`, `build_standard_data()` (excel_source)
- 调用：`_ensure_clean_code_size()`, `ensure_standard_columns()`

---

### build_database_url()
**所在文件**：`app/data_sources/database_source.py:21-49`

**作用**：构建数据库连接 URL

**输入**：无（从 config 读取配置）

**输出**：
- 字符串：数据库连接 URL

**调用关系**：
- 调用方：`build_standard_data_from_database()`

---

### build_standard_data_from_tplus_openapi()
**所在文件**：`app/data_sources/tplus_openapi_source.py:680-736`

**作用**：从 T+ API 获取标准数据（以销售为主，LEFT JOIN 库存）

**输入**：无

**输出**：
- 标准 DataFrame

**合并逻辑**：
1. 销售数据作为主体
2. 按存货编码+尺码 LEFT JOIN 现存量数据
3. 按存货编码 LEFT JOIN 存货档案（补充存货名称）
4. 总部库存默认为 0

**调用关系**：
- 调用方：`database_source.py:build_standard_data_from_database()`
- 调用：`TPlusOpenAPIClient()`, `_build_inventory_master_df()`, `_build_current_stock_df()`

## 数据清洗函数

### clean_columns(df)
**所在文件**：`app/data_sources/excel_source.py:8-16`

**作用**：清洗列名（去空格、换行符）

**输入**：
- `df`: DataFrame

**输出**：
- 清洗后的 DataFrame

**调用关系**：
- 调用方：`build_sales_standard_df()`, `build_inventory_standard_df()`, `build_hq_standard_df()`

---

### clean_code(value)
**所在文件**：`app/data_sources/excel_source.py:19-30`

**作用**：清洗编码字段（处理 Excel 浮点数问题）

**输入**：
- `value`: 任意值

**输出**：
- 字符串：清洗后的编码

**调用关系**：
- 调用方：多个数据源函数
- 被引用：`database_source.py`, `tplus_openapi_source.py`

---

### clean_size(value)
**所在文件**：`app/data_sources/excel_source.py:33-41`

**作用**：清洗尺码字段（去除"码"字）

**输入**：
- `value`: 任意值

**输出**：
- 字符串：清洗后的尺码

**调用关系**：
- 调用方：多个数据源函数
- 被引用：`database_source.py`, `tplus_openapi_source.py`

## 数据校验函数

### ensure_standard_columns(df)
**所在文件**：`app/data_sources/base.py:18-23`

**作用**：校验 DataFrame 是否包含所有标准列

**输入**：
- `df`: DataFrame

**输出**：
- 只包含标准列的 DataFrame

**异常**：
- ValueError: 缺少必要字段

**调用关系**：
- 调用方：所有数据源的最终输出函数

## T+ API 客户端方法

### TPlusOpenAPIClient.__init__(self)
**所在文件**：`app/data_sources/tplus_openapi_source.py:64-71`

**作用**：初始化配置校验和 requests Session

**输入**：无

**输出**：无

**调用关系**：
- 调用方：所有使用 TPlusOpenAPIClient 的地方

---

### TPlusOpenAPIClient.get_access_token(self, force_refresh=False)
**所在文件**：`app/data_sources/tplus_openapi_source.py:116-141`

**作用**：获取访问令牌（优先缓存，过期则刷新）

**输入**：
- `force_refresh`: bool，强制刷新

**输出**：
- 字符串：access_token

**调用关系**：
- 调用方：`_request()`, `_post_json_direct()`, `test_inventory_query()`
- 调用：`_read_cached_token()`, `_cached_access_token_is_valid()`, `refresh_access_token()`, `generate_self_built_token()`

---

### TPlusOpenAPIClient.query_inventory(self)
**所在文件**：`app/data_sources/tplus_openapi_source.py:153-155`

**作用**：查询存货档案

**输入**：无

**输出**：
- list[dict]: 存货记录列表

**调用关系**：
- 调用方：`build_standard_data_from_tplus_openapi()`
- 调用：`_request()`, `_extract_records()`

---

### TPlusOpenAPIClient.query_current_stock(self)
**所在文件**：`app/data_sources/tplus_openapi_source.py:157-159`

**作用**：查询现存量

**输入**：无

**输出**：
- list[dict]: 现存量记录列表

**调用关系**：
- 调用方：`build_standard_data_from_tplus_openapi()`
- 调用：`_request()`, `_extract_records()`

---

### TPlusOpenAPIClient.query_recent_sale_delivery_sales(self, days, page_size, max_pages, max_detail_workers, param_dic, end_date, force_refresh)
**所在文件**：`app/data_sources/tplus_openapi_source.py:223-331`

**作用**：查询近期销售出库单并汇总销量

**输入**：
- `days`: int，查询天数（默认 SAFE_DAYS=7）
- `page_size`: int，分页大小
- `max_pages`: int，最大扫描页数
- `max_detail_workers`: int，并发获取详情的线程数
- `param_dic`: dict，额外查询参数
- `end_date`: date，结束日期
- `force_refresh`: bool，强制刷新缓存

**输出**：
- DataFrame：包含 存货编码、尺码、近7天销量、日均销量

**调用关系**：
- 调用方：`build_standard_data_from_tplus_openapi()`
- 调用：`_find_sale_delivery_list_response()`, `get_sale_delivery_detail()`, `_extract_sale_delivery_sales_rows()`, `_build_recent_sales_summary_df()`

---

### TPlusOpenAPIClient._request(self, method, endpoint, include_token, **kwargs)
**所在文件**：`app/data_sources/tplus_openapi_source.py:385-454`

**作用**：通用 API 请求（含重试和错误处理）

**输入**：
- `method`: str，HTTP 方法
- `endpoint`: str，API 端点
- `include_token`: bool，是否包含 Token
- `**kwargs`: 其他请求参数

**输出**：
- dict: API 响应

**调用关系**：
- 调用方：`query_inventory()`, `query_current_stock()`, `_query_all_pages()`

## 路由处理函数

### upload_files(request, inventory_file, sales_file, hq_file)
**所在文件**：`app/routers/upload_router.py:114-139`

**作用**：处理 Excel 文件上传

**输入**：
- `request`: Request
- `inventory_file`: UploadFile
- `sales_file`: UploadFile
- `hq_file`: UploadFile

**输出**：
- HTMLResponse

**调用关系**：
- 路由：POST /upload
- 调用：`build_standard_data()`, `render_analysis_result()`

---

### analyze_from_database(request, hq_file)
**所在文件**：`app/routers/upload_router.py:142-179`

**作用**：处理数据库分析请求（支持可选的总部库存表上传）

**输入**：
- `request`: Request
- `hq_file`: UploadFile（可选，总部库存表）

**输出**：
- HTMLResponse

**调用关系**：
- 路由：POST /database-analysis
- 调用：`build_standard_data_from_database()`, `build_hq_standard_df()` (如上传了总部表), `render_analysis_result()`

---

### render_analysis_result(request, standard_df, data_source_name)
**所在文件**：`app/routers/upload_router.py:99-111`

**作用**：统一的结果渲染流程

**输入**：
- `request`: Request
- `standard_df`: 标准 DataFrame
- `data_source_name`: 数据源名称

**输出**：
- TemplateResponse

**调用关系**：
- 调用方：`upload_files()`, `analyze_from_database()`
- 调用：`analyze_standard_data()`, `build_result_context()`

---

### build_result_context(result_df, data_source_name)
**所在文件**：`app/routers/upload_router.py:38-86`

**作用**：将分析结果转换为模板渲染所需的上下文数据

**输入**：
- `result_df`: 分析结果 DataFrame
- `data_source_name`: 数据源名称

**输出**：
- dict: 模板上下文

**调用关系**：
- 调用方：`render_analysis_result()`

---

### get_user_facing_error(exc)
**所在文件**：`app/routers/upload_router.py:19-35`

**作用**：将技术异常转换为用户友好的错误信息

**输入**：
- `exc`: Exception

**输出**：
- 字符串：用户友好的错误信息

**调用关系**：
- 调用方：`upload_files()`, `analyze_from_database()`

---

### tplus_message_callback(request)
**所在文件**：`app/routers/tplus_oauth_router.py:73-123`

**作用**：处理 T+ 消息回调（接收 appTicket、certificate 等）

**输入**：
- `request`: Request

**输出**：
- dict: {"result": "success", "code": 0, "msg": "success"}

**调用关系**：
- 路由：GET/POST /tplus/message/callback
- 调用：`decrypt_chanjet_message()`, `_extract_app_ticket()`, `TPlusOpenAPIClient().save_app_ticket()`, `save_chanjet_certificate()`

---

### tplus_oauth_callback(request, code, state)
**所在文件**：`app/routers/tplus_oauth_router.py:126-145`

**作用**：处理 T+ OAuth 授权回调

**输入**：
- `request`: Request
- `code`: str，授权码
- `state`: str，状态参数

**输出**：
- TemplateResponse

**调用关系**：
- 路由：GET /tplus/oauth/callback
- 调用：`TPlusOpenAPIClient().exchange_code_for_token()`

## 通知函数

### send_wechat_message(content)
**所在文件**：`app/notifications/wechat.py:5-24`

**作用**：发送企业微信消息

**输入**：
- `content`: str，消息内容

**输出**：
- bool: 是否发送成功

**调用关系**：
- 调用方：暂无直接调用

---

### build_warning_message(red_list, yellow_list)
**所在文件**：`app/notifications/wechat.py:27-55`

**作用**：构建预警通知消息文本

**输入**：
- `red_list`: list，红色预警数据
- `yellow_list`: list，黄色预警数据

**输出**：
- 字符串：消息文本

**调用关系**：
- 调用方：暂无直接调用

---

### build_daily_summary_message(summary)
**所在文件**：`app/notifications/wechat.py:58-66`

**作用**：构建每日汇总消息文本

**输入**：
- `summary`: dict，汇总数据

**输出**：
- 字符串：消息文本

**调用关系**：
- 调用方：暂无直接调用

## T+ 内部辅助函数

### _build_inventory_master_df(records)
**所在文件**：`app/data_sources/tplus_openapi_source.py:761-789`

**作用**：将存货档案记录转换为 DataFrame

**输入**：
- `records`: list[dict]

**输出**：
- DataFrame

---

### _build_current_stock_df(records)
**所在文件**：`app/data_sources/tplus_openapi_source.py:792-836`

**作用**：将现存量记录转换为 DataFrame

**输入**：
- `records`: list[dict]

**输出**：
- DataFrame

---

### _extract_sale_delivery_sales_rows(detail_response, start, end)
**所在文件**：`app/data_sources/tplus_openapi_source.py:894-927`

**作用**：从销售出库单详情中提取销售行

**输入**：
- `detail_response`: dict
- `start`: date
- `end`: date

**输出**：
- list[dict]

---

### _build_recent_sales_summary_df(rows, days)
**所在文件**：`app/data_sources/tplus_openapi_source.py:930-952`

**作用**：汇总近期销售数据

**输入**：
- `rows`: list[dict]
- `days`: int

**输出**：
- DataFrame

---

### _field(item, *names)
**所在文件**：`app/data_sources/tplus_openapi_source.py:839-850`

**作用**：从字典中按优先级获取字段值

**输入**：
- `item`: dict
- `*names`: 字段名列表

**输出**：
- 任意值

---

### _dig(payload, *path)
**所在文件**：`app/data_sources/tplus_openapi_source.py:1021-1028`

**作用**：从嵌套字典中按路径获取值

**输入**：
- `payload`: dict
- `*path`: 路径

**输出**：
- 任意值

---

### _parse_columns_rows_response(response)
**所在文件**：`app/data_sources/tplus_openapi_source.py:1234-1256`

**作用**：解析 T+ 的 Columns/Rows 格式响应

**输入**：
- `response`: dict

**输出**：
- list[dict]

---

### _extract_app_ticket(payload)
**所在文件**：`app/data_sources/tplus_openapi_source.py:1273-1286`

**作用**：从消息回调中提取 appTicket

**输入**：
- `payload`: dict

**输出**：
- str 或 None

**调用关系**：
- 调用方：`tplus_oauth_router.py:tplus_message_callback()`

---

### decrypt_chanjet_message(encrypted_message, message_secret)
**所在文件**：`app/routers/tplus_oauth_router.py:30-44`

**作用**：解密畅捷通消息

**输入**：
- `encrypted_message`: str，Base64 编码的加密消息
- `message_secret`: str，密钥

**输出**：
- dict: 解密后的消息

**调用关系**：
- 调用方：`tplus_message_callback()`

---

### save_chanjet_certificate(certificate)
**所在文件**：`app/routers/tplus_oauth_router.py:47-70`

**作用**：保存畅捷通证书到 .env 文件

**输入**：
- `certificate`: str

**输出**：无

**调用关系**：
- 调用方：`tplus_message_callback()`
