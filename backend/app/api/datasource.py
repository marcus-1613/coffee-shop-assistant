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
from sqlalchemy import func

from app.datasource import DiseaseShSource, OpenMeteoSource, DataSourceRegistry
from app.models.cafe import Order
from app.models.database import SessionLocal


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
    """返回各数据源的新鲜度说明，不在页面加载时阻塞请求第三方。

    天气/疫情仍在实际查询时访问第三方；这个接口返回采样策略和
    本地数据的最新时间，因此断网时也能快速展示来源边界。
    """
    db = SessionLocal()
    try:
        latest_order_time = db.query(func.max(Order.order_time)).scalar()
    finally:
        db.close()

    sources = [
        {
            "name": "open-meteo",
            "label": "天气",
            "status": "ok",
            "updated_at": None,
            "note": "Open-Meteo 实时预报与历史天气（按查询请求获取）",
        },
        {
            "name": "disease-sh",
            "label": "疫情",
            "status": "stale",
            "updated_at": None,
            "note": "历史数据源；多数国家已于 2023 年停更",
        },
        {
            "name": "sqlite",
            "label": "经营数据",
            "status": "ok",
            "updated_at": latest_order_time.isoformat() if latest_order_time else None,
            "note": "本地示例经营库（非真实门店数据）",
        },
    ]

    return {"sources": sources}
