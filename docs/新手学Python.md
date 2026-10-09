# 新手学 Python

本文归纳阅读 TradingAgents-CN 源码时最容易卡住的语法：`-> dict:`、`await`、`async def`、函数内部再 `def` 嵌套函数，以及 MongoDB 里相当于 SQL `LIKE` 的 `$regex` 查询。例子来自本项目的股票数据准备、分析服务和搜索接口。

读项目代码前，可先看 [新手学习路线](新手学习路线.md)。读到 `app/services/simple_analysis_service.py`、`tradingagents/utils/stock_validator.py`、`app/routers/stock_data.py` 或 `app/routers/reports.py` 时，可回到本文对照。

## 一、`-> dict:` 是返回类型注解

`-> dict:` 不是运算符，也不改变运行时行为。它是函数返回值的类型注解。

拆开看：

| 符号 | 含义 |
| --- | --- |
| `->` | 声明「这个函数返回什么」 |
| `dict` | 返回类型是字典 |
| `:` | 普通函数定义结尾，函数体从下一行开始 |

例如：

```python
def get_user(user_id: int) -> dict:
    return {"id": user_id, "name": "Alice"}
```

意思是：`get_user` 接收一个 `int`，约定返回一个 `dict`。

项目里的同类写法：

```python
def prepare_stock_data(...) -> StockDataPreparationResult:
    ...
```

这里返回的不是裸 `dict`，而是 `StockDataPreparationResult` 对象。读法一样：函数约定返回这个类型。

容易误解的地方：

1. **运行时不强制。** 就算你 `return 123`，Python 也不会因为写了 `-> dict` 而报错。它主要给人和类型检查器（mypy / Pyright）看。
2. **更精确的写法现在更常见：** `-> dict[str, int]`、`-> dict[str, Any]`，而不是裸的 `dict`。
3. **没有返回值时写成 `-> None:`。**

看到 `def foo(...) -> dict:`，直接读成：「这个函数应该返回一个字典」。

## 二、`async def` 把函数声明成协程

`async def` 就是把函数声明成协程函数（asynchronous function）。它和普通 `def` 的差别不在“能不能做事”，而在调用方式：调用后不会立刻跑完，必须再 `await` 才会真正执行并拿到结果。

项目里正好有一对对照：

```python
def prepare_stock_data(...) -> StockDataPreparationResult:
    ...

async def prepare_stock_data_async(...) -> StockDataPreparationResult:
    ...
    return await preparer._prepare_data_by_market_async(...)
```

| | `def` | `async def` |
| --- | --- | --- |
| 调用后立刻得到 | 真实返回值 | coroutine 对象（还没跑完） |
| 函数体内能否写 `await` | 不能 | 能 |
| 等网络/数据库时 | 整条调用链卡住 | 当前任务暂停，事件循环去干别的 |

作用可以拆成三层：

1. **允许内部使用 `await`。** 没有 `async def`，就不能写 `await`。
2. **告诉调用方：这是异步任务，请用 `await` 取结果。** 名字带 `_async` 就是这个约定。
3. **在 IO 等待时让出 CPU。** 拉行情、查库、调 LLM 时，当前分析任务停在 `await` 上，FastAPI 还能处理其他请求。这不是多线程，是单线程协作式调度。

看到：

```python
async def prepare_stock_data_async(...):
```

直接读成：**这是一个可以暂停的函数。调用它只是创建任务，必须 `await` 才会真正去准备股票数据。**

注意：`async def` 本身不会自动变快。如果函数里全是同步阻塞（普通 `time.sleep`、同步 HTTP），写成 `async` 也没用，反而可能卡住整个事件循环。它适合“等外部结果”的场景。

## 三、`await` 等到异步调用真正跑完

`await` 的作用就一句话：**暂停当前函数，等到那个异步调用真正跑完，再拿到真实结果继续往下走。**

项目里这段就是典型用法，位于 `app/services/simple_analysis_service.py`：

```python
validation_result = await prepare_stock_data_async(
    stock_code=stock_code,
    market_type=market_type,
    period_days=30,
    analysis_date=analysis_date,
)

if not validation_result.is_valid:
    ...
```

`prepare_stock_data_async()` 是 `async def`，调用它时不会立刻返回股票校验结果，而是返回一个 coroutine（协程对象）。`await` 才真正启动它，并等到拉行情、校验格式这些 IO 做完。

没有 `await` 会怎样：

```python
# 错：validation_result 不是结果，而是 coroutine 对象
validation_result = prepare_stock_data_async(...)
validation_result.is_valid   # 这里会炸
```

有 `await` 才对：

