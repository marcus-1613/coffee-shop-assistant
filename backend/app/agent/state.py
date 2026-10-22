"""
Agent 状态定义（State）

State 是整个 Agent 运行过程中贯穿始终的「记事本」，
记录当前进行到哪了、规划了什么、执行结果如何。

这是 LangGraph 三个核心概念之一：State。

阶段二（多工具 Agent）改造说明：
- 相比旧版（给 Text2SQL 设计），状态字段改为围绕「工具调用序列」组织：
  - plan：规划出的工具调用序列（每个元素是 {"tool":..., "params":...}）
  - current_step：执行到第几步
  - results：每步执行结果
  - replan_count：重规划次数（防死循环，对应旧 Text2SQL 的 max_retries）
  - clarify_question：需要反问用户的问题（信息不足时）
"""
from typing import TypedDict, List, Optional, Any, Dict


class AgentState(TypedDict, total=False):
    """Agent 的完整状态"""

    # 用户输入的问题
    question: str

    # 规划出的工具调用序列（每个元素是 {"tool":..., "params":...} 或 {"tools":[...]}）
    plan: Dict[str, Any]

    # 当前执行到第几步（索引）
    current_step: int

    # 每一步的执行结果（对齐 DataSourceExecutionResult.to_dict()）
    results: List[dict]

    # 上下文：记录「已经查到的数据摘要」，供下一步骤/汇总使用
    context: Optional[str]

    # 任务状态：planning / running / success / failed / waiting_user
    status: str

    # 最终汇总的分析报告
    final_answer: Optional[str]

    # 需要反问用户的澄清问题（信息不足时不瞎猜）
    clarify_question: Optional[str]

    # 重规划次数（上限控制，防止 REPLAN 死循环）
    replan_count: int

    # 错误信息（如果有）
    error: Optional[str]
