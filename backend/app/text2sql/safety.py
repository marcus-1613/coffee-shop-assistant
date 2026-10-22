"""
SQL 安全校验器

职责：在执行 AI 生成的 SQL 之前，先校验它是否安全。

为什么必须做这一步（这是 Text2SQL 的「安全边界」，生死线）：
AI 生成的 SQL 不可信——它可能因为幻觉或恶意提示生成危险的语句，
比如 DROP TABLE（删表）、DELETE（删数据）、UPDATE（改数据）。
所以必须在执行前拦截，只放行「安全的 SELECT 查询」。

校验规则（参考 Java 项目的 SafeSqlExecutor，用 sqlglot 实现）：
1. 必须是单条语句（禁止多条）
2. 必须是 SELECT（禁止 INSERT/UPDATE/DELETE/DROP 等写操作）
3. 禁止危险特性（INTO OUTFILE、SLEEP() 等）

这是「阶段 3 小阶段 3.3」的产物。
"""
import sqlglot
from sqlglot import expressions as exp


class UnsafeSqlError(Exception):
    """SQL 不安全时抛出的异常"""
    pass


class SqlSafetyValidator:
    """SQL 安全校验器"""

    # 禁止的关键字/特性（黑名单）
    DANGEROUS_KEYWORDS = {
        "INTO OUTFILE",
        "INTO DUMPFILE",
        "LOAD_FILE",
        "SLEEP",
        "BENCHMARK",
        "GET_LOCK",
        "RELEASE_LOCK",
    }

    @staticmethod
    def validate(sql: str) -> str:
        """
        校验 SQL 是否安全。安全则原样返回，不安全则抛 UnsafeSqlError。

        返回规范化后的 SQL（去除首尾空白）。
        """
        if not sql or not sql.strip():
            raise UnsafeSqlError("SQL 不能为空")

        sql = sql.strip()

        # 解析 SQL。sqlglot 会尝试把一条或多条语句解析成表达式列表。
        # 如果 SQL 有语法错误，会抛 ParseError。
        try:
            expressions = sqlglot.parse(sql)
        except Exception as e:
            raise UnsafeSqlError(f"SQL 解析失败: {e}") from e

        # 规则 1：必须是单条语句
        if len(expressions) != 1:
            raise UnsafeSqlError("仅允许单条 SQL 语句")

        statement = expressions[0]

        # 规则 2：必须是 SELECT
        if not isinstance(statement, exp.Select):
            kind = type(statement).__name__.replace("Expression", "").upper()
            raise UnsafeSqlError(f"仅允许 SELECT 查询，禁止 {kind}")

        # 规则 3：禁止危险关键字
        sql_upper = sql.upper()
        for keyword in SqlSafetyValidator.DANGEROUS_KEYWORDS:
            if keyword in sql_upper:
                raise UnsafeSqlError(f"SQL 中包含不允许的危险特性: {keyword}")

        return sql

    @staticmethod
    def extract_select(sql: str) -> str:
        """从 ```sql ... ``` 包裹的文本中提取纯 SQL"""
        # 去掉 Markdown 代码块标记
        sql = sql.strip()
        if sql.startswith("```"):
            # 去掉首行的 ```sql 和末尾的 ```
            lines = sql.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            sql = "\n".join(lines).strip()
        return sql
