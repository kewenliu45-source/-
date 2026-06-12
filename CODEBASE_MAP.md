# 代码库地图

## 系统调用关系图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                   main.py                                   │
│                              (FastAPI 应用入口)                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ↓                       ↓                       ↓
┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│    page_router.py     │ │   upload_router.py    │ │ tplus_oauth_router.py │
│      (页面路由)        │ │   (数据上传和分析)     │ │   (T+ OAuth 授权)     │
└───────────────────────┘ └───────────────────────┘ └───────────────────────┘
            │                       │                       │
            ↓                       ↓                       ↓
┌───────────────────────┐ ┌───────────────────────┐ ┌───────────────────────┐
│    index.html         │ │                       │ │                       │
│    (首页模板)          │ │   excel_source.py     │ │                       │
└───────────────────────┘ │   (Excel 数据处理)     │ │                       │
                          └───────────────────────┘ │                       │
                                    │               │                       │
                                    ↓               │                       │
                          ┌───────────────────────┐ │                       │
                          │  database_source.py   │ │                       │
                          │  (数据库数据处理)      │ │                       │
                          └───────────────────────┘ │                       │
                                    │               │                       │
                                    ↓               │                       │
                          ┌───────────────────────┐ │                       │
                          │tplus_openapi_source.py│ │                       │
                          │  (T+ API 数据处理)     │ │                       │
                          └───────────────────────┘ │                       │
                                    │               │                       │
                                    ↓               ↓                       ↓
                          ┌───────────────────────────────────────────────┐
                          │               warning_service.py              │
                          │              (预警计算引擎)                    │
                          └───────────────────────────────────────────────┘
                                    │
                                    ↓
                          ┌───────────────────────┐
                          │    result.html        │
                          │    (结果展示)          │
                          └───────────────────────┘
```

## 核心路径

### 路径 1: Excel 上传分析 (最常用)
```
main.py
  ↓ include_router
upload_router.py: upload_files()
  ↓ 调用
excel_source.py: build_standard_data()
  ├── build_sales_standard_df() - 自动检测表头，仓库编码统一
  ├── build_inventory_standard_df() - 自动检测表头
  └── build_hq_standard_df() - 存货编码取后11位
  ↓ 合并后
base.py: build_standard_data_from_frames(already_cleaned=True)
  ├── 以销售为主 LEFT JOIN 库存
  └── ensure_standard_columns()
  ↓ 校验后
warning_service.py: analyze_standard_data()
  ↓ 计算后
upload_router.py: build_result_context()
  ↓ 渲染
result.html
```

**关键文件**：
- `app/routers/upload_router.py:114-139`
- `app/data_sources/excel_source.py:242-264`
- `app/data_sources/base.py:57-158`
- `app/services/warning_service.py:5-109`

---

### 路径 2: 数据库分析
```
main.py
  ↓ include_router
upload_router.py: analyze_from_database(hq_file)
  ↓ 调用
database_source.py: build_standard_data_from_database()
  ↓
  ├── mock → build_mock_standard_data()
  ├── tplus → tplus_openapi_source.py: build_standard_data_from_tplus_openapi()
  └── mysql/postgresql/sqlserver/oracle → SQL 查询
  ↓ 合并后
base.py: build_standard_data_from_frames() + ensure_standard_columns()
  ↓ 校验后
[如有 hq_file] excel_source.py: build_hq_standard_df() → merge
  ↓
warning_service.py: analyze_standard_data()
  ↓ 渲染
result.html
```

**关键文件**：
- `app/routers/upload_router.py:142-179`
- `app/data_sources/database_source.py:99-168`
- `app/data_sources/base.py:57-158`
- `app/data_sources/tplus_openapi_source.py:680-736`

---

### 路径 3: T+ OAuth 授权
```
main.py
  ↓ include_router
tplus_oauth_router.py: tplus_oauth_callback()
  ↓ 调用
tplus_openapi_source.py: TPlusOpenAPIClient
  ├── exchange_code_for_token()
  ├── _request_auth_token()
  ├── _extract_token_payload()
  └── _write_cached_token()
  ↓ 渲染
oauth_success.html
```

**关键文件**：
- `app/routers/tplus_oauth_router.py:126-145`
- `app/data_sources/tplus_openapi_source.py:73-88`

## 非核心路径

### 路径 4: T+ 消息回调
```
main.py
  ↓ include_router
tplus_oauth_router.py: tplus_message_callback()
  ↓ 处理
  ├── decrypt_chanjet_message() - 解密消息
  ├── save_chanjet_certificate() - 保存证书
  └── TPlusOpenAPIClient().save_app_ticket() - 保存 appTicket
```

**关键文件**：
- `app/routers/tplus_oauth_router.py:73-123`

---

### 路径 5: 畅捷通校验文件
```
main.py
  ↓ 路由
chanjet_check_file()
  ↓ 返回
