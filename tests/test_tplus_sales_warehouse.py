import unittest
from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd

from app.data_sources.tplus_openapi_source import (
    TPlusOpenAPIClient,
    _build_recent_sales_summary_df,
    _parse_date,
    REPORT_QUERY_ENDPOINT,
    SALE_REPORT_NAME,
    SALE_REPORT_COLUMNS,
)


class TPlusSalesWarehouseTests(unittest.TestCase):
    def test_recent_sales_summary_only_counts_warning_warehouse_when_available(self):
        rows = [
            {"存货编码": "15C1010000", "尺码": "150", "销售数量": 6, "仓库编码": "006"},
            {"存货编码": "15C1010000", "尺码": "150", "销售数量": 2, "仓库编码": "018"},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["存货编码"], "15C1010000")
        self.assertEqual(result.iloc[0]["尺码"], "150")
        self.assertEqual(result.iloc[0]["近7天销量"], 6)

    def test_parse_date_formats(self):
        """测试日期解析支持多种格式"""
        self.assertEqual(_parse_date("2026-07-13"), date(2026, 7, 13))
        self.assertEqual(_parse_date("2026-07-13 10:30:00"), date(2026, 7, 13))
        self.assertIsNone(_parse_date(""))
        self.assertIsNone(_parse_date(None))

    def test_report_query_endpoint_and_report_name(self):
        """测试报表接口常量正确"""
        self.assertEqual(REPORT_QUERY_ENDPOINT, "/tplus/api/v2/reportQuery/GetReportData")
        self.assertEqual(SALE_REPORT_NAME, "SA_SaleDeliveryDetailRpt")
        self.assertIn("voucherdate", SALE_REPORT_COLUMNS)
        self.assertIn("inventoryCode", SALE_REPORT_COLUMNS)
        self.assertIn("FreeItem0", SALE_REPORT_COLUMNS)
        self.assertIn("quantity", SALE_REPORT_COLUMNS)
        self.assertIn("warehouseCode", SALE_REPORT_COLUMNS)

    def test_report_query_request_format(self):
        """测试报表查询请求格式正确"""
        rows = [
            {
                "voucherdate": "2026-07-13",
                "inventoryCode": "SKU001",
                "inventoryName": "商品A",
                "specification": "",
                "FreeItem0": "M",
                "quantity": "10",
                "warehouseCode": "006",
                "warehouseName": "销售一库",
            }
        ]

        client = TPlusOpenAPIClient()
        client._fetch_report_data = MagicMock(return_value=rows)

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            result = client.query_recent_sale_delivery_sales(
                days=7,
                end_date=date(2026, 7, 13),
                force_refresh=True,
            )

        # 验证 _fetch_report_data 被调用
        client._fetch_report_data.assert_called_once()
        call_args = client._fetch_report_data.call_args

        # 验证 endpoint
        self.assertEqual(call_args.kwargs.get("report_name") or call_args[1].get("report_name"), SALE_REPORT_NAME)

        # 验证 ReportTableColNames
        self.assertEqual(call_args.kwargs.get("columns") or call_args[1].get("columns"), SALE_REPORT_COLUMNS)

    def test_report_query_with_warehouse_filter(self):
        """测试报表查询包含仓库过滤条件"""
        client = TPlusOpenAPIClient()
        client._fetch_report_data = MagicMock(return_value=[])

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            client.query_recent_sale_delivery_sales(
                days=7,
                end_date=date(2026, 7, 13),
                force_refresh=True,
            )

        # 验证查询条件包含仓库过滤
        call_args = client._fetch_report_data.call_args
        search_items = call_args.kwargs.get("search_items") or call_args[1].get("search_items")
        warehouse_items = [item for item in search_items if item.get("ColumnName") == "warehouseCode"]
        self.assertEqual(len(warehouse_items), 1)
        self.assertEqual(warehouse_items[0]["BeginDefault"], "006")
        self.assertEqual(warehouse_items[0]["EndDefault"], "006")

    def test_report_query_date_range_7days(self):
        """测试7天报表查询日期范围正确"""
        client = TPlusOpenAPIClient()
        client._fetch_report_data = MagicMock(return_value=[])

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            client.query_recent_sale_delivery_sales(
                days=7,
                end_date=date(2026, 7, 13),
                force_refresh=True,
            )

        # 验证日期范围
        call_args = client._fetch_report_data.call_args
        search_items = call_args.kwargs.get("search_items") or call_args[1].get("search_items")
        date_items = [item for item in search_items if item.get("ColumnName") == "voucherdate"]
        self.assertEqual(len(date_items), 1)
        self.assertEqual(date_items[0]["BeginDefault"], "2026-07-07")
        self.assertEqual(date_items[0]["EndDefault"], "2026-07-13")

    def test_report_query_date_range_90days(self):
        """测试90天报表查询日期范围正确"""
        from datetime import timedelta

        client = TPlusOpenAPIClient()
        client._fetch_report_data = MagicMock(return_value=[])

        end_date = date(2026, 7, 13)
        expected_start = end_date - timedelta(days=89)  # 90-1=89

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            client.query_recent_sale_delivery_sales(
                days=90,
                end_date=end_date,
                force_refresh=True,
                column_name="近90天销量",
            )

        # 验证日期范围
        call_args = client._fetch_report_data.call_args
        search_items = call_args.kwargs.get("search_items") or call_args[1].get("search_items")
        date_items = [item for item in search_items if item.get("ColumnName") == "voucherdate"]
        self.assertEqual(len(date_items), 1)
        self.assertEqual(date_items[0]["BeginDefault"], expected_start.isoformat())
        self.assertEqual(date_items[0]["EndDefault"], end_date.isoformat())

    def test_negative_quantity_included_in_summary(self):
        """退货负数参与汇总"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 10, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "M", "销售数量": -3, "仓库编码": "006"},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 7)  # 10 + (-3) = 7

    def test_negative_total_clipped_to_zero(self):
        """汇总后负数归零"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": -5, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "M", "销售数量": -3, "仓库编码": "006"},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 0)  # clip(lower=0)

    def test_sku_size_grouping(self):
        """多条明细按 SKU+尺码汇总"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 5, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 3, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "L", "销售数量": 2, "仓库编码": "006"},
            {"存货编码": "SKU002", "尺码": "M", "销售数量": 1, "仓库编码": "006"},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        self.assertEqual(len(result), 3)
        sku1_m = result[(result["存货编码"] == "SKU001") & (result["尺码"] == "M")]
        self.assertEqual(sku1_m.iloc[0]["近7天销量"], 8)

    def test_empty_result_format(self):
        """空结果返回正确格式"""
        result = _build_recent_sales_summary_df([], days=7)

        self.assertEqual(len(result), 0)
        self.assertIn("存货编码", result.columns)
        self.assertIn("尺码", result.columns)
        self.assertIn("近7天销量", result.columns)
        self.assertIn("日均销量", result.columns)

    def test_daily_sales_calculation(self):
        """日均销量计算正确"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 14, "仓库编码": "006"},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        self.assertAlmostEqual(result.iloc[0]["日均销量"], 2.0)

    def test_warehouse_local_filter_strict(self):
        """仓库本地过滤：只保留 WARNING_WAREHOUSE_CODE 匹配的记录"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 10, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 5, "仓库编码": "018"},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        # 只保留 006 仓库的数据
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 10)

    def test_warehouse_empty_code_filtered(self):
        """仓库编码为空时必须丢弃"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 10, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 5, "仓库编码": ""},
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        # 只保留 006 仓库的数据，空仓库编码被过滤
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 10)

    def test_warehouse_missing_code_filtered(self):
        """仓库字段缺失时必须丢弃"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 10, "仓库编码": "006"},
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 5},  # 缺少仓库编码
        ]

        result = _build_recent_sales_summary_df(rows, days=7)

        # 只保留 006 仓库的数据，缺失仓库编码被过滤
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 10)


class TestReportQueryIntegration(unittest.TestCase):
    """测试报表接口集成"""

    def test_fetch_report_data_pagination(self):
        """测试报表分页查询"""
        client = TPlusOpenAPIClient()
        client._request = MagicMock()

        # 模拟两页数据
        page1_rows = [{"voucherdate": "2026-07-13", "inventoryCode": "SKU001", "quantity": "10"}] * 1000
        page2_rows = [{"voucherdate": "2026-07-12", "inventoryCode": "SKU002", "quantity": "5"}] * 500
        client._request.side_effect = [
            {"DataSource": {"Rows": page1_rows}},
            {"DataSource": {"Rows": page2_rows}},
        ]

        result = client._fetch_report_data(
            report_name="SA_SaleDeliveryDetailRpt",
            columns="voucherdate,inventoryCode,quantity",
            search_items=[],
        )

        self.assertEqual(len(result), 1500)
        self.assertEqual(client._request.call_count, 2)

    def test_fetch_report_data_empty_first_page(self):
        """测试第一页为空时返回空列表"""
        client = TPlusOpenAPIClient()
        client._request = MagicMock(return_value={"DataSource": {"Rows": []}})

        result = client._fetch_report_data(
            report_name="SA_SaleDeliveryDetailRpt",
            columns="voucherdate,inventoryCode,quantity",
            search_items=[],
        )

        self.assertEqual(len(result), 0)
        self.assertEqual(client._request.call_count, 1)

    def test_fetch_report_data_missing_datasource_raises(self):
        """测试 DataSource 缺失时抛出异常"""
        client = TPlusOpenAPIClient()
        client._request = MagicMock(return_value={"error": "some error"})

        with self.assertRaises(RuntimeError) as cm:
            client._fetch_report_data(
                report_name="SA_SaleDeliveryDetailRpt",
                columns="voucherdate,inventoryCode,quantity",
                search_items=[],
            )

        self.assertIn("DataSource", str(cm.exception))

    def test_fetch_report_data_missing_rows_raises(self):
        """测试 Rows 缺失时抛出异常"""
        client = TPlusOpenAPIClient()
        client._request = MagicMock(return_value={"DataSource": {"Columns": []}})

        with self.assertRaises(RuntimeError) as cm:
            client._fetch_report_data(
                report_name="SA_SaleDeliveryDetailRpt",
                columns="voucherdate,inventoryCode,quantity",
                search_items=[],
            )

        self.assertIn("Rows", str(cm.exception))

    def test_fetch_report_data_second_page_failure_raises(self):
        """测试第二页失败时抛出异常，不返回第一页数据"""
        client = TPlusOpenAPIClient()
        client._request = MagicMock()

        # 第一页成功，第二页失败
        client._request.side_effect = [
            {"DataSource": {"Rows": [{"voucherdate": "2026-07-13"}] * 1000}},
            RuntimeError("网络错误"),
        ]

        with self.assertRaises(RuntimeError):
            client._fetch_report_data(
                report_name="SA_SaleDeliveryDetailRpt",
                columns="voucherdate,inventoryCode,quantity",
                search_items=[],
            )

    def test_second_page_failure_no_cache_write(self):
        """第二页失败时不得调用 _write_recent_sales_cache"""
        client = TPlusOpenAPIClient()
        client._request = MagicMock()

        # 第一页成功，第二页失败
        client._request.side_effect = [
            {"DataSource": {"Rows": [{"voucherdate": "2026-07-13", "inventoryCode": "SKU001", "quantity": "10", "warehouseCode": "006"}] * 1000}},
            RuntimeError("网络错误"),
        ]

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache") as mock_cache:
            with self.assertRaises(RuntimeError):
                client.query_recent_sale_delivery_sales(
                    days=7,
                    end_date=date(2026, 7, 13),
                    force_refresh=True,
                )

            # 验证缓存写入未被调用
            mock_cache.assert_not_called()


class TestNoOldApiCalls(unittest.TestCase):
    """测试生产查询不调用旧接口"""

    def test_no_find_voucher_list_call(self):
        """query_recent_sale_delivery_sales 不调用 FindVoucherList/GetVoucherDTO"""
        client = TPlusOpenAPIClient()
        client._fetch_report_data = MagicMock(return_value=[])

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            client.query_recent_sale_delivery_sales(
                days=7,
                end_date=date(2026, 7, 13),
                force_refresh=True,
            )

        # 验证没有调用旧接口（这些方法已被删除，但确认 mock 不存在）
        self.assertFalse(hasattr(client, 'find_sale_delivery_list'))
        self.assertFalse(hasattr(client, 'get_sale_delivery_detail'))
        self.assertFalse(hasattr(client, '_find_sale_delivery_list_response'))


class TestColumnNameParameter(unittest.TestCase):
    """测试 column_name 参数和 query_90day_sales"""

    def test_column_name_default_is_近7天销量(self):
        """默认列名不变"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 10, "仓库编码": "006"},
        ]
        result = _build_recent_sales_summary_df(rows, days=7)
        self.assertIn("近7天销量", result.columns)
        self.assertNotIn("近90天销量", result.columns)

    def test_column_name_custom(self):
        """自定义列名"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 100, "仓库编码": "006"},
        ]
        result = _build_recent_sales_summary_df(rows, days=90, column_name="近90天销量")
        self.assertIn("近90天销量", result.columns)
        self.assertNotIn("近7天销量", result.columns)
        self.assertEqual(result.iloc[0]["近90天销量"], 100)

    def test_empty_rows_with_custom_column_name(self):
        """空结果也用自定义列名"""
        result = _build_recent_sales_summary_df([], days=90, column_name="近90天销量")
        self.assertIn("近90天销量", result.columns)
        self.assertNotIn("近7天销量", result.columns)
        self.assertEqual(len(result), 0)

    def test_90day_summary_has_correct_columns(self):
        """_build_recent_sales_summary_df(days=90, column_name='近90天销量') 返回正确列"""
        rows = [
            {"存货编码": "SKU001", "尺码": "M", "销售数量": 50, "仓库编码": "006"},
        ]
        result = _build_recent_sales_summary_df(rows, days=90, column_name="近90天销量")

        self.assertIn("近90天销量", result.columns)
        self.assertIn("存货编码", result.columns)
        self.assertIn("尺码", result.columns)
        self.assertIn("日均销量", result.columns)
        self.assertEqual(result.iloc[0]["近90天销量"], 50)
        self.assertAlmostEqual(result.iloc[0]["日均销量"], 50 / 90, places=2)

    def test_query_90day_sales_drops_日均销量(self):
        """query_90day_sales 返回的 DataFrame 不含日均销量列"""
        from app.data_sources.tplus_openapi_source import query_90day_sales

        # mock TPlusOpenAPIClient 使其返回含日均销量的 DataFrame
        mock_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100, "日均销量": 1.11},
        ])

        with patch("app.data_sources.tplus_openapi_source.TPlusOpenAPIClient") as MockClient:
            instance = MockClient.return_value
            instance.query_recent_sale_delivery_sales.return_value = mock_df
            result = query_90day_sales()

        self.assertIn("近90天销量", result.columns)
        self.assertIn("存货编码", result.columns)
        self.assertIn("尺码", result.columns)
        self.assertNotIn("日均销量", result.columns)
        self.assertEqual(list(result.columns), ["存货编码", "尺码", "近90天销量"])


if __name__ == "__main__":
    unittest.main()
