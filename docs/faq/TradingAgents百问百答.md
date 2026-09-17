# TradingAgents 百问百答

> 更新日期：2026-09-15

## 1. 项目中的 AKShare 数据源是什么？

AKShare 不是项目内置的一份本地数据库，而是一个开源 Python 金融数据接口库。TradingAgents-CN 通过 AKShare SDK 调用公开互联网金融接口，并将获取到的数据转换为项目统一使用的格式。

项目中的 AKShare 主要提供以下数据：

- A 股股票代码和名称列表；
- 实时行情和个股盘口；
- 日线、周线、月线及分钟级 K 线；
- 主要财务指标、资产负债表、利润表和现金流量表；
- 个股新闻、市场新闻和上市公司公告；
- 部分港股数据支持。

从当前源码可以明确看到，AKShare 接入的数据上游包括：

- 东方财富：实时行情、个股盘口、财务报表、个股新闻和公告等；
- 新浪财经：A 股实时行情备用接口；
- 央视：市场新闻接口；
- AKShare 封装的其他公开金融数据接口。

因此，AKShare 本身更像一个“公开金融数据聚合与标准化工具”，并不是证券交易所官方行情服务。它免费且无需 Tushare Token，但公开接口可能受到网页改版、反爬策略、网络状况和访问频率限制的影响。项目为此增加了超时、重试、缓存、请求延迟和限流处理。

在中国市场数据源管理中，默认远程数据源顺序为：

```text
AKShare → Tushare → BaoStock
```

MongoDB 本地缓存的读取优先级更高。如果缓存中已有可用数据，实际查询不一定会访问 AKShare。默认数据源也可以通过 `DEFAULT_CHINA_DATA_SOURCE` 配置进行调整。

主要实现位置：

- `tradingagents/dataflows/providers/china/akshare.py`：核心统一数据提供器；
- `app/services/data_sources/akshare_adapter.py`：FastAPI 服务层数据源适配器；
- `tradingagents/dataflows/data_source_manager.py`：数据源选择、调用与降级逻辑；
- `tradingagents/constants/data_sources.py`：数据源元数据定义；
- `tradingagents/config/providers_config.py`：AKShare 超时、重试和缓存配置。

## 2. AKShare 是什么公司开发的？

AKShare 不是东方财富、新浪财经等数据上游公司开发的产品，也不是一家名为“AKShare”的商业公司提供的服务。

它是由 **AKFamily 开源团队及社区**开发和维护的开源项目，源码托管在 GitHub：

- <https://github.com/akfamily/akshare>

TradingAgents-CN 的数据源定义中也将 AKShare 的提供方标记为 `AKFamily`。

需要区分两个概念：

- **开发维护方**：AKFamily 开源团队及社区；
- **数据上游方**：东方财富、新浪财经、央视等公开金融数据网站或接口。

## 3. 使用手册中的“执行一次单股同步测试”是什么功能，怎么操作？

“单股同步测试”不是单元测试，而是针对一只股票执行一次真实的数据同步冒烟测试，用于确认以下链路是否正常：

- 数据源接口是否可访问；
- 股票行情、历史数据、财务数据或基础数据是否能正常获取；
- 数据转换和字段标准化是否正常；
- 数据是否成功写入 MongoDB；
- 主数据源失败时，回退数据源是否生效。

这项操作会产生实际的数据写入，不建议把它理解为“只读检查”。

### 页面操作步骤

1. 启动后端和前端并登录系统。
2. 打开一只 A 股的股票详情页，例如 `000001`。港股和美股详情页当前不显示“同步数据”按钮。
3. 点击右上角的“同步数据”。
4. 在弹窗中选择同步内容：
   - 实时行情；
   - 历史行情数据；
   - 财务数据；
   - 基础数据。
5. 选择数据源 `Tushare` 或 `AKShare`。如果勾选了历史行情，还需要设置历史数据天数，范围为 1～3650 天。
6. 点击“开始同步”。
7. 查看结果弹窗，确认各项成功状态、实际使用的数据源、错误原因，以及行情是否写入 `market_quotes`。

第一次验证建议只勾选“实时行情”，并选择 `AKShare`，这样请求范围小，便于快速判断数据源和数据库写入是否正常。

### 一个容易混淆的行为

页面默认选择的是“实时行情”和 `Tushare`，但后端对单股实时行情做了特殊处理：

1. 如果请求数据源是 Tushare，系统会先自动切换到 AKShare，以避免 Tushare 单股接口限制；
2. 如果 AKShare 单股同步失败，系统会回退到 Tushare 全量实时同步；
3. 结果弹窗会展示实际使用的数据源、尝试过的数据源和主链路/回退链路错误。

因此，页面上选择的“请求数据源”不一定等于最终实际使用的数据源。

### 同步内容与落库位置

| 同步内容 | 主要作用 | 典型落库位置 |
| --- | --- | --- |
| 实时行情 | 获取当前或最近可用的行情快照 | `market_quotes` |
| 历史行情 | 按指定天数同步日线等历史记录 | 历史行情集合，并将最新记录择优同步到 `market_quotes` |
| 财务数据 | 获取财务指标、资产负债表、利润表、现金流量表等 | 财务数据集合 |
| 基础数据 | 获取股票名称、市场、行业等基础信息 | `stock_basic_info` |

### 通过接口操作

前端调用的接口是：

```http
POST /api/stock-sync/single
```

例如，只测试股票 `000001` 的 AKShare 实时行情：

```json
{
  "symbol": "000001",
  "sync_realtime": true,
  "sync_historical": false,
  "sync_financial": false,
  "sync_basic": false,
  "data_source": "akshare",
  "days": 30
}
```

该接口需要登录认证。页面操作更适合日常使用，因为页面会自动显示同步明细，并在完成后刷新行情和基本面数据。

相关源码位置：

- `frontend/src/views/Stocks/Detail.vue`：同步按钮、弹窗和结果展示；
- `frontend/src/api/stockSync.ts`：单股同步接口封装；
- `app/routers/stock_sync.py`：单股同步 API 及落库逻辑；
- `app/worker/akshare_sync_service.py`：AKShare 行情和历史数据同步服务。
