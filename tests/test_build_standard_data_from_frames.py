import unittest
import pandas as pd

from app.data_sources.base import build_standard_data_from_frames


class TestBuildStandardDataFromFrames(unittest.TestCase):
    """测试 build_standard_data_from_frames() 函数"""

    def test_merge_sales_inventory_only(self):
        """测试无总部库存时合并逻辑"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "仓库编码": "006", "仓库": "销售库", "当前现存量": 5, "当前可用量": 3},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "近7天销量": 7},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertEqual(len(result), 2)
        self.assertIn("总部库存", result.columns)
        self.assertTrue((result["总部库存"] == 0).all())

    def test_merge_with_hq_inventory(self):
        """测试有总部库存时合并逻辑"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
        ])
        hq_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "总部库存": 100},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df, hq_df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["总部库存"], 100)

    def test_filter_zero_sales(self):
        """测试筛选近7天销量 > 0"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "仓库编码": "006", "仓库": "销售库", "当前现存量": 5, "当前可用量": 3},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "近7天销量": 0},  # 销量为 0
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["存货编码"], "SKU001")

    def test_daily_sales_calculation(self):
        """测试日均销量 = 近7天销量 / 7"""
        from app.config import SAFE_DAYS

        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        expected_daily = 14 / SAFE_DAYS
        self.assertAlmostEqual(result.iloc[0]["日均销量"], expected_daily, places=2)

    def test_missing_columns_raises_error(self):
        """测试缺少必要字段时抛异常"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M"},  # 缺少 当前现存量, 当前可用量
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近7天销量": 14},
        ])

        with self.assertRaises(ValueError):
            build_standard_data_from_frames(inventory_df, sales_df)

    def test_hq_df_none(self):
        """测试 hq_df 为 None 时总部库存为 0"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df, hq_df=None)

        self.assertEqual(result.iloc[0]["总部库存"], 0)

    def test_hq_df_empty(self):
        """测试 hq_df 为空 DataFrame 时总部库存为 0"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
        ])
        hq_df = pd.DataFrame(columns=["存货编码", "尺码", "总部库存"])

        result = build_standard_data_from_frames(inventory_df, sales_df, hq_df)

        self.assertEqual(result.iloc[0]["总部库存"], 0)


if __name__ == "__main__":
    unittest.main()
