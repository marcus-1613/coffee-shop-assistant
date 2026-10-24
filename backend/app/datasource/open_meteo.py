"""
Open-Meteo 天气数据源实现

对接公开天气 API（https://open-meteo.com），提供「未来天气预报」和「历史天气」。
免费、无需 key、稳定，是「咖啡店经营助手」的第二个真实数据源。

为什么选天气？（咖啡店经营分析的核心外部变量）
- 咖啡/冷饮销量和天气强相关：雨天热饮需求上升、冷饮下降
- 结合「未来预报」+「历史销量规律」，能推断「该备什么货」

支持查询（统一封装成 DataSource.query）：
1. forecast：未来 N 天预报（天气 + 温度 + 降水）
   - 支持 location 参数指定城市（内置常见城市坐标表）
   - 支持 start_date / end_date 指定日期范围（查「明天」用 start_date=明天日期）
2. history:YYYY-MM-DD~YYYY-MM-DD：历史某段天气
3. （默认）forecast 7 天

关键修复（阶段四）：
- 城市坐标：之前写死上海坐标，location 参数被忽略，导致「查南昌」实际查上海。
  现内置 CITY_COORDS 常见城市坐标表，按 location 参数查表取坐标。
- 日期语义：之前 forecast_days=1 返回「今天」（Open-Meteo 从今天起算），
  而用户问「明天」应该查明天。现支持 start_date 参数精确指定起始日期。

天气码（WMO weather code）→ 中文描述的映射，是「数据可读化」的关键：
把 API 返回的数字码（0/1/2/3/51/61/80…）翻译成「晴/多云/阴/小雨/大雨」等。
"""
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List
from urllib.request import urlopen, Request
from urllib.error import URLError

from app.datasource.base import DataSource
from app.datasource.cache import get_cache


# WMO 天气码 → 中文描述（关键：把数字码翻译成人话）
WMO_CODE_TO_TEXT = {
    0: "晴",
    1: "基本晴",
    2: "多云",
    3: "阴",
    45: "雾",
    48: "雾凇",
    51: "毛毛雨",
    53: "小雨",
    55: "中雨",
    56: "冻毛毛雨",
    57: "冻雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    66: "冻雨",
    67: "冻雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    77: "雪粒",
    80: "阵雨",
    81: "阵雨",
    82: "强阵雨",
    85: "阵雪",
    86: "强阵雪",
    95: "雷暴",
    96: "雷暴伴冰雹",
    99: "强雷暴伴冰雹",
}


def _weather_text(code) -> str:
    """把 WMO 天气码翻译成中文，未知码兜底为「未知」。"""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "未知"
    return WMO_CODE_TO_TEXT.get(code, f"未知({code})")


# 常见城市坐标表（纬度, 经度）。
# 用于把「location 参数里的城市名」转成经纬度，避免查错城市。
# 不在表里的城市，回退到默认坐标（上海）。
CITY_COORDS = {
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "广州": (23.1291, 113.2644),
    "深圳": (22.5431, 114.0579),
    "南昌": (28.6820, 115.8579),
    "杭州": (30.2741, 120.1551),
    "南京": (32.0603, 118.7969),
    "武汉": (30.5928, 114.3055),
    "成都": (30.5728, 104.0668),
    "重庆": (29.5630, 106.5516),
    "西安": (34.3416, 108.9398),
    "长沙": (28.2282, 112.9388),
    "郑州": (34.7466, 113.6254),
    "天津": (39.3434, 117.3616),
    "苏州": (31.2989, 120.5853),
    "青岛": (36.0671, 120.3826),
    "厦门": (24.4798, 118.0894),
    "昆明": (25.0389, 102.7183),
    "福州": (26.0745, 119.2965),
    "合肥": (31.8206, 117.2272),
    "济南": (36.6512, 117.1201),
    "贵阳": (26.6470, 106.6302),
    "哈尔滨": (45.8038, 126.5350),
    "沈阳": (41.8057, 123.4315),
    "长春": (43.8171, 125.3235),
    "石家庄": (38.0428, 114.5149),
    "太原": (37.8706, 112.5489),
    "兰州": (36.0611, 103.8343),
    "海口": (20.0440, 110.1999),
    "南宁": (22.8170, 108.3665),
    "乌鲁木齐": (43.8256, 87.6168),
    "拉萨": (29.6520, 91.1721),
}


