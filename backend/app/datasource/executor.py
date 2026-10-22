"""
数据源执行器（DataSourceExecutor）

职责：让 Agent / Text2SQL 能对「外部数据源」执行查询，并返回结构化结果。

关键设计：
- 数据源不是 SQL 数据库，不能直接跑 SELECT，所以这里把「自然语言查询意图」
  映射成「数据源的动作」（global / country:X / history:X）。
- 返回结构复用 SqlExecutionResult 的约定（columns / rows / row_count），
  并额外携带 meta（含 chart 图表建议 + 数据新鲜度）。

为什么不是让 Text2SqlEngine 直接查数据源？
- Text2SqlEngine 的核心是「LLM 生成 SQL → 安全校验 → 查 SQLite」，这是给
  关系型数据库设计的。
- 数据源是 HTTP API，查询方式是「动作 + 参数」，语义不同。
- 所以单独做一个执行器，未来 Agent 可以根据意图，选择「走 SQL 查库」还是
  「走数据源查 API」。这正是「多工具」的思想（Agent 的下一步演进）。

这是「企业级升级 · 阶段一」的产物。
"""
from typing import Any, Dict, Optional

from app.datasource.base import DataSource


class DataSourceExecutionResult:
    """数据源查询结果（对齐 SqlExecutionResult 的结构）"""

    def __init__(self, columns: list, rows: list, row_count: int, meta: Optional[Dict] = None):
        self.columns = columns
        self.rows = rows
        self.row_count = row_count
        self.meta = meta or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "meta": self.meta,
        }


class DataSourceExecutor:
    """数据源执行器：把「动作描述」转成真实查询"""

    def __init__(self, source: DataSource):
        self._source = source

    def execute(self, action: str, **params) -> DataSourceExecutionResult:
        """
        执行一次数据源查询。action 形如 "global" / "country:USA" / "history:China"。

        返回 DataSourceExecutionResult，其中 meta.chart 用于前端画图。
        """
        raw = self._source.query(action, **params)
        return DataSourceExecutionResult(
            columns=raw.get("columns", []),
            rows=raw.get("rows", []),
            row_count=raw.get("row_count", 0),
            meta=raw.get("meta", {}),
        )

    @property
    def schema(self) -> str:
        """数据源字段说明，供提示词使用"""
        return self._source.schema()
