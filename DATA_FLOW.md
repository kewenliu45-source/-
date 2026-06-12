# 数据流说明

## 完整数据流程

```
用户上传/选择数据源
        ↓
┌───────────────────────────────────────────────────────────────┐
│                    数据输入层                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Excel 上传   │  │ 数据库查询   │  │ T+ OpenAPI 查询     │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘  │
└─────────┼───────────────┼────────────────────┼───────────────┘
          ↓               ↓                    ↓
┌───────────────────────────────────────────────────────────────┐
│                    数据解析层                                  │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐│
│  │ excel_source.py │ │database_source.py│ │tplus_openapi_   ││
│  │                 │ │                 │ │    source.py    ││
│  │ • 销售表解析     │ │ • SQL 查询      │ │ • API 调用      ││
│  │ • 库存表解析     │ │ • DataFrame     │ │ • Token 管理    ││
│  │ • 总部表解析     │ │   合并          │ │ • 分页查询      ││
│  │ • 三表合并       │ │                 │ │ • 销售汇总      ││
│  └────────┬────────┘ └────────┬────────┘ └────────┬────────┘│
└───────────┼──────────────────┼──────────────────┼────────────┘
            ↓                  ↓                  ↓
┌───────────────────────────────────────────────────────────────┐
│                 标准数据层 (DataFrame)                         │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ 字段: 存货编码 | 存货 | 尺码 | 近7天销量 | 日均销量       │ │
│  │       仓库编码 | 仓库 | 当前现存量 | 当前可用量 | 总部库存 │ │
│  └─────────────────────────────────────────────────────────┘ │
│  校验: ensure_standard_columns()                              │
└───────────────────────────┬───────────────────────────────────┘
                            ↓
┌───────────────────────────────────────────────────────────────┐
│                  预警计算层                                    │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │              warning_service.py                          │ │
│  │                                                          │ │
│  │  可售天数 = 当前可用量 / 日均销量                          │ │
│  │  目标库存 = 日均销量 × 7                                  │ │
│  │  建议调货量 = max(0, 目标库存 - 当前可用量)                 │ │
│  │  总部可调数量 = min(总部库存, 建议调货量)                   │ │
│  │                                                          │ │
│  │  预警状态:                                                │ │
│  │    红色预警: 当前可用量 ≤ 0                                │ │
│  │    黄色预警: 可售天数 < 7                                  │ │
│  │    正常: 可售天数 ≥ 7                                     │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────┬───────────────────────────────────┘
                            ↓
┌───────────────────────────────────────────────────────────────┐
│                  结果输出层                                    │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │ Web 页面展示 │  │ Excel 导出   │  │ 企业微信通知        │  │
│  │ (result.html)│  │ /export/*    │  │ (wechat.py)        │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└───────────────────────────────────────────────────────────────┘
```

## 各步骤函数调用链

### Excel 上传流程

```
POST /upload
    ↓
upload_router.py: upload_files()
    ↓
excel_source.py: build_standard_data(inventory_file, sales_file, hq_file)
    ├── build_sales_standard_df(sales_file)
    │       ↓
    │   自动检测表头（扫描前10行查找"存货编码"）
    │       ↓
    │   clean_columns() - 清洗列名
    │       ↓
    │   clean_code() - 清洗存货编码
    │       ↓
    │   clean_size() - 清洗尺码
    │       ↓
    │   仓库编码格式统一（6.0 → "006"）
    │       ↓
    │   按 WARNING_WAREHOUSE_CODE 筛选仓库
    │       ↓
    │   groupby(["存货编码", "存货", "尺码"]).sum()["数量"]
    │       ↓
    │   计算日均销量 = 近7天销量 / SAFE_DAYS
    │
    ├── build_inventory_standard_df(inventory_file)
    │       ↓
    │   自动检测表头（扫描前10行查找"存货编码"）
    │       ↓
    │   clean_columns(), clean_code(), clean_size()
    │       ↓
    │   提取: 仓库编码, 仓库, 存货编码, 存货, 尺码, 现存量, 可用量
    │
    ├── build_hq_standard_df(hq_file) [可选]
    │       ↓
    │   读取 Excel (header=1)
    │       ↓
    │   存货编码取后11位
    │       ↓
    │   melt() 二维转一维
    │       ↓
    │   groupby(["存货编码", "尺码"]).sum()["总部库存"]
    │
    └── base.py: build_standard_data_from_frames(inventory_df, sales_df, hq_df, already_cleaned=True)
            ↓
        以销售为主 LEFT JOIN 库存和总部库存
            ↓
        ensure_standard_columns() - 校验标准字段
            ↓
        返回标准 DataFrame
    ↓
upload_router.py: render_analysis_result()
    ↓
warning_service.py: analyze_standard_data(standard_df)
    ↓
upload_router.py: build_result_context(result_df)
    ↓
templates/result.html - 渲染展示
```

