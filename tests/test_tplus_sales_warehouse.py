import unittest
from datetime import date
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
