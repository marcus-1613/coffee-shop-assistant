# ☕ 咖啡店经营助手 · 多数据源智能 Agent

> 一个「店长的数据副手」：用大白话问销量、查毛利、结合实时天气给备货建议。技术上是一个 **Plan-and-Execute 多工具 Agent**——大模型不写死任何 if-else，而是根据问题**自主规划、选工具、查多源数据、反思纠错、汇总成带图表的分析报告**。
>
> 一句话：**把「数据散落在经营库 / 天气 / 疫情三个异构源里」这件事，交给一个能自己查、自己纠错、自己解释的 Agent。**

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB)](https://www.python.org/) [![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688)](https://fastapi.tiangolo.com/) [![LangGraph](https://img.shields.io/badge/LangGraph-0.2-1C3C3C)](https://langchain-ai.github.io/langgraph/) [![React](https://img.shields.io/badge/React-18-61DAFB)](https://react.dev/) [![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-4D6BFE)](https://platform.deepseek.com/) [![Tests](https://img.shields.io/badge/tests-133%20passed-639922)]()

---

## 这是什么

开一家咖啡店，店长每天要面对三类分散的数据：

- **经营数据**在本地数据库里（销量、毛利、会员），需要会写 SQL 才能查；
- **天气**在外部的 Open-Meteo API 里，直接影响备货决策（降温→热饮涨、下雨→堂食降）；
- **外部参考数据**（如疫情）又在另一个 API 里，数据结构完全不同。

这三类数据的**查询方式、字段结构、可信度都不一样**。传统做法是写死三个 `if-else` 分支，每加一个新数据源就得改主流程。

这个项目用 **多工具 Agent** 统一了它们：把「查经营库」「查天气」「查疫情」「直接回答」都抽象成**工具**，大模型根据用户问题自己决定「该调哪个工具、传什么参数」，必要时**组合多个工具协同分析**（比如「备货」= 天气 × 销量）。加一个新数据源，只需写一个类 + 注册一行，核心流程零改动。

---

## 🧠 关键设计决策

> 这部分是项目最核心的「含金量」——不是「我做了什么功能」，而是「遇到什么问题、怎么权衡、为什么这么选」。

### 1. Text2SQL 的安全边界：AI 生成的 SQL 不可信，需要三道防线

LLM 生成的 SQL 是**不可信输入**——它可能因为幻觉或恶意提示生成 `DROP TABLE`、`DELETE` 这类危险语句。所以执行前必须拦截。这里没有用简单的字符串匹配（`DROP` 大写、加空格就能绕过），而是**三道分层防线**：

| 防线 | 做法 | 拦截什么 |
|------|------|----------|
| 单条语句校验 | `sqlglot` 解析后要求 `len(expressions) == 1` | 一条 SELECT 后面偷偷跟一条 DELETE |
| 只准 SELECT | 用 AST 判断 `isinstance(statement, exp.Select)` | INSERT / UPDATE / DELETE / DROP 等写操作 |
| 危险特性黑名单 | 关键字 `INTO OUTFILE` / `SLEEP` 等 | 读写服务器文件、时间盲注 |

关键在**第二道**：`sqlglot` 把 SQL 真正解析成**语法树（AST）**，看的是「语法上是什么结构」，而不是「文本长什么样」——这是 AST 校验相比字符串匹配的本质优势。

再加上**安全执行的单一入口**：所有 SQL 必须经过 `SqlExecutor`，而它内部第一件事就是校验。危险 SQL 永远到不了数据库，这是防御式设计的基本功。

### 2. 多工具 Agent 的依赖倒置：一个「重构故事」

最早 `DataSourceTool` 是**通用工具层**，但它内部却写死了 `if self._source.name == "open-meteo"` 来判断天气源需要哪些参数。这违反了**开闭原则**——每加一个需要特殊参数的数据源，就得回头改通用代码。

重构思路是**把「参数声明」这个知识，从通用层下沉到数据源自己身上**：

```python
# 基类：默认不需要额外参数
def extra_params(self) -> Dict[str, str]:
    return {}          # 疫情源用它，无需覆写

# 天气源：覆写，声明自己需要城市/日期
def extra_params(self) -> Dict[str, str]:
    return {"location": "城市名", "start_date": "日期(YYYY-MM-DD)", ...}

# 通用工具层：不再认识任何具体源
params.update(self._source.extra_params())   # 多态替代 if-else
```

这一改，通用层彻底「不认识」任何具体数据源了。以后加股票、汇率等新源，只需让它覆写 `extra_params()`，**通用代码零改动**。这就是**依赖倒置 + 多态替代条件分支**的落地。

### 3. 分层容错：Text2SQL 重试 ≠ 状态机 REPLAN

项目里有两层**互相独立**的纠错机制，很多人会混为一谈，但它们解决的问题不同：

| 层 | 机制 | 解决什么 | 特征 |
|----|------|----------|------|
| Text2SQL 层 | 失败把报错喂回 LLM 重写 SQL | SQL 写错了 | 局部、快（只重写 SQL） |
| 状态机层 | REPLAN 反思重规划 | 整个工具调用计划错了 | 全局、慢（换工具/换思路） |

两个层都带**最大重试上限（3 次）**作为「刹车」，防止 LLM 反复失败无限烧 token。这个「分层容错」设计保证了：错误不会一路传导到崩溃，每一层都在自己的边界内消化。

### 4. 多轮记忆的匿名会话：未登录也能记住上下文

多轮对话的难点在于：用户说「那我该怎么备货」，系统必须知道「那」指的是上一句的天气和销量。未登录用户没有 `user_id`，历史记录会落空。

解法是引入 **`session_id`（前端随机 UUID）作为匿名会话的隔离键**——不登录也能按会话记住上下文，登录后则按 `user_id` 隔离。这条链路的本质是：**「身份」是记忆的 key，而不是「登录状态」**。

---

## 🏗️ 架构

### 分层架构（六层，职责单一）

```
用户提问
   │
   ▼
┌─────────────┐   React + Vite（端口 5173）
│  前端层      │   收集输入、渲染 SSE 事件、画 SVG 图表
└─────────────┘
   │ SSE 流式
   ▼
┌─────────────┐   FastAPI（端口 8000）
│  API 层      │   意图路由（闲聊/分析）、SSE、多轮记忆、消息持久化
│  app/api/    │
└─────────────┘
   │
   ▼
┌─────────────┐   LangGraph 状态机（核心）
│  Agent 引擎层 │   planner → executor → decision → reflector/answer/clarify
│  app/agent/  │
└─────────────┘
   │ 选工具执行
   ▼
┌─────────────┐   ToolRegistry（工具名册，可热插拔）
│  工具层      │   SqliteTool / DataSourceTool(天气/疫情) / AnswerTool
│  app/tools/  │
└─────────────┘
   │
   ├── Text2SQL 层（app/text2sql/）：自然语言 → SQL → 三道安全校验 → 执行
   ├── 数据源层（app/datasource/）：OpenMeteo / Disease.sh（依赖倒置，可插拔）
   └── 模型层（app/models/）：SQLAlchemy ORM + SQLite
```

### 一次请求的工作流

```
用户提问
  → 意图分类（IntentClassifier：闲聊 / 数据分析）
  → 数据分析 → 进入状态机
       planner   规划：拆成「工具调用序列」，信息不足则反问澄清
       executor  执行：从名册取工具，一次跑一步
       decision  路由：next(继续) / replan(反思重规划) / clarify(反问) / done(汇总)
       reflector 反思：失败把报错喂回 LLM 换思路重规划（上限 3 次）
       answer    汇总：所有结果 → LLM 生成分析报告
  → 通用出图引擎：按结果结构自动判断折线图 / 柱状图
  → SSE 流式返回：报告 + 图表 + 逐步进度
```

---

## 🛠️ 技术栈

**后端（Python 3.11+）**

| 组件 | 版本 | 用途 |
|------|------|------|
| FastAPI / Uvicorn | 0.115 / 0.30 | Web 框架 / ASGI 服务器 |
| LangGraph | 0.2 | Agent 状态机（图表达状态流转） |
| SQLAlchemy | 2.0 | ORM + SQLite |
| sqlglot | — | SQL AST 级安全校验 |
| PyJWT + bcrypt | — | JWT 认证 + 密码哈希 |
| DeepSeek | — | LLM（OpenAI 兼容，可切换） |

**前端（Node + Vite）**

| 组件 | 用途 |
|------|------|
| React 18 + Vite | 框架与构建 |
| 原生 EventSource | SSE 流式接收（零第三方库） |
| 手写 SVG 图表 | 折线图 / 柱状图（不引入 ECharts，见「设计取舍」） |

**数据源**

| 数据源 | 说明 | 特点 |
|--------|------|------|
| 本地 SQLite | 咖啡店经营数据（销量/毛利/会员） | 演示数据，Text2SQL 查询 |
| Open-Meteo | 天气（预报 + 历史） | 免费无需 Key，30+ 城市坐标表 |
| Disease.sh | 全球疫情数据 | 多数国家停更于 2023，作为「多源热插拔」的架构证据 |

---

## 📁 项目结构

```
smart-assistant-python/
├── backend/
│   ├── app/
│   │   ├── agent/          # 多工具 Agent：状态机(graph/nodes)、工具(tools/tool_impls)、
│   │   │                   #   规划器、意图分类、澄清、审计
│   │   ├── api/            # FastAPI 路由：chat(SSE) / datasource / auth / history
│   │   ├── core/           # 安全(JWT/密码哈希)、依赖注入、结构化日志
│   │   ├── datasource/     # 数据源抽象 + 天气/疫情实现（依赖倒置，热插拔）
│   │   ├── llm/            # LLM 抽象：DeepSeek / Mock
│   │   ├── models/         # SQLAlchemy ORM + 数据库初始化
│   │   ├── services/       # 消息持久化（多轮记忆）
│   │   └── text2sql/       # Text2SQL：schema 提示 + SQL 安全 + 执行器 + 自我纠错
│   ├── tests/              # 13 个测试文件，133 条用例
│   ├── requirements.txt    # 依赖锁版本
│   └── .env.example        # 环境变量模板
├── frontend/               # React + Vite
│   └── src/App.jsx         # 聊天界面 + 手写 SVG 图表
└── docs/                   # 作战地图 / PRD / ADR / bug 复盘
```

---

## 🚀 快速开始

### 前置要求

- Python 3.11+（建议 3.13）
- Node.js 18+
- 一个 DeepSeek API Key（[platform.deepseek.com](https://platform.deepseek.com) 申请）

### 1. 配置环境变量

```bash
cd backend
cp .env.example .env      # Windows: copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY 和 SECRET_KEY
```

### 2. 启动后端

```bash
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

# 初始化数据库（建表 + 灌入咖啡店演示数据）
.venv/Scripts/python.exe -m app.models.init_db

# 启动服务（默认 http://127.0.0.1:8000）
.venv/Scripts/python.exe -m uvicorn app.main:app --reload
```

验证：浏览器打开 http://127.0.0.1:8000/health 应返回 `{"status":"healthy"}`。

### 3. 启动前端

```bash
cd frontend
npm install
npm run dev   # 默认 http://localhost:5173
```

浏览器打开前端地址即可提问。接口文档在 http://127.0.0.1:8000/docs。

> 调试提示：改完代码后如果发现「回复的还是旧逻辑」，先确认后端是否用了 `--reload` 热重载；若无，手动重启进程即可（旧进程跑的是改前代码）。

---

## 🧪 测试

```bash
cd backend
.venv/Scripts/python.exe -m pytest -q   # 133 passed
```

133 个用例覆盖：SQL 安全校验（三道防线）、意图分类、通用出图引擎、工具与数据源、JWT 认证与资源隔离、多轮记忆（匿名会话 + 登录隔离）、天气日期/城市解析、消息持久化等。

> 测试通过独立数据库 + Mock 数据源，不依赖外网、不污染演示数据。

---

## 🔍 问题复盘（Bug Log 精选）

> 这是比「功能清单」更有说服力的部分——它证明的不只是「会写代码」，而是「会定位问题、找根因、沉淀经验」。完整台账见 `docs/bug-log.md`。

### 天气返回「今天」而非「明天」——日期语义的坑

- **现象**：问「明天南昌天气」，返回的却是今天的数据、还是上海的城市。
- **根因**：`forecast_days=1` 语义是「从今天起 1 天」，不是「明天的 1 天」；同时城市参数在透传中被丢弃，坐标写死上海。
- **修复**：引入 30+ 城市坐标表 + 显式 `start_date`（把「明天」换算成具体日期）+ 参数全量透传。
- **教训**：**API 参数的语义和直觉往往不一致**，`days=1` 是「偏移」不是「目标日期」。规划器要注入「今天」的具体日期，让相对日期在进入工具前就被确定。

### 多轮对话「失忆」——身份才是记忆的 key

- **现象**：连续追问「那我该怎么备货」，每轮都像第一次问，接不上上一句。
- **根因**：未登录用户 `user_id = None`，历史记录查询落空，多轮上下文为空。
- **修复**：引入 `session_id` 匿名会话作为隔离键，`user_id` 改为可空，匿名用户也按会话记住上下文。
- **教训**：**「身份标识」才是记忆的 key，而不是「登录状态」**。匿名场景同样需要一套隔离机制，否则多轮能力对未登录用户形同虚设。

### 闲聊人设「错乱」——旧进程没重载

- **现象**：闲聊时系统自称「公共卫生数据智能分析助手」，而不是「咖啡店经营助手」。
- **根因**：8000 端口跑的是**旧进程**（无 `--reload`），用的还是改人设前的代码。
- **修复**：杀掉旧进程，用 `--reload` 重启。
- **教训**：**「代码改了但行为没变」，先怀疑是不是跑的还是旧代码**。这类问题代码本身没错，排查要从「部署/进程状态」入手。

---

## 📝 设计边界与取舍（诚实披露）

- **疫情数据**：Disease.sh 多数国家已停更于 2023，属历史数据。**保留它的目的不是「查实时疫情」，而是作为「多数据源热插拔」架构的证据**——证明系统不依赖单一数据源。
- **经营数据**：本地 SQLite 为内置演示数据，非真实门店。
- **聊天接口当前为「可选登录」**：未登录用户走匿名会话。这是**有意为之的取舍**——降低试用门槛；若正式上线给真店长用，应改为「强制登录」让 JWT + owner 隔离对主链路生效（已记录为待办）。
- **图表不引入 ECharts**：手写 SVG 折线/柱状图，够用且零依赖。图表是「锦上添花」，不为此背上一个前端图表库的重量。
- **向量记忆（RAG）尚未实施**：卡点在于 DeepSeek 不提供 embedding API，需另选 embedding 方案；且咖啡店量级下 Milvus 属过度设计，更合适 FAISS/Chroma。**前提是先有「文字类资料」（会员偏好笔记、备货经验、配方手册）RAG 才有料可喂。**

---

## 📄 文档

- `docs/00-项目作战地图.md` — 整体规划与阶段进度
- `docs/01-需求文档-PRD.md` — 需求说明
- `docs/02-技术方案-ADR.md` — 架构决策记录
- `docs/bug-log.md` — 已修复 bug 完整台账（7 条，含根因分析）

## 📜 License

MIT License
