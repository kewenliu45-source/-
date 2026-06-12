# 已知问题

## 潜在 Bug

### 1. Excel 表头行号硬编码（已修复）
**问题描述**：Excel 表头行号硬编码为 6、7、1，不同来源的 Excel 表头位置可能不同

**当前状态**：已修复 - 销售表和库存表现在自动检测表头位置（扫描前10行查找"存货编码"）

**影响范围**：
- `app/data_sources/excel_source.py:50-58` - sales_file 自动检测
- `app/data_sources/excel_source.py:121-129` - inventory_file 自动检测
- `app/data_sources/excel_source.py:180` - hq_file 仍使用 header=1

**建议优先级**：★☆☆☆☆（基本解决）

---

### 2. T+ 销售数据查询日期解析不稳定
**问题描述**：从单据编号中提取日期的正则表达式可能匹配到错误日期

**影响范围**：
- `app/data_sources/tplus_openapi_source.py:879-891` - `_extract_voucher_code_date()`

**建议优先级**：★★☆☆☆

---

### 3. 总部库存 T+ 模式默认为 0
**问题描述**：T+ OpenAPI 模式下，总部库存硬编码为 0，导致调货建议无法考虑总部可调数量

**影响范围**：
- `app/data_sources/tplus_openapi_source.py:712` - `standard_df["总部库存"] = 0`

**建议优先级**：★★★★☆

---

### 4. 仓库筛选逻辑不一致（已修复）
**问题描述**：Excel 模式未显式筛选仓库，依赖上传数据；数据库和 T+ 模式会筛选

**当前状态**：已修复 - 所有模式现在都统一筛选仓库

**影响范围**：
- `app/data_sources/excel_source.py:85-89` - 销售表筛选（含格式统一）
- `app/data_sources/base.py:102-105` - 库存表筛选（通过 build_standard_data_from_frames）
- `app/data_sources/tplus_openapi_source.py:841-842` - T+ 现存量筛选
- `app/data_sources/tplus_openapi_source.py:959-962` - T+ 销售筛选

**建议优先级**：★☆☆☆☆（已解决）

---

### 5. 日均销量计算除零风险
**问题描述**：虽然 warning_service.py 处理了零销量情况，但 SAFE_DAYS 配置为 0 时会除零

**影响范围**：
- `app/data_sources/excel_source.py:79` - `sales_standard_df["近7天销量"] / 7`（硬编码7）
- `app/data_sources/database_source.py:185` - `sales_df["近7天销量"] / SAFE_DAYS`
- `app/data_sources/tplus_openapi_source.py:951` - `result["近7天销量"] / days`

**建议优先级**：★★☆☆☆

## 重复代码

### 1. 数据清洗函数重复导入
**问题描述**：`clean_code()` 和 `clean_size()` 定义在 excel_source.py，但被 database_source.py 和 tplus_openapi_source.py 导入使用

**影响范围**：
- `app/data_sources/excel_source.py:19-41`
- `app/data_sources/database_source.py:18`
- `app/data_sources/tplus_openapi_source.py:39`

**建议优先级**：★★☆☆☆

**建议**：将通用清洗函数移到 base.py 或创建 utils.py

---

### 2. DataFrame 合并逻辑重复（已修复）
**问题描述**：excel_source.py 和 database_source.py 中的三表合并逻辑高度相似

**当前状态**：已修复 - 合并逻辑已抽取到 base.py 的 `build_standard_data_from_frames()`

**影响范围**：
- `app/data_sources/base.py:57-158` - 统一的合并函数
- `app/data_sources/excel_source.py:263` - 调用 base.py（already_cleaned=True）
- `app/data_sources/database_source.py:167` - 调用 base.py

**建议优先级**：★☆☆☆☆（已解决）

---

### 3. 仓库筛选逻辑重复
**问题描述**：仓库编码筛选逻辑在多处重复

**影响范围**：
- `app/data_sources/database_source.py:175-178`
- `app/data_sources/tplus_openapi_source.py:819-821`

**建议优先级**：★★☆☆☆

## 死代码

### 1. wechat.py 未被调用
**问题描述**：企业微信通知模块已实现但无调用入口

**影响范围**：
- `app/notifications/wechat.py` - 所有函数

**建议优先级**：★★★☆☆

**建议**：在 result.html 的"发送每日汇总"按钮中接入

---

### 2. test_inventory_query() 和 test_find_sale_delivery_list() 测试函数
**问题描述**：这两个函数仅用于调试，不应出现在生产代码中

**影响范围**：
- `app/data_sources/tplus_openapi_source.py:717-758`

**建议优先级**：★★☆☆☆

**建议**：移到 tests/ 目录或标记为 @pytest.mark.skip

---

