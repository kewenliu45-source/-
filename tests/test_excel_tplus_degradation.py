"""Excel 分析模式下 T+ 近90天销量失败降级测试。

不真实调用 T+ API，通过 mock 验证降级逻辑。
"""

import unittest
from unittest.mock import patch, MagicMock

import pandas as pd

from app.data_sources.excel_source import build_standard_data


class TestBuildStandardDataDegradation(unittest.TestCase):
    """build_standard_data 在 T+ 失败时的降级行为。"""

    @patch("app.data_sources.excel_source.build_hq_standard_df")
    @patch("app.data_sources.excel_source.build_intransit_standard_df")
    @patch("app.data_sources.excel_source.build_inventory_standard_df")
    @patch("app.data_sources.excel_source.build_sales_standard_df")
    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    def test_tplus_success_no_warning(
        self, mock_90d, mock_sales, mock_inv, mock_transit, mock_hq
    ):
        """T+ 成功时，warnings 为空。"""
        mock_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_inv.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "元通库",
             "当前现存量": 10, "当前可用量": 8, "在途仓": "元通库"},
        ])
        mock_transit.return_value = pd.DataFrame(columns=["存货编码", "尺码", "在途（未发货）"])
        mock_hq.return_value = pd.DataFrame(columns=["存货编码", "尺码", "总部库存"])
        mock_90d.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 100},
        ])

        df, warnings = build_standard_data(
            None, None, None, None
        )

        self.assertEqual(warnings, [])
        self.assertEqual(df.iloc[0]["近90天销量"], 100)

    @patch("app.data_sources.excel_source.build_hq_standard_df")
    @patch("app.data_sources.excel_source.build_intransit_standard_df")
    @patch("app.data_sources.excel_source.build_inventory_standard_df")
    @patch("app.data_sources.excel_source.build_sales_standard_df")
    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    def test_tplus_failure_returns_warning(
        self, mock_90d, mock_sales, mock_inv, mock_transit, mock_hq
    ):
        """T+ 失败时，warnings 包含降级提示。"""
        mock_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_inv.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "元通库",
             "当前现存量": 10, "当前可用量": 8, "在途仓": "元通库"},
        ])
        mock_transit.return_value = pd.DataFrame(columns=["存货编码", "尺码", "在途（未发货）"])
        mock_hq.return_value = pd.DataFrame(columns=["存货编码", "尺码", "总部库存"])
        mock_90d.side_effect = RuntimeError("T+ API 连接失败")

        df, warnings = build_standard_data(
            None, None, None, None
        )

        self.assertEqual(len(warnings), 1)
        self.assertIn("T+ 近90天销量获取失败", warnings[0])
        self.assertIn("橙色缺码", warnings[0])

    @patch("app.data_sources.excel_source.build_hq_standard_df")
    @patch("app.data_sources.excel_source.build_intransit_standard_df")
    @patch("app.data_sources.excel_source.build_inventory_standard_df")
    @patch("app.data_sources.excel_source.build_sales_standard_df")
    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    def test_tplus_failure_90d_sales_is_zero(
        self, mock_90d, mock_sales, mock_inv, mock_transit, mock_hq
    ):
        """T+ 失败时，近90天销量为 0。"""
        mock_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
        ])
        mock_inv.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "元通库",
             "当前现存量": 10, "当前可用量": 8, "在途仓": "元通库"},
        ])
        mock_transit.return_value = pd.DataFrame(columns=["存货编码", "尺码", "在途（未发货）"])
        mock_hq.return_value = pd.DataFrame(columns=["存货编码", "尺码", "总部库存"])
        mock_90d.side_effect = ValueError("未配置 TPLUS_API_BASE_URL")

        df, warnings = build_standard_data(
            None, None, None, None
        )

        self.assertEqual(df.iloc[0]["近90天销量"], 0)

    @patch("app.data_sources.excel_source.build_hq_standard_df")
    @patch("app.data_sources.excel_source.build_intransit_standard_df")
    @patch("app.data_sources.excel_source.build_inventory_standard_df")
    @patch("app.data_sources.excel_source.build_sales_standard_df")
    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    def test_tplus_failure_no_orange_warning(
        self, mock_90d, mock_sales, mock_inv, mock_transit, mock_hq
    ):
        """T+ 失败时，近90天销量=0，不触发橙色缺码。"""
        from app.services.warning_service import analyze_standard_data

        mock_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 5, "日均销量": 0.71},
        ])
        mock_inv.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "元通库",
             "当前现存量": 0, "当前可用量": 0, "在途仓": "元通库"},
        ])
        mock_transit.return_value = pd.DataFrame(columns=["存货编码", "尺码", "在途（未发货）"])
        mock_hq.return_value = pd.DataFrame(columns=["存货编码", "尺码", "总部库存"])
        mock_90d.side_effect = RuntimeError("网络不通")

        df, _ = build_standard_data(
            None, None, None, None
        )

        result = analyze_standard_data(df)
        # 近90天销量=0，现存量=0 → 不满足橙色条件（需要 近90天销量>0）
        self.assertNotEqual(result.iloc[0]["预警状态"], "橙色缺码")

    @patch("app.data_sources.excel_source.build_hq_standard_df")
    @patch("app.data_sources.excel_source.build_intransit_standard_df")
    @patch("app.data_sources.excel_source.build_inventory_standard_df")
    @patch("app.data_sources.excel_source.build_sales_standard_df")
    @patch("app.data_sources.tplus_openapi_source.query_90day_sales")
    def test_tplus_failure_red_yellow_still_work(
        self, mock_90d, mock_sales, mock_inv, mock_transit, mock_hq
    ):
        """T+ 失败时，红色和黄色预警仍然正常计算。"""
        from app.services.warning_service import analyze_standard_data

        mock_sales.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14, "日均销量": 2.0},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "近7天销量": 10, "日均销量": 1.43},
        ])
        mock_inv.return_value = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "元通库",
             "当前现存量": 0, "当前可用量": 0, "在途仓": "元通库"},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "仓库编码": "006", "仓库": "元通库",
             "当前现存量": 5, "当前可用量": 5, "在途仓": "元通库"},
        ])
        mock_transit.return_value = pd.DataFrame(columns=["存货编码", "尺码", "在途（未发货）"])
        mock_hq.return_value = pd.DataFrame(columns=["存货编码", "尺码", "总部库存"])
        mock_90d.side_effect = RuntimeError("token 过期")

        df, warnings = build_standard_data(
            None, None, None, None
        )

        self.assertEqual(len(warnings), 1)

        result = analyze_standard_data(df)
        statuses = dict(zip(result["存货编码"], result["预警状态"]))
        # SKU001: 可用量=0, 近7天>0 → 红色
        self.assertEqual(statuses["SKU001"], "红色预警")
        # SKU002: 可用量=5, 近7天>0, 可售天数=5/1.43≈3.5 < 7 → 黄色
        self.assertEqual(statuses["SKU002"], "黄色预警")


if __name__ == "__main__":
    unittest.main()

