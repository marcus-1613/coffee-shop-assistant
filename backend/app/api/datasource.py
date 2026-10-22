"""
数据源 API 路由

职责：把「真实数据源」暴露成 HTTP 接口，供前端直接调用 / 调试。

为什么要有独立的接口？
- Agent（Text2SQL）那条链路依赖大模型，慢且不稳定
- 调试数据源时，应该能「绕过 Agent、直接拉数据」，先确认数据源本身没问题
- 前端展示「示例卡片 / 能力披露」时，也需要直接读数据源清单

这是「企业级升级 · 阶段一」的产物。
"""
from fastapi import APIRouter, HTTPException

from app.datasource import DiseaseShSource, OpenMeteoSource, DataSourceRegistry


router = APIRouter()

# 全局数据源注册表（单例）
_registry = DataSourceRegistry()
_registry.register(OpenMeteoSource())
_registry.register(DiseaseShSource())


@router.get("/datasource/list")
def list_datasources():
    """列出所有数据源 + 各自能查什么（供前端「能力披露」展示）"""
    return {
        "sources": [
            {"name": s.name, "description": s.description}
            for s in _registry.list()
        ]
    }


@router.get("/datasource/query")
def query_datasource(q: str, days: int = 90):
    """
    直接查询数据源（调试用 / 前端示例卡片用）。

    参数：
    - q: 查询动作，如 "global"、"country:China"、"history:USA"
    - days: 历史趋势的天数（默认 90）
    """
    # 解析动作 + 数据源（简化：目前只有一个数据源，未来扩展成按名字路由）
    if q.startswith("history:"):
        source = _registry.get("disease-sh")
    elif q.startswith("country:"):
        source = _registry.get("disease-sh")
    elif q == "global":
        source = _registry.get("disease-sh")
    else:
        raise HTTPException(status_code=400, detail=f"未知查询：{q}")

    try:
        result = source.query(q, days=days)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))

    return result


@router.get("/datasource/freshness")
def datasource_freshness():
    """数据新鲜度：返回各数据源是否可用 + 最近可查到的日期。

    诚实标注数据来源与性质（关键：疫情数据 2023 年已停更，必须让用户知道）：
    - open-meteo：实时天气
    - disease-sh：疫情数据（注意：多数国家数据停更于 2023）
    - 本地经营库：内置示例数据
    """
    sources = []

    # 天气数据源
    try:
        weather = _registry.get("open-meteo")
        result = weather.query("forecast", days=7)
        rows = result.get("rows") or []
        sources.append({
            "name": "open-meteo",
            "label": "天气",
            "status": "ok",
            "updated_at": rows[0][0] if rows else "未知",
            "note": "实时天气（Open-Meteo）",
        })
    except Exception:
        sources.append({
            "name": "open-meteo",
            "label": "天气",
            "status": "error",
            "updated_at": None,
            "note": "天气数据源暂时不可用",
        })

    # 疫情数据源（诚实标注停更）
    try:
        disease = _registry.get("disease-sh")
        result = disease.query("global")
        meta = result.get("meta") or {}
        sources.append({
            "name": "disease-sh",
            "label": "疫情",
            "status": "ok",
            "updated_at": meta.get("updated_at"),
            "note": "疫情数据（多数国家已停更于 2023）",
        })
    except Exception:
        sources.append({
            "name": "disease-sh",
            "label": "疫情",
            "status": "error",
            "updated_at": None,
            "note": "疫情数据源暂时不可用",
        })

    # 本地经营库
    sources.append({
        "name": "sqlite",
        "label": "经营数据",
        "status": "ok",
        "updated_at": None,
        "note": "本地示例经营库（仅作演示）",
    })

    return {"sources": sources}
