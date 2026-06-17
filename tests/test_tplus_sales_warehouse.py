import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from app.data_sources.tplus_openapi_source import (
    TPlusOpenAPIClient,
    _build_recent_sales_summary_df,
    _extract_voucher_code_date,
    _extract_sale_delivery_sales_rows,
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

    def test_sale_delivery_rows_extract_line_warehouse(self):
        detail_response = {
            "data": {
                "VoucherDate": "2026-06-10",
                "SaleDeliveryDetails": [
                    {
                        "Inventory": {"Code": "15C1010000"},
                        "DynamicPropertyValues": ["150"],
                        "Quantity": 6,
                        "Warehouse": {"Code": "006", "Name": "销售一库"},
                    }
                ],
            }
        }

        rows = _extract_sale_delivery_sales_rows(
            detail_response,
            start=date(2026, 6, 4),
            end=date(2026, 6, 10),
        )

        self.assertEqual(rows[0]["仓库编码"], "006")
        self.assertEqual(rows[0]["仓库"], "销售一库")

    def test_recent_sales_query_scans_newest_pages_first(self):
        class FakeClient(TPlusOpenAPIClient):
            def __init__(self):
                pass

            def _find_sale_delivery_list_response(self, page_index=1, page_size=100, param_dic=None, debug=True):
                pages = {
                    1: [["1", "SA-20260610-001"]],
                    2: [["2", "SA-20260609-001"]],
                    3: [["3", "SA-20260501-001"]],
                }
                return {
                    "data": {
                        "TotalPageNum": 3,
                        "Columns": ["id", "code"],
                        "Rows": pages[page_index],
                    }
                }

            def get_sale_delivery_detail(self, voucher_id=None, voucher_code=None, debug=True):
                return {
                    "data": {
                        "VoucherDate": "2026-06-10",
                        "SaleDeliveryDetails": [
                            {
                                "Inventory": {"Code": "15C1010000"},
                                "DynamicPropertyValues": ["150"],
                                "Quantity": 6,
                                "Warehouse": {"Code": "006", "Name": "销售一库"},
                            }
                        ],
                    }
                }

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            result = FakeClient().query_recent_sale_delivery_sales(
                end_date=date(2026, 6, 11),
                force_refresh=True,
                max_detail_workers=1,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 12)

    def test_voucher_code_date_parses_hyphenated_tplus_code(self):
        voucher_date = _extract_voucher_code_date({"code": "SA-2026-06-0111"})

        self.assertEqual(voucher_date, date(2026, 6, 1))

    def test_recent_sales_query_scans_tail_pages_when_list_is_oldest_first(self):
        class FakeClient(TPlusOpenAPIClient):
            def __init__(self):
                pass

            def _find_sale_delivery_list_response(self, page_index=1, page_size=100, param_dic=None, debug=True):
                pages = {
                    1: [["old-1", "SA-2018-10-0111"]],
                    11: [["new-11", "SWY-2026061012000012345678"]],
                    12: [["old-return-12", "SWY-RE-2022092819215489785382"]],
                    13: [],
                }
                return {
                    "data": {
                        "TotalPageNum": 13,
                        "Columns": ["id", "code"],
                        "Rows": pages.get(page_index, []),
                    }
                }

            def get_sale_delivery_detail(self, voucher_id=None, voucher_code=None, debug=True):
                return {
                    "data": {
                        "VoucherDate": "2026-06-10",
                        "SaleDeliveryDetails": [
                            {
                                "Inventory": {"Code": "15C1010000"},
                                "DynamicPropertyValues": ["150"],
                                "Quantity": 6,
                                "Warehouse": {"Code": "006", "Name": "销售一库"},
                            }
                        ],
                    }
                }

        with patch("app.data_sources.tplus_openapi_source._write_recent_sales_cache"):
            result = FakeClient().query_recent_sale_delivery_sales(
                end_date=date(2026, 6, 11),
                force_refresh=True,
                max_detail_workers=1,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 6)


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
        # _build_recent_sales_summary_df 仍返回日均销量（基于 90 天）
        # 但 query_90day_sales() 会在外层去掉它
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
