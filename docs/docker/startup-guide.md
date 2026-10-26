# Docker启动指南

## 🚀 快速启动

### 📋 基本启动命令

```bash
# 日常启动（推荐）- 使用现有镜像
docker-compose up -d

# 首次启动或代码变更 - 重新构建镜像
docker-compose up -d --build

# 启动 backend 服务，输出日志
docker-compose logs backend --tail=100
```

### 🧠 智能启动（推荐）

智能启动脚本会自动判断是否需要重新构建镜像：

#### Windows环境
```powershell
# 方法1：直接运行
powershell -ExecutionPolicy Bypass -File scripts\smart_start.ps1

# 方法2：在PowerShell中运行
.\scripts\smart_start.ps1
```

#### Linux/Mac环境
```bash
# 添加执行权限并运行
chmod +x scripts/smart_start.sh
./scripts/smart_start.sh

# 或者一行命令
chmod +x scripts/smart_start.sh && ./scripts/smart_start.sh
```

## 🔧 启动参数说明

### `--build` 参数使用场景

| 场景 | 是否需要 `--build` | 原因 |
|------|-------------------|------|
| 首次启动 | ✅ 需要 | 镜像不存在，需要构建 |
| 代码修改后 | ✅ 需要 | 需要将新代码打包到镜像 |
| 依赖更新后 | ✅ 需要 | requirements.txt变化 |
| Dockerfile修改 | ✅ 需要 | 构建配置变化 |
| 日常重启 | ❌ 不需要 | 镜像已存在且无变化 |
| 容器异常重启 | ❌ 不需要 | 问题通常不在镜像层面 |

### 智能启动判断逻辑

1. **检查镜像存在性**
   - 镜像不存在 → 执行 `docker-compose up -d --build`
   
2. **检查代码变化**
   - 有未提交的代码变化 → 执行 `docker-compose up -d --build`
   - 无代码变化 → 执行 `docker-compose up -d`

## 🛠️ 故障排除

### 常见启动问题

1. **端口冲突**
   ```bash
   # 检查端口占用
   netstat -ano | findstr :8501  # Windows
   lsof -i :8501                 # Linux/Mac
   ```

2. **镜像构建失败**
   ```bash
   # 清理并重新构建
   docker-compose down
   docker system prune -f
   docker-compose up -d --build
   ```

3. **容器启动失败**
   ```bash
   # 查看详细日志
   docker-compose logs web
   docker-compose logs mongodb
   docker-compose logs redis
   ```

### 排查工具

使用项目提供的排查脚本：

```bash
# Windows
powershell -ExecutionPolicy Bypass -File scripts\debug_docker.ps1

# Linux/Mac
chmod +x scripts/debug_docker.sh && ./scripts/debug_docker.sh
```

## 📊 性能对比

| 启动方式 | 首次启动时间 | 后续启动时间 | 适用场景 |
|----------|-------------|-------------|----------|
| `docker-compose up -d --build` | ~3-5分钟 | ~3-5分钟 | 开发环境，代码频繁变更 |
| `docker-compose up -d` | ~3-5分钟 | ~10-30秒 | 生产环境，稳定运行 |
| 智能启动脚本 | ~3-5分钟 | ~10-30秒 | 推荐，自动优化 |

## 🎯 最佳实践

1. **开发环境**：使用智能启动脚本
2. **生产环境**：首次部署用 `--build`，后续用普通启动
3. **CI/CD**：始终使用 `--build` 确保最新代码
4. **故障排除**：先尝试普通重启，再考虑重新构建