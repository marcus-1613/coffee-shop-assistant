"""
工具抽象层测试（Tool + ToolRegistry + ToolPlanner + 具体工具）

验证「多工具 Agent 骨架」的核心能力：
1. Tool 接口 + ToolRegistry 能正确注册、列出、生成工具清单
2. DataSourceTool 能把「数据源」包装成统一工具调用
3. AnswerTool 能把「大模型回答」包装成统一工具调用
4. ToolPlanner 能根据「工具清单」让模型选工具、解析结构化调用

这组测试不碰真实网络（用假数据源 + MockLLM），离线、快速、确定。

这是「企业级升级 · 阶段二（多工具 Agent）· 2-A」的产物。
"""
from app.agent.tools import Tool, ToolRegistry
from app.agent.tool_impls import DataSourceTool, AnswerTool, SqliteTool
from app.agent.tool_planner import ToolPlanner
from app.llm.provider import MockLLM
from app.datasource.base import DataSource
from app.datasource.open_meteo import OpenMeteoSource
from app.text2sql.engine import Text2SqlEngine


class _FakeSource(DataSource):
    """测试用假数据源：不碰网络，返回固定结构化结果。"""

    def __init__(self):
        self.calls = []

    @property
    def name(self):
        return "fake-source"

    @property
    def description(self):
        return "测试用假数据源，能查 global/country/history"

    def schema(self):
        return "fake"

    def query(self, sql_or_action, **params):
        self.calls.append((sql_or_action, params))
        action = sql_or_action
        if action.startswith("history:"):
            return {
                "columns": ["date", "cases"],
                "rows": [["1/1/23", 100], ["1/2/23", 200]],
                "row_count": 2,
                "meta": {"kind": "history"},
            }
        if action.startswith("country:"):
            country = action.split(":", 1)[1]
            return {
                "columns": ["country", "cases"],
                "rows": [[country, 1000]],
                "row_count": 1,
                "meta": {"kind": "country", "country": country},
            }
        return {
            "columns": ["cases"],
            "rows": [[5000]],
            "row_count": 1,
            "meta": {"kind": "global"},
        }


class TestToolRegistry:
    """工具注册表的核心行为"""

    def test_register_and_get(self):
        """注册后能按名字取回。"""
        registry = ToolRegistry()
        tool = DataSourceTool(_FakeSource())
        registry.register(tool)
        assert registry.get("fake-source") is tool

    def test_list_returns_all(self):
        """能列出所有已注册工具。"""
        registry = ToolRegistry()
        registry.register(DataSourceTool(_FakeSource()))
        registry.register(AnswerTool(MockLLM()))
        names = [t.name for t in registry.list()]
        assert "fake-source" in names
        assert "answer" in names

    def test_describe_contains_tool_info(self):
        """工具清单描述包含工具名和描述。"""
        registry = ToolRegistry()
        registry.register(DataSourceTool(_FakeSource()))
        text = registry.describe()
        assert "fake-source" in text
        assert "测试用假数据源" in text

    def test_describe_empty(self):
        """空注册表给出明确提示。"""
        registry = ToolRegistry()
        assert "无可用工具" in registry.describe()


class TestDataSourceTool:
    """数据源工具：把数据源包装成统一调用"""

    def test_run_returns_structured_result(self):
        """执行后返回统一的 columns/rows/row_count/meta 结构。"""
        source = _FakeSource()
        tool = DataSourceTool(source)
        result = tool.run(action="country:China")
        assert result["columns"] == ["country", "cases"]
        assert result["rows"][0][0] == "China"
        assert result["row_count"] == 1
        assert result["meta"]["kind"] == "country"

    def test_run_passes_days(self):
        """days 参数能透传给数据源。"""
        source = _FakeSource()
        tool = DataSourceTool(source)
        tool.run(action="history:China", days=30)
        # 数据源收到 action + days
        assert source.calls[0][0] == "history:China"
        assert source.calls[0][1].get("days") == 30

    def test_run_passes_extra_params(self):
        """location/start_date 等额外参数能透传（阶段四修复：之前被丢弃）。"""
        source = _FakeSource()
        tool = DataSourceTool(source)
        tool.run(action="forecast", location="南昌", start_date="2026-10-23", days=1)
        params = source.calls[0][1]
        assert params.get("location") == "南昌"
        assert params.get("start_date") == "2026-10-23"
        assert params.get("days") == 1

    def test_run_ignores_none_params(self):
        """值为 None 的参数不透传（避免覆盖数据源默认值）。"""
        source = _FakeSource()
        tool = DataSourceTool(source)
        tool.run(action="global", location=None, start_date=None)
        params = source.calls[0][1]
        assert "location" not in params
        assert "start_date" not in params

    def test_weather_tool_declares_location_and_start_date(self):
        """天气工具的参数说明必须含 location/start_date（否则 LLM 不会生成）。"""
        tool = DataSourceTool(OpenMeteoSource())
        params = tool.parameters()
        assert "location" in params
        assert "start_date" in params
        assert "end_date" in params
        assert "action" in params

    def test_source_without_extra_params_declares_only_action(self):
        """没声明 extra_params 的数据源，参数说明只有 action（阶段四重构）。

        验证「额外参数」职责已下沉到数据源：通用工具层不再针对某个源硬编码，
        默认 extra_params 返回空，通用包装器不认识任何具体源（开闭原则）。
        """
        tool = DataSourceTool(_FakeSource())
        params = tool.parameters()
        # 假数据源没覆写 extra_params，应只有 action 一个参数
        assert set(params.keys()) == {"action"}