```python
# 对：等到真正返回 StockDataPreparationResult
validation_result = await prepare_stock_data_async(...)
```

三个关键点：

1. **只能写在 `async def` 里。** 普通 `def` 里写 `await` 会语法错误。
2. **等的是“这一次调用”，不是卡死整个程序。** 当前分析任务在等行情时，FastAPI 事件循环还能去处理别的请求。
3. **它不是“异步启动、立刻返回”。** `await` 之后的下一行，一定是这个函数已经结束了。所以后面才能安全地读 `validation_result.is_valid`。

项目注释也写了原因：分析服务本身跑在 FastAPI 异步上下文里，所以必须 `await` 异步版本，而不是直接调同步的 `prepare_stock_data()`。否则容易和已有事件循环打架。

## 四、三者怎么串起来

```text
async def 调用方
  -> await 暂停当前任务，交出事件循环
  -> async def 被调方真正执行（拉行情 / 校验）
  -> 完成后把真实结果交回调用方
  -> 调用方继续用 is_valid 等字段
```

对照本项目：

| 语法 | 本项目中的位置 | 读法 |
| --- | --- | --- |
| `-> StockDataPreparationResult` | `tradingagents/utils/stock_validator.py` | 约定返回数据准备结果 |
| `async def prepare_stock_data_async()` | 同上 | 这是异步版本，必须 await |
| `await prepare_stock_data_async(...)` | `app/services/simple_analysis_service.py` | 等到校验完成，再决定分析能否继续 |

可以记三句：

- `-> T`：约定返回类型 `T`，运行时不强制。
- `async def`：声明可暂停的协程函数。
- `await`：等到协程跑完，拿到真实结果。

## 五、函数内部再 `def`：嵌套函数 / 闭包

读到 `execute_analysis_background()` 时，会看到函数里面又定义了 `def create_progress_tracker():`。这不是再定义一套独立服务，而是 Python 的 **嵌套函数（nested function）**，也叫闭包。

外层 `execute_analysis_background()` 是 `async`，跑在 FastAPI 事件循环上。内部函数是为了把一段 **同步、可能阻塞** 的代码包起来，丢给线程池：

```python
# app/services/simple_analysis_service.py
# 在线程池中创建Redis进度跟踪器（避免阻塞事件循环）
def create_progress_tracker():
    """在线程中创建进度跟踪器"""
    logger.info(f"📊 [线程] 创建进度跟踪器: {task_id}")
    tracker = RedisProgressTracker(
        task_id=task_id,
        analysts=request.parameters.selected_analysts
        or ["market", "fundamentals"],
        research_depth=request.parameters.research_depth or "标准",
        llm_provider="dashscope",
    )
    logger.info(f"✅ [线程] 进度跟踪器创建完成: {task_id}")
    return tracker

progress_tracker = await asyncio.to_thread(create_progress_tracker)
```

### 为什么要写在里面

1. **给 `asyncio.to_thread()` 一个无参可调用对象。**  
   `to_thread(fn)` 需要的是“函数本身”，不是已经执行完的结果。内部 `def` 就是在造这个包装函数，后面 `await asyncio.to_thread(create_progress_tracker)` 才会在线程里真正执行。

2. **闭包直接用外层变量，少传一堆参数。**  
   内部函数能直接读到 `task_id`、`request`。如果提成类方法，还得把这些参数再传一遍。

3. **避开事件循环阻塞。**  
   `RedisProgressTracker.__init__()` 会连 Redis、生成步骤、写初始进度，这是同步 I/O。如果直接在 `async` 函数里 `RedisProgressTracker(...)`，Redis 稍慢就会卡住整个事件循环，别的请求也进不来。丢进线程后，主循环还能继续处理状态查询、WebSocket。

4. **这段逻辑只服务这一次任务。**  
   它不需要被别的模块复用，所以没必要提成类级方法。作用域收在当前任务里，更安全。

### 和 `async` / `await` 怎么配合

```text
async def execute_analysis_background()     跑在事件循环上
  -> def create_progress_tracker()          内部包装同步阻塞逻辑
  -> await asyncio.to_thread(...)           丢进线程池，事件循环继续干别的
  -> tracker 建好后再回到主流程
```

可以对照上一节：`await` 等的是异步调用跑完；这里 `await asyncio.to_thread(...)` 等的是 **线程里那段同步代码跑完**。两者都是“暂停当前协程，但不卡死整个服务”。

### 同一文件里的同类写法

