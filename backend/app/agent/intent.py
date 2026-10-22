"""
意图分类器（Intent Router / 路由守卫）

职责：在 Agent 图的最前面，判断用户输入属于哪一类，分流到不同处理链路。

为什么需要它？（对应你提出的问题 1）
之前的设计有个缺陷：不管用户问什么，都硬跑 Text2SQL → 生成 SQL → 执行 →
失败 → 自我纠错 → 打到 max_retries=3 才停。这会导致：
- 闲聊（"你好""今天天气怎么样"）白白烧 3 次大模型调用
- 用户干等，体验差

意图分类解决的是「失败成本前置」：在开始干活之前，先判断「这个活该走哪条路」。

关键设计（回应你的两点纠正）：
1. 不是「拦掉无关问题、回一句死话」——而是「分流」。
   闲聊也会走大模型，只是走「闲聊链路」，不是「Text2SQL 链路」。
2. 分类结果有三类，而不是两类（多了一个"分析"，因为数据源升级后，
   "分析趋势"和"查单个数字"是两种不同的处理）。

分类类型：
- chat      ：闲聊 / 与数据无关（走 LLM 直接对话）
- analysis  ：数据分析需求（走 Agent + 数据源查询 + 出图）
- unknown   ：分类失败（兜底走 LLM 对话，保证不中断）

这是「企业级升级 · 阶段一」的产物。
"""
import json
import re

from app.llm.provider import LLMProvider


class IntentClassifier:
    """意图分类器：判断用户输入该走哪条链路"""

    PROMPT_TEMPLATE = """你是一个意图识别器，服务于「咖啡店经营助手」。请判断店长这句话属于哪一类。

类别定义：
- "chat"：闲聊、问候、与任何数据查询/分析都无关的对话。例如"你好"、"你是谁"、
  "讲个笑话"、"谢谢"。
- "analysis"：想要查询或分析数据的需求。包括但不限于：
  * 经营数据：销量、毛利、会员、订单、时段、饮品排行
  * 天气：天气预报、历史天气、天气对销量的影响、备货建议
  * 疫情/公共卫生：某国疫情趋势、确诊/死亡/治愈数据、全球汇总、多国对比
  * 任何"查数字、看趋势、做对比"的需求

规则：
1. 只要店长想获取或分析「销量/毛利/会员/订单/天气/备货/疫情/趋势/对比」等数据，
   就归为 "analysis"。尤其是提到疫情、确诊、死亡、病例、趋势、对比等词，
   一定要归为 "analysis"，不要归为 chat。
2. 其余都归为 "chat"。
3. 只输出一个 JSON，不要任何解释。

输出格式（严格 JSON）：
{{"intent": "chat"}}

用户的话：
{question}

请判断："""

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    def classify(self, question: str) -> str:
        """返回 "chat" / "analysis" / "unknown" 之一。"""
        # 规则兜底：明显的数据查询关键词，直接判 analysis，不受 LLM 随机性影响
        if self._is_obvious_analysis(question):
            return "analysis"

        prompt = self.PROMPT_TEMPLATE.format(question=question)
        try:
            raw = self._llm.chat(prompt)
            return self._parse_intent(raw)
        except Exception:
            # 分类失败兜底：按 analysis 处理，保证查询类需求不会被漏掉
            return "analysis"

    @staticmethod
    def _is_obvious_analysis(question: str) -> bool:
        """规则兜底：命中明显的数据查询关键词，直接归为 analysis。

        设计动机：LLM 意图分类有随机性，同一个疫情问题可能时判 analysis
        时判 chat。对「确定性」强的关键词做规则硬匹配，避免疫情/趋势/对比
        类问题被误判成闲聊，导致「明明有疫情数据源却说没有」的尴尬。
        """
        q = (question or "").lower()
        keywords = [
            "疫情", "确诊", "死亡", "病例", "治愈", "新增",
            "趋势", "对比", "排行", "销量", "毛利", "会员",
            "备货", "天气", "预报", "降水", "温度", "气温",
            "多少", "几款", "哪款", "哪个时段", "top", "排名",
        ]
        return any(kw in q for kw in keywords)

    def _parse_intent(self, raw: str) -> str:
        """从 LLM 返回文本里解析 intent 字段（容错）。"""
        if not raw:
            return "analysis"
        try:
            data = json.loads(raw)
            intent = data.get("intent", "")
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                    intent = data.get("intent", "")
                except json.JSONDecodeError:
                    intent = ""
            else:
                intent = ""

        intent = (intent or "").strip().lower()
        if intent in ("chat", "analysis"):
            return intent
        return "analysis"
