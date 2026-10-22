"""
Schema 提示构建器

职责：把数据库的「表结构」转换成一段「大模型能看懂的描述文字」，
    拼进提示词里，让模型知道有哪些表、哪些字段、各自什么意思。

这是 Text2SQL 的第一大难点「Schema 感知」的解法。

这是「阶段 3 小阶段 3.1」的产物。
"""
from sqlalchemy import inspect

from app.models.database import engine


class SchemaPromptBuilder:
    """把数据库结构翻译成提示词"""

    def __init__(self, engine_=None):
        # 传入引擎，方便测试时替换
        self._engine = engine_ or engine

    def build_schema_context(self) -> str:
        """
        读取数据库元数据，生成表结构描述文本。

        返回类似：
            表 departments（科室表）：
              - id: INTEGER，主键
              - name: VARCHAR，科室名

            表 patients（患者表）：
              - id: INTEGER，主键
              - name: VARCHAR，患者姓名
              - department_id: INTEGER，外键，指向 departments.id
              - completed: BOOLEAN，是否完成治疗
              - visit_date: DATE，就诊日期
        """
        inspector = inspect(self._engine)
        lines = []

        for table_name in inspector.get_table_names():
            # 跳过 SQLAlchemy 内部表
            if table_name.startswith("sqlite_") or table_name == "alembic_version":
                continue

            lines.append(f"表 {table_name}：")
            for column in inspector.get_columns(table_name):
                col_type = column["type"]
                parts = [f"  - {column['name']}: {col_type}"]
                # 主键
                if column.get("primary_key"):
                    parts.append("主键")
                # 外键
                for fk in inspector.get_foreign_keys(table_name):
                    if column["name"] in fk.get("constrained_columns", []):
                        parts.append(f"外键→{fk['referred_table']}.{fk['referred_columns'][0]}")
                        break
                lines.append("，".join(parts))
            lines.append("")  # 表之间空一行

        return "\n".join(lines).strip()

    def build_sql_generation_prompt(self, question: str) -> str:
        """
        构建完整的「SQL 生成提示词」。

        包含：角色设定 + 表结构 + SQL 生成规则 + 用户问题
        """
        schema = self.build_schema_context()

        prompt = f"""你是一个专业的咖啡店经营数据分析师。

根据以下数据库表结构和用户问题，生成一条准确的 SQL 查询语句。

## 数据库表结构

{schema}

## SQL 生成规则

1. 只生成 SELECT 语句，禁止 INSERT/UPDATE/DELETE/DROP 等写操作
2. 必须使用上述表中实际存在的表名和字段名，不要臆造不存在的表或字段
3. 咖啡店相关表以 cafe_ 开头：cafe_products(饮品)、cafe_orders(订单)、
   cafe_order_items(订单明细)、cafe_members(会员)
4. 关联关系：
   - cafe_order_items.order_id → cafe_orders.id
   - cafe_order_items.product_id → cafe_products.id
   - cafe_orders.member_id → cafe_members.id
5. 算毛利用 price - cost（cafe_products 有 cost 成本字段）
6. 分析时段用 cafe_orders.order_time；分析天气用 cafe_orders.weather
7. cafe_orders.weather 字段的取值只有三种：'晴'、'阴'、'雨'。
   用户说的「下雨天/雨天」一律用 weather = '雨' 匹配；「晴天」用 weather = '晴'；
   「阴天」用 weather = '阴'。不要臆造 '下雨天'、'rain' 等不存在的取值。
8. 只输出一条 SQL 语句，用 ```sql ``` 包裹，不要有任何解释

## 用户问题

{question}"""
        return prompt