static/CHANJET_CHECK.txt
```

**关键文件**：
- `app/main.py:16-18`

## 数据流向图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据输入层                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────────────────────┐   │
│  │ Excel 上传   │     │ 数据库查询   │     │ T+ OpenAPI 查询             │   │
│  │             │     │             │     │                             │   │
│  │ • 库存表    │     │ • MySQL     │     │ • 存货档案                   │   │
│  │ • 销售表    │     │ • PostgreSQL│     │ • 现存量                     │   │
│  │ • 总部表    │     │ • SQL Server│     │ • 销售出库单                 │   │
│  │             │     │ • Oracle    │     │                             │   │
│  └──────┬──────┘     └──────┬──────┘     └──────────────┬──────────────┘   │
│         │                   │                           │                   │
└─────────┼───────────────────┼───────────────────────────┼───────────────────┘
          ↓                   ↓                           ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                              数据解析层                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐   │
│  │ excel_source.py │ │database_source.py│ │   tplus_openapi_source.py   │   │
│  │                 │ │                 │ │                             │   │
│  │ • clean_columns │ │ • build_db_url  │ │ • TPlusOpenAPIClient        │   │
│  │ • clean_code    │ │ • read_sql_df   │ │   • get_access_token        │   │
│  │ • clean_size    │ │ • build_frames  │ │   • query_inventory         │   │
│  │ • build_*_df    │ │                 │ │   • query_current_stock     │   │
│  │ • build_std_data│ │                 │ │   • query_recent_sales      │   │
│  └────────┬────────┘ └────────┬────────┘ └──────────────┬──────────────┘   │
│           │                   │                          │                   │
└───────────┼───────────────────┼──────────────────────────┼──────────────────┘
            ↓                   ↓                          ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                           标准数据层 (DataFrame)                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        base.py                                      │   │
│  │  STANDARD_COLUMNS = [                                               │   │
│  │      "存货编码", "存货", "尺码",                                      │   │
│  │      "近7天销量", "日均销量",                                         │   │
│  │      "仓库编码", "仓库",                                             │   │
│  │      "当前现存量", "当前可用量",                                      │   │
│  │      "总部库存"                                                      │   │
│  │  ]                                                                  │   │
│  │                                                                      │   │
│  │  ensure_standard_columns(df) - 校验并规范化                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                             预警计算层                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    warning_service.py                                │   │
│  │                                                                      │   │
│  │  analyze_standard_data(df)                                           │   │
│  │      │                                                               │   │
│  │      ├── 可售天数 = 当前可用量 / 日均销量                             │   │
│  │      ├── 目标库存 = 日均销量 × 7                                     │   │
│  │      ├── 建议调货量 = max(0, 目标库存 - 当前可用量)                    │   │
│  │      ├── 总部可调数量 = min(总部库存, 建议调货量)                      │   │
│  │      ├── 预警状态 = get_warning_status(row)                          │   │
│  │      │       ├── 红色预警: 当前可用量 ≤ 0                             │   │
│  │      │       ├── 黄色预警: 可售天数 < 7                               │   │
│  │      │       └── 正常: 可售天数 ≥ 7                                  │   │
│  │      └── 调货建议 = get_transfer_advice(row)                         │   │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                             结果输出层                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────────────────┐   │
│  │  result.html    │ │  wechat.py      │ │  Excel 导出 (已实现)         │   │
│  │  (Web 页面展示)  │ │  (企业微信通知)  │ │                             │   │
│  │                 │ │                 │ │ • /export/sales             │   │
│  │ • 统计卡片      │ │ • send_message  │ │ • /export/inventory         │   │
│  │ • 调货建议表    │ │ • build_warning │ │                             │   │
│  │ • 预警明细表    │ │ • build_summary │ │                             │   │
│  └─────────────────┘ └─────────────────┘ └─────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 模块依赖关系

### 核心依赖
```
upload_router.py
  ├── depends on → excel_source.py
  ├── depends on → database_source.py
  ├── depends on → warning_service.py
  └── depends on → config.py

excel_source.py
  └── depends on → base.py

database_source.py
  ├── depends on → base.py
  ├── depends on → excel_source.py (clean_code, clean_size)
  ├── depends on → tplus_openapi_source.py (条件依赖)
  └── depends on → config.py

tplus_openapi_source.py
  ├── depends on → base.py
  ├── depends on → excel_source.py (clean_code, clean_size)
  └── depends on → config.py

warning_service.py
  └── standalone (只依赖 pandas, numpy)

tplus_oauth_router.py
  ├── depends on → tplus_openapi_source.py
  └── depends on → config.py
```

## 未来扩展点

### 1. 新增数据源
**扩展位置**：`app/data_sources/`

**扩展方式**：
1. 创建新的 `xxx_source.py`
2. 实现 `build_standard_data_from_xxx()` 函数
3. 返回标准 DataFrame
4. 在 `upload_router.py` 中添加路由

**参考实现**：`database_source.py`

---

### 2. 新增预警规则
**扩展位置**：`app/services/warning_service.py`

**扩展方式**：
1. 修改 `get_warning_status()` 函数
2. 添加新的预警条件
3. 更新 `warning_order` 排序映射

---

### 3. 新增通知渠道
**扩展位置**：`app/notifications/`

**扩展方式**：
1. 创建新的通知模块（如 `dingtalk.py`）
2. 实现 `send_xxx_message()` 函数
3. 在预警分析完成后调用

**参考实现**：`wechat.py`

---

### 4. 新增 API 端点
**扩展位置**：`app/routers/`

**扩展方式**：
1. 在现有路由文件中添加新端点，或创建新路由文件
2. 在 `main.py` 中注册路由

---

### 5. 新增前端页面
**扩展位置**：`app/templates/`

**扩展方式**：
1. 创建新的 HTML 模板
2. 在路由函数中渲染模板

## 代码统计

### 文件数量
- Python 代码文件：12 个
- HTML 模板文件：4 个
- 测试文件：5 个
- 配置文件：3 个

### 代码行数（估算）
- `tplus_openapi_source.py`：~1317 行（最大）
- `warning_service.py`：~109 行
- `excel_source.py`：~264 行
- `database_source.py`：~169 行
- `upload_router.py`：~423 行（含导出功能）
- `base.py`：~159 行（含合并逻辑）

### 复杂度分布
- 高复杂度：`tplus_openapi_source.py`（T+ API 交互、Token 管理、并发查询）
- 中复杂度：`excel_source.py`（数据清洗和合并）
- 低复杂度：`warning_service.py`（纯计算逻辑）
