# 业务逻辑说明

## 预警规则

### 红色预警
**业务规则**：当前可用量 ≤ 0，表示已缺货

**对应函数**：`get_warning_status()`

**对应文件**：`app/services/warning_service.py:43-46`

```python
def get_warning_status(row):
    if row["当前可用量"] <= 0:
        return "红色预警"
```

---

### 黄色预警
**业务规则**：可售天数 < 7 天，表示库存不足需要提前调货

**对应函数**：`get_warning_status()`

**对应文件**：`app/services/warning_service.py:47-48`

```python
    elif row["可售天数"] < 7:
        return "黄色预警"
```

---

### 正常状态
**业务规则**：可售天数 ≥ 7 天，库存充足

**对应函数**：`get_warning_status()`

**对应文件**：`app/services/warning_service.py:50-51`

```python
    else:
        return "正常"
```

---

## 调货规则

### 建议调货量计算
**业务规则**：建议调货量 = 目标库存 - 当前可用量（最小为 0）

**对应函数**：`analyze_standard_data()`

**对应文件**：`app/services/warning_service.py:25-34`

```python
# 目标库存（7天安全库存）
result_df["目标库存"] = result_df["日均销量"] * 7

# 建议调货量
result_df["建议调货量"] = (
    result_df["目标库存"] - result_df["当前可用量"]
)

result_df["建议调货量"] = (
    result_df["建议调货量"]
    .clip(lower=0)
    .round(0)
)
```

---

### 调货建议文本生成
**业务规则**：
- 红色预警 → "建议立即调货"
- 黄色预警 → "建议尽快调货"
- 根据总部可调数量生成具体建议
- 使用 `int(float(...))` 进行安全类型转换，避免数据类型异常

**对应函数**：`get_transfer_advice()`

**对应文件**：`app/services/warning_service.py:59-83`

```python
def get_transfer_advice(row):
    try:
        suggest_qty = int(float(row["建议调货量"]))
        hq_available_qty = int(float(row["总部可调数量"]))
    except (ValueError, TypeError):
        suggest_qty = 0
        hq_available_qty = 0

    if row["预警状态"] == "红色预警":
        action = "建议立即调货"
    elif row["预警状态"] == "黄色预警":
        action = "建议尽快调货"
    else:
        return "-"

    if hq_available_qty <= 0:
        return f"{action} {suggest_qty} 件；总部暂无可调库存"
    if hq_available_qty < suggest_qty:
        shortage_qty = suggest_qty - hq_available_qty
        return f"{action} {suggest_qty} 件；总部可调 {hq_available_qty} 件，仍缺 {shortage_qty} 件"
    return f"{action} {suggest_qty} 件；总部可满足"
```

---

## 库存计算规则

### 可售天数
**业务规则**：可售天数 = 当前可用量 / 日均销量（无销量时设为 999）

**对应函数**：`analyze_standard_data()`

**对应文件**：`app/services/warning_service.py:15-20`

```python
result_df["可售天数"] = float("inf")
has_sales = result_df["日均销量"] > 0
result_df.loc[has_sales, "可售天数"] = (
    result_df.loc[has_sales, "当前可用量"]
    / result_df.loc[has_sales, "日均销量"]
)
```

---

### 目标库存
**业务规则**：目标库存 = 日均销量 × 7天（安全库存天数）

**对应函数**：`analyze_standard_data()`

**对应文件**：`app/services/warning_service.py:23`

```python
result_df["目标库存"] = result_df["日均销量"] * 7
```

**配置来源**：`app/config.py:29` - `SAFE_DAYS = 7`

---

## 销量计算规则

### Excel 数据源
**业务规则**：近7天销量 = 销售表中该 SKU 的数量总和；日均销量 = 近7天销量 / SAFE_DAYS

**对应函数**：`build_sales_standard_df()`

**对应文件**：`app/data_sources/excel_source.py:47-113`

**特殊处理**：
- 自动检测表头位置（扫描前10行查找"存货编码"）
- 仓库编码格式统一：浮点数 → 整数 → 三位补零字符串（如 6.0 → 6 → "006"）
- 按 WARNING_WAREHOUSE_CODE 筛选仓库
- 使用 `pd.to_numeric(errors="coerce").fillna(0)` 确保数据类型安全

```python
sales_standard_df = (
    sales_df
    .groupby(["存货编码", "存货", "尺码"], as_index=False)["数量"]
    .sum()
)
sales_standard_df = sales_standard_df.rename(columns={"数量": "近7天销量"})
sales_standard_df["日均销量"] = sales_standard_df["近7天销量"] / SAFE_DAYS
```

---

