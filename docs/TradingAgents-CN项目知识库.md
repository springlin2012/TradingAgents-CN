# TradingAgents-CN 项目知识库

> 更新日期：2026-10-23  
> 用途：按功能沉淀调用链，便于排障和二次开发。

## 功能目录

| 编号 | 功能 | 一句话 |
|---|---|---|
| 1 | 根据股票代码查询股票名称 | 添加自选股时，A 股代码失焦后读本地库自动填名称 |
| 2 | stock_basic_info 数据来源与同步 | A 股基础信息如何从 Tushare / AKShare / BaoStock 入库 |
| 3 | A股名称模糊搜索与自动填充 | 输入名称片段，选择候选后同时填入名称和六位代码 |
| 4 | Docker Compose 与 MongoDB / Redis | 一份 YAML 编排多容器；库是独立服务，不必在后端容器里手动安装 |

---

## 功能 1：根据股票代码查询股票名称

添加自选股时，A 股代码输入框失焦后自动填充股票名称。这条链路只读本地已入库的基础信息，不现场调用 Tushare / AKShare 查名。

### 1.1 使用场景

- 页面：我的自选股 → 添加自选股对话框
- 触发：股票代码输入框 `@blur="fetchStockInfo"`
- 条件：市场类型必须是 **A股**；港股、美股失焦不调接口，名称需手填

### 1.2 调用链

```
Favorites 添加对话框（blur）
  → GET /api/stock-data/basic-info/{symbol}
  → app/routers/stock_data.py :: get_stock_basic_info
  → StockDataService.get_stock_basic_info(symbol)
  → MongoDB.stock_basic_info
  → 返回 data.name，前端写入「股票名称」
```

### 1.3 接口

| 项 | 说明 |
|---|---|
| 方法 / 路径 | `GET /api/stock-data/basic-info/{symbol}` |
| 鉴权 | 需要登录（`get_current_user`） |
| 路由 | `app/routers/stock_data.py` |
| 路由前缀 | `/api/stock-data`，在 `app/main.py` 中 `include_router(stock_data_router.router)` |
| 成功 | `{ success: true, data: { name, ... }, message: "获取成功" }` |
| 未找到 | `{ success: false, message: "未找到股票代码 {symbol} 的基础信息" }` |

前端只取 `res.data.name`。查不到或请求失败时，提示手动输入股票名称。

### 1.4 服务与查询规则

服务类：`app/services/stock_data_service.py` 中的 `StockDataService.get_stock_basic_info()`。

1. 将 `symbol` 补齐为 6 位（`zfill(6)`）
2. 按 `symbol` 或 `code` 查询集合 `stock_basic_info`
3. 本次请求不传 `source`，按固定优先级取第一条命中记录：
   - `tushare`
   - `multi_source`
   - `akshare`
   - `baostock`
4. 以上都没有，再兜底查询无 `source` 字段的旧数据
5. 命中后经 `_standardize_basic_info()` 标准化，封装为 `StockBasicInfoExtended`

### 1.5 相关代码

| 层 | 文件 |
|---|---|
| 前端触发 | `frontend/src/views/Favorites/index.vue`（`fetchStockInfo`） |
| API 路由 | `app/routers/stock_data.py` |
| 数据服务 | `app/services/stock_data_service.py` |
| 数据集合 | MongoDB `stock_basic_info` |

### 1.6 注意

- 自动填名称依赖库里已经有该股票的基础信息；未同步入库时名称不会自动出现。
- 这条接口不是自选股 CRUD。自选股增删改仍走 `/api/favorites`，由 `FavoritesService` 读写 `user_favorites`。
- 详情页、筛选页加入自选时，名称来自当前页面已有字段，不会再走这条失焦查询。
- 数据从哪里来、何时写入，见 **功能 2**。
- 选择功能 3 的候选后跳过同代码失焦查名；手动代码须为六位数字才查询。请求返回前核对代码、名称编辑版本、市场和弹窗会话，防止旧响应覆盖后续编辑。

---

## 功能 2：stock_basic_info 数据来源与同步

`stock_basic_info` 是 A 股基础信息的本地副本，不是实时查外部接口的缓存表。港股、美股不进这个集合，分别写入 `stock_basic_info_hk` / `stock_basic_info_us`。

### 2.1 数据来源

同一只股票可以有多条文档，靠唯一键 `(code, source)` 区分：

| source | 外部接口 | 典型内容 |
|---|---|---|
| `tushare` | `stock_basic` + `daily_basic` + `fina_indicator` | 名称、行业、板块、上市日、市值、PE/PB/PS、换手、ROE |
| `akshare` | AKShare Provider `get_stock_basic_info` | 名称等基础字段，按只拉取 |
| `baostock` | BaoStock 基础信息 + 估值接口 | 名称、PE/PB、市值等 |

