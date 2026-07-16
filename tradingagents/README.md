# 智能体分析核心层架构说明

`tradingagents/` 是 TradingAgents-CN 的核心分析库，负责 LangGraph 多智能体工作流、LLM 适配、股票和新闻数据工具、记忆组件、信号处理和最终交易决策生成。它是相对独立的核心层，应尽量避免反向依赖 `app/` 后端 API 层。

## 目录结构

```text
tradingagents/
├── graph/          # LangGraph 工作流编排
├── agents/         # 分析师、研究员、交易员、风险管理和管理层节点
├── dataflows/      # 股票、新闻、行情、基本面和多数据源访问
├── tools/          # Agent 可调用工具
├── llm_clients/    # LLM 客户端工厂和模型目录
├── llm_adapters/   # OpenAI 兼容和厂商适配器
├── config/         # 核心库配置、数据库配置和用量统计
├── models/         # 核心数据模型
├── constants/      # 数据源等常量
├── api/            # 简化 API 封装
└── utils/          # 日志、股票识别、记忆和数据流工具
```

## 核心模块说明

### 1. `graph/`

**职责**：多智能体工作流编排和执行控制。

**核心文件说明**：
- `trading_graph.py`：核心入口；初始化 LLM、Toolkit、记忆组件和 LangGraph，并执行 `propagate()` 分析流程。
- `setup.py`：构建 LangGraph 节点和边，连接分析师、研究员、交易员、风险管理和管理层。
- `conditional_logic.py`：定义工具调用、辩论轮次、风险讨论和节点跳转条件。
- `signal_processing.py`：从最终状态中提取交易信号和决策。
- `reflection.py`：处理反思、总结和迭代优化逻辑。
- `propagation.py`：封装图传播过程中的状态推进能力。

**典型链路**：

```text
Selected Analysts
  -> Bull/Bear Research
  -> Research Manager
  -> Trader
  -> Risk Debate
  -> Risk Judge
  -> Final Signal
```

---

### 2. `agents/`

**职责**：定义各类智能体节点、状态结构、记忆和工具处理。

**主要分组**：
- `analysts/`：市场、基本面、新闻、社媒等分析师节点。
- `researchers/`：看涨和看跌研究员，围绕分析师结论进行辩论。
- `trader/`：交易员节点，生成交易计划。
- `risk_mgmt/`：保守、中性、激进风险分析和风险裁决。
- `managers/`：研究经理和风险经理，负责聚合辩论结论。
- `utils/`：状态定义、记忆管理、Google 工具调用处理等基础能力。

**核心文件说明**：
- `utils/agent_states.py`：LangGraph 主状态、投资辩论状态和风险辩论状态定义。
- `utils/chromadb_config.py`：智能体记忆向量存储管理。
- `utils/memory.py`：金融场景记忆检索和写入。
- `utils/google_tool_handler.py`：Google 模型工具调用兼容处理。

---

### 3. `dataflows/`

**职责**：统一数据访问、缓存、多数据源回退和格式化输出。

**核心文件说明**：
- `data_source_manager.py`：A 股数据源优先级、自动回退、缓存读取和格式化。
- `optimized_china_data.py`：A 股缓存数据和基本面报告生成。
- `stock_data_service.py`：股票基本信息查询和 MongoDB 到备用数据源降级。
- `data_completeness_checker.py`：数据完整性检查。
- `dataflows/cache/`：多层缓存实现。
- `dataflows/providers/`：Tushare、AKShare、BaoStock 等 A 股外部数据提供器。
- `dataflows/interface.py`、`stock_api.py`：统一数据访问接口。
- `realtime_news_utils.py`：实时新闻和中文财经情绪数据。
- `utils/dataflow_utils.py`：技术指标和数据流辅助能力。

**详细说明**：见 [dataflows/README.md](D:/workSpace/TradingAgents-CN/tradingagents/dataflows/README.md)。

---

### 4. `llm_clients/`

**职责**：LLM 客户端抽象、厂商选择和模型目录。

**核心文件说明**：
- `base_client.py`：LLM 客户端抽象基类。
- `openai_client.py`、`anthropic_client.py`、`google_client.py`：厂商客户端封装。
- `model_catalog.py`：维护已知模型和不同模式下的可选模型。
- `factory.py`：根据 provider、model、base_url 创建 LLM 实例。
- `validators.py`、`provider_keys.py`：模型名校验和 API Key 解析。

---

### 5. `llm_adapters/`

**职责**：兼容 OpenAI 协议的厂商适配。

**核心文件说明**：
- `openai_compatible_base.py`：OpenAI 兼容适配基类，统一 token 统计和调用参数。
- `deepseek_adapter.py`：DeepSeek 兼容适配。
- `dashscope_openai_adapter.py`：DashScope、Qianfan、Zhipu、Custom 等 OpenAI 兼容适配。
- `google_openai_adapter.py`：Google 模型的 OpenAI 风格适配。

---

### 6. `config/`

**职责**：核心库运行配置、缓存配置、数据库连接和用量统计。

**核心文件说明**：
- `config_manager.py`：模型、定价、token 使用记录和配置文件管理。
- `database_manager.py`：核心库侧 MongoDB/Redis 可用性、客户端和缓存后端选择。
- `mongodb_storage.py`：token 使用等数据的 MongoDB 持久化。
- `tushare_config.py`、`providers_config.py`、`database_config.py`：数据源和数据库配置封装。
- `usage_models.py`：用量、模型和价格数据结构。

---

### 7. `tools/`、`utils/`、`models/`

**职责**：Agent 工具、辅助能力和领域数据模型。

**核心文件说明**：
- `tools/unified_news_tool.py`：统一新闻分析工具。
- `utils/dataflow_utils.py`：技术指标规格和数据流辅助工具。
- `utils/stock_utils.py`、`utils/stock_validator.py`：股票代码市场识别、格式化和校验。
- `utils/logging_manager.py`、`utils/logging_init.py`：核心库日志管理。
- `utils/news_filter.py`、`utils/enhanced_news_filter.py`：新闻相关性过滤。
- `models/stock_data_models.py`：股票基础信息、日线、财务和新闻数据模型。

## 四层协作边界

核心层只关心分析、数据工具、模型适配和决策生成。它可以读取配置和访问数据源，但不应包含 FastAPI 路由、前端展示状态或部署脚本逻辑。后端 API 层应通过服务模块调用 `graph/trading_graph.py`，而不是让核心层反向调用 `app/`。

## 开发建议

1. 新分析节点放入 `agents/`，并在 `graph/setup.py` 接入节点和边。
2. 新数据源优先放入 `dataflows/providers/`，再由 `dataflows/data_source_manager.py` 或接口层统一暴露。
3. 新模型厂商优先扩展 `llm_clients/` 或 `llm_adapters/`，保持调用参数兼容。
4. 修改核心状态字段时同步检查 `agents/utils/agent_states.py`、图节点和报告保存逻辑。