class TestAnswerTool:
    """回答工具：把大模型回答包装成统一调用"""

    def test_run_returns_answer(self):
        """用预设回答，验证包装结构。"""
        llm = MockLLM(preset_chat="你好，我是助手")
        tool = AnswerTool(llm)
        result = tool.run(prompt="打个招呼")
        assert result["columns"] == ["answer"]
        assert result["rows"][0][0] == "你好，我是助手"
        assert result["meta"]["kind"] == "answer"


class TestSqliteTool:
    """本地库工具：把 Text2SQL 包装成统一调用"""

    def test_run_returns_structured_result(self):
        """用预设 SQL（MockLLM）验证包装结构，离线可测。"""
        llm = MockLLM(preset_sql="SELECT name FROM cafe_products LIMIT 2")
        tool = SqliteTool(Text2SqlEngine(llm=llm))
        result = tool.run(question="有哪些饮品")
        assert "columns" in result
        assert result["meta"]["kind"] == "sqlite"
        assert result["meta"]["sql"] is not None

    def test_run_returns_error_when_query_fails(self):
        """当 SQL 一直失败（重试耗尽）时，返回带 error 的结果而非抛异常。"""
        # 用一条必然被安全校验拒绝的「写操作」SQL，触发多次失败
        llm = MockLLM(preset_sql="DROP TABLE cafe_products")
        tool = SqliteTool(Text2SqlEngine(llm=llm))
        result = tool.run(question="删掉饮品表")
        assert result["row_count"] == 0
        assert "error" in result["meta"]


class TestToolPlanner:
    """工具规划器：让模型从工具清单里选工具"""

    def _registry(self):
        registry = ToolRegistry()
        registry.register(DataSourceTool(_FakeSource()))
        registry.register(AnswerTool(MockLLM()))
        return registry

    def test_plan_single_tool(self):
        """模型返回单工具调用，能正确解析。"""
        llm = MockLLM(preset_chat='{"tool": "fake-source", "params": {"action": "global"}}')
        planner = ToolPlanner(llm=llm, registry=self._registry())
        plan = planner.plan("全球有多少病例")
        assert plan["tool"] == "fake-source"
        assert plan["params"]["action"] == "global"

    def test_plan_multi_tools(self):
        """模型返回多工具调用（对比），能正确解析。"""
        raw = '{"tools": [{"tool": "fake-source", "params": {"action": "country:China"}}, '
        raw += '{"tool": "fake-source", "params": {"action": "country:USA"}}]}'
        llm = MockLLM(preset_chat=raw)
        planner = ToolPlanner(llm=llm, registry=self._registry())
        plan = planner.plan("中美对比")
        assert "tools" in plan
        assert len(plan["tools"]) == 2

    def test_plan_fallback_on_garbage(self):
        """模型返回乱码时，兜底成 answer 工具，不中断。"""
        llm = MockLLM(preset_chat="这是乱七八糟的回答，没有JSON")
        planner = ToolPlanner(llm=llm, registry=self._registry())
        plan = planner.plan("随便问")
        assert plan["tool"] == "answer"

    def test_plan_fallback_on_empty(self):
        """模型返回空，兜底成 answer 工具。"""
        llm = MockLLM(preset_chat="")
        planner = ToolPlanner(llm=llm, registry=self._registry())
        plan = planner.plan("随便问")
        assert plan["tool"] == "answer"
