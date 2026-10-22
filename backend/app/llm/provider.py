"""
LLM 抽象层（接口 + 实现）

核心设计思想（依赖倒置原则）：
- 上层代码只依赖「LLM 接口」，不依赖具体的模型
- 开发阶段用 MockLLM（不需要 API Key，返回预设内容）
- 上线阶段换成 DeepSeekLLM（真实调用 DeepSeek API）

好处：核心逻辑可以在没有网络/Key 的情况下独立开发和测试。

这是「阶段 3 + 阶段 4」的产物：LLM Provider 抽象。
阶段 4 新增了通用的 chat() 方法，供 planner / summarizer 复用。
"""
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 提供方的统一接口（抽象基类）"""

    @abstractmethod
    def chat(self, prompt: str) -> str:
        """通用对话：给一段提示词，返回模型的文本回答。

        这是最基础的接口，planner（拆解任务）、summarizer（汇总报告）都靠它。
        """
        raise NotImplementedError

    @abstractmethod
    def generate_sql(self, prompt: str) -> str:
        """根据提示词生成 SQL 语句（Text2SQL 专用）"""
        raise NotImplementedError


class MockLLM(LLMProvider):
    """
    假模型：不调用任何真实 API，返回预设的内容。

    用途：
    1. 开发阶段——不用 Key 就能跑通流程
    2. 单元测试——结果确定，可断言
    """

    def __init__(self, preset_sql: str | None = None, preset_chat: str | None = None):
        """
        preset_sql: 预设要返回的 SQL。
        preset_chat: 预设 chat() 要返回的文本（供 planner/summarizer 测试）。
        """
        self._preset_sql = preset_sql
        self._preset_chat = preset_chat

    def chat(self, prompt: str) -> str:
        # 返回预设文本，否则给一个兜底
        return self._preset_chat if self._preset_chat is not None else ""

    def generate_sql(self, prompt: str) -> str:
        # 返回预设 SQL（模拟"模型已经根据 prompt 生成了 SQL"）
        if self._preset_sql:
            return self._preset_sql
        # 默认示例：统计各科室患者总数
        return (
            "SELECT d.name AS 科室, COUNT(p.id) AS 患者总数 "
            "FROM patients p JOIN departments d ON p.department_id = d.id "
            "GROUP BY d.name"
        )
