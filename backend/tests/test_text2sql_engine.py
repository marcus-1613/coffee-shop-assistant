"""
Text2SQL 引擎的自我纠错测试

验证 ADR-008 的核心：Agent 循环必须设置最大重试上限，防止死循环。

这是「依赖倒置」价值的直接体现：
- Text2SqlEngine 依赖 LLMProvider 接口，不依赖具体模型
- 测试时用 MockLLM 注入「永远出错的 SQL」，不需要 API Key、不需要网络
- 这样就能离线、确定性地验证「重试 3 次就停」这个铁律

这是「企业级升级 · P0 测试」的第二组产物。
"""
import pytest

from app.text2sql.engine import Text2SqlEngine
from app.llm.provider import MockLLM
from app.text2sql.safety import SqlSafetyValidator


class TestText2SqlEngine:
    """Text2SQL 引擎自纠错的测试"""

    def test_stops_after_max_retries(self):
        """
        核心测试：模型一直生成错误 SQL 时，引擎必须在 max_retries 次后停止，
        而不是无限循环。
        """
        # 用一个「永远生成危险 SQL」的假模型（DROP 会被安全校验拦截）
        bad_llm = MockLLM(preset_sql="DROP TABLE cafe_products")

        engine = Text2SqlEngine(llm=bad_llm, max_retries=3)

        result = engine.query("统计患者数")

        # 关键断言：重试次数必须恰好等于 max_retries（3 次），不能多不能少
        assert result["retries"] == 3
        # 最终没有成功的 SQL
        assert result["sql"] is None
        # 有友好的错误提示（而不是抛异常）
        assert "3 次" in result["error"]

    def test_recovers_on_second_try(self):
        """
        验证「自我纠错」真的有用：模型第一次错，第二次对了，能恢复成功。
        """
        # 用自定义 LLM：第一次返回危险 SQL，之后返回正确 SQL
        class FlakyLLM(MockLLM):
            def __init__(self):
                super().__init__()
                self.calls = 0

            def generate_sql(self, prompt):
                self.calls += 1
                if self.calls == 1:
                    return "DROP TABLE cafe_products"  # 第一次故意错
                return "SELECT COUNT(*) AS total FROM cafe_products"  # 第二次对

        engine = Text2SqlEngine(llm=FlakyLLM(), max_retries=3)

        result = engine.query("统计患者数")

        # 第二次就成功了，重试次数 = 1（第一次失败，第二次成功）
        assert result["retries"] == 1
        assert result["sql"] is not None
        # 成功时没有 error 键（引擎只在失败时返回 error）
        assert "error" not in result

    def test_first_try_success_no_retry(self):
        """模型第一次就生成正确 SQL 时，重试次数应为 0。"""
        good_llm = MockLLM(preset_sql="SELECT COUNT(*) AS total FROM cafe_products")

        engine = Text2SqlEngine(llm=good_llm, max_retries=3)

        result = engine.query("统计患者数")

        assert result["retries"] == 0
        assert result["sql"] is not None
        # 成功时没有 error 键
        assert "error" not in result


class TestSqlSafetyValidatorDirect:
    """补充：验证引擎确实把安全校验器用上了（而不是跳过校验）"""

    def test_engine_uses_safety_validator(self):
        """
        即使模型返回「语法正确但危险」的 SQL，引擎也必须靠安全校验器拦截，
        而不是直接执行。
        """
        # 注入一条「语法正确但是写操作」的 SQL
        evil_llm = MockLLM(preset_sql="DELETE FROM cafe_products")

        engine = Text2SqlEngine(llm=evil_llm, max_retries=2)

        result = engine.query("删掉所有患者")

        # 危险 SQL 被安全校验拦截 → 重试耗尽 → 失败
        assert result["sql"] is None
        assert result["error"] is not None
