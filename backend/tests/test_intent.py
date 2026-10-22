"""
意图分类规则兜底测试

验证 _is_obvious_analysis 规则硬匹配：疫情/经营/天气/趋势类关键词
必须稳定判为 analysis，避免 LLM 分类随机性导致误判成 chat。
"""
from app.agent.intent import IntentClassifier


class TestObviousAnalysisRule:
    @staticmethod
    def _classify(q):
        return IntentClassifier._is_obvious_analysis(q)

    def test_epidemic_keywords(self):
        assert self._classify("美国疫情趋势") is True
        assert self._classify("全球确诊多少") is True
        assert self._classify("日本死亡病例") is True
        assert self._classify("新增治愈多少") is True

    def test_business_keywords(self):
        assert self._classify("这个月销量排行") is True
        assert self._classify("毛利最高的饮品") is True
        assert self._classify("会员平均消费") is True

    def test_weather_keywords(self):
        assert self._classify("今天天气怎么样") is True
        assert self._classify("下周有没有降水") is True
        assert self._classify("温度多少度") is True

    def test_trend_compare_keywords(self):
        assert self._classify("近30天趋势") is True
        assert self._classify("中美对比") is True
        assert self._classify("哪个时段订单最多") is True

    def test_chat_should_not_match(self):
        assert self._classify("你好") is False
        assert self._classify("你是谁") is False
        assert self._classify("谢谢") is False
        assert self._classify("讲个笑话") is False

    def test_case_insensitive(self):
        assert self._classify("美国疫情趋势") is True
        assert self._classify("TOP5 销量") is True


class TestClassifyWithRule:
    """验证 classify() 在命中规则时直接返回 analysis（不依赖 LLM）。"""

    def test_obvious_analysis_skips_llm(self):
        """命中规则时，即使 LLM 是坏的（抛异常），也应返回 analysis。"""
        classifier = IntentClassifier(llm=_BoomLLM())
        # "疫情" 命中规则 → 直接 analysis，不调 LLM
        assert classifier.classify("美国疫情趋势") == "analysis"

    def test_chat_still_uses_llm(self):
        """闲聊不命中规则 → 走 LLM 分类（这里 LLM 抛异常兜底为 analysis）。"""
        classifier = IntentClassifier(llm=_BoomLLM())
        # 兜底：LLM 异常 → analysis（保证查询不漏）
        assert classifier.classify("你好") == "analysis"


class _BoomLLM:
    """故意抛异常的 LLM，用于验证规则兜底不依赖 LLM。"""

    def chat(self, prompt):
        raise RuntimeError("LLM 不可用")
