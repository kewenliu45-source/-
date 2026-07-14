"""T+ 直接分析模式复用 build_standard_data_from_frames 的测试。

不真实调用 T+ API，通过 mock 验证数据流。
"""

import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

from app.data_sources.tplus_openapi_source import build_standard_data_from_tplus_openapi


class TestTPlusBuildStandard(unittest.TestCase):
    """T+ 直接分析走 build_standard_data_from_frames。"""

    def _mock_inventory_records(self):
        """存货档案：包含所有存货（含库存为0的）"""
        return [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
            {"Code": "SKU002", "Name": "商品B", "Specification": "L"},
        ]

    def _mock_stock_records(self):
        """当前库存：SKU002 有库存记录，SKU003 也有但不在存货档案中"""
        return [
            {
                "WarehouseCode": "006",
                "WarehouseName": "销售一库",
                "InventoryCode": "SKU002",
                "InventoryName": "商品B",
                "Specification": "L",
                "ExistingQuantity": 5,
                "AvailableQuantity": 3,
            },
        ]

    def _mock_sales_df(self):
        return pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "近7天销量": 7, "日均销量": 1.0},
        ])

    def _mock_sales_90_df(self):
        return pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
            {"存货编码": "SKU002", "尺码": "L", "近90天销量": 50},
        ])

    def _setup_mock(self, MockClient, mock_90d, stock_records=None):
        instance = MockClient.return_value
        instance.query_inventory.return_value = self._mock_inventory_records()
        instance.query_current_stock.return_value = stock_records or self._mock_stock_records()
        instance.query_recent_sale_delivery_sales.return_value = self._mock_sales_df()
        mock_90d.return_value = self._mock_sales_90_df()

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_calls_build_standard_data_from_frames(self, MockClient, mock_90d):
        """T+ 路径应调用 build_standard_data_from_frames。"""
        self._setup_mock(MockClient, mock_90d)

        with patch(
            "app.data_sources.base.build_standard_data_from_frames"
        ) as mock_frames:
            mock_frames.return_value = pd.DataFrame(columns=[
                "存货编码", "存货", "尺码", "近7天销量", "日均销量", "近90天销量",
                "仓库编码", "仓库", "当前现存量", "当前可用量", "总部库存", "在途仓", "在途（未发货）",
            ])
            build_standard_data_from_tplus_openapi()
            mock_frames.assert_called_once()

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_output_has_all_standard_columns(self, MockClient, mock_90d):
        """T+ 输出应包含全部 13 个标准列。"""
        from app.data_sources.base import STANDARD_COLUMNS
        self._setup_mock(MockClient, mock_90d)

        result = build_standard_data_from_tplus_openapi()

        for col in STANDARD_COLUMNS:
            self.assertIn(col, result.columns, f"缺少标准列: {col}")

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_zero_stock_item_preserved(self, MockClient, mock_90d):
        """存货档案中有但库存表中无的存货应保留（库存填0）。"""
        self._setup_mock(MockClient, mock_90d)

        result = build_standard_data_from_tplus_openapi()

        # SKU001 在存货档案中但不在库存表中 → 应保留，库存为0
        sku1_rows = result[result["存货编码"] == "SKU001"]
        self.assertEqual(len(sku1_rows), 1)
        sku1 = sku1_rows.iloc[0]
        self.assertEqual(sku1["当前现存量"], 0)
        self.assertEqual(sku1["当前可用量"], 0)
        self.assertEqual(sku1["近7天销量"], 14)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_stock_item_with_data(self, MockClient, mock_90d):
        """库存表中有数据的存货应正确合并库存数量。"""
        self._setup_mock(MockClient, mock_90d)

        result = build_standard_data_from_tplus_openapi()

        # SKU002 在库存表中有数据 → 应保留库存数量
        sku2_rows = result[result["存货编码"] == "SKU002"]
        self.assertEqual(len(sku2_rows), 1)
        sku2 = sku2_rows.iloc[0]
        self.assertEqual(sku2["当前现存量"], 5)
        self.assertEqual(sku2["当前可用量"], 3)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_90day_sales_merged(self, MockClient, mock_90d):
        """近90天销量应正确合并到结果中。"""
        self._setup_mock(MockClient, mock_90d)

        result = build_standard_data_from_tplus_openapi()

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["近90天销量"], 100)
        sku2 = result[result["存货编码"] == "SKU002"].iloc[0]
        self.assertEqual(sku2["近90天销量"], 50)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_90day_failure_raises(self, MockClient, mock_90d):
        """近90天销量查询失败时，应抛出异常。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = self._mock_inventory_records()
        instance.query_current_stock.return_value = self._mock_stock_records()
        instance.query_recent_sale_delivery_sales.return_value = self._mock_sales_df()
        mock_90d.side_effect = RuntimeError("T+ API 不可用")

        with self.assertRaises(RuntimeError):
            build_standard_data_from_tplus_openapi()

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_hq_df_passthrough(self, MockClient, mock_90d):
        """hq_df 应透传到 build_standard_data_from_frames。"""
        self._setup_mock(MockClient, mock_90d)

        hq_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "总部库存": 200},
        ])

        result = build_standard_data_from_tplus_openapi(hq_df=hq_df)

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["总部库存"], 200)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_transit_df_passthrough(self, MockClient, mock_90d):
        """transit_df 应透传到 build_standard_data_from_frames。"""
        self._setup_mock(MockClient, mock_90d)

        transit_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 30},
        ])

        result = build_standard_data_from_tplus_openapi(transit_df=transit_df)

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["在途（未发货）"], 30)


class TestTPlusSizeConsistency(unittest.TestCase):
    """T+ 尺码来源一致性问题探测。

    存货档案 / 当前库存 用 Specification 做尺码。
    销货单 用 DynamicPropertyValues[0] 做尺码。
    两者可能不同（如 Specification='M' vs DynamicPropertyValues='150'）。
    """

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_same_sku_should_not_appear_twice_with_different_sizes(self, MockClient, mock_90d):
        """同一 SKU 不应因尺码口径不同而出现在两行。

        存货档案 Specification='M'，销货单 DynamicPropertyValues='150'。
        如果尺码口径不一致，SKU001 会出两行（M 和 150），这是 bug。
        """
        instance = MockClient.return_value
        # 存货档案：Specification = "M"
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        # 当前库存：Specification = "M"，DynamicPropertyValues = "150"（与销货单一致）
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M",
                "DynamicPropertyValues": ["150"],
                "ExistingQuantity": 5, "AvailableQuantity": 3,
            },
        ]
        # 销货单：尺码 = "150"（来自 DynamicPropertyValues，与 Specification 不同）
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "150", "近7天销量": 10, "日均销量": 1.43},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "150", "近90天销量": 80},
        ])

        result = build_standard_data_from_tplus_openapi()

        sku1_rows = result[result["存货编码"] == "SKU001"]
        # 期望：只有一行。实际（bug）：两行（尺码 M 和 150 各一行）
        self.assertEqual(
            len(sku1_rows), 1,
            f"SKU001 应只有 1 行，但出现了 {len(sku1_rows)} 行，"
            f"尺码: {list(sku1_rows['尺码'])}。"
            "原因：存货档案用 Specification 做尺码，销货单用 DynamicPropertyValues，口径不一致。"
        )


class TestTPlusInventoryMasterNotSales(unittest.TestCase):
    """存货档案的 MinStockQuantity 不应被当作近7天销量。"""

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_min_stock_quantity_not_treated_as_sales(self, MockClient, mock_90d):
        """MinStockQuantity=20 但无销售记录时，近7天销量应为 0，不是 20。

        _build_inventory_master_df 把 MinStockQuantity 写入 近7天销量 列。
        当 sales_df 为空且走 sales_df=None 分支时，这个假销量会被保留。
        """
        instance = MockClient.return_value
        # 存货档案：MinStockQuantity = 20（安全库存，不是真实销量）
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M",
             "MinStockQuantity": 20},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
        ]
        # 销货单：没有 SKU001 的销售记录
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame(
            columns=["存货编码", "存货", "尺码", "近7天销量", "日均销量"]
        )
        mock_90d.return_value = None

        result = build_standard_data_from_tplus_openapi()

        sku1 = result[result["存货编码"] == "SKU001"]
        self.assertEqual(len(sku1), 1, "SKU001 应出现 1 行")
        # 期望：近7天销量=0。实际（bug）：近7天销量=20（来自 MinStockQuantity）
        self.assertEqual(
            sku1.iloc[0]["近7天销量"], 0,
            "近7天销量不应取 MinStockQuantity（安全库存），无销售记录时应为 0"
        )
        self.assertEqual(
            sku1.iloc[0]["日均销量"], 0,
            "日均销量不应基于 MinStockQuantity 计算"
        )


class TestTPlusZeroStockPreserved(unittest.TestCase):
    """零库存 SKU 保留测试。"""

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_sku_in_inventory_not_in_stock_or_sales_is_preserved(self, MockClient, mock_90d):
        """存货档案有 SKU002，但库存和销售都没有 → 应保留，库存=0，销量=0。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
            {"Code": "SKU002", "Name": "商品B", "Specification": "L"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        result = build_standard_data_from_tplus_openapi()

        sku2_rows = result[result["存货编码"] == "SKU002"]
        self.assertEqual(len(sku2_rows), 1, "SKU002 应保留在结果中")
        sku2 = sku2_rows.iloc[0]
        self.assertEqual(sku2["当前现存量"], 0)
        self.assertEqual(sku2["当前可用量"], 0)
        self.assertEqual(sku2["近7天销量"], 0)


class TestTPlusMultiSizeNotLost(unittest.TestCase):
    """同一存货编码多尺码不能丢。"""

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_multi_size_inventory_preserved_when_only_one_size_has_sales(self, MockClient, mock_90d):
        """存货档案有 SKU001/M 和 SKU001/L，销售只覆盖 M → L 仍应保留。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
            {"Code": "SKU001", "Name": "商品A", "Specification": "L"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        result = build_standard_data_from_tplus_openapi()

        sku1_rows = result[result["存货编码"] == "SKU001"]
        sizes = set(sku1_rows["尺码"])
        # 期望：两个尺码都在。判断基于 存货编码+尺码，不只按存货编码。
        self.assertIn("M", sizes, "尺码 M 应保留")
        self.assertIn("L", sizes, "尺码 L 应保留（来自存货档案，无销售但应保留）")


class TestTPlusTransitDfBuilder(unittest.TestCase):
    """_build_tplus_transit_df 标准化测试。"""

    def test_aggregates_same_code_size(self):
        """同一 存货编码+尺码 多条记录：数量求和，在途仓去重拼接。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_df

        records = [
            {"InventoryCode": "SKU001", "Specification": "M", "TransitWarehouse": "工厂仓A", "Quantity": 10},
            {"InventoryCode": "SKU001", "Specification": "M", "TransitWarehouse": "工厂仓B", "Quantity": 5},
            {"InventoryCode": "SKU001", "Specification": "M", "TransitWarehouse": "工厂仓A", "Quantity": 3},
        ]

        result = _build_tplus_transit_df(records)

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["存货编码"], "SKU001")
        self.assertEqual(row["在途（未发货）"], 18)  # 10+5+3
        # 在途仓去重拼接（排序后）
        self.assertIn("工厂仓A", row["在途仓"])
        self.assertIn("工厂仓B", row["在途仓"])

    def test_filters_zero_quantity(self):
        """在途数量 <= 0 的行应被过滤。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_df

        records = [
            {"InventoryCode": "SKU001", "Specification": "M", "TransitWarehouse": "工厂仓", "Quantity": 0},
            {"InventoryCode": "SKU002", "Specification": "L", "TransitWarehouse": "工厂仓", "Quantity": -5},
        ]

        result = _build_tplus_transit_df(records)

        self.assertEqual(len(result), 0)

    def test_empty_records_returns_empty_df(self):
        """空记录返回空 DataFrame，列结构正确。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_df

        result = _build_tplus_transit_df([])

        self.assertEqual(len(result), 0)
        for col in ["存货编码", "尺码", "在途仓", "在途（未发货）"]:
            self.assertIn(col, result.columns)

    def test_uses_dynamic_property_values_for_size(self):
        """尺码优先取 DynamicPropertyValues。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_df

        records = [
            {"InventoryCode": "SKU001", "Specification": "M", "DynamicPropertyValues": ["150"],
             "TransitWarehouse": "工厂仓", "Quantity": 10},
        ]

        result = _build_tplus_transit_df(records)

        self.assertEqual(result.iloc[0]["尺码"], "150")


class TestTPlusTransitFromStock(unittest.TestCase):
    """T+ 在途数据从 currentStock/Query 仓库维度拆分。"""

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_transit_warehouse_quantity_from_stock(self, MockClient, mock_90d):
        """T+ 在途仓数量来自 currentStock ExistingQuantity。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 30, "AvailableQuantity": 0,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        result = build_standard_data_from_tplus_openapi()

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        # 销售仓数据
        self.assertEqual(sku1["当前现存量"], 10)
        self.assertEqual(sku1["当前可用量"], 8)
        # 在途仓 = T+ currentStock 在途仓的 ExistingQuantity
        self.assertEqual(sku1["在途仓"], 30)
        # 在途（未发货）：无人工 transit_df，为 0
        self.assertEqual(sku1["在途（未发货）"], 0)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_transit_warehouse_with_manual_transit(self, MockClient, mock_90d):
        """T+ 在途仓数量 + 人工 transit_df 在途（未发货）数量。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 30, "AvailableQuantity": 0,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        manual_transit = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 5},
        ])

        result = build_standard_data_from_tplus_openapi(transit_df=manual_transit)

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        # 在途仓 = T+ currentStock 在途仓数量
        self.assertEqual(sku1["在途仓"], 30)
        # 在途（未发货） = 人工 transit_df 数量
        self.assertEqual(sku1["在途（未发货）"], 5)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_no_transit_records_gives_zero(self, MockClient, mock_90d):
        """没有在途仓记录时，在途仓=0，在途（未发货）=0。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        result = build_standard_data_from_tplus_openapi()

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["在途仓"], 0)
        self.assertEqual(sku1["在途（未发货）"], 0)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_transit_by_warehouse_code_config(self, MockClient, mock_90d):
        """通过 TPLUS_TRANSIT_WAREHOUSE_CODES 配置识别在途仓，数量来自 ExistingQuantity。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
            {
                "WarehouseCode": "ZT01", "WarehouseName": "某仓库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 25, "AvailableQuantity": 0,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        with patch("app.data_sources.tplus_openapi_source.TPLUS_TRANSIT_WAREHOUSE_CODES", ["ZT01"]):
            result = build_standard_data_from_tplus_openapi()

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        # 在途仓 = T+ 在途仓 ExistingQuantity
        self.assertEqual(sku1["在途仓"], 25)
        self.assertEqual(sku1["在途（未发货）"], 0)

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_transit_aggregates_multiple_records(self, MockClient, mock_90d):
        """同一 SKU+尺码 多条在途仓记录，数量求和。"""
        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 20,
            },
            {
                "WarehouseCode": "009", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 15,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        result = build_standard_data_from_tplus_openapi()

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        # 在途仓 = 20 + 15 = 35
        self.assertEqual(sku1["在途仓"], 35)


class TestBuildTransitFromStockDf(unittest.TestCase):
    """_build_tplus_transit_from_stock_df 单元测试。

    在途仓 = T+ currentStock 在途仓的 ExistingQuantity（数值）。
    在途（未发货） = 0（来自人工 transit_df）。
    """

    def test_mixed_warehouses_split_correctly(self):
        """销售一库和在途仓混合记录，只取在途仓数量。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        records = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "Specification": "M",
                "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "Specification": "M",
                "ExistingQuantity": 30, "AvailableQuantity": 0,
            },
        ]

        result = _build_tplus_transit_from_stock_df(records)

        self.assertEqual(len(result), 1)
        row = result.iloc[0]
        self.assertEqual(row["存货编码"], "SKU001")
        # 在途仓 = ExistingQuantity
        self.assertEqual(row["在途仓"], 30)
        # 在途（未发货） = 0
        self.assertEqual(row["在途（未发货）"], 0)

    def test_aggregates_multiple_transit_records(self):
        """同一 SKU+尺码 多条在途仓记录，数量求和。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        records = [
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "Specification": "M",
                "ExistingQuantity": 20,
            },
            {
                "WarehouseCode": "009", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "Specification": "M",
                "ExistingQuantity": 15,
            },
        ]

        result = _build_tplus_transit_from_stock_df(records)

        self.assertEqual(len(result), 1)
        # 在途仓 = 20 + 15 = 35
        self.assertEqual(result.iloc[0]["在途仓"], 35)
        self.assertEqual(result.iloc[0]["在途（未发货）"], 0)

    def test_empty_records_returns_empty_df(self):
        """空记录返回空 DataFrame，列结构正确。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        result = _build_tplus_transit_from_stock_df([])

        self.assertEqual(len(result), 0)
        for col in ["存货编码", "尺码", "在途仓", "在途（未发货）"]:
            self.assertIn(col, result.columns)

    def test_no_transit_warehouses_returns_empty(self):
        """所有记录都是销售仓时，返回空。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        records = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "Specification": "M",
                "ExistingQuantity": 10,
            },
        ]

        result = _build_tplus_transit_from_stock_df(records)

        self.assertEqual(len(result), 0)

    def test_uses_dynamic_property_values_for_size(self):
        """尺码优先取 DynamicPropertyValues。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        records = [
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "Specification": "M",
                "DynamicPropertyValues": ["150"],
                "ExistingQuantity": 30,
            },
        ]

        result = _build_tplus_transit_from_stock_df(records)

        self.assertEqual(result.iloc[0]["尺码"], "150")
        self.assertEqual(result.iloc[0]["在途仓"], 30)

    def test_uses_quantity_fallback(self):
        """ExistingQuantity 不存在时，使用 Quantity。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        records = [
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "Specification": "M",
                "Quantity": 25,
            },
        ]

        result = _build_tplus_transit_from_stock_df(records)

        self.assertEqual(result.iloc[0]["在途仓"], 25)

    def test_quantity_is_numeric(self):
        """在途仓是数值字段，不是文本。"""
        from app.data_sources.tplus_openapi_source import _build_tplus_transit_from_stock_df

        records = [
            {
                "WarehouseCode": "008", "WarehouseName": "在途仓",
                "InventoryCode": "SKU001", "Specification": "M",
                "ExistingQuantity": 30,
            },
        ]

        result = _build_tplus_transit_from_stock_df(records)

        self.assertIsInstance(result.iloc[0]["在途仓"], (int, float))
        self.assertEqual(result.iloc[0]["在途仓"], 30)


class TestDatabaseSourcePassthrough(unittest.TestCase):
    """build_standard_data_from_database 透传 hq_df/transit_df 到 T+ 函数。"""

    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    @patch("app.data_sources.database_source.DB_TYPE", "tplus")
    def test_hq_df_and_transit_df_passed_through(self, MockClient, mock_90d):
        from app.data_sources.database_source import build_standard_data_from_database

        instance = MockClient.return_value
        instance.query_inventory.return_value = [
            {"Code": "SKU001", "Name": "商品A", "Specification": "M"},
        ]
        instance.query_current_stock.return_value = [
            {
                "WarehouseCode": "006", "WarehouseName": "销售一库",
                "InventoryCode": "SKU001", "InventoryName": "商品A",
                "Specification": "M", "ExistingQuantity": 10, "AvailableQuantity": 8,
            },
        ]
        instance.query_recent_sale_delivery_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        hq_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "总部库存": 50}])
        transit_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 10}])

        result = build_standard_data_from_database(hq_df=hq_df, transit_df=transit_df)

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["总部库存"], 50)
        self.assertEqual(sku1["在途（未发货）"], 10)


class TestTPlusPagingDiagnostic(unittest.TestCase):
    """test_tplus_inventory_and_stock_paging 诊断函数测试。"""

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_diagnostic_handles_dict_response_with_pagination(self, MockClient):
        """response 为 dict 时，提取分页字段和 records。"""
        from app.data_sources.tplus_openapi_source import test_tplus_inventory_and_stock_paging

        instance = MockClient.return_value
        instance._request.side_effect = [
            {"data": {"rows": [{"Code": "SKU001", "Name": "A"}], "TotalCount": 500, "TotalPageNum": 3}},
            {"data": {"rows": [{"WarehouseCode": "006", "WarehouseName": "销售一库", "InventoryCode": "SKU001", "ExistingQuantity": 10}], "TotalCount": 1000, "TotalPageNum": 5}},
        ]

        result = test_tplus_inventory_and_stock_paging()

        self.assertIn("inventory", result)
        self.assertIn("stock", result)
        self.assertEqual(result["inventory"]["response_type"], "dict")
        self.assertEqual(result["inventory"]["records_count"], 1)
        self.assertEqual(result["inventory"].get("TotalCount"), 500)
        self.assertEqual(result["inventory"].get("TotalPageNum"), 3)
        self.assertEqual(result["stock"]["records_count"], 1)
        self.assertEqual(result["stock"].get("TotalCount"), 1000)
        self.assertEqual(result["stock"].get("TotalPageNum"), 5)

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_diagnostic_handles_list_response(self, MockClient):
        """response 为 list 时，直接作为 records，分页字段为 None。"""
        from app.data_sources.tplus_openapi_source import test_tplus_inventory_and_stock_paging

        instance = MockClient.return_value
        instance._request.side_effect = [
            [{"Code": "SKU001", "Name": "A"}, {"Code": "SKU002", "Name": "B"}],
            [{"WarehouseCode": "006", "WarehouseName": "销售一库", "InventoryCode": "SKU001", "ExistingQuantity": 10}],
        ]

        result = test_tplus_inventory_and_stock_paging()

        self.assertEqual(result["inventory"]["response_type"], "list")
        self.assertEqual(result["inventory"]["records_count"], 2)
        self.assertEqual(result["inventory"].get("TotalCount"), None)
        self.assertEqual(result["inventory"].get("TotalPageNum"), None)
        self.assertEqual(result["stock"]["records_count"], 1)

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_diagnostic_returns_all_sections(self, MockClient):
        """诊断函数应返回四个诊断区段。"""
        from app.data_sources.tplus_openapi_source import test_tplus_inventory_and_stock_paging

        instance = MockClient.return_value
        instance._request.side_effect = [
            {"data": {"rows": [], "TotalCount": 500, "TotalPageNum": 3}},
            {"data": {"rows": [], "TotalCount": 1000, "TotalPageNum": 5}},
        ]

        result = test_tplus_inventory_and_stock_paging()

        self.assertIn("inventory", result)
        self.assertIn("stock", result)
        self.assertIn("stock_distribution", result)
        self.assertIn("dataframes", result)
        self.assertEqual(result["inventory"].get("TotalCount"), 500)
        self.assertEqual(result["stock"].get("TotalPageNum"), 5)
        self.assertIn("inventory_master_df_rows", result["dataframes"])
        self.assertIn("stock_df_rows", result["dataframes"])
        self.assertIn("transit_df_rows", result["dataframes"])


class TestTPlusInventoryPagingCandidates(unittest.TestCase):
    """test_tplus_inventory_paging_candidates 诊断函数测试。"""

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_returns_results_for_all_candidates(self, MockClient):
        """应返回 5 种尝试的结果。"""
        from app.data_sources.tplus_openapi_source import test_tplus_inventory_paging_candidates

        instance = MockClient.return_value
        # 每种 body 格式都返回一个响应
        instance._request.return_value = {"data": {"rows": [{"Code": "SKU001"}], "TotalCount": 500}}

        results = test_tplus_inventory_paging_candidates()

        self.assertEqual(len(results), 5)
        for r in results:
            self.assertIn("label", r)
            self.assertIn("body", r)
            self.assertIn("response_type", r)
            self.assertIn("records_count", r)

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_handles_list_response(self, MockClient):
        """response 为 list 时应正确解析。"""
        from app.data_sources.tplus_openapi_source import test_tplus_inventory_paging_candidates

        instance = MockClient.return_value
        instance._request.return_value = [{"Code": "SKU001"}, {"Code": "SKU002"}]

        results = test_tplus_inventory_paging_candidates()

        # 所有 5 种都应返回 list response
        for r in results:
            self.assertEqual(r["response_type"], "list")
            self.assertEqual(r["records_count"], 2)

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_handles_api_error(self, MockClient):
        """接口报错时应捕获并记录。"""
        from app.data_sources.tplus_openapi_source import test_tplus_inventory_paging_candidates

        instance = MockClient.return_value
        instance._request.side_effect = RuntimeError("EXSV0011: 服务名不匹配")

        results = test_tplus_inventory_paging_candidates()

        for r in results:
            self.assertIn("error", r)
            self.assertIn("EXSV0011", r["error"])


class TestTPlusWarehouseQueryCandidates(unittest.TestCase):
    """test_tplus_warehouse_query_candidates 诊断函数测试。"""

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_probes_all_candidate_endpoints(self, MockClient):
        """应探测 4 个候选接口。"""
        from app.data_sources.tplus_openapi_source import test_tplus_warehouse_query_candidates

        instance = MockClient.return_value
        instance._request.return_value = {"data": []}

        results = test_tplus_warehouse_query_candidates()

        self.assertEqual(len(results), 4)
        endpoints = [r["endpoint"] for r in results]
        self.assertIn("/tplus/api/v2/warehouse/Query", endpoints)
        self.assertIn("/tplus/api/v2/Warehouse/Query", endpoints)

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_handles_records_as_list(self, MockClient):
        """response 为 list 时应正确解析记录。"""
        from app.data_sources.tplus_openapi_source import test_tplus_warehouse_query_candidates

        instance = MockClient.return_value
        instance._request.return_value = [
            {"Code": "006", "Name": "销售一库"},
            {"Code": "ZT01", "Name": "在途仓"},
        ]

        results = test_tplus_warehouse_query_candidates()

        # 所有接口都返回 list
        for r in results:
            if "error" not in r:
                self.assertEqual(r["records_count"], 2)


class TestTPlusStockWithWarehouseFilter(unittest.TestCase):
    """test_tplus_stock_with_warehouse_filter 诊断函数测试。"""

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_probes_with_warehouse_code(self, MockClient):
        """传入 warehouse_code 时应尝试 4 种 body（3 种编码 + 1 种名称）。"""
        from app.data_sources.tplus_openapi_source import test_tplus_stock_with_warehouse_filter

        instance = MockClient.return_value
        instance._request.return_value = {"data": []}

        results = test_tplus_stock_with_warehouse_filter(warehouse_code="ZT01", warehouse_name="在途仓")

        self.assertEqual(len(results), 4)
        labels = [r["label"] for r in results]
        self.assertTrue(any("WarehouseCode=ZT01" in l for l in labels))
        self.assertTrue(any("WarehouseName=在途仓" in l for l in labels))

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_probes_with_name_only(self, MockClient):
        """只传 warehouse_name 时应只尝试名称查询。"""
        from app.data_sources.tplus_openapi_source import test_tplus_stock_with_warehouse_filter

        instance = MockClient.return_value
        instance._request.return_value = {"data": []}

        results = test_tplus_stock_with_warehouse_filter(warehouse_code="", warehouse_name="在途仓")

        self.assertEqual(len(results), 1)
        self.assertIn("WarehouseName=在途仓", results[0]["label"])

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_no_candidates_returns_empty(self, MockClient):
        """warehouse_code 和 warehouse_name 都为空时返回空。"""
        from app.data_sources.tplus_openapi_source import test_tplus_stock_with_warehouse_filter

        results = test_tplus_stock_with_warehouse_filter(warehouse_code="", warehouse_name="")

        self.assertEqual(len(results), 0)

    @patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient")
    def test_handles_list_response(self, MockClient):
        """response 为 list 时应正确解析。"""
        from app.data_sources.tplus_openapi_source import test_tplus_stock_with_warehouse_filter

        instance = MockClient.return_value
        instance._request.return_value = [
            {"WarehouseCode": "ZT01", "WarehouseName": "在途仓", "InventoryCode": "SKU001", "ExistingQuantity": 30},
        ]

        results = test_tplus_stock_with_warehouse_filter(warehouse_code="ZT01", warehouse_name="在途仓")

        for r in results:
            if "error" not in r:
                self.assertEqual(r["records_count"], 1)


class TestQueryInventoryPagination(unittest.TestCase):
    """query_inventory 分页测试。"""

    def test_single_page(self):
        """单页能返回全部记录。"""
        from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
        records = [
            {"Code": "SKU001", "Name": "商品A"},
            {"Code": "SKU002", "Name": "商品B"},
        ]
        client = TPlusOpenAPIClient()
        client._request = MagicMock(return_value=records)
        client._extract_records = MagicMock(return_value=records)
        client._extract_total_count = MagicMock(return_value=None)

        result = client.query_inventory()

        self.assertEqual(len(result), 2)
        call_body = client._request.call_args[1]["json"]
        self.assertIn("PageIndex", call_body["param"])
        self.assertIn("PageSize", call_body["param"])

    def test_multi_page(self):
        """多页应循环翻页直到拿完（TPLUS_QUERY_PAGE_SIZE=100）。"""
        from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
        from app.config import TPLUS_QUERY_PAGE_SIZE
        page1 = [{"Code": f"SKU{i:03d}"} for i in range(TPLUS_QUERY_PAGE_SIZE)]
        page2 = [{"Code": f"SKU{i:03d}"} for i in range(TPLUS_QUERY_PAGE_SIZE, TPLUS_QUERY_PAGE_SIZE + 50)]

        client = TPlusOpenAPIClient()
        client._request = MagicMock(side_effect=[page1, page2])
        client._extract_records = MagicMock(side_effect=[page1, page2])
        client._extract_total_count = MagicMock(return_value=None)

        result = client.query_inventory()

        self.assertEqual(len(result), TPLUS_QUERY_PAGE_SIZE + 50)
        self.assertEqual(client._request.call_count, 2)
        second_call_body = client._request.call_args_list[1][1]["json"]
        self.assertEqual(second_call_body["param"]["PageIndex"], 2)

    def test_stops_when_page_smaller_than_page_size(self):
        """当返回条数 < PageSize 时停止翻页。"""
        from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
        from app.config import TPLUS_QUERY_PAGE_SIZE
        page1 = [{"Code": f"SKU{i:03d}"} for i in range(TPLUS_QUERY_PAGE_SIZE)]
        page2 = [{"Code": f"SKU{i:03d}"} for i in range(TPLUS_QUERY_PAGE_SIZE, TPLUS_QUERY_PAGE_SIZE + 20)]

        client = TPlusOpenAPIClient()
        client._request = MagicMock(side_effect=[page1, page2])
        client._extract_records = MagicMock(side_effect=[page1, page2])
        client._extract_total_count = MagicMock(return_value=None)

        result = client.query_inventory()

        self.assertEqual(len(result), TPLUS_QUERY_PAGE_SIZE + 20)
        self.assertEqual(client._request.call_count, 2)

    def test_preserves_base_body(self):
        """分页参数应追加到 base_body 的 param 内，不丢失原有字段。"""
        from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
        records = [{"Code": "SKU001"}]
        client = TPlusOpenAPIClient()
        client._request = MagicMock(return_value=records)
        client._extract_records = MagicMock(return_value=records)
        client._extract_total_count = MagicMock(return_value=None)

        client.query_inventory()

        call_body = client._request.call_args[1]["json"]
        self.assertIn("SelectFields", call_body["param"])
        self.assertEqual(call_body["param"]["PageIndex"], 1)


class TestQueryCurrentStock(unittest.TestCase):
    """query_current_stock 测试（不分页，返回全部记录）。"""

    def test_returns_all_records(self):
        """currentStock 应返回全部记录，不做分页。"""
        from app.data_sources.tplus_openapi_source import TPlusOpenAPIClient
        records = [
            {"WarehouseCode": "006", "WarehouseName": "销售一库", "InventoryCode": "SKU001", "ExistingQuantity": 10},
            {"WarehouseCode": "020", "WarehouseName": "在途仓", "InventoryCode": "SKU001", "ExistingQuantity": 30},
        ]
        client = TPlusOpenAPIClient()
        client._request = MagicMock(return_value=records)
        client._extract_records = MagicMock(return_value=records)
        client._extract_total_count = MagicMock(return_value=None)

        result = client.query_current_stock()

        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()
