"""
Agent 节点实现（Node）

每个节点是一个函数，负责一件具体的事：
- planner：用 ToolPlanner 把用户问题拆解成「工具调用序列」
- executor：从 ToolRegistry 选工具、执行当前步骤
- reflector：执行失败时，让 LLM 反思并「重新规划」（REPLAN）
- answer：把所有结果汇总成分析报告（复用 AnswerTool）
- clarify：信息不足时，生成反问用户的问题
- decision：决定下一步（路由函数，非节点）

阶段二（多工具 Agent）改造说明：
- 相比旧版，executor 不再写死调 Text2SqlEngine，而是从「工具名册」里选工具
- reflector 不再是「重置重试」，而是真正让 LLM 反思 + 重新规划（换思路）
- 新增 clarify 节点，把「澄清追问」从 chat.py 收编进状态机

这是 LangGraph 三个核心概念之一：Node。
"""
from typing import List

from app.agent.state import AgentState
from app.agent.audit import AuditLogger
from app.agent.tools import ToolRegistry
from app.agent.tool_planner import ToolPlanner
from app.agent.clarification import ClarificationChecker
from app.llm.provider import LLMProvider


# REPLAN 重规划次数上限（对应旧 Text2SQL 的 max_retries，防止死循环烧 token）
MAX_REPLAN = 3


