"""
SQL 安全校验器测试

这是项目「第一组自动化测试」，验证安全边界——Text2SQL 的生死线。

为什么先测它？（安全 > 功能）
- AI 生成的 SQL 不可信，可能包含 DROP/DELETE/多语句/危险函数
- 安全校验器是「最后一道闸」，它一旦失效，数据就危险
- 这类测试不需要网络、不需要 API Key，离线就能跑，最稳定

测试设计原则：
- 正向用例：合法 SELECT 必须放行
- 负向用例：危险 SQL 必须全部拦截（这是关键，漏一个都是事故）

这是「企业级升级 · P0 测试」的第一组产物。
"""
import pytest

from app.text2sql.safety import SqlSafetyValidator, UnsafeSqlError


class TestSqlSafetyValidator:
    """SQL 安全校验器的测试"""

    # ---------- 正向用例：安全 SQL 必须放行 ----------

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM patients",
        "SELECT name, completed FROM patients WHERE id = 1",
        "SELECT d.name, COUNT(p.id) FROM patients p JOIN departments d ON p.department_id = d.id GROUP BY d.name",
        "SELECT * FROM patients ORDER BY visit_date DESC LIMIT 10",
    ])
    def test_safe_select_passes(self, sql):
        """合法的 SELECT 查询应该被放行"""
        result = SqlSafetyValidator.validate(sql)
        assert result == sql  # 校验通过，原样返回

    # ---------- 负向用例：危险 SQL 必须拦截 ----------

    @pytest.mark.parametrize("sql", [
        "DROP TABLE patients",                    # 删表
        "DELETE FROM patients WHERE id = 1",      # 删数据
        "UPDATE patients SET name = 'x'",         # 改数据
        "INSERT INTO patients VALUES (1, 'x')",   # 插入
    ])
    def test_write_operations_blocked(self, sql):
        """所有写操作（DROP/DELETE/UPDATE/INSERT）都必须被拦截"""
        with pytest.raises(UnsafeSqlError):
            SqlSafetyValidator.validate(sql)

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM patients; DROP TABLE departments",   # 多语句注入
        "SELECT 1; SELECT 2",                                # 多语句
    ])
    def test_multiple_statements_blocked(self, sql):
        """多语句（分号注入）必须被拦截"""
        with pytest.raises(UnsafeSqlError):
            SqlSafetyValidator.validate(sql)

    @pytest.mark.parametrize("sql", [
        "SELECT * FROM patients INTO OUTFILE '/tmp/x'",   # 写文件
        "SELECT SLEEP(10)",                                # 延迟注入
        "SELECT BENCHMARK(1000000, MD5('x'))",            # 资源耗尽
    ])
    def test_dangerous_functions_blocked(self, sql):
        """危险函数（写文件/延迟/资源耗尽）必须被拦截"""
        with pytest.raises(UnsafeSqlError):
            SqlSafetyValidator.validate(sql)

    # ---------- 边界用例 ----------

    def test_empty_sql_blocked(self):
        """空 SQL 必须被拦截"""
        with pytest.raises(UnsafeSqlError):
            SqlSafetyValidator.validate("")

    def test_none_sql_blocked(self):
        """None 必须被拦截"""
        with pytest.raises(UnsafeSqlError):
            SqlSafetyValidator.validate(None)

    # ---------- extract_select 工具方法 ----------

    def test_extract_select_strips_markdown(self):
        """能从 ```sql ... ``` 包裹里提取纯 SQL"""
        raw = "```sql\nSELECT * FROM patients\n```"
        result = SqlSafetyValidator.extract_select(raw)
        assert result == "SELECT * FROM patients"