def _resolve_coords(location: str):
    """把城市名（中/英文）解析成 (纬度, 经度)。查不到返回 None。"""
    if not location:
        return None
    loc = location.strip()
    # 直接命中中文名
    if loc in CITY_COORDS:
        return CITY_COORDS[loc]
    # 尝试匹配英文/拼音（简单兼容：转小写比对常用英文名）
    _english = {
        "beijing": "北京", "shanghai": "上海", "guangzhou": "广州",
        "shenzhen": "深圳", "nanchang": "南昌", "hangzhou": "杭州",
        "nanjing": "南京", "wuhan": "武汉", "chengdu": "成都",
        "chongqing": "重庆", "xian": "西安", "changsha": "长沙",
        "zhengzhou": "郑州", "tianjin": "天津", "suzhou": "苏州",
        "qingdao": "青岛", "xiamen": "厦门", "kunming": "昆明",
        "fuzhou": "福州", "hefei": "合肥", "jinan": "济南",
        "guiyang": "贵阳", "harbin": "哈尔滨", "shenyang": "沈阳",
    }
    cn = _english.get(loc.lower())
    if cn and cn in CITY_COORDS:
        return CITY_COORDS[cn]
    # 用户可能带「市」后缀，去掉再试
    if loc.endswith("市") and loc[:-1] in CITY_COORDS:
        return CITY_COORDS[loc[:-1]]
    return None