读名称时（功能 1）按固定优先级取第一条：

`tushare` → `multi_source`（旧数据） → `akshare` → `baostock`

`multi_source` 现在已经不再作为新写入值；新数据会写成真正用到的源名。

### 2.2 获取机制

核心动作都是：**外部拉全量/批量 → 标准化 6 位代码 → `upsert({code, source})`**。

主路径有两条。

#### 2.2.1 多源同步

服务：`MultiSourceBasicsSyncService.run_full_sync()`  
时机：服务启动后立刻跑一次，之后默认每天 06:30（`SYNC_STOCK_BASICS_ENABLED`，可用 `SYNC_STOCK_BASICS_CRON` 或 `SYNC_STOCK_BASICS_TIME`）。

1. `DataSourceManager` 按 Tushare → AKShare → BaoStock 回退，拿股票列表
2. 探测最近交易日，拉日度指标（市值、估值、换手）
3. 拼文档：`code/name/industry/market/list_date/sse/...`，`source` 写成实际成功的源
4. 每 500 条 `bulk_write` upsert
5. 状态写入 `sync_status`，job 为 `stock_basics_multi_source`

#### 2.2.2 分源定时同步

| 任务 | 默认时间 | 服务 | 开关 |
|---|---|---|---|
| Tushare | 每天 02:00 | `TushareSyncService.sync_stock_basic_info` | `TUSHARE_UNIFIED_ENABLED` + `TUSHARE_BASIC_INFO_SYNC_ENABLED` |
| AKShare | 每天 03:00 | `AKShareSyncService.sync_stock_basic_info` | `AKSHARE_UNIFIED_ENABLED` + `AKSHARE_BASIC_INFO_SYNC_ENABLED` |
| BaoStock | 每天 04:00 | `BaoStockSyncService.sync_stock_basic_info` | `BAOSTOCK_UNIFIED_ENABLED` + `BAOSTOCK_BASIC_INFO_SYNC_ENABLED` |

Tushare 这条最完整：

1. `api.stock_basic(list_status='L')` 拉上市股名单
2. `daily_basic(trade_date=最近交易日)` 补市值/估值
3. `fina_indicator` 补 ROE
4. 24 小时内已更新的可跳过（`force_update=True` 除外）
5. `update_stock_basic_info(..., source="tushare")`

AKShare / BaoStock 是先拿列表，再按只拉详情，写入对应 `source`。对应 `UNIFIED_ENABLED` 关掉时，分源任务会被 pause。

### 2.3 写入入口

| 入口 | 说明 |
|---|---|
| 服务启动 | 后台立刻跑一次多源全量同步 |
| 定时任务 | 多源 06:30 + 上面三个分源 cron |
| 手动全量 | `POST /api/sync/stock_basics/run`（仅 Tushare，`BasicsSyncService`） |
| 手动多源 | `POST /api/multi-source-sync/stock_basics/run` |
| 初始化向导 | Tushare / AKShare / BaoStock 初始化服务 |
| 单只/批量同步 | 自选股页「同步」走 `stock_sync`，按所选数据源 upsert 对应文档 |

### 2.4 相关代码

| 层 | 文件 |
|---|---|
| 启动与定时 | `app/main.py` |
| 多源同步 | `app/services/multi_source_basics_sync_service.py` |
| Tushare 全量（含市值/ROE） | `app/services/basics_sync_service.py`、`app/services/basics_sync/utils.py` |
| Tushare 分源同步 | `app/worker/tushare_sync_service.py` |
| AKShare 分源同步 | `app/worker/akshare_sync_service.py` |
| BaoStock 分源同步 | `app/worker/baostock_sync_service.py` |
| 手动同步路由 | `app/routers/sync.py`、`app/routers/multi_source_sync.py`、`app/routers/stock_sync.py` |
| 配置项 | `app/core/config.py` |

### 2.5 注意

- 功能 1 的失焦填名称 **只读库，不再打外部行情**。库里没有这只股票、或对应 `source` 没同步过，名称就不会自动出来。
- 要补数据走功能 2 的同步入口，而不是功能 1 的 GET 接口。
- 港股 / 美股基础信息不写入 `stock_basic_info`。

---

## 功能 3：A股名称模糊搜索与自动填充

### 3.1 使用场景与调用链

我的自选股 → 添加自选股 → A股股票名称输入框。港股、美股继续使用普通名称输入框。

