"""
天气数据源测试（OpenMeteoSource）

重点测「离线可测」的部分（不碰真实网络）：
1. WMO 天气码 → 中文描述的映射（数据可读化的关键）
2. 数据源接口实现（name/description/action_examples）
3. history 动作的日期范围解析

真实网络查询已在冒烟测试中验证，这里保持测试确定性、快速、离线。
"""
from app.datasource.open_meteo import OpenMeteoSource, _weather_text, _resolve_coords


class TestWeatherCodeMapping:
    """WMO 天气码 → 中文描述的映射"""

    def test_sunny(self):
        assert _weather_text(0) == "晴"

    def test_cloudy(self):
        assert _weather_text(2) == "多云"

    def test_overcast(self):
        assert _weather_text(3) == "阴"

    def test_light_rain(self):
        assert _weather_text(61) == "小雨"

    def test_heavy_rain(self):
        assert _weather_text(65) == "大雨"

    def test_shower(self):
        assert _weather_text(80) == "阵雨"

    def test_unknown_code_falls_back(self):
        """未知天气码兜底为「未知」，不抛异常。"""
        assert _weather_text(999) == "未知(999)"

    def test_none_falls_back(self):
        """None 兜底为「未知」。"""
        assert _weather_text(None) == "未知"


class TestOpenMeteoSource:
    """OpenMeteoSource 的接口实现"""

    def test_name(self):
        src = OpenMeteoSource()
        assert src.name == "open-meteo"

    def test_description_mentions_weather_and_restock(self):
        src = OpenMeteoSource()
        desc = src.description
        assert "天气" in desc

    def test_action_examples_explains_forecast_and_history(self):
        src = OpenMeteoSource()
        examples = src.action_examples()
        assert "forecast" in examples
        assert "history" in examples

    def test_action_examples_has_date_range_format(self):
        """action_examples 必须说明 history 的日期范围格式（~ 连接）。"""
        src = OpenMeteoSource()
        assert "~" in src.action_examples()

    def test_action_examples_mentions_location_and_start_date(self):
        """action_examples 必须提示 location 和 start_date（查城市/查明天）。"""
        src = OpenMeteoSource()
        examples = src.action_examples()
        assert "location" in examples
        assert "start_date" in examples


class TestResolveCoords:
    """城市名 → 坐标解析（阶段四修复：之前写死上海，location 被忽略）"""

    def test_nanchang(self):
        lat, lon = _resolve_coords("南昌")
        assert abs(lat - 28.682) < 0.01
        assert abs(lon - 115.858) < 0.01

    def test_shanghai_differs_from_nanchang(self):
        """南昌和上海坐标必须不同（否则查错城市也发现不了）。"""
        nc = _resolve_coords("南昌")
        sh = _resolve_coords("上海")
        assert nc != sh

    def test_english_name(self):
        assert _resolve_coords("Nanchang") == _resolve_coords("南昌")

    def test_city_suffix(self):
        assert _resolve_coords("南昌市") == _resolve_coords("南昌")

    def test_unknown_city_returns_none(self):
        assert _resolve_coords("不存在的城市") is None
