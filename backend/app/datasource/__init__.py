"""
数据源层（datasource）

本包负责对接「外部真实数据源」，是项目从「本地 demo 数据」走向「企业级」的第一步。

核心设计思想（依赖倒置 + 面向接口）：
- 定义 DataSource 抽象接口
- DiseaseShSource 是其中一个实现（真实调用公开 API）
- 未来加其他数据源（WHO GHO、自有数据库…）只需新增实现类，不改上层代码

这是「企业级升级 · 阶段一」的产物。
"""
from app.datasource.base import DataSource, DataSourceRegistry
from app.datasource.disease_sh import DiseaseShSource
from app.datasource.open_meteo import OpenMeteoSource

__all__ = ["DataSource", "DataSourceRegistry", "DiseaseShSource", "OpenMeteoSource"]
