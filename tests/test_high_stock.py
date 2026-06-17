"""高库存预警纯函数测试。

只测试 analyze_high_stock_data()，不涉及路由、模板、CSS。
"""

import unittest
import pandas as pd

from app.services.warning_service import analyze_high_stock_data


class TestHighStockBasic(unittest.TestCase):
    """高库存预警基础判断测试。"""

    def _inventory_df(self, available=100, stock=100):
        return pd.DataFrame([{
            "存货编码": "SKU001",
            "存货": "商品A",
            "尺码": "M",
            "仓库编码": "006",
            "仓库": "销售一库",
            "当前现存量": stock,
            "当前可用量": available,
        }])

    def test_high_stock_triggered(self):
        """可用量=100，年销量=365 → 消化天数=100，高库存预警。"""
        inv = self._inventory_df(available=100)
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
        }])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["预警状态"], "高库存预警")
        self.assertAlmostEqual(row["预计消化库存天数"], 100.0, places=1)

    def test_normal_when_low_days(self):
        """可用量=20，年销量=365 → 消化天数=20，正常。"""
        inv = self._inventory_df(available=20)
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
        }])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["预警状态"], "正常")
        self.assertAlmostEqual(row["预计消化库存天数"], 20.0, places=1)

    def test_high_stock_large_quantity(self):
        """可用量=200，年销量=365 → 消化天数=200，高库存预警。"""
        inv = self._inventory_df(available=200)
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
        }])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["预警状态"], "高库存预警")
        self.assertAlmostEqual(row["预计消化库存天数"], 200.0, places=1)

    def test_zero_sales_no_division_error(self):
        """年销量=0 → 消化天数=999，高库存预警。"""
        inv = self._inventory_df(available=100)
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 0,
        }])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["预计消化库存天数"], 999)
        self.assertEqual(row["预警状态"], "高库存预警")

    def test_zero_available_not_triggered(self):
        """可用量=0 → 正常（不触发高库存）。"""
        inv = self._inventory_df(available=0)
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
        }])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["预警状态"], "正常")


class TestHighStockMerge(unittest.TestCase):
    """高库存数据合并测试。"""

    def test_missing_sales_defaults_to_zero(self):
        """库存有但年度销售没有 → 销量补0，消化天数=999。"""
        inv = pd.DataFrame([{
            "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
            "仓库编码": "006", "仓库": "销售一库",
            "当前现存量": 50, "当前可用量": 50,
        }])
        sales = pd.DataFrame(columns=["存货编码", "尺码", "近365天销量"])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["近365天销量"], 0)
        self.assertEqual(row["年日均销量"], 0)
        self.assertEqual(row["预计消化库存天数"], 999)
        self.assertEqual(row["预警状态"], "高库存预警")

    def test_duplicate_sales_aggregated(self):
        """年度销售重复 SKU+尺码 → 销量正确汇总。"""
        inv = pd.DataFrame([{
            "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
            "仓库编码": "006", "仓库": "销售一库",
            "当前现存量": 100, "当前可用量": 100,
        }])
        sales = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近365天销量": 200},
            {"存货编码": "SKU001", "尺码": "M", "近365天销量": 165},
        ])
        result = analyze_high_stock_data(inv, sales)
        row = result.iloc[0]
        self.assertEqual(row["近365天销量"], 365)
        self.assertAlmostEqual(row["年日均销量"], 1.0, places=2)
        self.assertAlmostEqual(row["预计消化库存天数"], 100.0, places=1)

    def test_warehouse_code_filtering(self):
        """多仓库库存 → 只保留 WARNING_WAREHOUSE_CODE=006。"""
        inv = pd.DataFrame([
            {
                "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
                "仓库编码": "006", "仓库": "销售一库",
                "当前现存量": 100, "当前可用量": 100,
            },
            {
                "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
                "仓库编码": "011", "仓库": "死货库",
                "当前现存量": 50, "当前可用量": 50,
            },
        ])
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
        }])
        result = analyze_high_stock_data(inv, sales)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["仓库编码"], "006")

    def test_warehouse_code_normalized(self):
        """仓库编码 6 / 6.0 / 006 都能匹配。"""
        for code in ["6", "6.0", "006"]:
            inv = pd.DataFrame([{
                "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
                "仓库编码": code, "仓库": "销售一库",
                "当前现存量": 10, "当前可用量": 10,
            }])
            sales = pd.DataFrame([{
                "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
            }])
            result = analyze_high_stock_data(inv, sales)
            self.assertEqual(len(result), 1, f"仓库编码 {code} 应匹配 006")

    def test_output_columns(self):
        """输出应包含所有必需字段。"""
        inv = pd.DataFrame([{
            "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
            "仓库编码": "006", "仓库": "销售一库",
            "当前现存量": 10, "当前可用量": 10,
        }])
        sales = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M", "近365天销量": 365,
        }])
        result = analyze_high_stock_data(inv, sales)
        expected = {
            "存货编码", "存货", "尺码", "仓库编码", "仓库",
            "当前现存量", "当前可用量",
            "近365天销量", "年日均销量", "预计消化库存天数", "预警状态",
        }
        self.assertTrue(expected.issubset(set(result.columns)))


