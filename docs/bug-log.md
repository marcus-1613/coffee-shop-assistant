# Bug Log（踩坑记录簿）

> 这是整个项目最有价值的资产之一 —— 每个 bug 都记录，写简历时可直接引用。

---

## 使用说明

- 每个 bug 按模板记录，编号递增
- 记录「现象 / 根因 / 解决 / 教训」四要素
- 面试时：讲"我如何定位并解决这个 bug"比讲"我做了什么功能"更有说服力

---

## 记录模板

```markdown
### Bug #XXX — 标题
- 阶段：阶段 X / 小阶段 X.X
- 现象：
- 报错信息：
- 根因分析：
- 解决方案：
- 经验教训：
```

---

## 记录区（按时间追加）

### Bug #001 — 中文路径参数导致 HTTP 请求无效（Invalid HTTP request）
- 阶段：阶段 1 / 小阶段 1.3（FastAPI 最小可运行）
- 现象：访问 `/hello/小明` 时返回 `Invalid HTTP request received.`，而 `/hello/alice`（英文）正常。
- 报错信息：`Invalid HTTP request received.`
- 根因分析：URL 中的中文（非 ASCII 字符）必须经过 **URL 编码（百分号编码）** 才能传输。直接在命令行用 `curl` 访问含中文的 URL，`curl` 未自动编码，导致服务端收到非法字符。用 `%E5%B0%8F%E6%98%8E`（"小明"的 UTF-8 编码）访问则完全正常。
- 解决方案：对 URL 中的非 ASCII 字符做 URL 编码。浏览器会自动完成这一步，所以用户在浏览器里输中文没问题；只有命令行 `curl` 或部分客户端需要手动编码。
- 经验教训：
  1. HTTP 协议本身只支持 ASCII，中文等字符必须编码（这是 HTTP 的底层规范，与框架无关）。
  2. 测试含中文/特殊字符的接口时，命令行要注意编码问题；优先用浏览器或 FastAPI 的 `/docs` 自动文档测试。

### Bug #002 — SQLite 中 `sum(Boolean)` 返回布尔值而非数字
- 阶段：阶段 2 / 小阶段 2.2（演示数据验证）
- 现象：统计"各科室完成人数"时，`func.sum(Patient.completed)` 的结果是 `True`/`False`，而不是数字（如 `完成True人`）。
- 根因分析：SQLite 没有真正的布尔类型，`Boolean` 列底层存的是整数 0/1。对布尔列做 `SUM` 聚合时，SQLAlchemy 仍按布尔类型解释结果，导致求和结果被当成布尔值返回。
- 解决方案：聚合时把布尔列显式转成整数再求和，例如 `func.sum(func.cast(Patient.completed, Integer))`，这样返回的就是数字。
- 经验教训：
  1. 数据库的布尔类型在不同引擎里实现不同（SQLite 用 0/1，MySQL 用 tinyint，PostgreSQL 是真 boolean），跨库时要小心聚合函数的行为差异。
  2. 对布尔列做数值运算（sum/count/avg）前，先显式 `cast` 成整数，这是通用安全写法。

### Bug #003 — LangGraph 条件边节点返回字符串而非 dict
- 阶段：阶段 4 / Agent 状态机（LangGraph）
- 现象：运行 `graph.invoke()` 报错 `InvalidUpdateError: Expected dict, got finish`，任务卡在 `decision` 节点。
- 根因分析：LangGraph 的**条件边（conditional edge）**路由节点，返回值应该是「路由键字符串」（如 "finish"）。但把 `decision` 节点同时用 `add_node` 注册成了普通节点，导致 LangGraph 把它当成普通节点，要求其返回 dict 来更新状态，于是字符串 "finish" 就报错了。
- 解决方案：条件边用于路由的节点，**不要用 `add_node` 注册**，只作为条件边的路由函数传入即可。修正后，`decision` 只返回字符串决定走哪条边，不再被当作更新状态的节点。
- 经验教训：
  1. LangGraph 中「更新状态的节点」和「决定路由的条件函数」是两回事，不能混用。
  2. 条件边语法：`add_conditional_edges(source, route_func, mapping)`，其中 `route_func` 返回字符串键，`mapping` 把键映射到目标节点名。

### Bug #004 — 查询结果行的数据结构假设错误（list vs dict）
- 阶段：阶段 4 / 进阶（真 planner + 真 summarizer）
- 现象：Agent 的 `executor` 节点在整理上下文时崩溃，报错 `AttributeError: 'list' object has no attribute 'get'`。
- 根因分析：我在写 `_summarize_for_context` 时，想当然地认为查询结果 `result['result']['rows']` 里的每一行是「字典（dict）」，于是用了 `row.get(col)` 取值。但实际上 SQL 执行器返回的是「列表的列表」（`rows = [["内科", 4], ["外科", 3]]`，即 list of list），每行是 list 而非 dict，list 没有 `.get()` 方法。
- 解决方案：改用「列名 + 行索引」配对：`columns` 是列名列表，`rows` 的每一行是按列顺序排列的值列表，用 `zip(columns, row)` 或索引对齐来生成「列名=值」的文本。
- 经验教训：
  1. **跨模块协作时，必须先确认对方返回的数据结构**，不能凭直觉假设是 dict 还是 list、tuple 还是对象。这是接口对接最常见的坑。
  2. 数据库查询结果的默认形态是「列名列表 + 行列表」，行内是「按列顺序的值」，不是键值对。要转成键值对，需要自己用 `columns` 和 `row` 配对（如 `dict(zip(columns, row))`）。

