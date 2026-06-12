# API 流程说明

## 接口清单

### 1. 首页

**URL**: `GET /`

**请求方式**: GET

**参数**: 无

**返回值**: HTML 页面（index.html）

**调用链**:
```
GET /
    ↓
page_router.py: index()
    ↓
templates/index.html
```

---

### 2. Excel 文件上传分析

**URL**: `POST /upload`

**请求方式**: POST

**参数**:
- `inventory_file`: UploadFile（本地库存表）
- `sales_file`: UploadFile（近期销售表）
- `hq_file`: UploadFile（总部库存二维表）

**返回值**: HTML 页面（result.html 或 error.html）

**调用链**:
```
POST /upload
    ↓
upload_router.py: upload_files()
    ↓
excel_source.py: build_standard_data(inventory_file, sales_file, hq_file)
    ├── build_sales_standard_df(sales_file)
    ├── build_inventory_standard_df(inventory_file)
    └── build_hq_standard_df(hq_file)
    ↓
base.py: ensure_standard_columns()
    ↓
upload_router.py: render_analysis_result()
    ↓
warning_service.py: analyze_standard_data(standard_df)
    ↓
upload_router.py: build_result_context(result_df)
    ↓
templates/result.html
```

---

### 3. 数据库分析

**URL**: `POST /database-analysis`

**请求方式**: POST

**参数**:
- `hq_file`: UploadFile（可选，总部库存表）

**返回值**: HTML 页面（result.html 或 error.html）

**调用链**:
```
POST /database-analysis
    ↓
upload_router.py: analyze_from_database(hq_file)
    ↓
database_source.py: build_standard_data_from_database()
    ↓
    ├── DB_TYPE == "mock"
    │       ↓
    │   build_mock_standard_data()
    │
    ├── DB_TYPE in {"tplus", "openapi", "chanjet"}
    │       ↓
    │   tplus_openapi_source.py: build_standard_data_from_tplus_openapi()
    │       ↓
    │   TPlusOpenAPIClient()
    │       ├── get_access_token()
    │       ├── query_inventory()
    │       ├── query_current_stock()
    │       └── query_recent_sale_delivery_sales()
    │
    └── DB_TYPE in {"mysql", "postgresql", "sqlserver", "oracle"}
            ↓
        build_database_url()
            ↓
        pd.read_sql_query() × 3
            ↓
        base.py: build_standard_data_from_frames()
    ↓
[如有 hq_file]
    excel_source.py: build_hq_standard_df(hq_file)
    ↓ merge on ["存货编码", "尺码"]
    ↓
base.py: ensure_standard_columns()
    ↓
upload_router.py: render_analysis_result()
    ↓
warning_service.py: analyze_standard_data(standard_df)
    ↓
templates/result.html
```

---

### 4. T+ OAuth 授权回调

**URL**: `GET /tplus/oauth/callback`

**请求方式**: GET

**参数**:
- `code`: str（授权码）
- `state`: str（状态参数，可选）

**返回值**: HTML 页面（oauth_success.html）

**调用链**:
```
GET /tplus/oauth/callback?code=xxx&state=xxx
    ↓
tplus_oauth_router.py: tplus_oauth_callback()
    ↓
TPlusOpenAPIClient().exchange_code_for_token(code)
    ↓
POST https://openapi.chanjet.com/auth/v2/getToken
    ↓
TPlusOpenAPIClient._extract_token_payload()
    ↓
TPlusOpenAPIClient._write_cached_token()
    ↓
templates/oauth_success.html
```

---

### 5. T+ 消息回调

**URL**: `GET/POST /tplus/message/callback`

**请求方式**: GET, POST

**参数**:
- Query Params 或 Body: 畅捷通推送的消息内容
- `encryptMsg`: str（加密消息，可选）

**返回值**: JSON
```json
{
    "result": "success",
    "code": 0,
    "msg": "success"
}
```

**调用链**:
```
GET/POST /tplus/message/callback
    ↓
tplus_oauth_router.py: tplus_message_callback()
    ↓
    ├── (如有 encryptMsg)
    │       ↓
    │   decrypt_chanjet_message(encrypted_message, CHANJET_MESSAGE_SECRET)
    │
    ├── (如有 certificate)
    │       ↓
    │   save_chanjet_certificate(certificate)
    │
    └── (如有 appTicket)
            ↓
        _extract_app_ticket(payload)
            ↓
        TPlusOpenAPIClient().save_app_ticket(payload)
```

---

### 6. 导出销售表

**URL**: `GET /export/sales`

**请求方式**: GET

**参数**: 无

**返回值**: Excel 文件（application/vnd.openxmlformats-officedocument.spreadsheetml.sheet）

**调用链**:
```
GET /export/sales
    ↓
upload_router.py: export_sales_table()
    ↓
    ├── DB_TYPE == "mock"
    │       ↓
    │   生成模拟销售数据
    │
    ├── DB_TYPE in {"tplus", "openapi", "chanjet"}
    │       ↓
    │   TPlusOpenAPIClient().query_recent_sale_delivery_sales()
    │
    └── DB_TYPE in {"mysql", "postgresql", "sqlserver", "oracle"}
            ↓
        pd.read_sql_query(sales_sql)
    ↓
    确保列顺序与原始 Excel 一致
    ↓
    pd.ExcelWriter() 写入
    ↓
    StreamingResponse 返回文件
```

---

### 7. 导出库存表

**URL**: `GET /export/inventory`

**请求方式**: GET

