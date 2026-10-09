# TradingAgents-CN 项目知识库

> 更新日期：2026-10-09  
> 用途：按功能沉淀调用链，便于排障和二次开发。

## 功能目录

| 编号 | 功能 | 一句话 |
|---|---|---|
| 1 | 根据股票代码查询股票名称 | 添加自选股时，A 股代码失焦后读本地库自动填名称 |
| 2 | stock_basic_info 数据来源与同步 | A 股基础信息如何从 Tushare / AKShare / BaoStock 入库 |

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