```text
Favorites/index.vue 的 el-autocomplete
  → useStockNameAutocomplete（300毫秒防抖）
  → stockData.ts :: searchStockCandidates
  → GET /api/stock-data/search?keyword=海&limit=10&mode=autocomplete
  → stock_data.py :: search_stocks
  → StockDataService.search_stock_candidates
  → MongoDB.stock_basic_info（聚合匹配、选源、去重、排序）
  → 候选列表显示名称和代码
  → selectStock 同时写入 stock_name / stock_code
  → 原 /api/favorites 添加流程
```

### 3.2 接口参数与响应

| 参数 | 规则 |
|---|---|
| `mode` | `default`（默认）保留原搜索行为；`autocomplete` 搜索名称候选 |
| `keyword` | 自动模式去除首尾空白后须为1～50字符，否则 HTTP 422 |
| `limit` | 接口接受1～50；自动模式最多10条，前端固定传10 |
| 鉴权 | 沿用 `get_current_user` 登录鉴权 |

响应沿用 `{success, data, total, keyword, source, message}`。自动模式的 `data` 是数组，每条固定为 `{symbol, name, source}`，代码为六位字符串；顶层 `source="mixed"`，`total` 表示本次返回数量。默认模式的来源策略和响应保持兼容。

### 3.3 数据规则

- 只读本地 `stock_basic_info`，不调用外部行情接口，不新增集合。入库机制见功能 2。
- 使用 `re.escape` 对名称作大小写不敏感的字面子串匹配；不支持拼音、错别字或历史名称搜索。
- 兼容 `symbol/code`，1～6位数字代码补齐六位；无效代码与显式 HK/US 记录排除。
- 同代码的匹配记录按 `tushare → multi_source → akshare → baostock → 其他来源` 选源；同来源按更新时间、记录标识稳定取最新，缺失来源返回 `unknown`。
- 去重后按名称完全匹配、前缀匹配、包含匹配排序，同级按代码升序，最后限制数量。不同来源名称有差异时，以本次匹配记录为准。

### 3.4 前端交互与请求保护

候选与输入框等宽，显示名称和六位代码，支持鼠标、上下键、回车及 Esc。选中后清除名称和代码的校验错误，跳过同代码查名；再次修改名称清除此次自动填入的代码，手动改代码清除旧选择及自动名称。

输入变化立即使旧请求失效；响应更新前核对请求版本、关键词、A股市场和弹窗会话。切换市场、关闭、重开、销毁时清除候选和计时器。代码查名也核对编辑版本与会话，避免覆盖后来输入。

无结果提示“未找到匹配股票，可输入完整代码和名称”；失败提示“搜索暂时不可用，可手动填写”。搜索设置 `skipErrorHandler=true`、`retryCount=0`，字段提示不重复弹全局错误；401仍沿用登录失效处理。

### 3.5 验证与相关文件

- 后端：`tests/test_stock_name_candidates.py`，23项测试覆盖真实 MongoDB 聚合、来源回退、排序、特殊字符、参数和默认模式兼容。仅使用随机独立测试库并清理，不访问业务集合。完整执行需显式设置 `TEST_STOCK_CANDIDATES_MONGO_URI`；无可用测试库时部分测试跳过。
- 前端：`node --test tests/frontend/test_stock_name_autocomplete.cjs tests/frontend/test_stock_search_request.cjs`，10项通过，覆盖防抖、乱序响应、表单联动、状态清理与静默错误/401。
- 构建：`npm run type-check`、`npm run build`；lint 使用 `npm run lint -- --no-fix --ignore-path ../.gitignore`，避免原脚本引用不存在的前端 `.gitignore`。本地补齐缺少的 `@rushstack/eslint-patch`，未修改依赖清单和锁文件。
- 浏览器模拟服务：`tests/frontend/stock_name_ui_fixture.cjs`，使用内存股票和自选数据验证界面，不代表真实业务环境或数据覆盖率。
- 实施设计与验收说明：[自选股名称模糊搜索实现方案](design/自选股名称模糊搜索实现方案_20261009.md)。未测真实库 P95；中文输入法组合输入依赖组件机制，尚未完成实机输入法验收。

---

## 功能 4：Docker Compose 与 MongoDB / Redis

Docker Compose 把一套多容器应用写成一份 YAML，再用一条命令创建、联网、启动、停掉。单容器用 `docker run` 即可；本仓库是前后端分离 + MongoDB + Redis，端口、网络、启动顺序和环境变量都声明在项目配置里，不靠人手记。

当前本地整套环境以仓库根目录 `docker-compose.yml` 为准。Kubernetes 适合多机、自愈、滚动发布；本仓库本机开发和单机部署走 Compose。

### 4.1 使用场景

- 一条命令拉起前端、后端、MongoDB、Redis
- 容器之间用服务名互访，不必在后端镜像或 Windows 宿主机里再装数据库
- 本机直接跑 `python -m app` 时，可以只起库容器，或改连云上的库

