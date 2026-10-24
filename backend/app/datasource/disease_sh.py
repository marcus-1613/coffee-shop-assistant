"""
Disease.sh 数据源实现

对接公开健康数据 API（https://disease.sh），提供全球/国家新冠、流感等
公共卫生数据。数据是「真实、实时、会变化」的——这正是企业级项目区别于
「本地造数据 demo」的关键。

支持三类查询（统一封装成 DataSource.query）：
1. 全球汇总：global
2. 国家现状：country:<国家名>        （如 country:China）
3. 历史趋势：history:<国家名>        （如 history:China，返回时间序列，可画折线图）

数据刷新说明：
- 通过 TTLCache 缓存，10 分钟有效，避免频繁打第三方、被限流
- API 无 key、无注册，可直接调用

这是「企业级升级 · 阶段一」的产物。
"""
import json
from datetime import datetime
from typing import Any, Dict, List
from urllib.request import urlopen, Request
from urllib.error import URLError

from app.datasource.base import DataSource
from app.datasource.cache import get_cache


class DiseaseShSource(DataSource):
    """Disease.sh 公共卫生数据源"""

    BASE_URL = "https://disease.sh/v3/covid-19"

    def __init__(self, timeout: int = 15):
        self._timeout = timeout

    # ---------- 接口实现 ----------

    @property
    def name(self) -> str:
        return "disease-sh"

    @property
    def description(self) -> str:
        return (
            "全球公共卫生数据（新冠/流感）：各国累计确诊、死亡、治愈、现有病例，"
            "以及按日的历史趋势。可查询某国现状、全球汇总、或某国历史趋势曲线。"
        )

    def schema(self) -> str:
        """返回「字段说明」，拼进 Text2SQL 提示词，帮大模型理解能查什么。"""
        return (
            "数据源 disease-sh（公共卫生/疫情数据）：\n"
            "  - country: 国家名（英文，如 China / USA / Japan）\n"
            "  - cases: 累计确诊数\n"
            "  - deaths: 累计死亡数\n"
            "  - recovered: 累计治愈数\n"
            "  - active: 现有病例数\n"
            "  - todayCases / todayDeaths: 今日新增\n"
            "  - population: 人口\n"
            "  - casesPerOneMillion / deathsPerOneMillion: 每百万人比率\n"
            "  - date: 日期（历史趋势，格式 M/D/YY）\n"
            "查询类型：global（全球汇总）、country:<国家>（某国现状）、"
            "history:<国家>（某国历史趋势，返回每日数据，可画折线图）"
        )

    def action_examples(self) -> str:
        """查询动作的格式说明（供工具清单喂给 LLM 选工具）。"""
        return (
            '疫情查询动作：用 "global" 查全球汇总；'
            '用 "country:China" 查某国现状；用 "history:USA" 查某国历史趋势。'
        )

    def query(self, sql_or_action: str, **params) -> Dict[str, Any]:
        """
        执行查询。sql_or_action 是「动作 + 参数」的描述，如：
        - "global"
        - "country:China"
        - "history:USA"
        """
        action = (sql_or_action or "").strip().lower()
        days = params.get("days") or params.get("lastdays") or 90

        if action == "global":
            return self._query_global()
        if action.startswith("country:"):
            country = action.split(":", 1)[1].strip()
            return self._query_country(country)
        if action.startswith("history:"):
            country = action.split(":", 1)[1].strip()
            return self._query_history(country, days=days)
        # 默认：当作全球汇总处理，避免报错
        return self._query_global()

    # ---------- 具体查询实现 ----------

    def _query_global(self) -> Dict[str, Any]:
        """全球汇总数据"""
        data = self._fetch("/all")
        return {
            "columns": [
                "cases", "deaths", "recovered", "active",
                "todayCases", "todayDeaths", "population", "affectedCountries",
            ],
            "rows": [[
                data.get("cases"),
                data.get("deaths"),
                data.get("recovered"),
                data.get("active"),
                data.get("todayCases"),
                data.get("todayDeaths"),
                data.get("population"),
                data.get("affectedCountries"),
            ]],
            "row_count": 1,
            "meta": {
                "kind": "global",
                "chart": None,
                "updated_at": data.get("updated"),
            },
        }

    def _query_country(self, country: str) -> Dict[str, Any]:
        """某国现状数据（单行）"""
        data = self._fetch(f"/countries/{country}")
        return {
            "columns": [
                "country", "cases", "deaths", "recovered", "active",
                "todayCases", "todayDeaths", "casesPerOneMillion",
                "deathsPerOneMillion", "population",
            ],
            "rows": [[
                data.get("country"),
                data.get("cases"),
                data.get("deaths"),
                data.get("recovered"),
                data.get("active"),
                data.get("todayCases"),
                data.get("todayDeaths"),
                data.get("casesPerOneMillion"),
                data.get("deathsPerOneMillion"),
                data.get("population"),
            ]],
            "row_count": 1,
            "meta": {
                "kind": "country",
                "country": data.get("country"),
                "chart": None,
                "updated_at": data.get("updated"),
            },
        }

    def _query_history(self, country: str, days: int = 90) -> Dict[str, Any]:
        """某国历史趋势（时间序列，返回多行，适合画折线图）"""
        data = self._fetch(f"/historical/{country}?lastdays={days}")
        timeline = data.get("timeline", {})
        cases_series = timeline.get("cases", {})

        # 把 {"3/3/23": 4903524, ...} 转成 [[date, cases], ...]
        rows: List[List] = []
        for date_str, cases_val in cases_series.items():
            rows.append([date_str, cases_val])

        # 日期字符串不能直接按字典序比较（9/9/23 会大于 10/1/23）。
        def _parse_date(value: str) -> datetime:
            try:
                return datetime.strptime(value, "%m/%d/%y")
            except ValueError:
                return datetime.min

        rows.sort(key=lambda row: _parse_date(row[0]))
        latest_date = rows[-1][0] if rows else None

        return {
            "columns": ["date", "cases"],
            "rows": rows,
            "row_count": len(rows),
            # 关键：meta 里声明 chart 类型，前端据此画折线图
            "meta": {
                "kind": "history",
                "country": country,
                "chart": {"type": "line", "x": "date", "y": "cases"},
                "latest_date": latest_date,
            },
        }

    # ---------- HTTP 抓取 + 缓存 ----------

    def _fetch(self, path: str) -> Dict:
        """抓取 API 数据，带缓存。缓存 key 用 path，命中则直接返回。"""
        cache = get_cache()
        url = f"{self.BASE_URL}{path}"

        # 先查缓存
        cached = cache.get(url)
        if cached is not None:
            return cached

        # 未命中 → 真正请求第三方
        req = Request(url, headers={"User-Agent": "smart-assistant/1.0"})
        try:
            with urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (URLError, TimeoutError, json.JSONDecodeError) as e:
            # 第三方挂了：抛出一个明确的异常，让上层做降级处理
            raise ConnectionError(f"数据源 disease-sh 请求失败：{e}") from e

        # 写入缓存
        cache.set(url, data)
        return data
