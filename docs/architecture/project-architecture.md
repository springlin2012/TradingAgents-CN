# TradingAgents-CN 当前项目架构分析

> 基于 Serena MCP 对当前仓库的目录、符号和关键调用链分析生成。本文描述代码现状，便于新贡献者快速理解系统边界和主要数据流。

## 1. 总体架构

TradingAgents-CN 是一个面向股票研究与学习场景的多智能体分析平台。当前架构由四层组成：

1. **前端交互层**：`frontend/` 提供 Vue 3 + Vite + Element Plus 单页应用；`web/` 保留 Streamlit 风格的辅助界面与工具模块。
2. **后端 API 层**：`app/` 基于 FastAPI，负责认证、任务提交、报告、配置、数据同步、通知、调度和系统管理接口。
3. **智能体分析核心层**：`tradingagents/` 承载 LangGraph 多智能体工作流、LLM 适配器、数据工具和分析节点。
4. **基础设施层**：MongoDB 存储任务、用户、配置和业务数据；Redis 用于缓存、队列、锁和进度；APScheduler 负责周期数据同步；Docker/Nginx 支撑部署。

核心分析链路是：前端提交分析请求 -> FastAPI 路由 -> 分析服务创建任务 -> 构建 `TradingAgentsGraph` -> LangGraph 执行多智能体节点 -> 保存报告、状态和通知。

## 2. 目录结构

| 路径 | 职责 |
| --- | --- |
| `app/main.py` | FastAPI 应用入口，注册中间件、生命周期、路由和调度任务 |
| `app/routers/` | HTTP API 路由，覆盖分析、报告、配置、股票、同步、调度、通知等模块 |
| `app/services/` | 后端业务服务，包含分析任务、配置、数据库、缓存、同步、筛选、通知等 |
| `app/core/` | 配置、数据库、Redis、日志、启动校验等基础能力 |
| `app/worker/` | Tushare、AKShare、BaoStock、新闻、财务和多周期数据同步任务 |
| `tradingagents/graph/` | LangGraph 工作流编排，核心类为 `TradingAgentsGraph` 和 `GraphSetup` |
| `tradingagents/agents/` | 分析师、研究员、交易员、风险辩论和管理节点 |
| `tradingagents/dataflows/` | 股票、新闻、基本面、行情和多数据源适配层 |
| `tradingagents/llm_clients/`、`tradingagents/llm_adapters/` | 多厂商 LLM 创建与兼容适配 |
| `frontend/src/` | Vue 前端源码，包含 API、路由、状态、视图、组件和样式 |
| `web/` | 旧版/辅助 Web 入口与工具模块 |
| `tests/` | pytest 测试、集成测试、诊断脚本 |
| `docs/`、`scripts/`、`docker/` | 文档、脚本和部署资源 |

## 3. 后端 API 层

`app/main.py` 是后端主入口。它创建 FastAPI 应用，配置：

- `lifespan` 生命周期：启动日志、校验配置、初始化 APScheduler，并在关闭时释放调度器和数据库连接。
- 中间件：CORS、操作日志、请求日志、Request ID；非调试模式启用 Trusted Host。
- 路由：集中注册健康检查、认证、分析、报告、筛选、股票、配置、数据库、缓存、日志、通知、SSE、调度、多数据源同步、初始化任务等。

接口分层大致为：

- `app/routers/*` 处理请求参数、权限和响应结构。
- `app/services/*` 执行业务流程和持久化。
- `app/core/*` 提供数据库、Redis、配置和日志基础能力。
- `app/worker/*` 承载可被调度器或接口触发的长任务。

## 4. 分析任务执行链路

分析服务主要集中在：

- `app/services/simple_analysis_service.py`
- `app/services/analysis_service.py`

当前更强调并发安全的链路在 `SimpleAnalysisService` 中。其关键流程：

1. 接收单股分析请求并创建任务。
2. 校验股票代码和市场类型。
3. 创建 Redis 进度跟踪器，并同步任务状态到内存/数据库。
4. 调用 `create_analysis_config()` 组装研究深度、分析师列表、模型、厂商、API Key、Base URL、辩论轮次和风险讨论轮次。
5. 每次任务创建新的 `TradingAgentsGraph`，避免共享图实例中的可变状态。
6. 执行分析后保存完整报告、模块化报告、任务状态和通知。

`AnalysisService` 也提供分析能力，但其 `_get_trading_graph()` 会按配置缓存 `TradingAgentsGraph`。与 `SimpleAnalysisService` 相比，它更偏复用实例；在并发场景下应优先关注共享状态风险。

## 5. 多智能体核心

`tradingagents/graph/trading_graph.py` 中的 `TradingAgentsGraph` 是分析核心。初始化时它会：

- 根据配置创建快速模型和深度模型。
- 支持 OpenAI、Google、Qwen、DeepSeek、Anthropic、AiHubMix、OpenRouter、SiliconFlow、Ollama、千帆、智谱和自定义 OpenAI 兼容端点。
- 初始化 `Toolkit` 数据工具。
- 可选初始化 ChromaDB 记忆组件。
- 创建条件逻辑、传播器、反思器和信号处理器。
- 通过 `GraphSetup.setup_graph()` 编译 LangGraph。

