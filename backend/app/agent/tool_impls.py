"""
具体工具实现（Tool 的实现类）

这里把项目里已有的能力，统一包装成「Tool」，供 Agent 调用：
- DataSourceTool：包装数据源执行器，把「查真实数据」变成一个工具
- AnswerTool：把「直接用大模型回答用户」也变成一个工具，
              让「查完数据后总结」这个动作同样走统一的工具协议

设计说明：
- 每个工具只关心「输入参数 → 结构化结果」，不关心谁来调用、何时调用
- 这样 Agent 的 executor 就只需要面对「工具」这一个概念，
  而不是在「查数据源」「调 LLM 对话」之间写死分支

这是「企业级升级 · 阶段二」的产物。
"""
from typing import Any, Dict

from app.agent.tools import Tool
from app.datasource.base import DataSource
from app.datasource.executor import DataSourceExecutor
from app.llm.provider import LLMProvider
from app.text2sql.engine import Text2SqlEngine


class DataSourceTool(Tool):
    """把「数据源查询」包装成一个工具。

    内部复用 DataSourceExecutor，把 action（global / country:X / history:X）
    转成结构化结果。这样 Agent 面对的是一个统一入口，而不是裸露的数据源 API。
    """

    def __init__(self, source: DataSource):
        self._executor = DataSourceExecutor(source)
        self._source = source

    @property
    def name(self) -> str:
        return self._source.name

    @property
    def description(self) -> str:
        return self._source.description

    def parameters(self) -> Dict[str, str]:
        # 暴露给 LLM 的参数说明：让每个数据源自己定义 action 格式
        # （优先用 action_examples，缺省则回退到 schema 的查询类型行）
        examples = getattr(self._source, "action_examples", None)
        params = {"action": examples} if examples else {"action": "查询动作，格式见数据源 schema"}
        # 额外参数由数据源自己声明（extra_params），通用工具层不认识任何具体源。
        # 这样加新数据源（如股票）时，只需让它覆写 extra_params，本类零改动。
        params.update(self._source.extra_params())
        return params

    def run(self, **params) -> Dict[str, Any]:
        action = params.get("action", "global")
        # 透传除 action 外的所有参数（days/location/start_date/end_date 等），
        # 让数据源能接收城市、日期范围等查询条件（之前只透传 days，导致
        # location/start_date 被丢弃，查错城市、查错日期）。
        extra = {k: v for k, v in params.items() if k != "action" and v is not None}
        result = self._executor.execute(action, **extra)
        return result.to_dict()


class SqliteTool(Tool):
    """把「本地数据库查询（Text2SQL）」包装成一个工具。

    内部复用 Text2SqlEngine（自然语言 → SQL → 执行 → 自我纠错重试），
    让 Agent 能通过「自然语言问题」查询本地经营数据（咖啡店），
    与 DataSourceTool（真实 API）并列成为 Agent 的两个数据查询工具。

    关键：run() 接收自然语言问题，内部完成「生成 SQL → 安全校验 → 执行」，
    上层（executor/状态机）无需关心 SQL 细节。
    """

    def __init__(self, engine: Text2SqlEngine):
        self._engine = engine

    @property
    def name(self) -> str:
        return "sqlite"

    @property
    def description(self) -> str:
        return (
            "查询本地咖啡店经营数据库（结构化数据）。"
            "用于回答关于销量、订单、饮品、会员、毛利等经营问题，"
            "例如「本月销量最高的饮品」「毛利最高的商品」「会员平均消费」。"
            "注意：这是查店内的经营数据，不是查天气或外部数据。"
        )

    def parameters(self) -> Dict[str, str]:
        return {
            "question": "要查询的自然语言问题，如「这个月销量最高的5款饮品」",
        }

    def run(self, **params) -> Dict[str, Any]:
        question = params.get("question", "")
        result = self._engine.query(question)
        # Text2SqlEngine 返回 {question, sql, result, retries, error}
        if result.get("error"):
            # 查询失败（重试耗尽）：返回错误信息，让上层能处理
            return {
                "columns": [],
                "rows": [],
                "row_count": 0,
                "meta": {
                    "kind": "sqlite",
                    "error": result["error"],
                    "sql": result.get("sql"),
                },
            }
        data = result["result"] or {"columns": [], "rows": [], "row_count": 0}
        return {
            "columns": data["columns"],
            "rows": data["rows"],
            "row_count": data["row_count"],
            "meta": {
                "kind": "sqlite",
                "sql": result.get("sql"),
                "retries": result.get("retries", 0),
            },
        }


class AnswerTool(Tool):
    """把「直接用大模型回答用户」包装成一个工具。

    作用：在 Agent 循环里，「总结数据结果 / 直接回复闲聊」这个动作，
    也作为一个可被调用的工具，从而让「选工具 → 执行工具」成为唯一的执行范式。
    """

    def __init__(self, llm: LLMProvider):
        self._llm = llm

    @property
    def name(self) -> str:
        return "answer"

    @property
    def description(self) -> str:
        return "直接用大模型生成一段回答（用于闲聊，或把已查到的数据总结成分析报告）"

    def parameters(self) -> Dict[str, str]:
        return {
            "prompt": "要模型回答的提示词（含上下文、数据结果等）",
        }

    def run(self, **params) -> Dict[str, Any]:
        prompt = params.get("prompt", "")
        answer = self._llm.chat(prompt)
        # 对齐统一返回结构：answer 是一段文本，放在 rows 里便于上层处理
        return {
            "columns": ["answer"],
            "rows": [[answer]],
            "row_count": 1,
            "meta": {"kind": "answer"},
        }
