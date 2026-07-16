# 后端 API 层架构说明

`app/` 是 TradingAgents-CN 的 FastAPI 后端 API 层，负责 HTTP 接口、认证鉴权、任务编排、配置管理、数据同步、调度任务、通知和运行期基础设施接入。它向上服务 `frontend/`，向下调用 `tradingagents/` 核心分析库，并连接 MongoDB、Redis、APScheduler 等基础设施。

## 目录结构

```text
app/
├── main.py        # FastAPI 应用入口、路由注册、生命周期和调度初始化
├── routers/       # HTTP 路由层
├── services/      # 业务服务层
├── models/        # Pydantic 领域模型和响应模型
├── schemas/       # API Schema 补充定义
├── core/          # 配置、数据库、Redis、日志、限流和启动校验
├── middleware/    # 请求日志、操作日志、CORS、Request ID 等中间件
├── worker/        # 数据同步、初始化和后台任务服务
├── utils/         # 后端工具函数
└── constants/     # 后端常量
```

## 核心文件说明

### 1. `main.py`

**职责**：FastAPI 应用装配入口。

**主要功能**：
- 创建 FastAPI 应用和生命周期 `lifespan`。
- 注册中间件、路由、健康检查和异常处理。
- 初始化 MongoDB、Redis、配置桥接和 APScheduler。
- 在应用关闭时释放调度器、数据库连接和用户服务资源。

**使用场景**：本地 `python -m app`、容器启动和部署入口。

---

### 2. `routers/`

**职责**：HTTP API 路由层，只处理请求参数、权限、响应结构和错误转换。

**主要模块**：
- `auth_db.py`：登录、刷新令牌、改密、用户管理。
- `analysis.py`：单股/批量分析任务、进度、WebSocket/SSE 相关接口。
- `reports.py`：报告列表、详情、模块内容和导出入口。
- `config.py`、`system_config.py`：模型、厂商、数据源、系统配置管理。
- `stocks.py`、`stock_data.py`、`multi_market_stocks.py`：股票行情、K 线、基本面和多市场查询。
- `scheduler.py`、`sync.py`、`stock_sync.py`：调度任务和数据同步控制。
- `database.py`、`cache.py`、`logs.py`：数据库、缓存和日志运维接口。

**使用建议**：路由函数不要承载复杂业务逻辑；复杂流程放到 `services/`。

---

### 3. `services/`

**职责**：后端业务流程层，连接路由、核心库、数据库和缓存。

**核心文件说明**：
- `simple_analysis_service.py`：主分析任务服务；创建任务、组装模型配置、调用 `tradingagents/graph/trading_graph.py`、保存报告和进度。
- `analysis_service.py`：分析服务的复用图实例版本；需要关注并发共享状态风险。
- `queue_service.py`：Redis 队列、用户并发限制、任务入队出队和状态管理。
- `scheduler_service.py`：APScheduler 任务注册、触发、历史记录和元数据维护。
- `config_service.py`：模型、数据源、系统配置、API Key、数据库配置的统一管理。
- `user_service.py`：用户创建、认证、密码哈希、角色和登录时间更新。
- `database_service.py`：数据库备份、导入导出、状态和集合统计。
- `stock_data_service.py`、`unified_stock_service.py`、`foreign_stock_service.py`：A 股、港股、美股查询和统一股票数据访问。
- `screening_service.py`、`enhanced_screening_service.py`、`database_screening_service.py`：选股字段、条件筛选和数据库筛选。
- `historical_data_service.py`、`financial_data_service.py`、`news_data_service.py`、`social_media_service.py`：历史行情、财务、新闻和社媒数据服务。
- `quotes_ingestion_service.py`、`quotes_service.py`：实时行情采集和行情查询。
- `notifications_service.py`、`internal_message_service.py`、`websocket_manager.py`：通知、站内消息和实时连接。
- `model_capability_service.py`、`usage_statistics_service.py`：模型能力校验和用量统计。
- `operation_log_service.py`、`log_export_service.py`：操作日志和日志导出。

**使用建议**：新增业务优先建服务类；路由只依赖服务公开方法。

---

### 4. `core/`

**职责**：后端基础能力。

**核心文件说明**：
- `config.py`：读取 `.env` 并提供运行配置。
- `database.py`：MongoDB、Redis 初始化、健康检查、索引和视图创建。
- `redis_client.py`：Redis JSON、计数、队列、锁和键名封装。
- `startup_validator.py`：启动配置校验和安全提示。
- `unified_config.py`、`config_compat.py`：统一配置读取和兼容旧配置。
- `rate_limiter.py`：外部数据源调用限流。
- `logging_config.py`、`logging_context.py`：日志格式和 trace 上下文。

---

### 5. `models/`

**职责**：后端领域模型和 API 数据结构。

**核心文件说明**：
- `user.py`：用户、认证、令牌和响应模型。
- `analysis.py`：分析任务、批次、参数和结果模型。
- `config.py`：系统配置、模型厂商、模型信息和数据库配置请求模型。
- `screening.py`：选股请求、筛选条件和字段信息模型。
- `stock_models.py`：股票基础信息和行情响应模型。
- `notification.py`：通知存储和输出模型。
- `operation_log.py`：操作日志创建和响应模型。

---

### 6. `worker/`

**职责**：后台同步、初始化和长任务执行。

**核心文件说明**：
- `analysis_worker.py`：消费队列并执行分析任务。
- `tushare_sync_service.py`、`akshare_sync_service.py`、`baostock_sync_service.py`：A 股数据源同步。
- `tushare_init_service.py`、`akshare_init_service.py`、`baostock_init_service.py`：数据源初始化。
- `multi_period_sync_service.py`：多周期行情同步编排。
- `financial_data_sync_service.py`、`news_data_sync_service.py`：财务和新闻同步。
- `hk_data_service.py`、`hk_sync_service.py`、`us_data_service.py`、`us_sync_service.py`：港股/美股数据服务和同步。

## 四层协作边界

后端 API 层对外提供 HTTP/SSE/WebSocket 接口，对内调用 `tradingagents/` 执行分析。它可以访问 MongoDB、Redis 和调度器，但不应把前端展示逻辑写入服务层，也不应在 `tradingagents/` 核心库中反向依赖 `app/`。

## 开发建议

1. 新接口：先建或复用 `services/` 方法，再在 `routers/` 暴露 API。
2. 新模型：放在 `models/`，避免在路由文件里散落大型 Pydantic 类。
3. 新后台任务：放入 `worker/` 或 `services/`，由 `scheduler_service.py` 或 `main.py` 生命周期接入。
4. 涉及配置读取时优先使用 `app/core/config.py` 和统一配置服务，避免散落读取环境变量。
