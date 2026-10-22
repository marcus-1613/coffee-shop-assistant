"""
API 路由：智能助手聊天接口（SSE 流式）

职责：接收用户输入，先做「意图路由」，再分流：
- 闲聊（chat）      → 直接走 DeepSeek 对话，不碰数据
- 数据分析（analysis）→ 进入「多工具 Agent 状态机」（规划 → 选工具执行 → REPLAN → 汇总）

架构分层（阶段二 · 多工具 Agent）：
- API 层（本文件）：负责「意图路由」（去哪）+ SSE 流式输出 + 多轮记忆 + 消息持久化
- 引擎层（app/agent）：负责「怎么干」（状态机：planner → executor → reflector/answer）

分析链路（2-C 改造后）：
  1. IntentClassifier 判断意图（chat / analysis）
  2. analysis 则进入 build_graph 编译的状态机，用 stream_mode="updates" 逐步执行
  3. 每走完一个节点，向 SSE 发一个事件（intent/planner/executor/summary/chart/done）
  4. 状态机内部：planner 选工具 → executor 执行 → 失败则 reflector REPLAN → answer 汇总

SSE 格式：每条消息以 "data: <json>\n\n" 结尾。

这是「企业级升级 · 阶段二」的产物。
"""
import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.intent import IntentClassifier
from app.agent import ToolRegistry, DataSourceTool, AnswerTool, SqliteTool, AgentNodes, build_graph
from app.llm.deepseek import DeepSeekLLM
from app.datasource import DiseaseShSource, OpenMeteoSource
from app.text2sql.engine import Text2SqlEngine
from app.core.deps import get_current_user_optional
from app.core.logging_config import get_logger
from app.models.database import get_db
from app.models.user import User
from app.services.message_repository import MessageRepository

logger = get_logger(__name__)


class ChatRequest(BaseModel):
    question: str
    session_id: str | None = None  # 匿名会话标识（未登录时的多轮记忆 key）


router = APIRouter()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _build_chart_from_results(results: list) -> dict | None:
    """根据查询结果，判断能否出图，并生成图表数据（通用出图引擎）。

    优先级（从高到低）：
    1. 数据源已在 meta.chart 里声明了出图建议（天气/疫情数据源都埋了这个）→ 直接用
    2. 单条时间序列结果（多行，首列日期/名称 + 第二列数值）→ 折线图
    3. 多条对比结果（多行，首列名称 + 第二列数值）→ 柱状图
    4. 都不满足 → 不出图（纯文本）

    设计说明：出图不应该写死「疫情专用」，而要根据结果的结构 + 数据源建议来推断，
    这样咖啡店销量排行、天气趋势等新场景也能自动出图。
    """
    if not results:
        return None

    # 情况 1：优先尊重数据源埋好的 meta.chart（最准确，数据源最懂自己能不能出图）
    for r in results:
        meta = (r.get("meta") or {})
        chart = meta.get("chart")
        if chart and chart.get("type") in ("line", "bar"):
            # 用 meta.chart 声明的 x/y 字段，从 rows 里抽出对应的列
            return _build_chart_from_meta(r, chart)

    # 情况 2：单条多行结果 → 折线图（时间序列）或柱状图（排行/分类）
    if len(results) == 1:
        r = results[0]
        rows = r.get("rows", [])
        columns = r.get("columns", [])
        meta = (r.get("meta") or {})
        # 至少 2 行、每行至少 2 列、第二列是数值才能画
        if len(rows) >= 2 and all(len(row) >= 2 for row in rows) and all(_is_number(row[1]) for row in rows):
            data = [{"label": row[0], "value": row[1]} for row in rows]
            x_label = columns[0] if columns else "名称"
            y_label = columns[1] if len(columns) > 1 else "数值"
            # 首列像日期 → 折线图（时间序列）；否则 → 柱状图（排行/分类）
            if _looks_like_date(rows[0][0]):
                return {"type": "line", "x": x_label, "y": y_label, "data": data}
            return {"type": "bar", "x": x_label, "y": y_label, "data": data}
        return None

    # 情况 3：多条结果 → 尝试柱状图（对比）
    #   每条结果取「首行首列做标签 + 首行第二列做值」
    labels, values = [], []
    for r in results:
        meta = (r.get("meta") or {})
        rows = r.get("rows", [])
        if not rows:
            continue
        row = rows[0]
        if len(row) < 2 or not _is_number(row[1]):
            continue
        labels.append(meta.get("country") or meta.get("name") or row[0])
        values.append(row[1])
    if labels and len(labels) == len(results):
        return {
            "type": "bar",
            "x": "对比项",
            "y": "数值",
            "data": [{"label": l, "value": v} for l, v in zip(labels, values)],
        }
    return None