| 内部函数 | 所在位置 | 目的 |
| --- | --- | --- |
| `create_progress_tracker()` | `execute_analysis_background` | 线程里创建 Redis 进度器 |
| `update_progress_sync()` | `_run_analysis_sync` | 线程池里同步更新进度 |
| `simulate_progress()` | `_run_analysis_sync` | 模拟进度推进 |
| `graph_progress_callback()` | `_run_analysis_sync` | 给 LangGraph 当回调，捕获当前 `progress_tracker` |

本质都是：**外层是 async / 线程池编排，内层用闭包包住“只属于这次任务”的同步逻辑。**

如果写成 lambda 也行，但多行构造、日志、默认值用 `def` 更清楚。提成 `_create_progress_tracker(self, task_id, request)` 也能跑，只是会多一层传参。当前写法是为了少传参、把阻塞点隔离出去。

看到函数里面再 `def xxx():`，先问两句：

1. 它是不是马上被 `asyncio.to_thread()` / `run_in_executor()` / 回调注册拿走？
2. 它有没有直接使用外层的 `task_id`、`request`、`progress_tracker`？

两句都是，就是闭包，不是“函数套函数写乱了”。

## 六、MongoDB 没有 `LIKE`，用 `$regex`

读到股票搜索、报告搜索时，会看到 `{"name": {"$regex": keyword, "$options": "i"}}`。这不是 Python 语法，而是 MongoDB 查询条件。SQL 的 `LIKE` 在 MongoDB 里对应 `$regex`。

| SQL | MongoDB |
| --- | --- |
| `LIKE '%茅台%'` | `{ "name": { "$regex": "茅台" } }` |
| `LIKE '茅台%'` | `{ "name": { "$regex": "^茅台" } }` |
| `LIKE '%茅台'` | `{ "name": { "$regex": "茅台$" } }` |
| `LIKE '茅台'` | `{ "name": "茅台" }`（精确匹配，不要用正则） |
| 忽略大小写 | `{ "name": { "$regex": "maotai", "$options": "i" } }` |

`^` 表示开头，`$` 表示结尾，和普通正则一样。`$options: "i"` 表示 ignore case，大小写不敏感。

### 项目里怎么写

股票搜索在 `app/routers/stock_data.py`：6 位数字按代码精确匹配，否则按名称模糊匹配；关键词里带数字时，代码也做一次正则。

```python
# app/routers/stock_data.py
search_conditions = []

# 如果是6位数字，按代码精确匹配
if keyword.isdigit() and len(keyword) == 6:
    search_conditions.append({"symbol": keyword})
else:
    # 按名称模糊匹配
    search_conditions.append({"name": {"$regex": keyword, "$options": "i"}})
    # 如果包含数字，也尝试代码匹配
    if any(c.isdigit() for c in keyword):
        search_conditions.append({"symbol": {"$regex": keyword}})

query = {
    "$and": [
        {"$or": search_conditions},
        {"source": preferred_source},
    ]
}
```

报告搜索在 `app/routers/reports.py`：关键词同时打到股票代码、分析 ID、摘要三个字段。

```python
# app/routers/reports.py
if search_keyword:
    query["$or"] = [
        {"stock_symbol": {"$regex": search_keyword, "$options": "i"}},
        {"analysis_id": {"$regex": search_keyword, "$options": "i"}},
        {"summary": {"$regex": search_keyword, "$options": "i"}},
    ]
```

筛选服务把前端的 `contains` 直接映射成 `$regex`，见 `app/services/database_screening_service.py`：

```python
self.operators = {
    ...
    "contains": "$regex",   # 字符串包含
}
```

### 和 SQL 怎么对应着读

```text
SQL:     WHERE name LIKE '%茅台%'
Mongo:   { "name": { "$regex": "茅台" } }

SQL:     WHERE name LIKE '%茅台%' OR symbol LIKE '%600519%'
Mongo:   { "$or": [
             { "name": { "$regex": "茅台" } },
             { "symbol": { "$regex": "600519" } }
         ]}
```

看到 `{"$regex": keyword, "$options": "i"}`，直接读成：**这个字段做模糊包含匹配，并且忽略大小写。**

### 写的时候注意

1. **用户输入先转义。** `keyword` 如果含 `. * + ?` 会被当成正则。更稳妥的写法是 `re.escape(keyword)`。本项目部分搜索接口目前直接把关键词塞进 `$regex`，读代码时要知道这个风险。
2. **前缀 `^xxx` 才容易走索引。** 中间包含（`%xxx%`）基本是扫描，数据量大时会慢。
3. **精确匹配不要用正则。** 6 位股票代码用 `{"symbol": keyword}` 就够了，项目里也是这样分的。
4. **这是查询文档，不是 Python 运算符。** 它出现在 `collection.find(query)` 的 `query` 字典里，由 MongoDB 服务端执行。
