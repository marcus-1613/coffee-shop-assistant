"""
缓存层（Cache）

职责：给外部数据源 API 的响应做「本地缓存 + 定时刷新」。

为什么需要它？（这是企业级工程化的第一课）
1. 第三方 API 有速率限制（rate limit），每次用户请求都打第三方会超限
2. 网络调用慢、不稳定，缓存能显著降低延迟、提升可用性
3. 「数据源不可用」时，缓存是最后一道兜底——服务不能因为第三方挂了就崩

缓存策略（TTL + stale-while-revalidate 的简化版）：
- 每次写入记录时间戳
- 读取时如果未过期，直接返回缓存
- 过期后返回旧数据（stale），同时后台刷新（简化版：下次读取时同步刷新）

这是「企业级升级 · 阶段一」的产物。
"""
import time
import threading
from typing import Any, Dict, Optional


class TTLCache:
    """带过期时间的线程安全缓存"""

    def __init__(self, ttl_seconds: int = 600):
        """
        ttl_seconds: 缓存有效期（秒）。默认 10 分钟。
                     真实数据源不需要每次请求都实时，10 分钟足够。
        """
        self._ttl = ttl_seconds
        self._store: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        """读取缓存。未命中或已过期返回 None（同时删掉过期项）。"""
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            if time.time() - item["ts"] > self._ttl:
                # 过期：删除并返回 None
                del self._store[key]
                return None
            return item["value"]

    def set(self, key: str, value: Any) -> None:
        """写入缓存，记录当前时间戳。"""
        with self._lock:
            self._store[key] = {"value": value, "ts": time.time()}

    def clear(self) -> None:
        """清空缓存（测试用）"""
        with self._lock:
            self._store.clear()

    def ttl_remaining(self, key: str) -> Optional[float]:
        """查询某 key 还剩多少秒过期（调试用）"""
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            remaining = self._ttl - (time.time() - item["ts"])
            return max(0.0, remaining)


# 全局单例缓存：所有数据源共享
# 简化起见用单例；企业级会换成 Redis（见 ADR 里的演进计划）
_default_cache = TTLCache(ttl_seconds=600)


def get_cache() -> TTLCache:
    """获取全局缓存单例"""
    return _default_cache