def _build_chart_from_meta(result: dict, chart: dict) -> dict | None:
    """按 meta.chart 声明的 x/y 字段，从结果 rows 里抽取数据画图。"""
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    x_field = chart.get("x", "")
    y_field = chart.get("y", "")
    chart_type = chart.get("type", "line")

    # 找到 x/y 字段在 columns 里的下标
    try:
        x_idx = columns.index(x_field) if x_field in columns else 0
        y_idx = columns.index(y_field) if y_field in columns else 1
    except (ValueError, IndexError):
        x_idx, y_idx = 0, 1

    data = []
    for row in rows:
        if len(row) <= max(x_idx, y_idx):
            continue
        if not _is_number(row[y_idx]):
            continue
        data.append({"label": row[x_idx], "value": row[y_idx]})
    if not data:
        return None
    return {
        "type": chart_type,
        "x": x_field or columns[x_idx] if columns else "x",
        "y": y_field or (columns[y_idx] if len(columns) > y_idx else "y"),
        "data": data,
    }


def _is_number(v) -> bool:
    """判断值能否当数值画图（int/float 或数字字符串）。"""
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return True
    if isinstance(v, str):
        try:
            float(v)
            return True
        except ValueError:
            return False
    return False


def _looks_like_date(v) -> bool:
    """判断首列值是否像日期/时间（用于区分折线图 vs 柱状图）。"""
    import re
    if not isinstance(v, str):
        return False
    # 匹配 YYYY-MM-DD / M/D/YY / MM-DD / 2023-03-01 等日期格式
    if re.match(r"^\d{1,4}[-/]\d{1,2}([-/]\d{1,4})?$", v.strip()):
        return True
    return False


def _build_history_context(history: list[dict]) -> str:
    """把多轮历史拼成一段「对话上下文」，喂给 LLM。"""
    if not history:
        return ""

    lines = ["历史对话（供你理解上下文）："]
    for turn in history:
        lines.append(f"用户：{turn['question']}")
        lines.append(f"助手：{turn['answer']}")
    return "\n".join(lines)


def _format_result_for_llm(result: dict) -> str:
    """把查询结果格式化成文字，喂给汇总 LLM。"""
    columns = result.get("columns", [])
    rows = result.get("rows", [])
    meta = result.get("meta") or {}
    kind = meta.get("kind", "")

    lines = []
    if kind == "history":
        lines.append(f"历史趋势（共 {len(rows)} 天，以下为完整数据）：")
        for row in rows:
            lines.append(f"  {row[0]}：{row[1]}")
    elif kind == "answer":
        lines.append(rows[0][0] if rows else "")
    else:
        lines.append(f"字段：{'、'.join(columns)}")
        for row in rows:
            lines.append("  " + "，".join(f"{c}={v}" for c, v in zip(columns, row)))
    return "\n".join(lines)


def _build_agent(llm: DeepSeekLLM):
    """构建多工具 Agent：注册本地经营库 + 天气 + 疫情数据源 + 回答工具，编译状态机。

    工具组合（咖啡店经营助手）：
    - SqliteTool                 → 查本地咖啡店经营数据（销量/毛利/会员）
    - DataSourceTool(OpenMeteo)  → 查真实天气（未来预报 + 历史）
    - DataSourceTool(DiseaseSh)  → 查疫情（保留，作为「多数据源热插拔」的架构证据）
    - AnswerTool                 → 汇总回答
    """
    registry = ToolRegistry()
    registry.register(SqliteTool(Text2SqlEngine(llm=llm)))
    registry.register(DataSourceTool(OpenMeteoSource()))
    registry.register(DataSourceTool(DiseaseShSource()))
    registry.register(AnswerTool(llm))
    nodes = AgentNodes(llm=llm, registry=registry)
    return build_graph(nodes), nodes


