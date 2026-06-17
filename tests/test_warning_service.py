import unittest
from decimal import Decimal

import pandas as pd

from app.services.warning_service import analyze_standard_data


def _make_row(**overrides):
    """构建一行标准数据，未指定字段用合理默认值。"""
    row = {
        "存货编码": "SKU001",
        "存货": "测试商品",
        "尺码": "M",
        "仓库编码": "006",
        "仓库": "销售一库",
        "近7天销量": 14,
        "日均销量": 2.0,
        "当前现存量": 10,
        "当前可用量": 8,
        "总部库存": 50,
    }
    row.update(overrides)
    return row


class TestOldBehavior(unittest.TestCase):
    """确保旧逻辑不回归。"""

    def test_zero_decimal_daily_sales_does_not_divide_by_zero(self):
        """原有测试：日均销量为 Decimal(0) 时不除零，结果为正常。"""
        df = pd.DataFrame([_make_row(
            近7天销量=Decimal("0"),
            日均销量=Decimal("0"),
            当前现存量=Decimal("1"),
            当前可用量=Decimal("1"),
            总部库存=Decimal("0"),
        )])

        result = analyze_standard_data(df)

        self.assertEqual(result.iloc[0]["可售天数"], 999.0)
        self.assertEqual(result.iloc[0]["预警状态"], "正常")


class TestRedWarning(unittest.TestCase):
    """红色预警：当前可用量 <= 0 且 近7天销量 > 0"""

    def test_red_when_available_zero_and_sales_positive(self):
        df = pd.DataFrame([_make_row(当前可用量=0, 近7天销量=10)])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "红色预警")

    def test_red_when_available_negative(self):
        df = pd.DataFrame([_make_row(当前可用量=-3, 近7天销量=5)])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "红色预警")


class TestOrangeWarning(unittest.TestCase):
    """橙色缺码：当前现存量 <= 0 且 近90天销量 > 0，且不满足红色。"""

    def test_orange_when_stock_zero_and_90d_sales_positive(self):
        """当前可用量 > 0（不满足红色），现存量 <= 0，近90天有销量 → 橙色。"""
        df = pd.DataFrame([_make_row(
            当前可用量=0,
            当前现存量=0,
            近7天销量=0,
            近90天销量=30,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "橙色缺码")

    def test_orange_when_stock_zero_available_positive(self):
        """当前可用量 > 0、现存量 = 0、近90天有销量 → 橙色。"""
        df = pd.DataFrame([_make_row(
            当前现存量=0,
            当前可用量=2,
            近7天销量=0,
            近90天销量=50,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "橙色缺码")


class TestRedOverridesOrange(unittest.TestCase):
    """红色优先于橙色：当同时满足红色和橙色条件时，应为红色。"""

    def test_red_overrides_orange(self):
        """可用量=0、近7天>0、现存量=0、近90天>0 → 红色（不是橙色）。"""
        df = pd.DataFrame([_make_row(
            当前可用量=0,
            当前现存量=0,
            近7天销量=10,
            近90天销量=100,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "红色预警")


class TestYellowWarning(unittest.TestCase):
    """黄色预警：当前可用量 > 0 且 近7天销量 > 0 且 可售天数 < 7"""

    def test_yellow_basic(self):
        """可用量=5、日均=2.0 → 可售天数=2.5 < 7 → 黄色。"""
        df = pd.DataFrame([_make_row(
            当前可用量=5,
            当前现存量=5,
            近7天销量=14,
            日均销量=2.0,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "黄色预警")
        self.assertAlmostEqual(result.iloc[0]["可售天数"], 2.5, places=1)

    def test_yellow_unaffected_by_orange(self):
        """黄色逻辑不受橙色影响（近90天销量高也不改变黄色判断）。"""
        df = pd.DataFrame([_make_row(
            当前可用量=5,
            当前现存量=5,
            近7天销量=14,
            日均销量=2.0,
            近90天销量=100,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "黄色预警")


class TestNormal(unittest.TestCase):
    """正常：不满足任何预警条件。"""

    def test_normal_when_all_zero(self):
        """销量和库存全为 0 → 正常。"""
        df = pd.DataFrame([_make_row(
            近7天销量=0,
            日均销量=0,
            当前现存量=0,
            当前可用量=0,
            近90天销量=0,
            总部库存=0,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "正常")

    def test_normal_when_stock_and_sales_ok(self):
        """库存充足、销量正常 → 正常。"""
        df = pd.DataFrame([_make_row(
            当前可用量=100,
            当前现存量=100,
            近7天销量=7,
            日均销量=1.0,
            近90天销量=90,
        )])
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["预警状态"], "正常")


class TestMissingColumns(unittest.TestCase):
    """缺少新增字段时不报错，降级处理。"""

    def test_no_近90天销量_column(self):
        """缺少近90天销量列时，默认为 0，不报错。"""
        df = pd.DataFrame([_make_row()])
        # 确保没有近90天销量列
        self.assertNotIn("近90天销量", df.columns)
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["近90天销量"], 0)
        self.assertEqual(result.iloc[0]["预警状态"], "黄色预警")

    def test_no_当前现存量_column(self):
        """缺少当前现存量列时，用当前可用量兜底。"""
        df = pd.DataFrame([{
            "存货编码": "SKU001", "存货": "商品", "尺码": "M",
            "近7天销量": 10, "日均销量": 1.43,
            "当前可用量": 5, "总部库存": 20,
        }])
        self.assertNotIn("当前现存量", df.columns)
        result = analyze_standard_data(df)
        self.assertEqual(result.iloc[0]["当前现存量"], 5)


class TestSortOrder(unittest.TestCase):
    """排序：红色 > 橙色 > 黄色 > 正常"""

    def test_sort_order(self):
        df = pd.DataFrame([
            _make_row(存货编码="A", 当前可用量=100, 当前现存量=100, 近7天销量=1, 日均销量=0.14, 近90天销量=0),   # 正常
            _make_row(存货编码="B", 当前可用量=0, 当前现存量=0, 近7天销量=10, 近90天销量=100),                    # 红色
            _make_row(存货编码="C", 当前可用量=3, 当前现存量=3, 近7天销量=14, 日均销量=2.0, 近90天销量=0),         # 黄色
            _make_row(存货编码="D", 当前可用量=0, 当前现存量=0, 近7天销量=0, 近90天销量=50),                        # 橙色
        ])
        result = analyze_standard_data(df)
        statuses = list(result["预警状态"])
        self.assertEqual(statuses[0], "红色预警")
        self.assertEqual(statuses[1], "橙色缺码")
        self.assertEqual(statuses[2], "黄色预警")
        self.assertEqual(statuses[3], "正常")


class TestTransferAdvice(unittest.TestCase):
    """调货建议包含橙色缺码的文案。"""

    def test_orange_advice_text(self):
        df = pd.DataFrame([_make_row(
            当前可用量=0,
            当前现存量=0,
            近7天销量=0,
            近90天销量=30,
            总部库存=20,
            建议调货量=10,
        )])
        result = analyze_standard_data(df)
        advice = result.iloc[0]["调货建议"]
        self.assertIn("缺码待补", advice)


if __name__ == "__main__":
    unittest.main()