`GraphSetup.setup_graph()` 的执行图顺序为：

```text
Selected Analysts
  -> Bull Researcher <-> Bear Researcher
  -> Research Manager
  -> Trader
  -> Risky Analyst -> Safe Analyst -> Neutral Analyst
  -> Risk Judge
  -> END
```

其中分析师节点可按请求选择，例如 `market`、`social`、`news`、`fundamentals`。每个分析师节点通过条件边决定是否调用工具节点，再清理消息并进入下一节点。

`TradingAgentsGraph.propagate()` 负责实际运行图。它创建初始状态，使用 `graph.stream()` 流式执行节点，记录每个节点耗时，发送进度回调，最终生成 `final_state` 和交易决策。

## 6. 数据源与缓存

数据源层位于 `tradingagents/dataflows/`，核心是 `DataSourceManager` 和 provider 体系：

- `providers/base_provider.py` 定义股票数据 Provider 抽象能力。
- `providers/china/` 提供 Tushare、AKShare、BaoStock 等 A 股数据适配。
- `providers/hk/`、`providers/us/` 分别覆盖港股和美股数据。
- `data_source_manager.py` 负责数据源优先级、当前数据源切换、MongoDB 缓存读取、外部数据回退和响应格式化。

缓存体系包括：

- `app/core/database.py`：MongoDB 与 Redis 初始化、健康检查、索引和视图创建。
- `app/core/redis_client.py`：JSON 缓存、计数、队列、集合和分布式锁。
- `tradingagents/dataflows/cache/`：文件缓存、MongoDB 缓存、集成缓存和自适应缓存。

整体策略是优先复用本地/数据库缓存，必要时调用外部数据源，并在失败时尝试回退数据源。

## 7. 调度与后台任务

后端启动时在 `app/main.py` 的生命周期中初始化 `AsyncIOScheduler`。调度任务覆盖：

- 股票基础信息同步。
- 实时行情/日 K/历史数据同步。
- 财务数据同步。
- 数据源状态检查。
- 新闻数据同步。
- 行情摄取服务。

Tushare、AKShare、BaoStock 等数据源都有独立 worker，任务是否启用由配置开关和 cron 表达式控制。调度器实例会注入到 `scheduler_service`，供 API 层查询或管理。

## 8. 前端架构

`frontend/src/main.ts` 创建 Vue 应用，注册 Pinia、Vue Router、Element Plus、图标和全局样式。主要结构：

- `api/`：Axios 请求封装，`VITE_API_BASE_URL` 控制后端地址，统一处理 token、错误和响应。
- `router/`：Vue Router 路由表，覆盖仪表盘、分析、股票详情、报告、配置、系统管理等页面。
- `stores/`：Pinia 状态，如 `auth`、`app`、`notifications`。
- `views/`：业务页面。
- `components/`：可复用组件。

前端通过 REST API、SSE/WebSocket 通知和轮询/状态接口与后端协作，长耗时分析任务由后端进度跟踪器驱动状态更新。

## 9. 部署与运行形态

仓库支持本地和容器两种运行方式：

- Python 依赖：`requirements.txt`、`requirements-lock.txt`、`uv.lock`。
- 前端依赖：`frontend/package.json`、`frontend/yarn.lock`。
- 容器部署：`Dockerfile.backend`、`Dockerfile.frontend`、`docker-compose.yml`、`docker-compose.hub.nginx.yml`、`nginx/`。
- 配置入口：`.env.example`、`app/core/config.py`、统一配置和数据库配置桥接模块。

常用命令：

```bash
pip install -r requirements.txt
python main.py
python -m pytest tests/

cd frontend
npm install
npm run dev
npm run build

docker compose up --build
```

## 10. 架构关注点

1. **分析图实例状态**：`TradingAgentsGraph` 持有 `ticker`、`curr_state` 等可变状态。并发分析应使用每任务独立实例，避免复用导致状态串扰。
2. **路由规模较大**：`app/main.py` 注册大量路由和启动任务，后续可考虑按领域拆分启动配置和路由装配逻辑。
3. **配置来源复杂**：模型、厂商、API Key、Base URL 可能来自数据库、模型配置、厂商配置或环境变量，排障时要明确优先级。
4. **数据源回退链路长**：MongoDB、Tushare、AKShare、BaoStock、US/HK providers 与缓存共同参与数据获取，问题定位需同时检查配置、缓存和外部接口。
5. **新旧 Web 并存**：`frontend/` 是现代 Vue 前端，`web/` 仍包含运行入口和工具模块。新增功能前应确认目标入口，避免重复实现。

## 11. 建议阅读顺序

1. `app/main.py`：理解后端应用装配和调度启动。
2. `app/services/simple_analysis_service.py`：理解分析任务生命周期。
3. `tradingagents/graph/trading_graph.py`：理解图实例、LLM 和执行入口。
4. `tradingagents/graph/setup.py`：理解 LangGraph 节点和边。
5. `tradingagents/dataflows/data_source_manager.py`：理解数据源选择和回退。
6. `frontend/src/api/request.ts` 与 `frontend/src/router/index.ts`：理解前端请求和页面结构。