### 数据库分析流程

```
POST /database-analysis
    ↓
upload_router.py: analyze_from_database()
    ↓
database_source.py: build_standard_data_from_database()
    ↓
    ├── DB_TYPE == "mock" → build_mock_standard_data()
    │
    ├── DB_TYPE in {"tplus", "openapi", "chanjet"}
    │       ↓
    │   tplus_openapi_source.py: build_standard_data_from_tplus_openapi()
    │
    └── DB_TYPE in {"mysql", "postgresql", "sqlserver", "oracle"}
            ↓
        build_database_url() - 构建连接字符串
            ↓
        create_engine() - 创建 SQLAlchemy 引擎
            ↓
        pd.read_sql_query(inventory_sql, engine)
        pd.read_sql_query(sales_sql, engine)
        pd.read_sql_query(hq_sql, engine)
            ↓
        build_standard_data_from_frames(inventory_df, sales_df, hq_df)
            ↓
        ensure_standard_columns()
    ↓
upload_router.py: render_analysis_result()
    ↓
warning_service.py: analyze_standard_data(standard_df)
    ↓
templates/result.html - 渲染展示
```

### T+ OpenAPI 分析流程

```
POST /database-analysis (DB_TYPE=tplus)
    ↓
upload_router.py: analyze_from_database()
    ↓
database_source.py: build_standard_data_from_database()
    ↓
tplus_openapi_source.py: build_standard_data_from_tplus_openapi()
    ↓
TPlusOpenAPIClient()
    ↓
    ├── get_access_token()
    │       ↓
    │   _read_cached_token() - 读缓存
    │       ↓
    │   _cached_access_token_is_valid() - 校验有效期
    │       ↓
    │   (如过期) refresh_access_token() 或 generate_self_built_token()
    │
    ├── query_inventory() - 存货档案
    │       ↓
    │   _request("POST", INVENTORY_QUERY_ENDPOINT)
    │       ↓
    │   _extract_records() - 提取记录
    │
    ├── query_current_stock() - 现存量
    │       ↓
    │   _request("POST", CURRENT_STOCK_QUERY_ENDPOINT)
    │
    └── query_recent_sale_delivery_sales() - 近期销售
            ↓
        检查缓存（TTL 1800秒）
            ↓
        _find_sale_delivery_list_response() - 分页查询列表
            ↓
        筛选日期范围内的单据
            ↓
        ThreadPoolExecutor - 并发获取详情
            ↓
        get_sale_delivery_detail() - 获取每张单据明细
            ↓
        _extract_sale_delivery_sales_rows() - 提取销售行
            ↓
        _build_recent_sales_summary_df() - 汇总（按仓库筛选）
    ↓
以销售为主 LEFT JOIN 库存数据
    ↓
补充存货名称（从存货档案）
    ↓
ensure_standard_columns()
    ↓
返回标准 DataFrame
    ↓
upload_router.py: render_analysis_result()
    ↓
warning_service.py: analyze_standard_data(standard_df)
    ↓
templates/result.html
```

## 数据库模式说明

### Mock 模式
**配置**：`DB_TYPE=mock`

**用途**：本地开发和流程测试，无需连接真实数据库

**数据来源**：`build_mock_standard_data()` 硬编码的测试数据

**代码位置**：`app/data_sources/database_source.py:52-92`

---

### SQL Server 模式
**配置**：`DB_TYPE=sqlserver`

**连接串**：`mssql+pyodbc://user:password@host:port/database?driver=SQL Server`

**特点**：使用 `DATEADD` 函数计算日期范围

**代码位置**：`app/data_sources/database_source.py:39-44`

---

### MySQL 模式
**配置**：`DB_TYPE=mysql`

**连接串**：`mysql+pymysql://user:password@host:port/database?charset=utf8mb4`

**代码位置**：`app/data_sources/database_source.py:33-34`

---

### PostgreSQL 模式
**配置**：`DB_TYPE=postgresql`

**连接串**：`postgresql+psycopg2://user:password@host:port/database`

**代码位置**：`app/data_sources/database_source.py:36-37`

---

### Oracle 模式
**配置**：`DB_TYPE=oracle`

**连接串**：`oracle+oracledb://user:password@host:port/?service_name=database`

**代码位置**：`app/data_sources/database_source.py:46-48`

---

### T+ OpenAPI 模式
**配置**：`DB_TYPE=tplus` 或 `DB_TYPE=openapi` 或 `DB_TYPE=chanjet`

**认证方式**：
- OAuth 授权码模式（默认）
- 自建应用模式