### T+ OpenAPI 数据源
**业务规则**：从销售出库单明细中汇总指定天数内的销量

**对应函数**：`query_recent_sale_delivery_sales()`

**对应文件**：`app/data_sources/tplus_openapi_source.py:223-331`

---

### 数据库数据源
**业务规则**：通过 SQL 聚合查询近 N 天销量

**对应函数**：`build_standard_data_from_database()`

**对应文件**：`app/data_sources/database_source.py:99-162`

---

## 数据来源

### Excel 上传
**数据文件**：
1. 本地库存表（自动检测表头位置）
2. 近期销售表（自动检测表头位置）
3. 总部库存二维表（header=1，存货编码取后11位匹配）

**对应函数**：`build_standard_data()`

**对应文件**：`app/data_sources/excel_source.py:242-264`

**数据合并逻辑**：以销售为主体，LEFT JOIN 库存数据（通过 `build_standard_data_from_frames()` in `base.py`，`already_cleaned=True`）

---

### 数据库直连
**支持数据库**：
- MySQL（pymysql）
- PostgreSQL（psycopg2）
- SQL Server（pyodbc）
- Oracle（oracledb）

**对应函数**：`build_database_url()`

**对应文件**：`app/data_sources/database_source.py:21-49`

---

### T+ OpenAPI
**数据接口**：
- 存货档案查询：`/tplus/api/v2/inventory/Query`
- 现存量查询：`/tplus/api/v2/currentStock/Query`
- 销售出库单列表：`/tplus/api/v2/SaleDeliveryOpenApi/FindVoucherList`
- 销售出库单详情：`/tplus/api/v2/SaleDeliveryOpenApi/GetVoucherDTO`

**对应类**：`TPlusOpenAPIClient`

**对应文件**：`app/data_sources/tplus_openapi_source.py:63-678`

---

## 总部库存参与逻辑

### 总部可调数量计算
**业务规则**：总部可调数量 = min(总部库存, 建议调货量)

**对应函数**：`analyze_standard_data()`

**对应文件**：`app/services/warning_service.py:37-40`

```python
result_df["总部可调数量"] = np.minimum(
    result_df["总部库存"],
    result_df["建议调货量"]
)
```

### 总部库存数据处理
**业务规则**：
- Excel：二维表转一维，存货编码取后11位匹配，按存货编码+尺码汇总
- 数据库：SQL 查询汇总，可通过上传 HQ 文件补充
- T+ API：当前版本总部库存默认为 0（需扩展）

**对应函数**：
- Excel: `build_hq_standard_df()` - `app/data_sources/excel_source.py:178-237`
- 数据库: `build_standard_data_from_frames()` - `app/data_sources/base.py:57-158`
- T+: `build_standard_data_from_tplus_openapi()` - `app/data_sources/tplus_openapi_source.py:680-736`

---

## 仓库筛选逻辑

### 业务规则
只分析指定仓库（默认 006）的库存数据。仓库编码格式统一处理（如 Excel 中的浮点数 6.0 转换为字符串 006）。

**配置项**：`WARNING_WAREHOUSE_CODE = "006"`

**实现位置**：
- Excel 销售表: `app/data_sources/excel_source.py:85-89` - 浮点数转整数再补零
- Excel 库存表: `app/data_sources/base.py:102-105` - 通过 `build_standard_data_from_frames()` 筛选
- 数据库: `app/data_sources/base.py:102-105` - 通过 `build_standard_data_from_frames()` 筛选
- T+: `app/data_sources/tplus_openapi_source.py:841-842` - 现存量筛选；`959-962` - 销售筛选

```python
# Excel 销售表仓库编码处理
sales_df["仓库编码"] = pd.to_numeric(sales_df["仓库编码"], errors="coerce")
sales_df = sales_df[sales_df["仓库编码"].notna()]
sales_df["仓库编码"] = sales_df["仓库编码"].astype(int).astype(str).str.zfill(3)
sales_df = sales_df[sales_df["仓库编码"] == WARNING_WAREHOUSE_CODE]

# 通用筛选
if WARNING_WAREHOUSE_CODE:
    df = df[df["仓库编码"].astype(str).str.strip() == WARNING_WAREHOUSE_CODE]
```

---

## 排序规则

**业务规则**：先按预警状态排序（红色 → 黄色 → 正常），再按可售天数升序

**对应函数**：`analyze_standard_data()`

**对应文件**：`app/services/warning_service.py:87-99`

```python
warning_order = {"红色预警": 0, "黄色预警": 1, "正常": 2}
result_df["排序"] = result_df["预警状态"].map(warning_order)
result_df = result_df.sort_values(by=["排序", "可售天数"])
```
