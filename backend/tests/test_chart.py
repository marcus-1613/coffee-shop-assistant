"""
出图引擎单元测试（通用出图 _build_chart_from_results）

覆盖：
- 疫情历史趋势 → 折线图（通过 meta.chart 声明）
- 天气预报 → 折线图（通过 meta.chart 声明）
- 单条多行排行（sqlite 销量排行）→ 柱状图
- 单条多行日期序列 → 折线图
- 多条对比 → 柱状图
- 不可出图（单行/非数值）→ None
"""
import pytest

from app.api.chat import (
    _build_chart_from_results,
    _is_number,
    _looks_like_date,
)


def _result(columns, rows, meta=None):
    return {"columns": columns, "rows": rows, "row_count": len(rows), "meta": meta or {}}


class TestIsNumber:
    def test_int(self):
        assert _is_number(5) is True

    def test_float(self):
        assert _is_number(3.14) is True

    def test_numeric_string(self):
        assert _is_number("42") is True

    def test_non_numeric_string(self):
        assert _is_number("拿铁") is False

    def test_bool(self):
        assert _is_number(True) is False

    def test_none(self):
        assert _is_number(None) is False


class TestLooksLikeDate:
    def test_iso_date(self):
        assert _looks_like_date("2026-10-22") is True

    def test_slash_date(self):
        assert _looks_like_date("2/8/23") is True

    def test_month_day(self):
        assert _looks_like_date("10-22") is True

    def test_chinese_name(self):
        assert _looks_like_date("冰美式") is False

    def test_number(self):
        assert _looks_like_date(123) is False


class TestBuildChartFromMeta:
    def test_weather_forecast_uses_meta_chart(self):
        """天气预报：meta.chart 声明 line，x=date y=precipitation"""
        r = _result(
            ["date", "weather", "temp_max", "temp_min", "precipitation"],
            [
                ["2026-10-22", "晴", 25, 15, 0.0],
                ["2026-10-23", "雨", 20, 12, 12.5],
                ["2026-10-24", "多云", 22, 13, 2.0],
            ],
            meta={"kind": "forecast", "chart": {"type": "line", "x": "date", "y": "precipitation"}},
        )
        chart = _build_chart_from_results([r])
        assert chart["type"] == "line"
        assert chart["x"] == "date"
        assert chart["y"] == "precipitation"
        assert len(chart["data"]) == 3
        assert chart["data"][1]["value"] == 12.5

    def test_disease_history_uses_meta_chart(self):
        """疫情历史趋势：meta.chart 声明 line"""
        r = _result(
            ["date", "cases"],
            [["2/8/23", 100], ["2/9/23", 120], ["2/10/23", 130]],
            meta={"kind": "history", "chart": {"type": "line", "x": "date", "y": "cases"}},
        )
        chart = _build_chart_from_results([r])
        assert chart["type"] == "line"
        assert chart["data"][-1]["value"] == 130


class TestBuildChartFallback:
    def test_rank_bar_without_meta(self):
        """sqlite 销量排行（无 meta.chart，首列非日期）→ 柱状图"""
        r = _result(
            ["饮品", "销量"],
            [["冰美式", 120], ["拿铁", 95], ["卡布奇诺", 80]],
            meta={"kind": "sqlite"},
        )
        chart = _build_chart_from_results([r])
        assert chart["type"] == "bar"
        assert chart["data"][0] == {"label": "冰美式", "value": 120}

    def test_time_series_line_without_meta(self):
        """日期序列（无 meta.chart，首列是日期）→ 折线图"""
        r = _result(
            ["date", "销量"],
            [["2026-10-01", 30], ["2026-10-02", 35], ["2026-10-03", 40]],
            meta={"kind": "sqlite"},
        )
        chart = _build_chart_from_results([r])
        assert chart["type"] == "line"

    def test_multi_country_bar(self):
        """多条对比结果 → 柱状图"""
        r1 = _result(["country", "cases"], [["China", 1000]], meta={"kind": "country", "country": "China"})
        r2 = _result(["country", "cases"], [["USA", 2000]], meta={"kind": "country", "country": "USA"})
        chart = _build_chart_from_results([r1, r2])
        assert chart["type"] == "bar"
        assert chart["data"][0] == {"label": "China", "value": 1000}
        assert chart["data"][1] == {"label": "USA", "value": 2000}


class TestNoChart:
    def test_empty(self):
        assert _build_chart_from_results([]) is None

    def test_single_row(self):
        r = _result(["cases"], [[100]], meta={"kind": "global"})
        assert _build_chart_from_results([r]) is None

    def test_non_numeric_value(self):
        r = _result(
            ["饮品", "分类"],
            [["冰美式", "咖啡"], ["柠檬茶", "茶饮"]],
            meta={"kind": "sqlite"},
        )
        assert _build_chart_from_results([r]) is None

    def test_answer_result(self):
        r = _result(["answer"], [["你好"]], meta={"kind": "answer"})
        assert _build_chart_from_results([r]) is None