@router.post("/chat/stream")
async def chat_stream(
    req: ChatRequest,
    current_user: User = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
):
    llm = DeepSeekLLM()
    classifier = IntentClassifier(llm=llm)
    intent = classifier.classify(req.question)

    # 消息持久化仓库（可选登录：登录了才落库）
    repo = MessageRepository(db)
    user_id = current_user.id if current_user else None

    # 多轮记忆：捞取该用户（或匿名会话）最近 N 轮历史（滑动窗口 + 按用户/会话隔离）
    history = repo.get_recent_history(user_id, limit=5, session_id=req.session_id)
    history_context = _build_history_context(history)

    # ---- 闲聊链路 ----
    if intent == "chat":
        def chat_generator():
            try:
                yield _sse({"type": "intent", "intent": intent, "message": "闲聊"})
                answer = llm.chat(
                    "你是「咖啡店经营助手」，是店长的数据副手。请友好、简洁地用中文回应用户，"
                    "并可以引导店长询问经营问题（如销量排行、毛利分析、天气与备货建议）。\n"
                    "重要：你具备三类数据查询能力——(1)本地经营库(销量/毛利/会员)；"
                    "(2)实时天气(Open-Meteo)；"
                    "(3)全球疫情数据(Disease.sh，多数国家数据停更于2023)。"
                    "如果用户问到疫情、天气或经营数据，请直接帮他查询或引导他明确提出查询需求，"
                    "不要否认自己没有相关数据能力。\n"
                    f"{history_context}\n"
                    f"用户说：{req.question}"
                )
                yield _sse({"type": "answer", "answer": answer, "message": "回答"})
                conv_id = repo.create(req.question, user_id, session_id=req.session_id)
                repo.complete(conv_id, answer)
                yield _sse({"type": "done", "message": "完成"})
            except Exception as e:
                logger.error("闲聊链路异常：%s（问题：%s）", e, req.question)
                yield _sse({"type": "error", "message": str(e)})

        return StreamingResponse(
            chat_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    # ---- 数据分析链路（多工具 Agent 状态机）----
    def event_generator():
        try:
            yield _sse({"type": "intent", "intent": intent, "message": "数据分析"})
            yield _sse({"type": "start", "message": "开始分析", "question": req.question})

            # 持久化：先存「用户提问」，answer 暂空（断连也保留 partial）
            conv_id = repo.create(req.question, user_id, session_id=req.session_id)

            # 构建状态机（注意：多轮历史要拼进用户问题，让状态机能理解指代）
            graph, nodes = _build_agent(llm)
            input_state = {
                "question": req.question,
            }
            if history_context:
                # 把历史上下文拼进问题，供 planner 理解"那日本呢"这类指代
                input_state["question"] = f"{history_context}\n用户当前问题：{req.question}"

            # 用 stream_mode="updates" 逐步执行，每走完一个节点发一个 SSE 事件
            final_state = None
            step_counter = 0
            for chunk in graph.stream(input_state, stream_mode="updates"):
                # chunk 形如 {"planner": {...}} / {"executor": {...}} / {"answer": {...}}
                for node_name, state in chunk.items():
                    final_state = state

                    if node_name == "planner":
                        plan = state.get("plan") or {}
                        steps = json.dumps(plan, ensure_ascii=False)
                        yield _sse({"type": "planner", "message": "规划完成", "steps": [steps]})

                    elif node_name == "executor":
                        # 报告「当前执行到第几步 + 用了哪个工具」，并把 SQL/结果行带给前端展示
                        step_counter += 1
                        results = state.get("results") or []
                        last_result = results[-1] if results else {}
                        meta = last_result.get("meta") or {}
                        tool_desc = meta.get("kind", "") or "查询"
                        if state.get("error"):
                            yield _sse({"type": "executor", "message": f"第 {step_counter} 步执行失败，准备重规划", "step": step_counter, "error": state.get("error")})
                        else:
                            yield _sse({
                                "type": "executor",
                                "message": f"正在执行第 {step_counter} 步（{tool_desc}）...",
                                "step": step_counter,
                                "sql": meta.get("sql"),
                                "rows": last_result.get("rows", [])[:5],
                                "columns": last_result.get("columns", []),
                            })

                    elif node_name == "reflector":
                        # REPLAN：告诉前端「正在反思重规划」
                        yield _sse({"type": "executor", "message": f"正在反思并重新规划（第 {state.get('replan_count', 0)} 次）...", "step": step_counter})

                    elif node_name == "answer":
                        answer = state.get("final_answer") or ""
                        yield _sse({"type": "summary", "answer": answer, "message": "分析报告"})

            # 状态机跑完：从最终状态取结果，判断能否出图
            if final_state:
                results = final_state.get("results") or []
                chart = _build_chart_from_results(results)
                if chart:
                    yield _sse({"type": "chart", "chart": chart, "message": "生成图表"})

                # 拿最终回答（answer 节点已发 summary，这里做持久化 + done）
                final_answer = final_state.get("final_answer") or ""
                if final_state.get("status") == "waiting_user":
                    # 澄清追问：final_answer 就是澄清问题
                    final_answer = final_state.get("clarify_question") or final_answer
                    yield _sse({"type": "clarify", "question": final_answer, "message": "需要补充信息"})

                # 持久化：回答生成后更新记录
                repo.complete(conv_id, final_answer or "抱歉，未能完成分析。")

            yield _sse({"type": "done", "message": "分析完成"})

        except Exception as e:
            logger.error("分析链路异常：%s（问题：%s）", e, req.question)
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