class OpenMeteoSource(DataSource):
    """Open-Meteo 天气数据源

    默认坐标：上海（31.23, 121.47）。支持 location 参数切换城市。
    """

    FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
    ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self, latitude: float = 31.23, longitude: float = 121.47, timeout: int = 15):
        self._latitude = latitude
        self._longitude = longitude
        self._timeout = timeout

    # ---------- 接口实现 ----------

    @property
    def name(self) -> str:
        return "open-meteo"

    @property
    def description(self) -> str:
        return (
            "天气数据（真实 API）：查询某地未来 N 天的天气预报，或历史某段时间的天气。"
            "返回天气状况（晴/雨/阴）、最高最低温、降水量。"
            "支持指定城市（location 参数，如 location=南昌）。"
            "用于分析天气对咖啡店销量的影响，辅助备货决策。"
        )

    def schema(self) -> str:
        return (
            "数据源 open-meteo（天气数据）：\n"
            "  - date: 日期（YYYY-MM-DD）\n"
            "  - weather: 天气状况（晴/多云/阴/小雨/中雨/大雨/阵雨…）\n"
            "  - temp_max: 最高温（℃）\n"
            "  - temp_min: 最低温（℃）\n"
            "  - precipitation: 降水量（mm）\n"
            "查询类型：forecast（未来7天预报）、history:YYYY-MM-DD~YYYY-MM-DD（历史天气）\n"
            "可选参数：location（城市名，如 南昌/北京/上海）、"
            "start_date（起始日期 YYYY-MM-DD，查「明天」要传明天的具体日期）、"
            "end_date（结束日期）"
        )

    def action_examples(self) -> str:
        """查询动作的格式说明（供工具清单喂给 LLM 选工具）。"""
        return (
            '天气查询动作：用 "forecast" 查未来预报；'
            '用 "history:2026-10-15~2026-10-22" 查历史某段天气（日期范围用 ~ 连接）。'
        )

    def extra_params(self) -> Dict[str, str]:
        """天气源除了 action 外，还需要城市/日期等查询条件（阶段四重构）。

        之前这些参数说明用 if 硬编码在 DataSourceTool.parameters() 里，
        导致通用工具层认识具体数据源（违反开闭原则）。现下沉到数据源自身声明。
        """
        return {
            "location": "城市名（如 南昌/北京/上海），指定查询哪个城市的天气",
            "start_date": "起始日期 YYYY-MM-DD，查「明天」传明天的具体日期",
            "end_date": "结束日期 YYYY-MM-DD（可选）",
            "days": "预报天数（查「未来N天」时用，默认7）",
        }

    def query(self, sql_or_action: str, **params) -> Dict[str, Any]:
        """执行查询。sql_or_action 是「动作 + 参数」描述，如：
        - "forecast"                       → 未来 7 天预报
        - "forecast" + location=南昌       → 南昌未来 7 天预报
        - "forecast" + start_date=2026-10-23 → 从 10-23 开始的预报
        - "history:2026-10-15~2026-10-22"  → 历史某段天气
        """
        action = (sql_or_action or "").strip().lower()
        days = int(params.get("days") or params.get("forecast_days") or 7)
        location = params.get("location") or params.get("city") or ""
        start_date = params.get("start_date") or params.get("start") or ""
        end_date = params.get("end_date") or params.get("end") or ""

        if action.startswith("history:"):
            date_range = action.split(":", 1)[1].strip()
            return self._query_history(date_range, location=location)
        # 未来预报（支持 location + start_date）
        return self._query_forecast(days, location=location, start_date=start_date, end_date=end_date)

    # ---------- 具体查询实现 ----------

    def _resolve_lat_lon(self, location: str):
        """解析坐标：location 指定城市则查表，否则用默认（上海）。"""
        if location:
            coords = _resolve_coords(location)
            if coords:
                return coords[0], coords[1]
        return self._latitude, self._longitude

    def _query_forecast(
        self,
        days: int = 7,
        location: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> Dict[str, Any]:
        """未来 N 天预报（时间序列，可画折线图）。

        - location：城市名，查表取坐标
        - start_date：起始日期（YYYY-MM-DD），Open-Meteo 用它替代「从今天起 forecast_days 天」
        """
        lat, lon = self._resolve_lat_lon(location)

        # 查询参数：有 start_date 时用日期范围，否则用 forecast_days
        date_part = ""
        if start_date:
            date_part = f"&start_date={start_date}"
            if end_date:
                date_part += f"&end_date={end_date}"
            else:
                # 只给了起始日，默认取 N 天（从 start_date 起）
                try:
                    from datetime import datetime, timedelta
                    s = datetime.strptime(start_date, "%Y-%m-%d")
                    e = (s + timedelta(days=days - 1)).strftime("%Y-%m-%d")
                    date_part += f"&end_date={e}"
                except ValueError:
                    pass
        else:
            date_part = f"&forecast_days={days}"

        url = (
            f"{self.FORECAST_URL}?latitude={lat}&longitude={lon}"
            f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_sum"
            f"&timezone=Asia%2FShanghai{date_part}"
        )
        data = self._fetch(url)
        daily = data.get("daily", {})

        dates = daily.get("time", [])
        codes = daily.get("weathercode", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        precip = daily.get("precipitation_sum", [])

        rows: List[List] = []
        for i, d in enumerate(dates):
            rows.append([
                d,
                _weather_text(codes[i] if i < len(codes) else None),
                tmax[i] if i < len(tmax) else None,
                tmin[i] if i < len(tmin) else None,
                precip[i] if i < len(precip) else None,
            ])

        return {
            "columns": ["date", "weather", "temp_max", "temp_min", "precipitation"],
            "rows": rows,
            "row_count": len(rows),
            "meta": {
                "kind": "forecast",
                "chart": {"type": "line", "x": "date", "y": "precipitation"},
                "latest_date": dates[-1] if dates else None,
                "location": location or "上海",
            },
        }

    def _query_history(self, date_range: str, location: str = "") -> Dict[str, Any]:
        """历史某段天气（用于回填本地库 / 分析历史天气与销量的关系）"""
        # 解析 "YYYY-MM-DD~YYYY-MM-DD"，缺省用「过去 7 天」
        try:
            if "~" in date_range:
                start, end = date_range.split("~", 1)
            else:
                start = date_range
                end = date_range
        except Exception:
            start = end = None

        if not start or not end:
            today = datetime.now()
            start = (today - timedelta(days=7)).strftime("%Y-%m-%d")
            end = today.strftime("%Y-%m-%d")

        lat, lon = self._resolve_lat_lon(location)

        params = (
            f"latitude={lat}&longitude={lon}"
            f"&start_date={start}&end_date={end}"
            f"&daily=weathercode,temperature_2m_max,precipitation_sum"
            f"&timezone=Asia%2FShanghai"
        )
        data = self._fetch(f"{self.ARCHIVE_URL}?{params}")
        daily = data.get("daily", {})

        dates = daily.get("time", [])
        codes = daily.get("weathercode", [])
        tmax = daily.get("temperature_2m_max", [])
        precip = daily.get("precipitation_sum", [])

        rows: List[List] = []
        for i, d in enumerate(dates):
            rows.append([
                d,
                _weather_text(codes[i] if i < len(codes) else None),
                tmax[i] if i < len(tmax) else None,
                precip[i] if i < len(precip) else None,
            ])

        return {
            "columns": ["date", "weather", "temp_max", "precipitation"],
            "rows": rows,
            "row_count": len(rows),
            "meta": {
                "kind": "history",
                "chart": {"type": "line", "x": "date", "y": "precipitation"},
                "latest_date": dates[-1] if dates else None,
                "location": location or "上海",
            },
        }

    # ---------- HTTP 抓取 + 缓存 ----------

    def _fetch(self, url: str) -> Dict:
        """抓取 API 数据，带缓存。缓存 key 用 url，命中则直接返回。"""
        cache = get_cache()
        cached = cache.get(url)
        if cached is not None:
            return cached

        req = Request(url, headers={"User-Agent": "smart-assistant/1.0"})
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            raise ConnectionError(f"数据源 open-meteo 请求失败：{e}") from e

        cache.set(url, data)
        return data
