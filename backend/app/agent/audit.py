"""
事件审计器（Audit Logger）

职责：记录 Agent 运行过程中每一步发生的「事件」，让黑盒变透明。

这是「可观测性（Observability）」的落地——像给 Agent 装了个行车记录仪。

用途：
1. 调试：出错了能定位是哪一步、哪条 SQL 出错
2. 审计：能追溯「这个分析结果是怎么一步步算出来的」
3. 产品：阶段 6 流式输出时，前端能实时展示「Agent 正在做第几步」

这是「阶段 5 小阶段 5.1」的产物。
"""
import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class AuditEvent:
    """一条审计事件"""
    # 事件类型：planner / executor / reflector / summarizer / error / finish
    type: str
    # 事件描述（人话）
    message: str
    # 事件发生时间戳
    timestamp: float = field(default_factory=time.time)
    # 附加数据（如 SQL、步骤索引等）
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "message": self.message,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class AuditLogger:
    """事件审计器：收集并保存 Agent 运行事件"""

    def __init__(self):
        self._events: list[AuditEvent] = []

    def log(self, event_type: str, message: str, **data):
        """记录一条事件"""
        self._events.append(AuditEvent(type=event_type, message=message, data=data))

    def get_events(self) -> list[dict]:
        """获取所有事件的字典形式（方便 JSON 序列化）"""
        return [e.to_dict() for e in self._events]

    def clear(self):
        """清空事件（开始新任务前调用）"""
        self._events.clear()
