"""
Agent 图构建（Graph）

用 LangGraph 的 StateGraph 把节点（Node）用边（Edge）串起来，
形成完整的状态机。

这是 LangGraph 三个核心概念之一：Edge + Graph。

阶段二（多工具 Agent）改造后的图结构：

    entry → planner → executor ──(条件边)──┐
                 ↑                          │
                 │            decision      │
                 │             ├─ next     → 回 executor
                 │             ├─ replan   → 回 reflector（反思重规划）
                 │             ├─ clarify  → clarify → END（等用户）
                 │             ├─ done     → answer → END
                 │             └─ end      → END（失败放弃）
                 │                          │
                 └──── reflector ←──────────┘

相比旧版新增：
- replan 分支：失败时让 LLM 反思重规划（而非傻重试）
- clarify 节点：信息不足时反问用户（从 chat.py 收编进来）
"""
from langgraph.graph import StateGraph, END

from app.agent.state import AgentState
from app.agent.nodes import AgentNodes


def build_graph(nodes: AgentNodes, checkpointer=None):
    """构建 Agent 状态机图。

    checkpointer: 检查点持久化器，传入后支持「暂停/恢复」。
    """
    graph = StateGraph(AgentState)

    # 添加节点（decision 是「路由函数」，不是节点，不 add_node）
    graph.add_node("planner", nodes.planner)
    graph.add_node("executor", nodes.executor)
    graph.add_node("reflector", nodes.reflector)
    graph.add_node("answer", nodes.answer)
    graph.add_node("clarify", nodes.clarify)

    # 入口：从 planner 开始
    graph.set_entry_point("planner")

    # 固定边
    graph.add_edge("reflector", "executor")   # 重规划后回 executor
    graph.add_edge("answer", END)
    graph.add_edge("clarify", END)

    # 条件边：planner 规划完，由 decision 路由
    # （planner 里做了澄清检查，信息不足时置 waiting_user → 走 clarify）
    graph.add_conditional_edges(
        "planner",
        nodes.decision,
        {
            "next": "executor",     # 正常 → 去执行
            "clarify": "clarify",   # 信息不足 → 反问用户
            "end": END,             # 其他异常 → 结束
        },
    )

    # 条件边：executor 执行完后，由 decision 路由
    graph.add_conditional_edges(
        "executor",
        nodes.decision,
        {
            "next": "executor",     # 还有步骤 → 回 executor
            "replan": "reflector",  # 失败 → 反思重规划
            "done": "answer",       # 完成 → 汇总
            "clarify": "clarify",   # 信息不足 → 反问用户
            "end": END,             # 失败放弃 / 等待用户 → 结束
        },
    )

    if checkpointer is not None:
        return graph.compile(checkpointer=checkpointer)
    return graph.compile()