### 4.2 编排关系

```text
docker-compose.yml
  → Compose 引擎
  → tradingagents-network
      frontend   （Vue，宿主机 3000 → 容器 80）
      backend    （FastAPI，宿主机 8000）
      mongodb    （官方镜像 mongo:4.4）
      redis      （官方镜像 redis:7-alpine）
```

启动顺序由 `depends_on` + `healthcheck` 约束，不是并行乱起：

```text
mongodb 健康 ─┐
              ├─→ backend 健康 → frontend
redis 健康  ─┘
```

`redis-commander`、`mongo-express` 打了 `profiles: [management]`，默认 `up` 不会启动；需要管理界面时再加 `--profile management`。

### 4.3 YAML 关键字段（对照本仓库）

| 字段 | 作用 | 本仓库实际值 |
|---|---|---|
| `services` | 要启动的容器清单 | 默认四件套：`backend`、`frontend`、`mongodb`、`redis` |
| `depends_on` | 启动顺序与健康等待 | 库先健康 → 后端 → 前端 |
| `networks` | 容器互相用服务名通信 | 全部挂在 `tradingagents-network`；后端连库用主机名 `mongodb` / `redis`，不写 `127.0.0.1` |
| `volumes` | 数据落盘，删容器不丢 | 命名卷 `mongodb_data` / `redis_data`；`logs`、`config`、`data` 绑定挂载到仓库目录 |
| `ports` | 映射到本机端口 | 前端 `3000:80`，后端 `8000:8000`，MongoDB `27017`，Redis `6379` |
| `profiles` | 可选服务 | 管理界面默认不起 |

每个 service 相当于一次带好参数的 `docker run`，但名字、网络、依赖写在同一份文件里。服务名就是容器内 DNS。

### 4.4 MongoDB / Redis 要不要手动安装

**走 `docker compose up` 时，Windows 本机和后端容器里都不必再装 MongoDB / Redis。** 它们是独立服务，不是装进后端镜像的系统包。

| 位置 | 装什么 | 谁负责 |
|---|---|---|
| Windows 宿主机 | 只装 Docker Desktop | 使用者 |
| `backend` 容器 | Python 客户端：`pymongo` / `motor` / `redis` | `Dockerfile.backend` + `pyproject.toml` |
| `mongodb` / `redis` 容器 | 数据库服务本身 | Compose 拉官方镜像 `mongo:4.4`、`redis:7-alpine` |

`Dockerfile.backend` 里没有 `apt-get install mongodb` / `redis`，也不该有：一个容器只跑一个进程。库和应用拆开，才能单独重启、单独扩容，数据落在 volume 上。

Docker 内标准连接（见 `.env.docker`）：

- MongoDB：`mongodb://admin:tradingagents123@mongodb:27017/tradingagentscn?authSource=admin`
- Redis：`redis://:tradingagents123@redis:6379/0`

这是容器内 DNS，不是本机回环地址。`docker-compose.yml` 的 `environment` 会覆盖 `env_file`；排障时以容器内实际环境变量为准。

只有两种情况才需要自己准备库：

1. **本机直接跑** `python -m app`（不用 Compose）  
   要么本机安装 MongoDB / Redis，要么只起库：`docker compose up -d mongodb redis`，再连 `localhost:27017` / `localhost:6379`。
2. **故意用云上的库**  
   改连接串即可，Compose 里的 `mongodb` / `redis` 服务可以不启。

### 4.5 常用命令

```bash
docker compose up --build
docker compose ps
docker compose logs -f backend
docker compose down
docker compose --profile management up -d
```

`down` 拆除容器和网络，命名卷默认还在，数据库不会跟着消失。

### 4.6 相关文件

| 层 | 文件 |
|---|---|
| 编排入口 | `docker-compose.yml` |
| 后端镜像 | `Dockerfile.backend` |
| 前端镜像 | `Dockerfile.frontend` |
| Docker 环境变量 | `.env.docker` |
| Python 客户端依赖 | `pyproject.toml`（`motor`、`pymongo`、`redis`） |
| 部署说明 | `docs/deployment/docker/docker_deployment_guide.md` |
| 库连接排障 | `docs/troubleshooting-mongodb-docker.md` |

### 4.7 注意

- 改 Compose 或 Dockerfile 后，本地 `python -m app` 不会吃到这些变更；要验证容器内行为必须重新 `docker compose up --build`。
- 后端连库必须用服务名 `mongodb` / `redis`。在容器里写 `127.0.0.1` 会连到后端自己，而不是库容器。
- 不要把 MongoDB / Redis 装进 `backend` 镜像。功能 1～3 读的 `stock_basic_info` 等集合，落在 `mongodb` 容器的命名卷上。
