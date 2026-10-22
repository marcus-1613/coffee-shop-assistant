"""
工具抽象层（Tool + ToolRegistry）

核心设计思想（依赖倒置，与 LLMProvider / DataSource 一脉相承）：
- 上层 Agent 只依赖「Tool 接口」，不关心每个工具内部怎么实现
- 每个工具 = 一个 Agent 能调用的「能力」（查数据、算数、直接回答…）
- ToolRegistry 把工具收集起来，生成「工具清单」喂给大模型，让模型「选工具」，
  而不是代码里写死 if-else 判断该走哪条路

为什么需要这一层？（这是「多工具 Agent」的骨架）
之前的设计只有「一个数据源」+「手写流水线」，链路是写死的：
意图 → 动作规划 → 查 Disease.sh → 汇总。
一旦要加第二个工具（比如计算器、查天气、另一个数据源），就得改 chat.py 的
主流程。有了 Tool 抽象后：
- 加一个工具 = 写一个类 + 注册一下，核心流程零改动
- 大模型根据「工具清单」自己决定调用谁，这正是 OpenAI function calling /
  LangChain tool 的业界标准做法

这是「企业级升级 · 阶段二（Agent 智能升级）」的第一步产物。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class Tool(ABC):
    """工具的统一接口（抽象基类）

    一个工具 = 一个可以被 Agent 调用的能力。
    它需要向大模型「自我介绍」：叫什么、能干什么、需要什么参数，
    这样大模型才能从一堆工具里选出正确的那个来调用。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """工具唯一标识，如 "disease-sh" / "calculator" """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """一句话描述：这个工具能干什么。

        这段文字会被拼进「工具清单」提示词，帮助大模型判断该选哪个工具。
        """
        raise NotImplementedError

    @abstractmethod
    def parameters(self) -> Dict[str, str]:
        """参数说明：{参数名: 含义}，拼进工具清单让模型知道要传什么。"""
        raise NotImplementedError

    @abstractmethod
    def run(self, **params) -> Dict[str, Any]:
        """真正执行这个工具。

        返回结构统一（上层才能无差别处理）：
        {
            "columns": [str, ...],
            "rows": [[...], ...],
            "row_count": int,
            "meta": {...}   # 可选：图表建议、来源、新鲜度等
        }
        """
        raise NotImplementedError

    def describe(self) -> str:
        """生成一段「工具自我介绍」，拼进提示词供大模型选工具。

        格式（供参考）：
        - 工具名：disease-sh
          描述：全球公共卫生数据……
          参数：country=国家名, days=天数
        """
        params = "、".join(f"{k}={v}" for k, v in self.parameters().items()) or "无"
        return f"- 工具名：{self.name}\n  描述：{self.description}\n  参数：{params}"


class ToolRegistry:
    """工具注册表：集中管理所有可用工具。

    用法：
        registry = ToolRegistry()
        registry.register(DataSourceTool(...))
        registry.register(AnswerTool(...))   # 未来加工具只需这一行
        registry.list()      # -> [DataSourceTool, AnswerTool]
        registry.describe()  # -> 所有工具的自我介绍文本（喂给 LLM）
    """

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册一个工具（用 name 做 key，重复注册会覆盖）"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        """按名字取工具"""
        return self._tools.get(name)

    def list(self) -> List[Tool]:
        """列出所有工具"""
        return list(self._tools.values())

    def describe(self) -> str:
        """生成「所有工具 + 各自能力」的描述文本，拼进大模型提示词。

        这是「多工具 Agent」的关键：让模型从这段文本里知道有哪些选择。
        """
        if not self._tools:
            return "（无可用工具）"
        return "\n".join(t.describe() for t in self._tools.values())
