"""
数据源动作规划器（DataSourceActionPlanner）

职责：把用户的自然语言数据问题，翻译成「数据源动作」。
例如：
- "全球累计确诊多少"      → {"action": "global"}
- "美国现在的情况"        → {"action": "country:USA"}
- "美国最近 90 天趋势"    → {"action": "history:USA", "days": 90}
- "中美日三国对比"        → {"actions": ["country:China", "country:USA", "country:Japan"]}

这是把「数据源」接进 Agent 的关键一步：LLM 不再生成 SQL（因为数据源不是
关系型数据库），而是生成「动作 + 参数」。这体现了「Function Calling」的
变体思想——模型输出结构化意图，程序去执行。

这是「企业级升级 · 阶段一」的产物。
"""
import json
import re

from app.llm.provider import LLMProvider


class DataSourceActionPlanner:
    """把自然语言问题翻译成数据源动作"""

    PROMPT_TEMPLATE = """你是一个数据查询意图解析器。用户会问一个公共卫生数据问题，
你需要把它翻译成「数据源动作」。

可用的数据源是 disease-sh（全球公共卫生/疫情数据），支持的动作：
- global：查询全球汇总（累计确诊、死亡、治愈等）
- country:<国家英文名>：查询某国现状（如 country:China、country:USA）
- history:<国家英文名>：查询某国历史趋势（返回每日数据，可画折线图）

解析规则：
1. 如果用户要「趋势/变化/最近N天」，用 history，并在 days 里填天数（默认 30）。
2. 如果用户要「对比」多个国家，用 actions 数组列出多个 country 动作。
3. 国家名用英文（中国=China，美国=USA，日本=Japan，德国=Germany，印度=India，巴西=Brazil）。
4. 只输出一个 JSON，不要任何解释。

输出格式（严格 JSON，二选一）：
单个动作：{{"action": "country:USA"}}
历史趋势：{{"action": "history:USA", "days": 90}}
多个对比：{{"actions": ["country:China", "country:USA"]}}

用户的问题：
{question}

请解析："""

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    def plan(self, question: str) -> dict:
        """返回 {"action": ...} 或 {"actions": [...]} 或 {"action":..., "days":...}"""
        prompt = self.PROMPT_TEMPLATE.format(question=question)
        try:
            raw = self._llm.chat(prompt)
            return self._parse(raw)
        except Exception:
            return {"action": "global"}  # 兜底：查全球汇总

    def _parse(self, raw: str) -> dict:
        """从 LLM 返回文本解析动作（容错）"""
        if not raw:
            return {"action": "global"}

        try:
            data = json.loads(raw)
            return data
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                return data
            except json.JSONDecodeError:
                pass

        return {"action": "global"}
