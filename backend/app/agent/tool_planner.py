"""
工具规划器（ToolPlanner）

职责：把用户的自然语言问题，翻译成「对某个工具的一次结构化调用」。
这是「多工具 Agent」的核心 —— 让大模型从「工具清单」里选工具，
而不是代码里写死 if-else。

与 DataSourceActionPlanner 的关系：
- DataSourceActionPlanner 只认识 disease-sh 一个数据源，是「特例」
- ToolPlanner 是「通用版」：输入 = 问题 + 工具清单，输出 = 结构化工具调用
  未来加任何工具（计算器、查天气、第二个数据源），只需注册进 ToolRegistry，
  ToolPlanner 会自动把它写进提示词，让模型可选，无需改这里的代码

输出结构（严格 JSON，二选一）：
- 单工具：{"tool": "disease-sh", "params": {"action": "history:USA", "days": 30}}
- 多工具（对比等）：{"tools": [{"tool": "disease-sh", "params": {"action": "country:China"}},
                               {"tool": "disease-sh", "params": {"action": "country:USA"}}]}

这是「企业级升级 · 阶段二」的产物。
"""
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.llm.provider import LLMProvider
from app.agent.tools import ToolRegistry


class ToolPlanner:
    """把自然语言问题翻译成「工具调用」"""

    PROMPT_TEMPLATE = """你是一个工具调用规划器。用户会提出一个问题，你需要从
下面的「工具清单」里选出合适的工具，并给出调用参数。

{registry}

今天是 {today}。规划时如需用具体日期，请据此换算「今天/明天/后天/下周」等相对日期
（例如「明天」= {tomorrow}）。

规划规则：
1. 严格按工具清单里各工具的「参数说明」填参数，不要臆造不存在的参数名。
   - 查天气：用 open-meteo 工具，带 location（城市名）参数；
     查「明天/某天」的天气要用 start_date=具体日期（YYYY-MM-DD）指定，
     而不是用 days=1（days=1 从今天起算，会返回今天而非明天）。
   - 查疫情：用 disease-sh 工具，趋势用 action=history:<国家>，对比用多个 country 动作。
   - 查本地经营数据：用 sqlite 工具，question 参数传自然语言问题。
2. 「备货」「进货」「该备什么货」「要进多少货」这类问题，本质是经营分析需求，
   不要用 answer 工具，而要联合查询数据：用 sqlite 查销量排行/销量规律，
   用 open-meteo 查天气，用多个 tools 数组并列调用（备货 = 天气 × 销量协同分析）。
3. 如果用户只是闲聊/问候，选 answer 工具，prompt 里带上用户的问题。
4. 只输出一个 JSON，不要任何解释。

输出格式（严格 JSON，二选一）：
单个工具：{{"tool": "open-meteo", "params": {{"action": "forecast", "location": "南昌", "start_date": "2026-10-23"}}}}
多个工具：{{"tools": [{{"tool": "disease-sh", "params": {{"action": "country:China"}}}}, {{"tool": "disease-sh", "params": {{"action": "country:USA"}}}}]}}

用户的问题：
{question}

请规划："""

    def __init__(self, llm: LLMProvider, registry: ToolRegistry):
        self._llm = llm
        self._registry = registry

    def plan(self, question: str) -> Dict[str, Any]:
        """返回 {"tool": ..., "params": {...}} 或 {"tools": [...]}。

        解析失败时兜底：返回一个 answer 工具调用（保证流程不中断）。
        """
        today = datetime.now()
        tomorrow = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        prompt = self.PROMPT_TEMPLATE.format(
            registry=self._registry.describe(),
            question=question,
            today=today.strftime("%Y-%m-%d"),
            tomorrow=tomorrow,
        )
        try:
            raw = self._llm.chat(prompt)
            return self._parse(raw)
        except Exception:
            return self._fallback()

    def _fallback(self) -> Dict[str, Any]:
        """兜底：让模型直接回答，避免流程中断。"""
        return {"tool": "answer", "params": {"prompt": "请直接回答用户"}}

    def _parse(self, raw: str) -> Dict[str, Any]:
        """从 LLM 返回文本解析工具调用（容错）。"""
        if not raw:
            return self._fallback()

        data = self._parse_json(raw)
        if data:
            # 至少要有 tool 或 tools 字段，否则视为无效
            if "tool" in data or "tools" in data:
                return data

        return self._fallback()

    @staticmethod
    def _parse_json(raw: str) -> Dict[str, Any]:
        """容错解析 LLM 返回的 JSON。"""
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {}
