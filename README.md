# 咖啡店经营助手 · 多数据源智能 Agent

一个「店长的数据副手」：用大白话问销量、查毛利、结合实时天气给备货建议，还能查全球疫情数据。核心亮点是**多数据源热插拔 + 多工具 Agent 自动分流**——没有写死 if-else，大模型根据问题自己选工具、自己查数据、自己出分析报告和图表。

> 定位：咖啡店经营主导 + 疫情数据可查（作为「多数据源热插拔」的架构证据）。

---

## ✨ 核心能力

| 能力 | 说明 | 数据源 |
|------|------|--------|
| 经营数据查询 | 销量排行 / 毛利分析 / 会员洞察（自然语言 → SQL） | 本地 SQLite |
| 备货建议 | 结合天气 × 历史销量，给出「该多备什么货」 | Open-Meteo + SQLite |
| 天气预报 | 支持城市 + 日期（「明天南昌天气」能查对城市、查对日期） | Open-Meteo |
| 疫情数据 | 国家现状 / 历史趋势（折线图） | Disease.sh |
| 多轮对话 | 记住上下文（「那我该怎么备货」能接上上一句） | 匿名会话 / 登录用户 |

---

## 🧠 技术亮点（面试可讲）

1. **多工具 Agent**：`Tool` 抽象 + `ToolRegistry` + `ToolPlanner`（LLM 选工具），依赖倒置、开闭原则，加工具不用改状态机。
2. **LangGraph 状态机**：`planner → executor → decision(next/replan/clarify/done) → answer`，失败自动 REPLAN 反思重规划（防死循环上限 3 次）。
3. **Text2SQL 三道安全校验**：白名单（只准 SELECT）、`sqlglot` 语法校验、错误重试（把报错喂回 LLM 改）。
4. **多数据源协同**：本地库 / 天气 / 疫情三个数据源统一封装，planner 自动分流。
5. **认证与资源隔离**：JWT 身份认证 + owner 校验（防越权 IDOR），密码 bcrypt 哈希。
6. **通用出图引擎**：按结果结构自动判断折线图/柱状图，不写死场景。
7. **132 条单元测试**：覆盖 SQL 安全、意图分类、出图、工具、认证、多轮记忆等。

---

## 🚀 快速开始（3 分钟跑起来）

### 前置要求

- Python 3.11+（建议 3.13）
- Node.js 18+
- 一个 DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com) 申请）

### 第一步：配置环境变量

```bash
cd backend
cp .env.example .env   # 复制模板
# 编辑 .env，填入你的 DEEPSEEK_API_KEY 和 SECRET_KEY
```

### 第二步：启动后端

```bash
cd backend
python -m venv .venv                          # 创建虚拟环境
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# 或 source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# 初始化数据库（建表 + 灌入咖啡店演示数据）
.venv/Scripts/python.exe -m app.models.init_db

# 启动服务（默认 http://127.0.0.1:8000）
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

验证：浏览器打开 http://127.0.0.1:8000/health 应返回 `{"status":"healthy"}`。

### 第三步：启动前端

```bash
cd frontend
npm install
npm run dev   # 默认 http://localhost:5173（若被占用会自动换端口）
```

浏览器打开前端地址，即可在界面上提问。

---

## 🧪 运行测试

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q   # 132 条测试
```

---

## 📁 目录结构

```
smart-assistant-python/
├── backend/
│   ├── app/
│   │   ├── agent/          # 多工具 Agent：状态机、工具、规划器、澄清、审计
│   │   ├── api/            # FastAPI 路由：chat / datasource / auth / history
│   │   ├── core/           # 安全（JWT/密码哈希）、依赖注入
│   │   ├── datasource/     # 数据源：天气 / 疫情（热插拔）
│   │   ├── llm/            # LLM 抽象：DeepSeek / Mock
│   │   ├── models/         # ORM 模型 + 数据库初始化
│   │   ├── services/       # 消息持久化（多轮记忆）
│   │   └── text2sql/       # Text2SQL：schema 提示 + SQL 安全 + 执行器
│   ├── tests/              # 13 个测试文件，132 条用例
│   ├── requirements.txt
│   └── .env.example
├── frontend/               # React + Vite
│   └── src/App.jsx         # 聊天界面 + SVG 图表（零第三方图表库）
└── docs/                   # 作战地图 / PRD / ADR / bug 日志
```

---

## 🔌 API 一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/stream` | 聊天（SSE 流式，意图路由 + 多工具 Agent） |
| POST | `/auth/register` | 注册 |
| POST | `/auth/login` | 登录（返回 JWT） |
| GET | `/auth/me` | 查看当前用户（需 token） |
| GET | `/history` | 当前用户的会话历史（需 token） |
| GET | `/history/{id}` | 会话详情（owner 校验，防越权） |
| GET | `/datasource/freshness` | 数据源新鲜度 |

---

## 📝 已知边界（诚实披露）

- **疫情数据**：Disease.sh 多数国家数据已停更于 2023，属历史数据，非实时疫情。
- **经营数据**：本地 SQLite 为内置演示数据，非真实门店数据。
- **天气**：来自 Open-Meteo 预报模型，远期预报准确度会下降。
- **认证**：聊天接口当前为「可选登录」，未登录用户按匿名会话隔离（正式上线建议改为强制登录）。

---

## 📄 文档

- `docs/00-项目作战地图.md` — 整体规划与进度
- `docs/01-需求文档-PRD.md` — 需求说明
- `docs/02-技术方案-ADR.md` — 架构决策记录
- `docs/bug-log.md` — 已修复 bug 台账
