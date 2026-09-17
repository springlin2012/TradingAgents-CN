# TradingAgents-CN 开发问题解决指南

> 适用范围：当前 Vue + FastAPI + MongoDB 主应用，以及仓库中保留的旧版 Web/Streamlit 登录模块。
>
> 更新时间：2026-09-17

## 场景总览

| 场景 | 典型现象 | 处理章节 |
| --- | --- | --- |
| 场景一：正常登录后修改密码 | 已知当前密码，希望更换新密码 | [场景一](#场景一正常登录后修改密码) |
| 场景二：主应用无法登录 | `admin / admin123` 提示用户名或密码错误 | [场景二](#场景二主应用无法登录) |
| 场景三：管理员账号不存在 | 数据库更新结果 `matched=0` | [场景三](#场景三管理员账号不存在) |
| 场景四：脚本缺少依赖 | `No module named 'pymongo'` | [场景四](#场景四脚本缺少-pymongo-依赖) |
| 场景五：使用旧版 Web | 运行 `web/` 界面或 JSON 用户配置 | [场景五](#场景五旧版-webstreamlit-登录) |
| 场景六：密码已改仍失败 | 返回 401、连接错库、前端状态异常 | [场景六](#场景六密码已改仍无法登录) |
| 场景七：阿里云百炼 API 测试失败 | 厂家配置测试返回 HTTP 401，修改 `default_base_url` 后仍失败 | [场景七](#场景七阿里云百炼-api-测试返回-http-401) |

## 场景一：正常登录后修改密码

### 现象

可以使用当前账号登录，只是希望更换密码。

### 处理

1. 进入 `设置` → `安全设置`；
2. 点击 `修改密码`；
3. 输入当前密码、新密码和确认密码；
4. 保存后退出并重新登录。

主应用会先验证旧密码，再更新 MongoDB `users.hashed_password`。新密码至少 6 位，生产环境建议使用 12 位以上的随机密码。

## 场景二：主应用无法登录

### 现象

当前 Vue/FastAPI 主应用登录页提示“用户名或密码错误”，但可以连接目标 MongoDB，且已忘记 `admin` 当前密码。

### 判断依据

主应用请求 `/api/auth/login`，认证数据位于 MongoDB 当前数据库的 `users` 集合，不读取旧版 `web/config/users.json`。

### 处理

在项目根目录使用项目虚拟环境执行以下命令。新密码通过交互输入，不写入命令历史：

```powershell
.\.venv\Scripts\python.exe -c 'import getpass,hashlib; from pymongo import MongoClient; from app.core.config import settings; p=getpass.getpass("新密码: "); db=MongoClient(settings.MONGO_URI)[settings.MONGO_DB]; r=db.users.update_one({"username":"admin"},{"$set":{"hashed_password":hashlib.sha256(p.encode()).hexdigest()}}); print(f"matched={r.matched_count}, modified={r.modified_count}")'
```

### 结果

- `matched=1, modified=1`：密码已更新，可重新登录；
- `matched=0`：当前数据库没有 `admin`，转到[场景三](#场景三管理员账号不存在)；
- `modified=0`：可能输入了原密码，或数据库连接/权限异常。

执行前必须核对 `.env` 的 MongoDB 主机、数据库名和认证源，避免误改共享环境。

## 场景三：管理员账号不存在

### 现象

使用默认账号 `admin / admin123` 登录时，后端返回 HTTP 401。

### 根因

后端实际连接的 `tradingagentscn` 数据库中，`users` 集合为空，默认管理员账号并未创建。因此，登录请求无法匹配有效用户，即使输入默认账号和密码也会返回 HTTP 401。

### 解决过程

在确认后端连接的数据库实例和数据库名称无误后，创建默认管理员账号，并确保账号处于启用状态且具有管理员权限：

- 用户名：`admin`
- 密码：`admin123`
- 账号状态：启用
- 管理员权限：已启用

### 本次实际创建方式

本次没有通过前端注册，也没有运行旧版 `scripts/create_default_admin.py`。该旧脚本使用固定的本机 MongoDB 连接参数，可能把账号创建到与当前后端不同的数据库。

实际使用项目虚拟环境执行一次性 Python 初始化命令，通过 `app.core.config.settings` 读取后端当前生效的 MongoDB 配置，再调用 `UserService.create_admin_user()`：

```powershell
@'
import asyncio
from app.core.config import settings
from app.services.user_service import UserService

service = UserService()
user = asyncio.run(service.create_admin_user(
    username="admin",
    password="admin123",
    email="admin@tradingagents.cn",
))
print("created_admin=", bool(user))
service.close()
'@ | .\.venv\Scripts\python.exe -
```

该方法会先检查 `users` 集合中的 `admin` 用户；仅在用户不存在时创建，不会覆盖已有账号。密码按主应用当前规则以 SHA-256 摘要保存。

本次实际连接的是后端配置对应的 `tradingagentscn` 数据库，创建后通过 `POST /api/auth/login` 使用 `admin / admin123` 验证，返回 HTTP 200 和有效访问令牌。

### 验证结果

重新调用登录接口，验证结果如下：

- HTTP 状态码：`200`
- 接口返回有效访问令牌

至此确认默认管理员账号已创建成功，认证流程恢复正常。

### 风险提示

- 创建账号前必须核对后端实际使用的 MongoDB 主机、数据库和认证源，避免将账号写入错误数据库。
- `admin123` 仅适合作为本地开发环境的初始密码，首次登录后应立即修改；生产环境禁止使用默认密码。
- 如果脚本提示用户已存在，不要直接追加 `--overwrite`。该参数会先删除旧用户再重建，可能造成用户属性、关联记录或会话信息丢失；如确需覆盖，必须由具备权限的人工流程确认。

## 场景四：脚本缺少 `pymongo` 依赖

### 现象

执行管理员脚本时出现：

```text
ModuleNotFoundError: No module named 'pymongo'
```

### 原因

运行脚本的 Python 解释器没有安装项目依赖。Windows 中直接输入 `python` 可能调用系统 Python，而不是项目虚拟环境；这不是密码参数错误。

### 处理步骤

先确认解释器和依赖是否对应：

```powershell
python --version
python -m pip show pymongo
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip show pymongo
```

若 `.venv` 中已有 `pymongo`，使用它运行脚本：

```powershell
.\.venv\Scripts\python.exe scripts/create_default_admin.py --username admin --password "你的新密码"
```

或先激活虚拟环境：

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip show pymongo
python scripts/create_default_admin.py --username admin --password "你的新密码"
```

若必须使用系统 Python，安装依赖：

```powershell
python -m pip install "pymongo>=4.0.0"
```

项目依赖声明位于 `pyproject.toml`、`requirements.txt` 和 `requirements-lock.txt`。必须确保 `python -m pip` 与运行脚本的 `python` 是同一个解释器。

缺少依赖时不要改用 `--overwrite`；如果 `admin` 已存在，应回到[场景二](#场景二主应用无法登录)使用定向更新。

## 场景五：旧版 Web/Streamlit 登录

### 现象

实际运行的是 `web/` 下的旧版界面，或修改 MongoDB 后旧 Web 仍不能登录。

### 处理

```powershell
.\.venv\Scripts\python.exe scripts/user_password_manager.py change-password admin "你的新密码"
```

该命令只修改 `web/config/users.json`，不会修改主应用的 MongoDB 密码。旧版默认账号通常是 `admin / admin123`，普通用户通常是 `user / user123`。

## 场景六：密码已改仍无法登录

### 6.1 接口或前端服务不一致

主应用应请求：

```text
http://localhost:8000/api/auth/login
```

不要误请求旧接口或旧前端服务。密码修改后，退出登录并重新打开页面；必要时清理当前站点本地存储后刷新。

### 6.2 数据库环境不一致

核对 `.env` 中的：

- `MONGODB_HOST`、端口和认证源；
- `MONGODB_DATABASE`；
- `MONGODB_DATABASE_SCOPE` 的实际生效值；
- `scripts/create_default_admin.py` 内置连接参数。

连接错数据库时，即使密码哈希正确也会登录失败。

### 6.3 用户记录或字段不一致

在目标数据库 `users` 集合中确认：

- 存在 `username=admin`；
- `is_active=true`；
- 主应用字段为 `hashed_password`；
- 主应用密码算法为 SHA-256。

旧版 Web 使用 `web/config/users.json` 和 `password_hash`，不能与主应用的 MongoDB 用户记录混用。

### 6.4 接口验证

```powershell
$body = @{ username = "admin"; password = "你的新密码" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/auth/login" -ContentType "application/json" -Body $body
```

成功响应应包含 `success: true` 和 `data.access_token`。后端日志重点区分“用户不存在”“密码错误”“数据库连接失败”。

## 场景七：阿里云百炼 API 测试返回 HTTP 401

### 7.1 现象与结论

在厂家配置页面测试阿里云百炼 API 时返回：

```text
阿里云百炼 API测试失败: HTTP 401
```

排查期间，MongoDB 中 DashScope 厂家的 `default_base_url` 已修改为：

```text
https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
```

本次厂家测试使用的模型为 `qwen3.6-flash`。已有日志返回 `invalid_api_key`，说明请求在认证阶段失败，早于正常的模型可用性判断，因此模型名称不是本次故障的首要原因。

核心结论是：厂家测试入口虽然读取了 MongoDB 的 `default_base_url`，但 DashScope 分支没有把该值传入实际测试方法；同时，排查时运行中的后端早于相关源码修改启动，没有加载最新实现。修改数据库地址并不能单独解决问题，仍需确认实际请求端点与 API Key 是否匹配。

### 7.2 配置与数据类问题

#### MongoDB 配置在哪个集合

MongoDB 中没有关系数据库的“表”，对应概念是集合。DashScope 厂家配置位于：

```text
集合：llm_providers
文档条件：name = "dashscope"
地址字段：default_base_url
模型字段：test_model
密钥字段：api_key
```

配置结构示例：

```json
{
  "name": "dashscope",
  "api_key": "已脱敏",
  "test_model": "qwen3.6-flash",
  "default_base_url": "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
}
```

`default_base_url` 只能保存纯 URL，不应包含中文标点、“请帮我替换”等说明文字。厂家测试优先使用 MongoDB 中通过基础格式校验的 `api_key`；只有数据库 Key 无效时才回退环境变量。因此，只修改 `.env` 不一定会改变实际请求所用的 Key。

### 7.3 代码实现类问题

厂家默认配置和初始化逻辑主要位于：

```text
app/scripts/init_providers.py
```

厂家 API 测试、MongoDB 配置读取及 DashScope 请求实现主要位于：

```text
app/services/config_service.py
app/services/config_service.py::_test_dashscope_api
```

测试入口会读取：

```python
base_url = provider_data.get("default_base_url")
test_model = provider_data.get("test_model")
```

但进入 DashScope 分支时只传递了 API Key、厂家显示名称和测试模型，没有把 `base_url` 传给 `_test_dashscope_api()`。因此，即使 MongoDB 中的地址保存成功，当前厂家测试也不会消费该字段。工作树中的请求地址曾直接硬编码为 `token-plan` 专属地址，修改前则使用公共地址：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions
```

建议把 `base_url` 作为明确的关键字参数传入，优先使用厂家配置，未配置时回退公共地址，并规范尾部斜杠：

```python
base_url = (
    base_url
    or "https://dashscope.aliyuncs.com/compatible-mode/v1"
).rstrip("/")
url = f"{base_url}/chat/completions"
```

使用关键字参数可避免后续扩展时把 `test_model` 与 `base_url` 等位置参数传错。

### 7.4 服务运行与部署类问题

排查时后端进程与源码时间如下：

```text
后端启动命令：python -m app
后端启动时间：2026-09-15 18:06:21
相关源码修改时间：2026-09-17 16:52:23
```

后端启动时间早于源码修改时间。如果没有启用并触发热重载，运行进程仍会执行启动时加载的旧实现，可能继续请求公共 DashScope 地址。数据库配置读取、代码参数传递和运行进程版本应分别验证，不能把数据库修改与源码修改混为一谈。修改代码后必须重启后端，再进行厂家测试。

### 7.5 API 认证与端点匹配类问题

历史错误日志中存在阿里云返回的完整错误：

```text
HTTP 401
code: invalid_api_key
message: Incorrect API key provided.
request_id: 9d22bb3e-202e-9769-9612-cf68df74f121
```

该日志来自分析请求，不一定与本次点击“厂家测试”是同一条请求，但能证明系统中实际使用过的某个阿里云 API Key 曾被服务端判定无效。本地格式校验通过只代表字符串形式正常，并不代表阿里云认证成功。常见原因包括：

1. Coding Plan 或专属套餐 Key 被旧进程发送到公共 DashScope 地址；
2. API Key 与北京地域 `token-plan` 实例不匹配；
3. API Key 所属账号或 Workspace 与当前实例不一致；
4. API Key 已撤销、过期或复制不完整；
5. MongoDB 中保存的并非预期的专属 Key。

根据现有证据，根因优先级为：

1. 运行中的后端没有加载源码修改；
2. DashScope 厂家测试没有使用 MongoDB 的 `default_base_url`；
3. 实际 API Key 与端点、地域、账号或 Workspace 不匹配，或者 Key 已失效；
4. Coding Plan 专属 Key 被旧进程发往公共端点。

### 7.6 日志与可观测性类问题

当前厂家测试在非 200 响应时只显示 HTTP 状态码，没有记录实际 URL、测试模型、阿里云 `error.code`、`error.message` 和 `request_id`。因此，仅凭页面上的 HTTP 401 无法确认请求命中了公共地址还是 `token-plan` 专属地址。

建议安全记录以下内容：

- 实际请求 URL 或 Host；
- 测试模型和配置来源；
- HTTP 状态码；
- 阿里云错误码、错误消息和 `request_id`。

不得记录完整 API Key 或 Authorization 请求头。

### 7.7 自动化测试与验证类问题

修复代码时应补充以下验证：

1. MongoDB 自定义 `default_base_url` 被 DashScope 厂家测试实际使用；
2. 带或不带尾部 `/` 的地址都能正确拼接；
3. 未配置自定义地址时回退公共 DashScope 地址；
4. `test_model` 与 `base_url` 独立、正确传递；
5. HTTP 401 的诊断信息完整且不泄露 API Key。

### 7.8 建议处理顺序

1. 确认 MongoDB `llm_providers` 集合中 `name = "dashscope"` 文档的地址只包含正确 URL；
2. 修复 DashScope 测试调用，使 `default_base_url` 真正传入 `_test_dashscope_api()`；
3. 重启 `python -m app` 后端，使最新代码生效；
4. 重新执行厂家 API 测试并记录脱敏后的实际 URL、模型、错误码和 `request_id`；
5. 确认 MongoDB 中的 API Key 属于北京地域对应的 Coding Plan 或专属实例；
6. 若仍返回 `invalid_api_key`，继续核对 Key 的账号、Workspace、地域及有效状态。

## 共性背景：默认值和认证链路

- 新部署初始化通常使用 `admin / admin123`；
- 登录页的默认提示只是初始化约定，不代表数据库中一定存在该用户；
- `config/admin_password.json` 属于旧初始化兼容配置，修改它不会自动更新已有 MongoDB 用户；
- 文档中出现的 `1234567` 是历史配置说明，不能作为当前密码判断依据；
- 当前主应用登录处理位于 `app/routers/auth_db.py`，密码校验和修改位于 `app/services/user_service.py`；
- 密码哈希方法为 `UserService.hash_password`，算法是 SHA-256。

## 安全边界

- 生产环境首次登录后立即更换默认密码；
- 新密码不要与 MongoDB、Redis、JWT 密钥或操作系统密码复用；
- 不要把真实密码写入脚本、`.env`、Markdown、终端截图或 Git 提交；
- 执行数据库更新前确认主机、数据库名和账号权限；
- 不要把 `--overwrite`、`reset` 或任何删除用户的逻辑作为常规排障步骤；
- 本指南不执行数据库删除、清空、重置或配置中心修改操作。若必须覆盖或清理数据，应由具备权限的人工流程审批执行。

## 相关文件

- `frontend/src/views/Auth/Login.vue`
- `frontend/src/views/Settings/index.vue`
- `frontend/src/api/auth.ts`
- `frontend/src/stores/auth.ts`
- `app/main.py`
- `app/routers/auth_db.py`
- `app/services/user_service.py`
- `app/services/config_service.py`
- `app/scripts/init_providers.py`
- `scripts/create_default_admin.py`
- `scripts/user_password_manager.py`
- `scripts/docker_deployment_init.py`
- `pyproject.toml`
- `requirements.txt`
- `requirements-lock.txt`
- `docs/deployment/docker/docker_deployment_guide.md`
