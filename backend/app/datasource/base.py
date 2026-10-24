"""
数据源抽象层（接口 + 注册表）

核心设计思想（依赖倒置原则，和 LLMProvider 一脉相承）：
- 上层 Agent / Text2SQL 只依赖 DataSource 接口，不关心数据从哪来
- 每个数据源是一个「实现类」，实现统一的查询接口
- DataSourceRegistry 是「注册表」，Agent 启动时自动发现所有数据源，
  让大模型「选数据源」，而不是写死 if-else

为什么这是企业级的关键？
- 加一个数据源 = 写一个类 + 注册一下，核心代码零改动
- 数据源可以热插拔、可以 mock、可以独立测试

这是「企业级升级 · 阶段一」的产物。
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class DataSource(ABC):
    """数据源的统一接口（抽象基类）

    一个数据源 = 一个可以被自然语言查询的数据集合。
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """数据源唯一标识，如 "disease-sh" """
        raise NotImplementedError

    @property
    @abstractmethod
    def description(self) -> str:
        """数据源的一句话描述，告诉大模型「这个源能查什么」。
        这段文字会被拼进提示词，帮助大模型判断该选哪个源。
        """
        raise NotImplementedError

    @abstractmethod
    def schema(self) -> str:
        """返回数据源的「字段说明」，格式类似 SQL 表结构描述。
        供 Text2SQL 生成提示词使用。
        """
        raise NotImplementedError

    def extra_params(self) -> Dict[str, str]:
        """声明本数据源在「查询动作」之外，还需要哪些额外查询参数。

        返回 {参数名: 参数说明}。默认返回空字典，表示除了 action 外不需要
        额外参数（如疫情源）。需要城市/日期等条件的源（如天气）覆写本方法。

        这一设计让「参数说明」的职责归属于数据源自身，通用工具层
        （DataSourceTool）无需认识任何具体数据源，符合开闭原则。
        """
        return {}

    @abstractmethod
    def query(self, sql_or_action: str, **params) -> Dict[str, Any]:
        """执行一次查询。

        注意：这里参数名叫 sql_or_action，是因为不同的数据源
        「查询方式」不同——有的是 SQL，有的是 HTTP 动作。
        统一抽象成「接收一段查询描述 + 参数，返回结构化结果」。

        返回结构必须统一，上层才能无差别处理：
        {
            "columns": [str, ...],
            "rows": [[...], ...],
            "row_count": int,
            "meta": {...}  # 可选：图表建议、单位等
        }
        """
        raise NotImplementedError


class DataSourceRegistry:
    """数据源注册表：集中管理所有可用数据源。

    用法：
        registry = DataSourceRegistry()
        registry.register(DiseaseShSource())
        registry.register(CsvSalesSource())   # 未来加数据源只需这一行
        registry.list()  # -> [DiseaseShSource, ...]
    """

    def __init__(self):
        self._sources: Dict[str, DataSource] = {}

    def register(self, source: DataSource) -> None:
        """注册一个数据源（用 name 做 key，重复注册会覆盖）"""
        self._sources[source.name] = source

    def get(self, name: str) -> Optional[DataSource]:
        """按名字取数据源"""
        return self._sources.get(name)

    def list(self) -> List[DataSource]:
        """列出所有数据源"""
        return list(self._sources.values())

    def describe(self) -> str:
        """生成一段「所有数据源 + 各自能查什么」的描述文本，
        拼进大模型提示词，让模型知道有哪些选择。
        """
        if not self._sources:
            return "（无可用数据源）"
        lines = []
        for s in self._sources.values():
            lines.append(f"- {s.name}：{s.description}")
        return "\n".join(lines)
