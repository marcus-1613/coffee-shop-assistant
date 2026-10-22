"""
多工具 Agent 状态机测试（2-B）

验证重写后的状态机核心行为：
1. 规划 → 选工具执行 → 汇总，端到端跑通
2. 失败时触发 REPLAN（反思重规划），而非傻重试
3. REPLAN 次数上限，防止死循环
4. 澄清追问（信息不足时不瞎猜）

不碰真实网络（用 MockLLM + 假数据源），离线、快速、确定。

这是「企业级升级 · 阶段二（多工具 Agent）· 2-B」的产物。
"""
from app.agent import ToolRegistry, DataSourceTool, AnswerTool, AgentNodes, build_graph
from app.llm.provider import MockLLM
from app.datasource.base import DataSource


class _FakeSource(DataSource):
    """假数据源：不碰网络。可配置成「成功」或「抛异常」。"""

    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    @property
    def name(self):
        return "fake-source"

    @property
    def description(self):
        return "测试用假数据源"

    def schema(self):
        return "fake"

    def query(self, sql_or_action, **params):
        self.calls.append(sql_or_action)
        if self.fail:
            raise ConnectionError("数据源挂了")
        if sql_or_action.startswith("history:"):
            return {
                "columns": ["date", "cases"],
                "rows": [["1/1/23", 100], ["1/2/23", 200]],
                "row_count": 2,
                "meta": {"kind": "history", "country": "China"},
            }
        return {
            "columns": ["country", "cases"],
            "rows": [["China", 1000]],
            "row_count": 1,
            "meta": {"kind": "country", "country": "China"},
        }


class _PlannerLLM(MockLLM):
    """带「计划/反思/回答」能力的假 LLM：按 prompt 关键词区分阶段。

    注意：ToolPlanner 的 prompt 含「工具清单」，answer 的 prompt 含「数据分析师」，
    reflector 的 prompt 含「重新规划」。用这三个特征词精确区分阶段。
    """

    def __init__(self, plan_json: str, replan_json: str = "", answer_text: str = "分析完成"):
        super().__init__()
        self._plan = plan_json
        self._replan = replan_json
        self._answer = answer_text
        self.calls = []

    def chat(self, prompt: str) -> str:
        self.calls.append(prompt)
        # reflector：含「重新规划」或「反思」（answer 工具描述里也有「分析」字样，故用更独特的词）
        if "重新规划" in prompt or "反思" in prompt:
            return self._replan
        # answer：用「你是一名数据分析师」这个独有的开场白判断
        if "数据分析师" in prompt:
            return self._answer
        # planner / 其他：返回计划 JSON
        return self._plan


def _build_graph(llm, source=None):
    registry = ToolRegistry()
    registry.register(DataSourceTool(source or _FakeSource()))
    registry.register(AnswerTool(llm))
    nodes = AgentNodes(llm=llm, registry=registry)
    return build_graph(nodes)