### 3. _first_value() 函数
**问题描述**：与 _field() 功能重复，且未被使用

**影响范围**：
- `app/data_sources/tplus_openapi_source.py:1289-1294`

**建议优先级**：★☆☆☆☆

---

### 4. 未实现的 API 端点
**问题描述**：模板中引用了未实现的 API

**影响范围**：
- `POST /send-daily-summary` - result.html:38 - 未实现
- `GET /download/{filename}` - result.html:41 - 未实现（分析结果下载）

**已实现的导出功能**：
- `GET /export/sales` - 导出近7天销售表
- `GET /export/inventory` - 导出库存表

**建议优先级**：★★★☆☆

## 未完成模块

### 1. 企业微信通知集成
**问题描述**：wechat.py 已实现但未接入业务流程

**影响范围**：
- 预警分析完成后无自动通知
- 每日汇总功能缺失

**建议优先级**：★★★★☆

---

### 2. Excel 结果下载
**问题描述**：result.html 中有下载按钮但后端未实现（分析结果下载）

**影响范围**：
- 用户无法下载分析结果

**已实现的导出功能**：
- `GET /export/sales` - 导出近7天销售表
- `GET /export/inventory` - 导出库存表

**建议优先级**：★★☆☆☆

---

### 3. 定时任务
**问题描述**：无定时自动执行预警分析的功能

**影响范围**：
- 需要人工触发分析

**建议优先级**：★★★☆☆

---

### 4. 前端筛选功能
**问题描述**：result.html 中的筛选按钮无 JavaScript 实现

**影响范围**：
- 用户无法按预警状态筛选

**建议优先级**：★★☆☆☆

## 高风险模块

### 1. T+ Token 管理
**问题描述**：Token 缓存和刷新逻辑复杂，涉及多线程并发

**风险点**：
- 多线程同时刷新 Token 可能导致冲突
- Token 缓存文件损坏时无恢复机制
- OAuth 授权码过期处理

**影响范围**：
- `app/data_sources/tplus_openapi_source.py:116-141` - get_access_token()
- `app/data_sources/tplus_openapi_source.py:491-534` - Token 缓存

**建议优先级**：★★★★★

---

### 2. T+ 销售数据并发查询
**问题描述**：使用 ThreadPoolExecutor 并发获取销售单详情，异常处理可能不完善

**风险点**：
- 线程池大小控制
- 单个请求失败不影响其他请求
- 大量数据时内存占用

**影响范围**：
- `app/data_sources/tplus_openapi_source.py:306-322`

**建议优先级**：★★★☆☆

---

### 3. 数据库连接管理
**问题描述**：每次请求都创建新的 SQLAlchemy 引擎，无连接池管理

**风险点**：
- 高并发时连接数过多
- 连接未正确关闭

**影响范围**：
- `app/data_sources/database_source.py:113`

**建议优先级**：★★★☆☆

---

### 4. Excel 文件大小限制
**问题描述**：未限制上传文件大小，可能导致内存溢出

**风险点**：
- 大文件上传导致服务崩溃

**影响范围**：
- `app/routers/upload_router.py:114-139`

**建议优先级**：★★☆☆☆

## 配置问题

### 1. .env 文件敏感信息
**问题描述**：.env 文件包含敏感信息但未在 .gitignore 中排除

**影响范围**：
- `.env` 文件

**建议优先级**：★★★★★

**建议**：确认 .gitignore 包含 .env

---

### 2. T+ 配置项过多
**问题描述**：T+ 相关配置项超过 20 个，增加部署复杂度

**影响范围**：
- `app/config.py:44-92`

**建议优先级**：★★☆☆☆

**建议**：提供配置向导或默认配置模板

## 代码质量问题

### 1. 缺少类型注解
**问题描述**：部分函数缺少参数和返回值类型注解

**影响范围**：
- 多个文件

**建议优先级**：★★☆☆☆

---

### 2. 缺少文档字符串
**问题描述**：部分函数缺少 docstring 说明

**影响范围**：
- 多个文件

**建议优先级**：★★☆☆☆

---

### 3. 异常处理过于宽泛
**问题描述**：部分地方使用 `except Exception` 捕获所有异常

**影响范围**：
- `app/routers/upload_router.py:130`
- `app/routers/upload_router.py:151`
- `app/data_sources/tplus_openapi_source.py:320`

**建议优先级**：★★☆☆☆

---

### 4. 硬编码的魔法数字
**问题描述**：代码中存在硬编码的数字

**影响范围**：
- `7` - 安全天数（部分位置硬编码，部分使用 SAFE_DAYS）
- `999` - 无销量时的可售天数显示值
- `006` - 预警仓库编码

**建议优先级**：★★☆☆☆
