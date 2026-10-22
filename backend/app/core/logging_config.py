"""
统一日志配置（结构化日志）

职责：给整个后端配置一套统一的日志输出，让上线后可观测、可排查。

设计说明：
- 用 Python 标准库 logging（不引重型框架），够用且零依赖。
- 双输出：
  1. 控制台（StreamHandler）：开发时实时看
  2. 文件（RotatingFileHandler）：落盘，按大小滚动，供上线后排查
- 统一的日志格式：时间 + 级别 + 模块 + 消息，便于 grep / 接入 ELK 等。

与 AuditLogger 的区别：
- AuditLogger 是「内存事件收集器」，给前端流式展示 Agent 步骤用（产品功能）。
- 这里是「进程级日志」，给开发者/运维排查问题用（可观测性）。
  两者互补，不重复。

这是「企业级可观测性」的落地（对应 ADR 中「可观测性」一项）。
"""
import logging
import os
from logging.handlers import RotatingFileHandler

# 日志目录（backend 下，已被 .gitignore 覆盖的 logs/）
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

# 单文件最大 5MB，最多保留 3 个（自动滚动，避免日志无限膨胀）
MAX_BYTES = 5 * 1024 * 1024
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging(level: int = logging.INFO) -> None:
    """初始化全局日志配置（幂等：重复调用不会叠加 handler）。"""
    root = logging.getLogger()
    if getattr(root, "_cafe_configured", False):
        return

    root.setLevel(level)
    formatter = logging.Formatter(_FORMAT)

    # 1. 控制台输出
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # 2. 文件输出（滚动）
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        # 文件日志创建失败（如权限问题）不阻塞启动，降级为仅控制台
        root.warning("日志文件创建失败，仅输出到控制台")

    root._cafe_configured = True


def get_logger(name: str) -> logging.Logger:
    """获取一个命名 logger（建议每个模块传 __name__）。"""
    return logging.getLogger(name)
