# Hustle2026 交易系统

## 系统简介
Hustle2026 是一个专业的加密货币套利交易系统，支持 Binance 和 Bybit (MT5) 平台的实时交易和风险管理。

## 主要功能
- 实时市场数据监控
- 自动套利策略执行
- 风险管理和预警
- 多平台账户管理
- 系统版本管理和备份
- 飞书通知集成

## 技术栈
- **前端**: Vue 3 + Vite + TailwindCSS
- **后端**: FastAPI + Python 3.9
- **数据库**: PostgreSQL 18
- **缓存**: Redis
- **交易平台**: Binance Futures API + MetaTrader 5

## 快速启动

### 1. 环境要求
- Windows Server 2022
- Python 3.9+
- Node.js 16+
- PostgreSQL 18
- Redis
- MetaTrader 5

### 2. 启动服务
双击桌面上的 `启动Hustle2026.bat` 或等待系统自动启动（已配置开机自启）

服务将按以下顺序启动：
1. MetaTrader 5 客户端
2. 后端服务 (http://localhost:8000)
3. 前端服务 (http://localhost:5173)

### 3. 访问系统
- 前端界面: http://13.115.21.77:3000
- 后端API: http://13.115.21.77:8000
- API文档: http://13.115.21.77:8000/docs

## 系统管理

### 版本管理
系统支持自动版本管理，每次推送到 GitHub 时会自动递增版本号。

访问 http://13.115.21.77:3000/system 进行：
- 查看当前版本信息
- 推送代码到 GitHub
- 查看版本历史
- 回滚到历史版本

### 数据库备份
数据库备份文件存储在 `database_backups/` 目录，每次推送时会自动包含最新备份。

手动备份命令：
\`\`\`bash
PGPASSWORD=postgres pg_dump -U postgres -h localhost -d postgres -F c -f database_backups/backup_$(date +%Y%m%d).backup
\`\`\`

### 恢复数据库
\`\`\`bash
PGPASSWORD=postgres pg_restore -U postgres -h localhost -d postgres -c database_backups/backup_YYYYMMDD.backup
\`\`\`

## 项目结构
\`\`\`
hustle2026/
├── backend/                 # 后端服务
│   ├── app/                # 应用代码
│   │   ├── api/           # API路由
│   │   ├── core/          # 核心配置
│   │   ├── models/        # 数据模型
│   │   ├── services/      # 业务逻辑
│   │   └── tasks/         # 后台任务
│   ├── version.json       # 版本信息
│   └── .env              # 环境变量
├── frontend/               # 前端应用
│   ├── src/
│   │   ├── views/        # 页面组件
│   │   ├── components/   # 通用组件
│   │   └── stores/       # 状态管理
│   └── .env              # 环境变量
├── database_backups/       # 数据库备份
├── start_services.bat      # 启动脚本
└── start_services_silent.vbs  # 静默启动脚本

\`\`\`

## 配置说明

### 后端配置 (backend/.env)
\`\`\`env
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres
REDIS_HOST=localhost
REDIS_PORT=6379
SECRET_KEY=your-secret-key
ENCRYPTION_KEY=your-encryption-key
\`\`\`

### 前端配置 (frontend/.env)
\`\`\`env
VITE_API_BASE_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
\`\`\`

## 维护说明

### 清理日志和缓存
系统已自动清理：
- Python 缓存文件 (__pycache__, *.pyc)
- 前端构建缓存 (dist, .vite)
- 旧的调试日志文件

### 数据库维护
- 市场数据保留 3 天
- 通知日志保留 7 天
- 点差记录保留 7 天

定期执行 VACUUM 优化：
\`\`\`sql
VACUUM FULL ANALYZE;
\`\`\`

## 故障排查

### 服务无法启动
1. 检查 MetaTrader 5 是否正常运行
2. 检查 PostgreSQL 和 Redis 服务状态
3. 查看日志文件：
   - 后端: backend/backend.log
   - 前端: frontend/frontend.log

### 版本推送失败
1. 检查 Git 配置和网络连接
2. 确认 GitHub 仓库访问权限
3. 查看系统管理页面的错误信息

## 联系方式
如有问题，请联系系统管理员。

## 更新日志

### v1.0.0 (2026-03-15)
- 初始版本发布
- 实现版本管理功能
- 添加自动备份到 GitHub
- 优化系统启动流程
- 清理和瘦身项目文件
