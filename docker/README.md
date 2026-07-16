# 基础设施层架构说明

`docker/` 是 TradingAgents-CN 基础设施层的容器配置入口之一。基础设施层不只包含本目录，还包括根目录 Dockerfile、`docker-compose*.yml`、`nginx/`、`scripts/`、`.env`、MongoDB、Redis、APScheduler 和部署文档。它负责把前端、后端、数据库、缓存、反向代理和运维脚本组合成可运行环境。

## 目录和文件结构

```text
docker/
├── nginx.conf          # Docker 场景下的 Nginx 配置片段

../nginx/
└── nginx.conf          # 前端静态资源和后端 API 反向代理配置

../scripts/
├── docker/             # Docker 服务启动、停止和 mongo-init.js
├── installer/          # Windows 安装版 start_all/stop_all/setup 脚本
├── portable/           # 便携版停止脚本
├── startup/            # 本地后端、前端、Web、调试服务启动脚本
├── setup/              # 数据库集合、索引、初始化和依赖安装脚本
├── deployment/         # 打包、发布、嵌入式 Python 和便携版构建脚本
├── maintenance/        # 数据修复、索引优化、版本和目录维护脚本
└── validation/         # 环境、依赖和数据校验脚本
```

## 核心组件说明

### 1. Docker Compose

**职责**：编排前端、后端、MongoDB、Redis 和 Nginx 等服务。

**主要文件**：
- `docker-compose.yml`：本地容器化启动主入口。
- `docker-compose.hub*.yml`：镜像仓库部署形态。
- `Dockerfile.backend`：构建 FastAPI 后端镜像。
- `Dockerfile.frontend`：构建 Vue 前端镜像。
- `Dockerfile.nginx`：构建 Nginx 静态资源和反向代理镜像。

**使用场景**：完整容器化部署、演示环境、生产近似环境。

---

### 2. Nginx

**职责**：前端静态资源服务和 API 反向代理。

**主要文件**：
- `nginx/nginx.conf`：常规 Nginx 配置。
- `docker/nginx.conf`：Docker 场景使用的代理配置。

**主要功能**：
- 将前端 SPA 请求回退到 `index.html`。
- 将 `/api`、WebSocket 或 SSE 请求转发到后端。
- 统一处理压缩、缓存、跨服务访问和反向代理头。

---

### 3. MongoDB

**职责**：主要持久化存储。

**存储内容**：
- 用户、认证和偏好。
- 分析任务、批次、报告和通知。
- 系统配置、模型配置、数据源配置。
- 股票基础信息、行情、历史数据、财务数据和新闻数据。

**相关代码**：
- `app/core/database.py`：后端 MongoDB 连接、索引和视图初始化。
- `tradingagents/config/database_manager.py`：核心库侧数据库可用性和缓存后端选择。
- `scripts/import_config_and_create_user.py`：导入系统配置并创建默认用户。
- `scripts/setup/init_mongodb_indexes.py`：初始化 MongoDB 索引。

---

### 4. Redis

**职责**：缓存、队列、锁和进度状态。

**存储内容**：
- 分析任务队列和处理集合。
- 任务进度、批次进度和实时状态。
- 限流计数、会话和临时缓存。
- 分布式锁和调度辅助状态。

**相关代码**：
- `app/core/redis_client.py`：Redis 连接、键名封装和服务对象。
- `app/services/queue_service.py`：任务队列服务。
- `app/services/progress/tracker.py`：分析进度跟踪。
- `tradingagents/dataflows/cache/db_cache.py`：核心数据缓存。

---

### 5. APScheduler

**职责**：后端进程内定时任务调度。

**主要任务**：
- 股票基础信息同步。
- 实时行情、历史行情和多周期数据同步。
- 财务数据、新闻数据和数据源状态检查。

**相关代码**：
- `app/main.py`：应用启动时创建调度器和注册任务。
- `app/services/scheduler_service.py`：调度元数据、触发、历史和统计。
- `app/worker/*_sync_service.py`：具体同步任务实现。

---

### 6. 脚本体系

**职责**：安装、启动、停止、初始化、迁移、校验和维护。

**常用目录**：
- `scripts/docker/`：Docker 容器服务启动和停止。
- `scripts/startup/`：源码方式启动后端、前端或 Web 辅助界面。
- `scripts/setup/`：初始化数据库集合、索引和系统数据。
- `scripts/installer/`、`scripts/portable/`：Windows 安装版和便携版运行脚本。
- `scripts/maintenance/`：数据库修复、索引优化、日志和版本维护。
- `scripts/validation/`：依赖、导入、数据结构和系统状态验证。

## 四层协作边界

基础设施层负责运行环境和外部服务，不承载业务规则。业务逻辑应位于 `app/` 或 `tradingagents/`；前端展示应位于 `frontend/`；部署脚本只负责启动、停止、初始化和运维动作。

## 常用命令

```bash
# Docker 启动
docker compose up --build

# Docker 停止
docker compose down

# Windows Docker 辅助脚本
scripts\docker\start_docker_services.bat
scripts\docker\stop_docker_services.bat

# 本地源码安装后的配置导入
python scripts/import_config_and_create_user.py --host
```

## 开发建议

1. 修改服务端口时同步检查 `.env`、`docker-compose*.yml`、`nginx/` 和前端 `VITE_API_BASE_URL`。
2. MongoDB/Redis 数据结构调整应配套迁移脚本和回滚说明。
3. 新增定时任务应同时补充 `app/services/scheduler_service.py` 元数据，方便前端管理。
4. 停止脚本谨慎使用按进程名强杀的方式，避免影响同机其它 Python、MongoDB 或 Redis 进程。
