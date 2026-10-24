"""
智能分析助手 · 程序入口

这是整个后端的启动文件。运行它，FastAPI 服务就起来了。
本阶段（阶段 1）只做最小可运行验证，后续会逐步接入 Agent、Text2SQL 等。

运行方式（在 backend 目录下）：
    .venv/Scripts/python.exe -m uvicorn app.main:app --reload
"""
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging_config import setup_logging, get_logger
from app.api.chat import router as chat_router
from app.api.datasource import router as datasource_router
from app.api.auth import router as auth_router
from app.api.history import router as history_router

# 启动即初始化日志（幂等）
setup_logging()
logger = get_logger(__name__)

# 创建 FastAPI 应用实例
# 这是整个后端的"总开关"，所有接口都挂在这个 app 上
app = FastAPI(
    title="智能分析助手 API",
    description="Python 版智能分析 AI 助手 —— 核心能力：智能分析 Agent + Text2SQL",
    version="0.1.0",
)

# 浏览器只允许配置过的前端来源跨域访问。Bearer Token 不依赖 Cookie，
# 因此关闭 credentials，避免“通配来源 + 凭证”这一不安全的组合。
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:3008,http://127.0.0.1:3008",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# 注册聊天路由（阶段 6：SSE 流式接口）
app.include_router(chat_router)

# 注册数据源路由（企业级升级：对接真实数据源）
app.include_router(datasource_router)

# 注册认证路由（企业级升级 · P0：用户认证）
app.include_router(auth_router)

# 注册会话历史路由（企业级升级 · P0：资源隔离）
app.include_router(history_router)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    """请求日志中间件：记录每个请求的方法、路径、状态码、耗时。

    这是「可观测性」的落地——上线后用户报错，能靠日志定位到具体请求。
    """
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "请求 %s %s -> %d（%.1fms）",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


@app.get("/")
def root():
    """根路径：访问 http://localhost:8000/ 会执行这里"""
    return {"message": "智能分析助手已启动", "status": "ok"}


@app.get("/health")
def health():
    """健康检查接口：用于确认服务是否正常运行"""
    return {"status": "healthy"}


@app.get("/hello/{name}")
def say_hello(name: str):
    """路径参数示例：访问 /hello/小明 会返回针对小明的问候"""
    return {"message": f"你好，{name}！"}