class TestBuildAnnualSalesDf(unittest.TestCase):
    """build_annual_sales_standard_df Excel 解析测试。"""

    def _make_excel(self, data, columns=None):
        """创建临时 Excel 文件用于测试。"""
        import tempfile, os
        df = pd.DataFrame(data, columns=columns)
        path = os.path.join(tempfile.gettempdir(), "test_annual_sales.xlsx")
        df.to_excel(path, index=False)
        return path

    def test_standard_annual_sales(self):
        """标准年度销售表可正确输出近365天销量和年日均销量。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        path = self._make_excel({
            "存货编码": ["SKU001", "SKU002"],
            "存货": ["商品A", "商品B"],
            "尺码": ["M", "L"],
            "数量": [365, 730],
        })
        result = build_annual_sales_standard_df(path)
        self.assertEqual(len(result), 2)
        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["近365天销量"], 365)
        self.assertAlmostEqual(sku1["年日均销量"], 1.0, places=2)

    def test_duplicate_aggregation(self):
        """重复 存货编码+尺码 正确汇总。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        path = self._make_excel({
            "存货编码": ["SKU001", "SKU001"],
            "存货": ["商品A", "商品A"],
            "尺码": ["M", "M"],
            "数量": [100, 200],
        })
        result = build_annual_sales_standard_df(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近365天销量"], 300)

    def test_warehouse_code_matching(self):
        """仓库编码 6、6.0、006 都能匹配 006。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        for code in ["6", "6.0", "006"]:
            path = self._make_excel({
                "存货编码": ["SKU001"],
                "存货": ["商品A"],
                "尺码": ["M"],
                "仓库编码": [code],
                "数量": [100],
            })
            result = build_annual_sales_standard_df(path)
            self.assertEqual(len(result), 1, f"仓库编码 {code} 应匹配 006")

    def test_non_matching_warehouse_filtered(self):
        """非 006 仓库被过滤。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        path = self._make_excel({
            "存货编码": ["SKU001", "SKU002"],
            "存货": ["商品A", "商品B"],
            "尺码": ["M", "L"],
            "仓库编码": ["006", "011"],
            "数量": [100, 200],
        })
        result = build_annual_sales_standard_df(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["存货编码"], "SKU001")

    def test_header_not_first_row(self):
        """表头不在第一行时能自动识别。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        import tempfile, os
        # 创建一个前面有无关行的 Excel
        data = [
            ["某某公司年度销售报表", "", "", ""],
            ["2024-01-01 至 2024-12-31", "", "", ""],
            ["存货编码", "存货", "尺码", "数量"],
            ["SKU001", "商品A", "M", "365"],
        ]
        df = pd.DataFrame(data)
        path = os.path.join(tempfile.gettempdir(), "test_header_offset.xlsx")
        df.to_excel(path, index=False, header=False)
        result = build_annual_sales_standard_df(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近365天销量"], 365)

    def test_non_numeric_quantity_handled(self):
        """数量为空/非数字时不报错，不计入正销量。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        path = self._make_excel({
            "存货编码": ["SKU001", "SKU002", "SKU003"],
            "存货": ["商品A", "商品B", "商品C"],
            "尺码": ["M", "L", "S"],
            "数量": [100, "abc", None],
        })
        result = build_annual_sales_standard_df(path)
        # 只有 SKU001 有正销量
        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["存货编码"], "SKU001")

    def test_zero_quantity_filtered(self):
        """数量为 0 的记录不保留。"""
        from app.data_sources.excel_source import build_annual_sales_standard_df
        path = self._make_excel({
            "存货编码": ["SKU001", "SKU002"],
            "存货": ["商品A", "商品B"],
            "尺码": ["M", "L"],
            "数量": [100, 0],
        })
        result = build_annual_sales_standard_df(path)
        self.assertEqual(len(result), 1)


class TestHighStockContext(unittest.TestCase):
    """高库存结果 context 构建测试。"""

    def test_context_fields(self):
        """context 应包含所有必需字段。"""
        from app.routers.upload_router import build_high_stock_context
        result_df = pd.DataFrame([
            {
                "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
                "仓库编码": "006", "仓库": "销售一库",
                "当前现存量": 100, "当前可用量": 100,
                "近365天销量": 365, "年日均销量": 1.0,
                "预计消化库存天数": 100.0, "预警状态": "高库存预警",
            },
            {
                "存货编码": "SKU002", "存货": "商品B", "尺码": "L",
                "仓库编码": "006", "仓库": "销售一库",
                "当前现存量": 10, "当前可用量": 10,
                "近365天销量": 365, "年日均销量": 1.0,
                "预计消化库存天数": 10.0, "预警状态": "正常",
            },
        ])
        ctx = build_high_stock_context(result_df)
        self.assertEqual(ctx["summary"]["total"], 2)
        self.assertEqual(ctx["summary"]["high_stock_count"], 1)
        self.assertEqual(ctx["summary"]["normal_count"], 1)
        self.assertEqual(ctx["summary"]["high_stock_total_qty"], 100)
        self.assertEqual(len(ctx["preview_data"]), 2)

    def test_context_empty_high_stock(self):
        """没有高库存时，高库存总件数为 0。"""
        from app.routers.upload_router import build_high_stock_context
        result_df = pd.DataFrame([
            {
                "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
                "当前可用量": 10, "预警状态": "正常",
            },
        ])
        ctx = build_high_stock_context(result_df)
        self.assertEqual(ctx["summary"]["high_stock_count"], 0)
        self.assertEqual(ctx["summary"]["high_stock_total_qty"], 0)


if __name__ == "__main__":
    unittest.main()
