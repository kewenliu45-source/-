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

    def test_zero_sales_item_preserved(self):
        """测试近7天销量为 0 的存货仍然保留（以库存为主表）"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "仓库编码": "006", "仓库": "销售库", "当前现存量": 5, "当前可用量": 3},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "近7天销量": 0},  # 销量为 0
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertEqual(len(result), 2)
        sku2 = result[result["存货编码"] == "SKU002"].iloc[0]
        self.assertEqual(sku2["近7天销量"], 0)
        self.assertEqual(sku2["日均销量"], 0)
        self.assertEqual(sku2["当前现存量"], 5)

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

    # ---------- 新增标准字段测试 ----------

    def _base_inv_sales(self):
        """复用的基础库存+销售数据"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8, "在途仓": 5},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "仓库编码": "006", "仓库": "销售库", "当前现存量": 5, "当前可用量": 3, "在途仓": 3},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
            {"存货编码": "SKU002", "存货": "商品B", "尺码": "L", "近7天销量": 7},
        ])
        return inventory_df, sales_df

    def test_new_columns_present_without_optional_dfs(self):
        """不传 transit_df / sales_90_df 时，标准结果仍包含三个新字段"""
        inventory_df, sales_df = self._base_inv_sales()
        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertIn("近90天销量", result.columns)
        self.assertIn("在途仓", result.columns)
        self.assertIn("在途（未发货）", result.columns)
        self.assertTrue((result["近90天销量"] == 0).all())
        self.assertTrue((result["在途（未发货）"] == 0).all())
        # 在途仓是数值字段，来自 inventory_df
        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["在途仓"], 5)

    def test_default_values_when_none(self):
        """transit_df=None, sales_90_df=None 时默认值为 0"""
        inventory_df, sales_df = self._base_inv_sales()
        result = build_standard_data_from_frames(
            inventory_df, sales_df, transit_df=None, sales_90_df=None,
        )

        self.assertEqual(result.iloc[0]["近90天销量"], 0)
        self.assertEqual(result.iloc[0]["在途（未发货）"], 0)

    def test_merge_sales_90_df(self):
        """sales_90_df 能按 存货编码+尺码 合并近90天销量"""
        inventory_df, sales_df = self._base_inv_sales()
        sales_90_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "近90天销量": 120},
            {"存货编码": "SKU002", "尺码": "L", "近90天销量": 60},
        ])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, sales_90_df=sales_90_df,
        )

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        sku2 = result[result["存货编码"] == "SKU002"].iloc[0]
        self.assertEqual(sku1["近90天销量"], 120)
        self.assertEqual(sku2["近90天销量"], 60)

    def test_merge_transit_df(self):
        """transit_df 能按 存货编码+尺码 合并在途（未发货）"""
        inventory_df, sales_df = self._base_inv_sales()
        transit_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 20},
        ])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, transit_df=transit_df,
        )

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        sku2 = result[result["存货编码"] == "SKU002"].iloc[0]
        self.assertEqual(sku1["在途（未发货）"], 20)
        self.assertEqual(sku2["在途（未发货）"], 0)  # 未匹配到的填 0

    def test_transit_df_warehouse_merges_with_inventory(self):
        """transit_df 含在途仓数值列时，与 inventory_df 的在途仓求和"""
        inventory_df, sales_df = self._base_inv_sales()
        transit_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 15, "在途仓": 10},
        ])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, transit_df=transit_df,
        )

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        # 在途仓 = inventory_df(5) + transit_df(10) = 15
        self.assertEqual(sku1["在途仓"], 15)
        self.assertEqual(sku1["在途（未发货）"], 15)

    def test_transit_df_only_merges_quantity(self):
        """transit_df 只有在途（未发货）列时，不影响在途仓"""
        inventory_df, sales_df = self._base_inv_sales()
        transit_df = pd.DataFrame([
            {"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 10},
        ])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, transit_df=transit_df,
        )

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        self.assertEqual(sku1["在途（未发货）"], 10)
        # 在途仓仍来自 inventory_df
        self.assertEqual(sku1["在途仓"], 5)

    def test_transit_df_empty(self):
        """transit_df 为空 DataFrame 时，在途（未发货） 默认 0"""
        inventory_df, sales_df = self._base_inv_sales()
        transit_df = pd.DataFrame(columns=["存货编码", "尺码", "在途（未发货）"])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, transit_df=transit_df,
        )

        self.assertTrue((result["在途（未发货）"] == 0).all())

    def test_sales_90_df_empty(self):
        """sales_90_df 为空 DataFrame 时，近90天销量默认 0"""
        inventory_df, sales_df = self._base_inv_sales()
        sales_90_df = pd.DataFrame(columns=["存货编码", "尺码", "近90天销量"])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, sales_90_df=sales_90_df,
        )

        self.assertTrue((result["近90天销量"] == 0).all())

    def test_original_fields_unaffected(self):
        """新增参数不影响原有字段的值"""
        inventory_df, sales_df = self._base_inv_sales()
        hq_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "总部库存": 50}])
        sales_90_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "近90天销量": 100}])
        transit_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 30}])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, hq_df=hq_df,
            transit_df=transit_df, sales_90_df=sales_90_df,
        )

        sku1 = result[result["存货编码"] == "SKU001"].iloc[0]
        # 原有字段不受影响
        self.assertEqual(sku1["近7天销量"], 14)
        self.assertEqual(sku1["当前现存量"], 10)
        self.assertEqual(sku1["当前可用量"], 8)
        self.assertEqual(sku1["总部库存"], 50)
        # 新字段正确合并
        self.assertEqual(sku1["近90天销量"], 100)
        self.assertEqual(sku1["在途（未发货）"], 30)

    def test_all_new_columns_in_standard_output(self):
        """五表合并后，标准输出包含全部 13 列"""
        from app.data_sources.base import STANDARD_COLUMNS

        inventory_df, sales_df = self._base_inv_sales()
        hq_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "总部库存": 50}])
        sales_90_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "近90天销量": 100}])
        transit_df = pd.DataFrame([{
            "存货编码": "SKU001", "尺码": "M",
            "在途（未发货）": 10, "在途仓": 20,
        }])

        result = build_standard_data_from_frames(
            inventory_df, sales_df, hq_df=hq_df,
            transit_df=transit_df, sales_90_df=sales_90_df,
        )

        for col in STANDARD_COLUMNS:
            self.assertIn(col, result.columns, f"缺少标准列: {col}")

    def test_inventory_only_item_preserved(self):
        """库存有但销售表没有的存货应保留（近7天销量填0）"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
            {"存货编码": "SKU003", "存货": "商品C", "尺码": "S", "仓库编码": "006", "仓库": "销售库", "当前现存量": 0, "当前可用量": 0},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 14},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertEqual(len(result), 2)
        sku3 = result[result["存货编码"] == "SKU003"].iloc[0]
        self.assertEqual(sku3["近7天销量"], 0)
        self.assertEqual(sku3["日均销量"], 0)
        self.assertEqual(sku3["当前现存量"], 0)
        self.assertEqual(sku3["当前可用量"], 0)

    def test_zero_stock_zero_sales_preserved(self):
        """零库存零销售的存货应保留在结果中"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 0, "当前可用量": 0},
        ])
        sales_df = pd.DataFrame(columns=["存货编码", "存货", "尺码", "近7天销量"])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["存货编码"], "SKU001")
        self.assertEqual(result.iloc[0]["近7天销量"], 0)
        self.assertEqual(result.iloc[0]["当前现存量"], 0)

    def test_duplicate_sales_rows_are_aggregated_before_merge(self):
        """销售明细重复时应先聚合，不能把库存行 merge 成多行。"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])
        sales_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 3},
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "近7天销量": 4},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["近7天销量"], 7)
        self.assertEqual(result.iloc[0]["当前现存量"], 10)

    def test_warehouse_code_is_normalized_when_already_cleaned(self):
        """已清洗入口也要兼容仓库编码 6 / 006 的格式差异。"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "6", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])

        result = build_standard_data_from_frames(inventory_df, sales_df=None, already_cleaned=True)

        self.assertEqual(len(result), 1)
        self.assertEqual(result.iloc[0]["仓库编码"], "006")

    def test_optional_frames_override_premerged_quantity_columns(self):
        """预合并数据中已有旧数量时，可选表应覆盖为本次最新查询结果。"""
        inventory_df = pd.DataFrame([
            {
                "存货编码": "SKU001", "存货": "商品A", "尺码": "M",
                "仓库编码": "006", "仓库": "销售库",
                "当前现存量": 10, "当前可用量": 8,
                "近7天销量": 7, "日均销量": 1,
                "近90天销量": 1, "在途（未发货）": 1,
            },
        ])
        sales_90_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "近90天销量": 90}])
        transit_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "在途（未发货）": 20}])

        result = build_standard_data_from_frames(
            inventory_df,
            sales_df=None,
            sales_90_df=sales_90_df,
            transit_df=transit_df,
            already_cleaned=True,
        )

        self.assertEqual(result.iloc[0]["近90天销量"], 90)
        self.assertEqual(result.iloc[0]["在途（未发货）"], 20)

    def test_optional_frame_missing_quantity_column_raises_clear_error(self):
        """可选表缺少数量列时应抛业务错误，而不是静默填 0。"""
        inventory_df = pd.DataFrame([
            {"存货编码": "SKU001", "存货": "商品A", "尺码": "M", "仓库编码": "006", "仓库": "销售库", "当前现存量": 10, "当前可用量": 8},
        ])
        sales_90_df = pd.DataFrame([{"存货编码": "SKU001", "尺码": "M", "销量": 90}])

        with self.assertRaisesRegex(ValueError, "近90天销量数据缺少必要字段"):
            build_standard_data_from_frames(inventory_df, sales_df=None, sales_90_df=sales_90_df)


if __name__ == "__main__":
    unittest.main()
