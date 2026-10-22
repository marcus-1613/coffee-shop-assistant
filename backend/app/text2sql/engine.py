"""
Text2SQL 引擎（核心编排 + 自我纠错）

职责：把「自然语言 → SQL → 查询结果」整条链路串起来。

完整流程：
1. 用 SchemaPromptBuilder 构建提示词
2. 用 LLMProvider 生成 SQL
3. 用 SqlExecutor（内含安全校验）执行查询
4. 如果失败 → 把错误信息喂回 LLM，让它反思重写（最多重试 N 次）
5. 重试上限到了仍失败 → 兜底返回友好错误（避免死循环）

这是「阶段 3 → 阶段 4 过渡」的核心产物：
加入了「自我纠错 + 最大重试刹车」机制。
"""
from app.llm.provider import LLMProvider
from app.text2sql.schema_prompt import SchemaPromptBuilder
from app.text2sql.executor import SqlExecutor
from app.text2sql.safety import UnsafeSqlError


class Text2SqlEngine:
    """Text2SQL 引擎（带自我纠错）"""

    # 最大重试次数：这是「刹车」，防止死循环
    MAX_RETRIES = 3

    def __init__(
        self,
        llm: LLMProvider | None = None,
        schema_builder: SchemaPromptBuilder | None = None,
        executor: SqlExecutor | None = None,
        max_retries: int = MAX_RETRIES,
    ):
        # 依赖注入：默认用 MockLLM，但可替换成真实模型
        from app.llm.provider import MockLLM

        self._llm = llm or MockLLM()
        self._schema_builder = schema_builder or SchemaPromptBuilder()
        self._executor = executor or SqlExecutor()
        self._max_retries = max_retries

    def query(self, question: str) -> dict:
        """
        核心方法：自然语言 → 查询结果（带自我纠错）

        返回 dict，包含：
        - question: 原始问题
        - sql: 最终成功的 SQL
        - result: 查询结果
        - retries: 重试次数
        """
        # 1. 构建提示词（含表结构）
        base_prompt = self._schema_builder.build_sql_generation_prompt(question)

        # 2. 循环：生成 SQL → 执行 → 失败则反思重试
        last_error = None
        for attempt in range(1, self._max_retries + 1):
            # 第一次用基础提示词；后续重试时附加上次的错误信息
            if attempt == 1:
                prompt = base_prompt
            else:
                prompt = self._build_retry_prompt(base_prompt, last_error)

            # 让 LLM 生成 SQL
            sql = self._llm.generate_sql(prompt)

            # 执行 SQL（安全校验 + 查库）
            try:
                result = self._executor.execute(sql)
                # 成功！
                return {
                    "question": question,
                    "sql": sql,
                    "result": result.to_dict(),
                    "retries": attempt - 1,
                }
            except (UnsafeSqlError, Exception) as e:
                # 失败：记录错误，进入下一轮反思重试
                last_error = str(e)

        # 3. 兜底：重试上限到了仍失败，返回友好错误（不抛异常、不死循环）
        return {
            "question": question,
            "sql": None,
            "result": None,
            "retries": self._max_retries,
            "error": f"抱歉，我尝试了 {self._max_retries} 次仍无法生成正确的 SQL，请换个问法或提供更多信息。",
        }

    def _build_retry_prompt(self, base_prompt: str, error: str) -> str:
        """构建「反思重试」提示词：把错误信息喂给 LLM，让它修正"""
        return (
            f"{base_prompt}\n\n"
            f"## 注意\n"
            f"你上一次生成的 SQL 执行失败了，错误信息如下：\n"
            f"{error}\n\n"
            f"请仔细分析错误原因，重新生成一条正确的 SQL。"
        )
