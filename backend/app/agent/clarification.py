"""
澄清追问（Clarification）

职责：在「动作规划之后、执行查询之前」，检查用户问题所对应的「数据源动作」
信息是否完整、是否有歧义。信息不足时不瞎猜，而是生成一句「澄清问题」反问用户。

这是「企业级升级 · Agent 智能升级 · 澄清追问」的核心。

设计：规则层 + 大模型层（先规则后大模型）
-------------------------------------------------
1. 规则层（确定性、免费、可测试）：检查动作的「必填参数」是否缺失。
   - history / country 动作需要国家名（country），没解析出来 → 硬缺口
   - 硬缺口能 100% 判断，用规则做，不调大模型（符合「确定性逻辑与 LLM 分离」）

2. 大模型层（语义歧义、需要理解）：规则说「不缺参数」了，但可能仍有
   语义歧义（如"最新情况"指什么、"中美"是不是"中国和美国"）。
   这类判断规则做不了，交给大模型。

原则：能确定的事交给规则，只有「不确定、需要理解」的事才交给大模型。
"""
import json
import re
from typing import Optional

from app.llm.provider import LLMProvider


class ClarificationChecker:
    """信息完整性检查器：返回是否需要澄清，以及澄清问题"""

    # 动作 → 必填参数（规则层的「检查表」）
    REQUIRED_PARAMS = {
        "global": [],                    # 全球汇总：无必填参数
        "country": ["country"],          # 某国现状：必须有国家名
        "history": ["country"],          # 历史趋势：必须有国家名
    }

    CLARIFY_PROMPT = """你是一个严谨的数据查询助手。用户提出了一个数据查询问题，
系统已经把它解析成以下动作，但可能信息不足或存在歧义。

用户的原始问题：
{question}

系统解析出的动作：
{action_summary}

请你判断：要准确回答这个问题，是否还缺少关键信息？

需要追问的情况（信息真的不足）：
- 指代不清：比如"那个卖得怎么样"里"那个"不知道指哪款饮品；
- 缺关键实体：比如要对比国家却没说明对比哪些国家；
- 时间范围完全缺失且对结论有决定性影响。

不需要追问的情况（不要过度较真）：
- "这个月""最近""今天""上周"这类相对时间表达，默认指当前自然周期，是明确的；
- "卖得最好""销量最高"这类已经是完整、可执行的查询意图；
- 泛指"所有""整体"的统计，不强制追问细分维度；
- "备货""该备什么货""进货"这类开放性经营建议问题：不要追问"备什么品类""哪个门店"
  这类细节——门店默认当前门店、品类默认全品类，系统会结合天气和销量给出整体建议即可；
- 如果用户的问题里已经包含上下文（如前面已提过"南昌""明天""咖啡"），
  直接沿用这些信息，不要因为用户省略重复表述就当作"信息缺失"再追问。

如果信息充足、可以直接查询，请输出：{{"needs_clarification": false}}
如果信息不足、需要追问，请输出：{{"needs_clarification": true, "question": "你要追问用户的问题"}}

只输出 JSON，不要任何解释。"""

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    @staticmethod
    def _has_query_action(normalized: dict) -> bool:
        """判断规范化后的 plan 是否包含「实质查询动作」。

        只有「查询数据」类动作才需要澄清；纯 answer（直接回答）无需追问。
        """
        if not normalized:
            return False
        # 多动作
        if "actions" in normalized:
            return bool(normalized["actions"])
        # 单动作：有 action 字段且非空
        action = normalized.get("action", "")
        return bool(action)

    def check(self, question: str, plan: dict) -> Optional[str]:
        """检查信息是否完整。

        支持两种 plan 格式（阶段二改造后）：
        - 旧格式：{"action": "country:USA"} 或 {"actions": [...]}
        - 工具调用格式：{"tool": "disease-sh", "params": {"action": "country"}}

        返回：
        - None：信息完整，可以直接执行查询
        - str：需要澄清，返回「澄清问题」文本

        分层策略（阶段三·咖啡店经营助手）：
        - 规则层：只对「数据源类动作」（疫情 global/country/history）做「必填参数」硬检查，
          因为只有它们有「查国家必须带国家名」这类确定性缺口。
        - 大模型层：对所有工具（含 sqlite 经营查询）做「语义歧义」检查，
          识别「那个/它」指代不清、时间范围不明等模糊点。
          这样咖啡店问题（"那个卖得怎么样"）也能被反问，而不是靠 Text2SQL 失败兜底。
        """
        # 先规范化成「动作摘要」，统一两种格式
        normalized = self._normalize_plan(plan)

        # 纯 answer / 无实质动作：无需澄清，直接放行
        if not normalized or not self._has_query_action(normalized):
            return None

        # ---- 第 1 层：规则检查硬缺口（只对数据源动作，不调大模型）----
        if self._is_datasource_plan(normalized):
            missing = self._rule_check(normalized)
            if missing:
                return self._build_rule_question(missing)

        # ---- 第 2 层：大模型判断语义歧义（对所有查询类工具）----
        return self._llm_check(question, normalized)

    @staticmethod
    def _is_datasource_plan(normalized: dict) -> bool:
        """判断规范化后的 plan 是否属于「数据源查询」类动作。

        只有 global / country / history 这类疫情数据源动作才需要澄清追问；
        其他（sqlite 工具、answer 工具等）不参与澄清。
        """
        # 多动作对比：全是数据源动作才算
        if "actions" in normalized:
            actions = normalized["actions"]
            if not isinstance(actions, list):
                return False
            for a in actions:
                if not isinstance(a, str):
                    return False
                kind = a.split(":")[0]
                if kind not in ClarificationChecker.REQUIRED_PARAMS:
                    return False
            return True

        # 单动作：action 必须在数据源动作表里
        action = normalized.get("action", "")
        if not isinstance(action, str):
            return False
        kind = action.split(":")[0]
        return kind in ClarificationChecker.REQUIRED_PARAMS

    def _normalize_plan(self, plan: dict) -> dict:
        """把「工具调用格式」的 plan 规范化成「动作摘要」格式。

        工具调用格式：{"tool": "disease-sh", "params": {"action": "history", "days": 30}}
        → 动作摘要：{"action": "history", "days": 30}

        多工具：{"tools": [{...}, {...}]}
        → {"actions": ["history:China", "country:USA"]}

        已经是动作格式则原样返回。
        """
        if not plan:
            return {}

        # 已是旧格式（含 action / actions）→ 原样返回
        if "action" in plan or "actions" in plan:
            return plan

        # 工具调用格式：单工具
        if "tool" in plan:
            params = plan.get("params") or {}
            result = dict(params)
            # 对 sqlite 这类「自然语言查询」工具，action 用其 question 表达，
            # 让大模型能理解「用户在查什么」，而不是一个光秃秃的工具名
            if plan["tool"] == "sqlite" and "question" in result:
                result["action"] = f"查询本地经营数据：{result['question']}"
            else:
                result.setdefault("action", plan["tool"])
            return result

        # 工具调用格式：多工具
        if "tools" in plan and isinstance(plan["tools"], list):
            actions = []
            for t in plan["tools"]:
                params = t.get("params") or {}
                action = params.get("action", t.get("tool", ""))
                actions.append(action)
            return {"actions": actions}

        return plan

    # ---------- 规则层 ----------

    def _rule_check(self, plan: dict) -> Optional[str]:
        """检查动作的必填参数是否缺失。返回缺失的参数名，或 None。"""
        # 情况 A：多动作对比（actions 列表）
        if "actions" in plan:
            # 对比至少要有 2 个动作才叫"对比"
            actions = plan["actions"]
            if not isinstance(actions, list) or len(actions) < 2:
                return "countries"
            return None

        # 情况 B：单动作
        action = plan.get("action", "")
        action_type = action.split(":")[0] if ":" in action else action

        required = self.REQUIRED_PARAMS.get(action_type, [])
        for param in required:
            if param not in plan and ":" not in action:
                # 动作里没带参数（如 "history" 而非 "history:USA"），且 plan 里也没补
                return param

        # 兼容：如果 action 是 "history" 或 "country" 但没带国家（没冒号），也算缺
        if action_type in ("history", "country") and ":" not in action:
            return "country"

        return None

    def _build_rule_question(self, missing: str) -> str:
        """根据缺失的参数，生成针对性的澄清问题。"""
        if missing == "country":
            return "你想查询哪个国家/地区的数据？请告诉我具体国家名。"
        if missing == "countries":
            return "你想对比哪些国家？请至少告诉我两个国家名。"
        return "你的问题还缺少一些信息，能补充一下吗？"

    # ---------- 大模型层 ----------

    def _llm_check(self, question: str, plan: dict) -> Optional[str]:
        """让大模型判断是否有语义歧义。返回澄清问题，或 None。"""
        prompt = self.CLARIFY_PROMPT.format(
            question=question,
            action_summary=json.dumps(plan, ensure_ascii=False),
        )
        try:
            raw = self._llm.chat(prompt)
            data = self._parse_json(raw)
            if data.get("needs_clarification"):
                return data.get("question") or "你的问题还不够明确，能补充一下吗？"
            return None
        except Exception:
            # 大模型判断失败时，倾向「不拦截」（放行，让后续链路处理）
            return None

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """容错解析 LLM 返回的 JSON。"""
        if not raw:
            return {}
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