**参数**: 无

**返回值**: Excel 文件（application/vnd.openxmlformats-officedocument.spreadsheetml.sheet）

**调用链**:
```
GET /export/inventory
    ↓
upload_router.py: export_inventory_table()
    ↓
    ├── DB_TYPE == "mock"
    │       ↓
    │   生成模拟库存数据
    │
    ├── DB_TYPE in {"tplus", "openapi", "chanjet"}
    │       ↓
    │   TPlusOpenAPIClient().query_current_stock()
    │       ↓
    │   按 WARNING_WAREHOUSE_CODE 筛选
    │
    └── DB_TYPE in {"mysql", "postgresql", "sqlserver", "oracle"}
            ↓
        pd.read_sql_query(inventory_sql)
    ↓
    确保列顺序与原始 Excel 一致
    ↓
    pd.ExcelWriter() 写入
    ↓
    StreamingResponse 返回文件
```

---

### 8. 畅捷通校验文件

**URL**: `GET /CHANJET_CHECK.txt`

**请求方式**: GET

**参数**: 无

**返回值**: 纯文本文件

**调用链**:
```
GET /CHANJET_CHECK.txt
    ↓
main.py: chanjet_check_file()
    ↓
FileResponse("static/CHANJET_CHECK.txt")
```

## 路由注册

### main.py 路由注册

```python
app.include_router(page_router.router)          # 页面路由
app.include_router(upload_router.router)         # 上传和分析路由
app.include_router(tplus_oauth_router.router)    # T+ OAuth 路由
```

### 路由前缀

当前所有路由均无前缀，直接挂载在根路径。

## 请求流程图

### Excel 上传流程
```
用户浏览器
    ↓ POST /upload (multipart/form-data)
FastAPI
    ↓
upload_router.py: upload_files()
    ↓
excel_source.py: build_standard_data()
    ↓ (DataFrame)
warning_service.py: analyze_standard_data()
    ↓ (DataFrame + 预警)
upload_router.py: build_result_context()
    ↓ (dict)
Jinja2 Template
    ↓ (HTML)
用户浏览器
```

### 数据库分析流程
```
用户浏览器
    ↓ POST /database-analysis
FastAPI
    ↓
upload_router.py: analyze_from_database()
    ↓
database_source.py: build_standard_data_from_database()
    ↓
    ├── mock → build_mock_standard_data()
    ├── tplus → tplus_openapi_source.py: build_standard_data_from_tplus_openapi()
    └── mysql/postgresql/sqlserver/oracle → SQL 查询
    ↓ (DataFrame)
warning_service.py: analyze_standard_data()
    ↓ (DataFrame + 预警)
upload_router.py: build_result_context()
    ↓ (dict)
Jinja2 Template
    ↓ (HTML)
用户浏览器
```

### T+ OAuth 授权流程
```
用户浏览器
    ↓ 访问 T+ 授权页面
畅捷通
    ↓ 302 Redirect /tplus/oauth/callback?code=xxx
FastAPI
    ↓
tplus_oauth_router.py: tplus_oauth_callback()
    ↓
TPlusOpenAPIClient().exchange_code_for_token(code)
    ↓ POST https://openapi.chanjet.com/auth/v2/getToken
畅捷通
    ↓ 返回 Token
TPlusOpenAPIClient._write_cached_token()
    ↓
templates/oauth_success.html
    ↓ (HTML)
用户浏览器
```

### T+ 消息推送流程
```
畅捷通平台
    ↓ POST /tplus/message/callback
FastAPI
    ↓
tplus_oauth_router.py: tplus_message_callback()
    ↓
    ├── decrypt_chanjet_message() (如有加密)
    ├── save_chanjet_certificate() (如有证书)
    └── TPlusOpenAPIClient().save_app_ticket() (如有 appTicket)
    ↓
JSON Response: {"result": "success", "code": 0, "msg": "success"}
```

## 错误处理

### 统一错误响应

所有分析接口的错误都会被捕获并渲染到 error.html 页面。

**错误处理函数**：`get_user_facing_error(exc)`

**常见错误**：
- EXERROR0002: 畅捷通内部连接失败
- Read timed out: API 超时
- 其他异常: 原始错误信息

**代码位置**：`app/routers/upload_router.py:19-35`

---

### T+ API 错误处理

**错误处理位置**：
- `_raise_for_api_error()` - API 响应错误检查
- `_format_tplus_request_error()` - 请求错误格式化
- `_is_api_error()` - 判断是否为 API 错误

**代码位置**：`app/data_sources/tplus_openapi_source.py`

## 静态资源

### 静态文件路由

**URL**: `/static/*`

**目录**: `app/static/`

**用途**：CSS、JS、图片等静态资源

**配置**：`app/main.py:13`
```python
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
```

---

### 畅捷通校验文件

**URL**: `/CHANJET_CHECK.txt`

**文件**: `app/static/CHANJET_CHECK.txt`

**用途**：畅捷通 T+ 平台校验文件

**配置**：`app/main.py:16-18`

## 未实现的 API

以下 API 在模板中引用但代码中未实现：

### 1. 发送每日汇总

**URL**: `POST /send-daily-summary`

**引用位置**：`app/templates/result.html:38`

**状态**：未实现

---

### 2. 下载 Excel（分析结果）

**URL**: `GET /download/{filename}`

**引用位置**：`app/templates/result.html:41`

**状态**：未实现

**注意**：原始数据的导出已通过 `/export/sales` 和 `/export/inventory` 实现