class TestAgentGraph:
    """状态机端到端行为"""

    def test_single_tool_flow(self):
        """规划→执行→汇总，端到端跑通。"""
        llm = _PlannerLLM(
            plan_json='{"tool": "fake-source", "params": {"action": "country:China"}}',
            answer_text="中国累计确诊 1000 例",
        )
        graph = _build_graph(llm)
        result = graph.invoke({"question": "中国确诊多少"})

        assert result["status"] == "success"
        assert result["final_answer"] == "中国累计确诊 1000 例"
        assert len(result["results"]) == 1  # 执行了一个工具

    def test_multi_tool_flow(self):
        """多工具（对比）能逐步执行完。"""
        llm = _PlannerLLM(
            plan_json='{"tools": [{"tool": "fake-source", "params": {"action": "country:China"}}, '
                      '{"tool": "fake-source", "params": {"action": "country:USA"}}]}',
            answer_text="对比完成",
        )
        graph = _build_graph(llm)
        result = graph.invoke({"question": "中美对比"})

        assert result["status"] == "success"
        assert len(result["results"]) == 2  # 执行了两个工具

    def test_clarify_flow(self):
        """信息不足（history 缺国家名）→ 走 clarify 反问，不进 executor。"""
        # planner 返回 history 但缺国家名，触发澄清
        llm = _PlannerLLM(
            plan_json='{"tool": "fake-source", "params": {"action": "history"}}',
            answer_text="分析完成",
        )
        graph = _build_graph(llm)
        result = graph.invoke({"question": "查一下疫情趋势"})

        # 关键：状态置 waiting_user，clarify_question 被填充，且没有执行任何工具
        assert result["status"] == "waiting_user"
        assert result.get("clarify_question")
        assert "国家" in result["clarify_question"]
        assert len(result.get("results", [])) == 0  # 没进 executor

    def test_replan_on_failure(self):
        """工具执行失败 → 触发 REPLAN → 重新规划后成功。"""
        # 数据源第一次会失败，但 REPLAN 后规划成 answer 工具，绕过数据源
        llm = _PlannerLLM(
            plan_json='{"tool": "fake-source", "params": {"action": "country:China"}}',
            replan_json='{"tool": "answer", "params": {"prompt": "数据源不可用，直接回答"}}',
            answer_text="抱歉，暂时查不到数据",
        )
        source = _FakeSource(fail=True)  # 数据源会抛异常
        graph = _build_graph(llm, source=source)
        result = graph.invoke({"question": "中国确诊多少"})

        # 关键：REPLAN 发生了（replan_count >= 1），且最终成功
        assert result["replan_count"] >= 1
        assert result["status"] == "success"
        assert result["final_answer"] == "抱歉，暂时查不到数据"

    def test_replan_max_limit(self):
        """REPLAN 次数达到上限后放弃，不会无限循环。"""
        # 数据源一直失败，REPLAN 也一直返回失败的工具调用
        llm = _PlannerLLM(
            plan_json='{"tool": "fake-source", "params": {"action": "country:China"}}',
            replan_json='{"tool": "fake-source", "params": {"action": "country:China"}}',
        )
        source = _FakeSource(fail=True)
        graph = _build_graph(llm, source=source)
        result = graph.invoke({"question": "中国确诊多少"})

        # 达到 MAX_REPLAN=3 后放弃，状态 failed
        assert result["status"] == "failed"
        assert result["replan_count"] >= 3


class TestDecisionRouting:
    """decision 路由逻辑（直接测，不跑完整图）"""

    def _nodes(self):
        llm = _PlannerLLM(plan_json='{"tool": "answer", "params": {}}')
        registry = ToolRegistry()
        registry.register(AnswerTool(llm))
        return AgentNodes(llm=llm, registry=registry)

    def test_decision_next_when_steps_remain(self):
        """还有步骤没执行 → next。"""
        nodes = self._nodes()
        state = {
            "plan": {"tools": [{"tool": "answer", "params": {}}, {"tool": "answer", "params": {}}]},
            "current_step": 0,
            "status": "running",
            "replan_count": 0,
        }
        assert nodes.decision(state) == "next"

    def test_decision_replan_when_failed(self):
        """失败且未超上限 → replan。"""
        nodes = self._nodes()
        state = {
            "plan": {"tool": "answer", "params": {}},
            "current_step": 0,
            "status": "failed",
            "error": "工具挂了",
            "replan_count": 0,
        }
        assert nodes.decision(state) == "replan"

    def test_decision_end_when_replan_exhausted(self):
        """失败且超上限 → end（放弃）。"""
        nodes = self._nodes()
        state = {
            "plan": {"tool": "answer", "params": {}},
            "current_step": 0,
            "status": "failed",
            "error": "工具挂了",
            "replan_count": 3,  # 达到 MAX_REPLAN
        }
        assert nodes.decision(state) == "end"

    def test_decision_done_when_finished(self):
        """所有步骤完成 → done（汇总）。"""
        nodes = self._nodes()
        state = {
            "plan": {"tool": "answer", "params": {}},
            "current_step": 1,  # 已执行完 1 步（共 1 步）
            "status": "running",
            "replan_count": 0,
        }
        assert nodes.decision(state) == "done"