**Token 缓存**：`outputs/tplus_token_cache.json`

**销售数据缓存**：`outputs/tplus_recent_sales_cache.json`（TTL 1800秒）

**代码位置**：`app/data_sources/tplus_openapi_source.py`

## 数据转换细节

### Excel 销售表 → 标准销售数据
**输入格式**：
| 存货编码 | 存货 | 尺码 | 数量 | 仓库编码 | ... |
|----------|------|------|------|----------|-----|

**转换逻辑**：
1. 自动检测表头：扫描前10行查找包含"存货编码"的行
2. 清洗列名、编码、尺码
3. 仓库编码格式统一：浮点数 → 整数 → 三位补零字符串（如 6.0 → "006"）
4. 按 WARNING_WAREHOUSE_CODE 筛选仓库
5. 只保留数量 > 0 的记录
6. groupby(["存货编码", "存货", "尺码"]).sum()["数量"]
7. 重命名为"近7天销量"
8. 计算"日均销量" = 近7天销量 / SAFE_DAYS

**输出格式**：
| 存货编码 | 存货 | 尺码 | 近7天销量 | 日均销量 |
|----------|------|------|-----------|----------|

---

### Excel 库存表 → 标准库存数据
**输入格式**：
| 仓库编码 | 仓库 | 存货编码 | 存货 | 尺码 | 现存量(主) | 可用量(主) | ... |
|----------|------|----------|------|------|------------|------------|-----|

**转换逻辑**：
1. 自动检测表头：扫描前10行查找包含"存货编码"的行
2. 清洗列名、编码、尺码
3. 重命名：现存量(主) → 当前现存量，可用量(主) → 当前可用量
4. 提取必要列

**输出格式**：
| 仓库编码 | 仓库 | 存货编码 | 存货 | 尺码 | 当前现存量 | 当前可用量 |
|----------|------|----------|------|------|------------|------------|

---

### Excel 总部库存表 → 标准总部数据
**输入格式**（二维表）：
| 存货编码 | 存货名称 | 尺码1 | 尺码2 | 尺码3 | ... |
|----------|----------|-------|-------|-------|-----|

**转换逻辑**：
1. 读取 header=1（第2行为表头）
2. 存货编码取后11位（`clean_hq_code`），与销售表/库存表匹配
3. melt() 二维转一维
4. 过滤存货编码为空的行（如"总计"行）
5. groupby(["存货编码", "尺码"]).sum()["总部库存"]
6. 只保留总部库存 > 0 的记录

**输出格式**：
| 存货编码 | 尺码 | 总部库存 |
|----------|------|----------|

---

### 三表合并逻辑（以销售为主）
```
sales_df (销售) - 主体
    ↓ merge on ["存货编码", "尺码"], how="left"
inventory_group_df (库存聚合)
    ↓ merge on ["存货编码", "尺码"], how="left"
hq_df (总部库存)
    ↓
fillna(0) 处理空值
    ↓
ensure_standard_columns() 校验
```

**关键特性**：
- 以销售数据为主体（LEFT JOIN），确保有销售但无库存的 SKU 也能被识别
- 编码和尺码在合并前已清洗（already_cleaned=True 时跳过重复清洗）
- 仓库编码在库存数据中按 WARNING_WAREHOUSE_CODE 筛选

**代码位置**：`app/data_sources/base.py:57-158`

## 缓存机制

### T+ Token 缓存
**文件**：`outputs/tplus_token_cache.json`

**缓存内容**：
- access_token
- refresh_token
- access_token_expires_at
- refresh_token_expires_at
- org_id, user_id, app_name, scope, sid

**有效期**：
- access_token：由 T+ 返回的 expires_in 决定
- refresh_token：由 T+ 返回的 refresh_expires_in 决定
- 提前刷新：`TPLUS_TOKEN_REFRESH_SKEW_SECONDS = 43200`（12小时）

**代码位置**：`app/data_sources/tplus_openapi_source.py:491-534`

---

### T+ AppTicket 缓存
**文件**：`outputs/tplus_app_ticket_cache.json`

**缓存内容**：
- app_ticket
- received_at

**有效期**：`TPLUS_APP_TICKET_MAX_AGE_SECONDS = 1500`（25分钟）

**代码位置**：`app/data_sources/tplus_openapi_source.py:541-578`

---

### T+ 销售数据缓存
**文件**：`outputs/tplus_recent_sales_cache.json`

**缓存内容**：
- cache_key（包含 version, days, end_date, param_dic）
- cached_at
- rows

**有效期**：`TPLUS_RECENT_SALES_CACHE_TTL_SECONDS = 1800`（30分钟）

**代码位置**：`app/data_sources/tplus_openapi_source.py:977-1011`
