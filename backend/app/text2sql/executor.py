"""
SQL 执行器

职责：安全地执行 SQL 查询，返回结果。

关键设计（安全边界的「单一入口」）：
- Agent 只能通过这里执行 SQL，不能绕过安全校验
- 先校验（SqlSafetyValidator）→ 再执行，保证危险 SQL 永远到不了数据库

这是「阶段 3 小阶段 3.4」的产物。
"""
from sqlalchemy import text

from app.models.database import engine
from app.text2sql.safety import SqlSafetyValidator, UnsafeSqlError

# 限制：最多返回多少行、查询超时多少秒
MAX_ROWS = 500


class SqlExecutionResult:
    """SQL 执行结果"""

    def __init__(self, columns: list[str], rows: list[tuple], row_count: int):
        self.columns = columns
        self.rows = rows
        self.row_count = row_count

    def to_dict(self) -> dict:
        """转成字典，方便序列化成 JSON"""
        return {
            "columns": self.columns,
            "rows": [list(r) for r in self.rows],
            "row_count": self.row_count,
        }

    def __repr__(self):
        return f"<SqlExecutionResult rows={self.row_count}>"


class SqlExecutor:
    """SQL 执行器（唯一的安全执行入口）"""

    def __init__(self, engine_=None, validator: SqlSafetyValidator | None = None):
        self._engine = engine_ or engine
        self._validator = validator or SqlSafetyValidator()

    def execute(self, sql: str) -> SqlExecutionResult:
        """
        安全地执行一条 SQL。

        流程：
        1. 提取纯 SQL（去掉 ```sql 标记）
        2. 安全校验（只放行 SELECT）
        3. 执行查询
        4. 封装结果
        """
        # 1. 提取纯 SQL
        sql = self._validator.extract_select(sql)

        # 2. 安全校验（危险 SQL 在这里被拦截）
        sql = self._validator.validate(sql)

        # 3. 执行查询（只读 SELECT，安全）
        with self._engine.connect() as conn:
            result = conn.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchmany(MAX_ROWS)  # 最多取 MAX_ROWS 行

        # 4. 封装结果
        return SqlExecutionResult(
            columns=columns,
            rows=[tuple(r) for r in rows],
            row_count=len(rows),
        )
