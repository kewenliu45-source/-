import unittest
from decimal import Decimal

import pandas as pd

from app.services.warning_service import analyze_standard_data


class WarningServiceTests(unittest.TestCase):
    def test_zero_decimal_daily_sales_does_not_divide_by_zero(self):
        df = pd.DataFrame(
            [
                {
                    "存货编码": "15C101",
                    "存货": "测试商品",
                    "尺码": "130",
                    "仓库编码": "006",
                    "仓库": "销售一库",
                    "近7天销量": Decimal("0"),
                    "日均销量": Decimal("0"),
                    "当前现存量": Decimal("1"),
                    "当前可用量": Decimal("1"),
                    "总部库存": Decimal("0"),
                }
            ]
        )

        result = analyze_standard_data(df)

        self.assertEqual(result.iloc[0]["可售天数"], 999.0)
        self.assertEqual(result.iloc[0]["预警状态"], "正常")


if __name__ == "__main__":
    unittest.main()
