"""
澄清追问测试

重点测「规则层」（确定性逻辑，最适合自动化测试）：
1. 缺国家名 → 反问
2. 对比但国家数不足 → 反问
3. 信息完整 → 放行（返回 None）
4. global 动作 → 永不需要澄清
"""
import pytest

from app.agent.clarification import ClarificationChecker
from app.llm.provider import MockLLM


@pytest.fixture
def checker():
    """用 MockLLM（不调真实大模型），规则层会先拦截，测不到大模型层。"""
    return ClarificationChecker(llm=MockLLM())


def test_missing_country_in_history_asks_for_clarification(checker):
    """history 动作缺国家名 → 应反问国家。"""
    result = checker.check("查一下疫情趋势", {"action": "history"})
    assert result is not None
    assert "国家" in result


def test_missing_country_in_country_action_asks(checker):
    """country 动作缺国家名 → 应反问国家。"""
    result = checker.check("查一下现状", {"action": "country"})
    assert result is not None
    assert "国家" in result


def test_compare_with_single_country_asks_for_more(checker):
    """对比但只有 1 个国家 → 应反问"对比哪些国家"。"""
    result = checker.check("对比一下", {"actions": ["country:USA"]})
    assert result is not None
    assert "对比" in result


def test_complete_history_passes(checker):
    """history:USA 带国家名 → 信息完整，放行（返回 None）。"""
    result = checker.check("美国30天趋势", {"action": "history:USA", "days": 30})
    assert result is None


def test_complete_country_passes(checker):
    """country:USA 带国家名 → 放行。"""
    result = checker.check("美国现状", {"action": "country:USA"})
    assert result is None


def test_global_never_needs_clarification(checker):
    """global 动作无必填参数 → 永不放行返回 None。"""
    result = checker.check("全球汇总", {"action": "global"})
    assert result is None


def test_compare_with_two_countries_passes(checker):
    """对比两个国家 → 放行。"""
    plan = {"actions": ["country:China", "country:USA"]}
    result = checker.check("中美对比", plan)
    assert result is None


# ---------- 工具调用格式（阶段二新增） ----------

def test_tool_format_history_missing_country(checker):
    """工具调用格式：history 缺国家名 → 反问国家。"""
    plan = {"tool": "disease-sh", "params": {"action": "history"}}
    result = checker.check("查一下疫情趋势", plan)
    assert result is not None
    assert "国家" in result


def test_tool_format_complete_passes(checker):
    """工具调用格式：action 带国家名 → 放行。"""
    plan = {"tool": "disease-sh", "params": {"action": "history:USA", "days": 30}}
    result = checker.check("美国30天趋势", plan)
    assert result is None


def test_tool_format_multi_tools_normalize(checker):
    """工具调用格式：多工具对比 → 归一化成 actions。"""
    plan = {
        "tools": [
            {"tool": "disease-sh", "params": {"action": "country:China"}},
            {"tool": "disease-sh", "params": {"action": "country:USA"}},
        ]
    }
    result = checker.check("中美对比", plan)
    assert result is None


# ---------- 非数据源工具（阶段三新增） ----------

def test_sqlite_tool_clear_question_passes(checker):
    """sqlite 工具：问题明确（不含指代不清）→ 语义层不拦截，放行。"""
    plan = {"tool": "sqlite", "params": {"question": "这个月销量最好的饮品"}}
    result = checker.check("这个月销量最好的饮品", plan)
    # MockLLM 的 chat 不返回「需要澄清」，故语义层放行
    assert result is None


def test_answer_tool_never_needs_clarification(checker):
    """answer 工具（直接回答，无实质查询动作）→ 不参与澄清，直接放行。"""
    plan = {"tool": "answer", "params": {"prompt": "随便聊聊"}}
    result = checker.check("你好", plan)
    assert result is None


def test_sqlite_tool_vague_reference_asks_clarification():
    """sqlite 工具：指代不清（「那个」）→ 语义层反问用户。

    用自定义假 LLM 返回「需要澄清」，验证 sqlite 也走大模型语义层。
    """
    class _ClarifyLLM(MockLLM):
        def chat(self, prompt):
            return '{"needs_clarification": true, "question": "您说的「那个」是指哪款饮品？"}'

    c = ClarificationChecker(llm=_ClarifyLLM())
    plan = {"tool": "sqlite", "params": {"question": "那个卖得怎么样"}}
    result = c.check("那个卖得怎么样", plan)
    assert result is not None
    assert "饮品" in result