### Bug #005 — 为省 Token 截断数据，导致 LLM 误判"数据不完整"
- 阶段：企业级升级 / 阶段一（数据源 + 出图）
- 现象：查"美国最近 30 天确诊趋势"，后端正确返回了完整 30 天数据并生成折线图，但 LLM 生成的《分析报告》里却写"本次查询仅返回前 5 天，后 25 天被省略，无法判断整月趋势"。
- 根因分析：这不是数据丢失，而是「提示词误导」。我在 `_format_result_for_llm` 里为了省 Token，只把前 5 天喂给汇总 LLM，末尾还写了"…（还有 N 天）"。模型看到这个省略标记，误以为数据真的不完整，于是在报告里反复提醒"数据不完整、无法下结论"。
- 解决方案：把「完整趋势数据」喂给 LLM（历史趋势天数通常 ≤ 90，Token 可控），并明确标注"以下为完整数据"，去掉误导性的省略号。
- 经验教训：
  1. **省 Token 不能以牺牲信息完整性为代价**——喂给 LLM 的数据如果被截断，必须明确告诉它"这是截断的样本"，否则它会基于错误前提推理（这也是一种"幻觉"的诱因）。
  2. LLM 的输出质量，上限取决于你喂给它的上下文质量。喂残缺数据，得到的就是残缺结论。
  3. 这类 bug 很隐蔽：数据其实是对的，但"呈现给模型的方式"错了，属于「prompt engineering」层面的坑。

### Bug #006 — passlib 与 bcrypt 5.x 不兼容导致密码哈希崩溃
- 阶段：企业级升级 / P0（用户认证与资源隔离）
- 现象：调用 `hash_password()` 时抛异常 `ValueError: password cannot be longer than 72 bytes`，且伴随后台 `AttributeError: module 'bcrypt' has no attribute '__about__'`，导致注册接口 500。
- 根因分析：这是一个**第三方库兼容性 bug**。`passlib`（老牌密码哈希库）已经**多年停止维护**，其内部通过读取 `bcrypt.__about__.__version__` 来探测 bcrypt 版本，但 `bcrypt` 升级到 5.x 后删除了 `__about__` 属性，导致 passlib 探测失败，最终误判密码超长而崩溃。
- 解决方案：**放弃 passlib，直接使用 `bcrypt` 库**（活跃维护）做哈希和校验，并显式处理 bcrypt 的 72 字节长度限制。
- 经验教训：
  1. **依赖选型必须看"维护状态"**——passlib 这种"曾经的主流、现已停更"的库，一旦底层依赖升级就会崩。企业级选库要选活跃维护的。
  2. 这类 bug 的特点是"代码没写错，但环境一升级就炸"，排查时要从「依赖兼容性」角度想，而不是死盯着自己的逻辑。
  3. 属于「技术债」类 bug：用停更库埋下的雷，迟早被依赖升级引爆。

### Bug #007 — 测试未做数据清理，导致全量测试互相污染（唯一约束冲突）
- 阶段：企业级升级 / Agent 智能升级（多轮记忆）
- 现象：单跑 `tests/test_memory.py` 全部通过（5 条全绿），但一跑全量 `pytest` 就大面积失败，报 `sqlalchemy.exc.IntegrityError: UNIQUE constraint failed: users.username`。
- 根因分析：这是**测试隔离问题**，不是业务代码 bug。多轮记忆的测试往真实 SQLite 数据库的 `users` 表插入了 `mem_user_1` 等测试用户，但**测试结束时没有清理**。于是：
  1. 第一次单跑 → 数据残留在了库里
  2. 第二次全量跑 → 同名测试用户再次插入 → 触发 `username` 唯一约束冲突 → 全挂
- 解决方案：给测试 fixture 加 **teardown**（清理逻辑），每个测试结束删除自己插入的 `mem_%` 前缀用户及其会话，保证测试之间互不污染。
- 经验教训：
  1. **测试必须「自清理」**：测试之间不能共享可变状态（数据库、文件、全局变量），否则会互相污染。这是「测试隔离性（Test Isolation）」的基本功。
  2. 一个测试"单跑通过、全量失败"，是典型的「测试间耦合」信号——排查时先想"是不是上个测试留下了脏数据"，而不是死盯失败的断言。
  3. 生产环境的自动化测试通常用「事务回滚」或「独立测试库」来做隔离，比"手动删数据"更稳（这是后续可优化的方向）。

