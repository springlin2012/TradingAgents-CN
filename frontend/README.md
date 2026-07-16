# 前端交互层架构说明

`frontend/` 是 TradingAgents-CN 的现代化前端交互层，基于 Vue 3、TypeScript、Vite、Pinia、Vue Router 和 Element Plus 构建。它负责用户登录、分析任务提交、进度展示、报告查看、配置管理和系统状态可视化。

## 目录结构

```text
frontend/
├── src/
│   ├── api/          # Axios 请求封装和业务 API 模块
│   ├── components/   # 可复用 UI 组件
│   ├── constants/    # 前端常量
│   ├── layouts/      # 页面骨架和导航布局
│   ├── router/       # Vue Router 路由表和守卫
│   ├── stores/       # Pinia 全局状态
│   ├── styles/       # 全局样式和主题变量
│   ├── types/        # TypeScript 类型定义
│   ├── utils/        # 前端工具函数
│   └── views/        # 业务页面
├── public/           # 静态资源
├── package.json      # 脚本和依赖
└── vite.config.ts    # Vite 构建和代理配置
```

## 核心模块说明

### 1. `src/main.ts`

**职责**：前端应用启动入口。

**主要功能**：
- 创建 Vue 应用实例。
- 注册 Pinia、Vue Router、Element Plus、图标和全局样式。
- 挂载根组件 `App.vue`。

**依赖**：`router/`、`stores/`、`styles/`、Element Plus。

---

### 2. `src/api/`

**职责**：后端 API 访问层，隔离 HTTP 细节。

**主要功能**：
- 统一维护 Axios 实例、Base URL、Token 注入和错误处理。
- 封装认证、分析、报告、配置、股票、调度、通知等接口。
- 将后端响应转换为页面可直接使用的数据结构。

**使用场景**：`views/` 页面、`stores/` 状态模块和复用组件。

---

### 3. `src/router/`

**职责**：页面路由和访问控制。

**主要功能**：
- 定义登录、仪表盘、股票分析、报告、系统配置、数据同步等页面路由。
- 通过路由守卫检查认证状态。
- 为布局和菜单提供路由元信息。

**依赖**：`stores/auth`、`layouts/`、`views/`。

---

### 4. `src/stores/`

**职责**：全局状态管理。

**主要模块**：
- `auth`：登录用户、访问令牌、退出登录和权限状态。
- `app`：主题、侧边栏、加载状态等应用级状态。
- `notifications`：系统通知、未读数和实时消息状态。

**使用建议**：跨页面共享的状态放在 store；单页面临时状态保留在组件内。

---

### 5. `src/views/`

**职责**：业务页面层。

**主要功能**：
- 组织分析任务提交、股票筛选、报告查看、配置管理等完整页面。
- 调用 `api/` 获取数据，调用 `stores/` 读写全局状态。
- 将业务页面拆分为局部组件，避免单个视图文件过大。

---

### 6. `src/components/`

**职责**：可复用 UI 和业务组件。

**使用建议**：
- 通用按钮、表格、弹窗、状态块放在组件层。
- 与具体页面强绑定的复杂组件优先放在对应 `views/` 子目录。
- 组件通过 props 和 emits 暴露接口，避免直接耦合页面状态。

## 四层协作边界

前端交互层只负责展示、表单校验、状态呈现和 API 调用；认证、调度、数据同步、分析执行和持久化都由 `app/` 后端 API 层完成。前端不得直接访问 MongoDB、Redis 或 `tradingagents/` 核心库。

## 常用命令

```bash
npm install
npm run dev
npm run type-check
npm run lint
npm run build
```

## 开发建议

1. 新页面先在 `views/` 建立页面，再在 `router/` 注册路由。
2. 新接口先在 `types/` 定义请求/响应类型，再在 `api/` 封装调用。
3. 跨页面共享状态放入 `stores/`；页面私有状态不要提升为全局状态。
4. UI 修改后运行 `npm run type-check` 和 `npm run lint`。