class AgentNodes:
    """Agent 的所有节点（多工具版）"""

    def __init__(
        self,
        llm: LLMProvider,
        registry: ToolRegistry,
        audit: AuditLogger | None = None,
    ):
        """
        llm: 大模型，供 planner / reflector / answer 使用
        registry: 工具名册（ToolRegistry），executor 从里面选工具
        audit: 事件审计器（可选），用于记录每一步执行
        """
        self._llm = llm
        self._registry = registry
        self._planner = ToolPlanner(llm=llm, registry=registry)
        self._clarifier = ClarificationChecker(llm=llm)
        self._audit = audit or AuditLogger()

    def planner(self, state: AgentState) -> AgentState:
        """规划节点：用 ToolPlanner 把问题翻译成「工具调用序列」。

        相比旧版（拆成 Text2SQL 步骤），这里产出的是结构化工具调用，
        由 ToolPlanner 从工具名册里选工具。

        规划完成后，做「澄清检查」：信息不足则不瞎猜，置 waiting_user
        让 decision 走 clarify 分支反问用户。
        """
        question = state["question"]

        plan = self._planner.plan(question)

        self._audit.log(
            "planner",
            "规划完成，生成工具调用",
            plan=plan,
        )

        state["plan"] = plan
        state["current_step"] = 0
        state["results"] = []
        state["context"] = ""
        state["replan_count"] = 0

        # 澄清检查：信息不足 → 反问用户，不进执行
        clarify_question = self._clarifier.check(question, plan)
        if clarify_question:
            state["status"] = "waiting_user"
            state["clarify_question"] = clarify_question
            state["final_answer"] = clarify_question
            self._audit.log("planner", "信息不足，需要澄清", question=clarify_question)
            return state

        state["status"] = "running"
        return state

    def executor(self, state: AgentState) -> AgentState:
        """执行节点：从工具名册选工具，执行当前步骤。

        关键改造：不再写死调 Text2SqlEngine，而是：
        1. 从 plan 里取出当前要调用的「工具名 + 参数」
        2. 用 ToolRegistry.get(name) 找到工具
        3. 调 tool.run(**params) 执行
        """
        # 取出当前步骤的工具调用
        calls = self._extract_calls(state["plan"])
        step_index = state["current_step"]
        if step_index >= len(calls):
            # 没有更多步骤了（异常兜底）
            state["status"] = "success"
            return state

        call = calls[step_index]
        tool_name = call.get("tool", "")
        params = call.get("params", {})

        # 从名册里选工具（找不到工具也算失败，交给 decision 处理）
        tool = self._registry.get(tool_name)
        if tool is None:
            error = f"找不到工具：{tool_name}"
            self._audit.log("executor", error, tool=tool_name, error=error)
            state["status"] = "failed"
            state["error"] = error
            return state

        # 执行工具
        try:
            result = tool.run(**params)
        except Exception as e:
            error = f"工具 {tool_name} 执行失败：{e}"
            self._audit.log("executor", error, tool=tool_name, error=error)
            state["status"] = "failed"
            state["error"] = error
            return state

        # 工具可能不抛异常，而是用结构化结果报告业务错误
        # （例如 Text2SQL 重试耗尽）。这类结果不能当成功继续汇总。
        result_error = (
            result.get("error")
            or (result.get("meta") or {}).get("error")
        )
        if result_error:
            state["results"].append(result)
            error = f"工具 {tool_name} 执行失败：{result_error}"
            self._audit.log("executor", error, tool=tool_name, error=result_error)
            state["status"] = "failed"
            state["error"] = error
            return state

        self._audit.log(
            "executor",
            f"执行第 {step_index + 1} 步：{tool_name}",
            tool=tool_name,
            params=params,
        )

        state["results"].append(result)

        # 更新上下文（供下一步依赖 + 最终汇总）
        state["context"] = self._summarize_for_context(result, state["context"])

        # 这一步成功，前进到下一步
        state["current_step"] += 1
        return state

    def reflector(self, state: AgentState) -> AgentState:
        """反思节点（REPLAN）：让 LLM 反思失败原因，重新规划。

        相比旧版（只重置状态重试同一步），这里是真正的「换思路」：
        - 把「失败信息 + 原计划」喂给 LLM
        - LLM 给出新的工具调用计划
        - 重规划次数 +1，超过上限则放弃（防死循环）

        这样失败时不是「原地硬撞」，而是「换个问法 / 换个工具 / 拆成更小步骤」。
        """
        replan_count = state.get("replan_count", 0) + 1
        state["replan_count"] = replan_count

        if replan_count > MAX_REPLAN:
            # 超过上限：放弃，直接转失败（避免无限烧 token）
            state["status"] = "failed"
            state["error"] = state.get("error") or "多次重规划仍失败"
            self._audit.log("reflector", "超过重规划上限，放弃", replan_count=replan_count)
            return state

        # 让 LLM 反思并重新规划
        new_plan = self._replan(state)
        state["plan"] = new_plan
        state["current_step"] = 0
        state["results"] = []
        state["status"] = "running"
        state["error"] = None

        self._audit.log(
            "reflector",
            f"第 {replan_count} 次重规划",
            replan_count=replan_count,
            new_plan=new_plan,
        )
        return state

    def clarify(self, state: AgentState) -> AgentState:
        """澄清节点：生成反问用户的问题，状态置为等待用户。"""
        state["status"] = "waiting_user"
        state["final_answer"] = state.get("clarify_question")
        self._audit.log("clarify", "需要澄清", question=state.get("clarify_question"))
        return state

    def answer(self, state: AgentState) -> AgentState:
        """汇总节点：把所有步骤结果，用 LLM 总结成人话分析报告。

        复用 AnswerTool（而非单独写汇总逻辑），保持「一切皆工具」的统一范式。
        """
        results_text = self._build_results_text(state["results"])
        question = state["question"]

        prompt = (
            "你是一名数据分析师。下面是根据用户问题逐步查询得到的数据结果，"
            "请把它们汇总成一段清晰、可读的分析报告，用中文回答，"
            "适当指出数据反映的结论，并提醒数据可能存在滞后。\n\n"
            f"用户问题：{question}\n\n"
            f"查询结果：\n{results_text}\n\n"
            "请输出分析报告："
        )
        answer = self._llm.chat(prompt)

        self._audit.log("answer", "汇总完成", answer_length=len(answer or ""))

        state["final_answer"] = answer
        state["status"] = "success"
        return state

    def decision(self, state: AgentState) -> str:
        """决策函数（路由函数，不是节点）：根据状态决定下一步去哪。

        返回字符串键对应 graph.py 里的 mapping：
        - "next"    ：还有步骤没执行，回 executor
        - "replan"  ：当前步骤失败，回 reflector 重规划
        - "clarify" ：信息不足，去 clarify 反问用户
        - "done"    ：全部完成，去 answer 汇总
        - "end"     ：失败放弃或等待用户，直接结束
        """
        # 失败：优先判断是否还能重规划
        if state.get("status") == "failed":
            if state.get("replan_count", 0) >= MAX_REPLAN:
                return "end"  # 超过上限，放弃
            return "replan"

        # 等待用户澄清：去 clarify 节点（生成反问 → 结束，等下一轮用户输入）
        if state.get("status") == "waiting_user":
            return "clarify"

        # 还有步骤没执行完
        calls = self._extract_calls(state["plan"])
        if state["current_step"] < len(calls):
            return "next"

        # 全部完成 → 汇总
        return "done"

    # ---------- 辅助方法 ----------

    def _extract_calls(self, plan: dict) -> List[dict]:
        """把 plan 统一成「工具调用列表」。

        plan 有两种形态：
        - 单工具：{"tool": ..., "params": {...}}
        - 多工具：{"tools": [{"tool":..., "params":...}, ...]}
        统一返回一个 list，方便 executor/decision 按索引处理。
        """
        if not plan:
            return []
        if "tools" in plan and isinstance(plan["tools"], list):
            return plan["tools"]
        if "tool" in plan:
            return [{"tool": plan["tool"], "params": plan.get("params", {})}]
        return []

    def _replan(self, state: AgentState) -> dict:
        """让 LLM 反思失败原因，返回新的工具调用计划。"""
        error = state.get("error") or "未知错误"
        question = state["question"]
        old_plan = state.get("plan") or {}

        prompt = (
            "你是一个任务规划器。之前针对用户问题生成的工具调用计划执行失败了，"
            "请反思失败原因，并重新生成一个更合理的计划。\n\n"
            "可用的工具清单：\n"
            f"{self._registry.describe()}\n\n"
            f"用户问题：{question}\n"
            f"原计划：{old_plan}\n"
            f"失败原因：{error}\n\n"
            "请重新规划。可以：换个工具、调整参数、或把复杂查询拆成多个简单步骤。\n"
            "输出格式（严格 JSON）：\n"
            '单工具：{"tool": "disease-sh", "params": {"action": "country:USA"}}\n'
            '多工具：{"tools": [{"tool": "disease-sh", "params": {"action": "country:China"}}, '
            '{"tool": "disease-sh", "params": {"action": "country:USA"}}]}\n'
            "只输出 JSON，不要解释。"
        )
        try:
            raw = self._llm.chat(prompt)
            plan = self._parse_plan(raw)
            return plan if plan else {"tool": "answer", "params": {"prompt": "请直接回答用户"}}
        except Exception:
            return {"tool": "answer", "params": {"prompt": "请直接回答用户"}}

    @staticmethod
    def _parse_plan(raw: str) -> dict:
        """容错解析 LLM 返回的 JSON 计划。"""
        import json
        import re
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            if "tool" in data or "tools" in data:
                return data
        except json.JSONDecodeError:
            pass
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
                if "tool" in data or "tools" in data:
                    return data
            except json.JSONDecodeError:
                pass
        return {}

    @staticmethod
    def _summarize_for_context(result: dict, prev_context: str) -> str:
        """把单步结果压缩成简短上下文，供下一步/汇总使用。

        限制长度避免上下文膨胀（对应「数据精简」的设计思想）。
        """
        rows = result.get("rows", [])
        columns = result.get("columns", [])
        meta = result.get("meta") or {}

        # 时间序列类（history/forecast）：数据多，只取最新几条 + 总数
        if meta.get("kind") in ("history", "forecast"):
            name = meta.get("country") or meta.get("name") or meta.get("kind", "数据")
            snippet = f"{name}共{len(rows)}条"
            if rows:
                snippet += f"（最新：{'，'.join(f'{c}={v}' for c, v in zip(columns, rows[-1]))}）"
        elif rows:
            lines = []
            for row in rows[:10]:
                lines.append("，".join(f"{c}={v}" for c, v in zip(columns, row)))
            snippet = "；".join(lines)
        else:
            return prev_context

        if prev_context:
            return f"{prev_context}\n{snippet}"
        return snippet

    @staticmethod
    def _build_results_text(results: list[dict]) -> str:
        """把所有步骤结果拼成文本，喂给汇总模型。

        关键：不再硬编码「history 只有 2 列」，而是按 columns 通用拼接，
        这样疫情（date/cases）和天气（date/weather/temp_max/...）都能完整呈现。
        """
        text_parts = []
        for i, r in enumerate(results, 1):
            columns = r.get("columns", [])
            rows = r.get("rows", [])
            meta = r.get("meta") or {}
            kind = meta.get("kind", "")
            if kind == "answer":
                text_parts.append(f"第{i}步：{rows[0][0] if rows else ''}")
            elif kind in ("history", "forecast"):
                # 时间序列类：首列是日期，其余列按字段名拼接
                lines = ["  " + "，".join(f"{c}={v}" for c, v in zip(columns, row)) for row in rows]
                text_parts.append(f"第{i}步（{kind}，共{len(rows)}天）：\n" + "\n".join(lines))
            else:
                lines = ["  " + "，".join(f"{c}={v}" for c, v in zip(columns, row)) for row in rows]
                text_parts.append(f"第{i}步（字段：{'、'.join(columns)}）：\n" + "\n".join(lines))
        return "\n\n".join(text_parts) if text_parts else "（无查询结果）"
