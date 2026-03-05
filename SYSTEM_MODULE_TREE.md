# 系统功能模块目录树

> 📌 标注说明：✅ 已实现 | ❌ 未实现 | 🚧 部分实现

## 一、后端系统 (Backend)

### 1. API层 (`backend/app/api/v1/`)

#### 1.1 用户与权限管理
- ✅ `auth.py` - 用户认证（登录、登出、Token刷新）
- ✅ `users.py` - 用户管理（CRUD、个人信息）
- ✅ `rbac.py` - 角色权限管理（RBAC系统）
- ✅ `key_management.py` - API密钥管理（加密存储）

#### 1.2 交易核心
- ✅ `trading.py` - 交易接口（下单、撤单、查询）
- ✅ `strategies.py` - 策略管理（创建、启停、配置）
- ✅ `accounts.py` - 账户管理（余额、持仓、资金费率）
- ✅ `market.py` - 市场数据（行情、深度、K线）
- ❌ `execution_history.py` - 执行历史记录查询

#### 1.3 风险管理
- ✅ `risk.py` - 风险监控（风险指标、告警配置）
- ❌ `risk_limits.py` - 风险限额管理（单笔限额、日限额）
- ❌ `drawdown_monitor.py` - 回撤监控（实时回撤计算）

#### 1.4 系统管理
- ✅ `system.py` - 系统配置（参数设置、健康检查）
- ✅ `security_components.py` - 安全组件管理
- ✅ `ssl_certificates.py` - SSL证书管理
- ✅ `websocket.py` - WebSocket连接管理
- ❌ `backup_restore.py` - 数据备份与恢复

#### 1.5 自动化与测试
- ✅ `automation.py` - 自动化任务管理
- ✅ `test.py` - 测试接口
- ❌ `scheduled_tasks.py` - 定时任务管理

---

### 2. 核心层 (`backend/app/core/`)

#### 2.1 基础设施
- ✅ `config.py` - 配置管理（环境变量、系统参数）
- ✅ `database.py` - 数据库连接（PostgreSQL）
- ✅ `redis_client.py` - Redis客户端（缓存、消息队列）

#### 2.2 安全机制
- ✅ `security.py` - 安全工具（密码哈希、Token生成）
- ✅ `encryption.py` - 加密服务（AES加密、密钥管理）
- ✅ `csrf.py` - CSRF防护
- ✅ `signature.py` - 请求签名验证
- ✅ `ip_whitelist.py` - IP白名单管理
- ✅ `log_sanitizer.py` - 日志脱敏
- ✅ `request_id.py` - 请求ID追踪

---

### 3. 服务层 (`backend/app/services/`)

#### 3.1 交易所客户端
- ✅ `binance_client.py` - Binance REST API客户端
- ✅ `binance_ws_client.py` - Binance WebSocket客户端
- ✅ `bybit_client.py` - Bybit REST API客户端
- ✅ `mt5_client.py` - MetaTrader 5客户端
- ❌ `okx_client.py` - OKX交易所客户端（未来扩展）

#### 3.2 账户与持仓管理
- ✅ `account_service.py` - 账户服务（余额查询、资金费率）
- ✅ `account_sync_service.py` - 账户数据同步
- ✅ `position_manager.py` - 持仓管理（持仓跟踪、更新）
- ✅ `position_monitor.py` - 持仓监控（实时监控）

#### 3.3 订单执行
- ✅ `order_executor_v2.py` - 订单执行器V2（主要版本）
- ✅ `order_executor.py` - 订单执行器V1（旧版本）
- ✅ `ladder_order.py` - 阶梯订单管理
- ❌ `smart_routing.py` - 智能路由（订单拆分、最优执行）

#### 3.4 策略引擎
- ✅ `strategy_executor_v2.py` - 策略执行器V2
- ✅ `strategy_manager.py` - 策略管理器
- ✅ `strategy_base.py` - 策略基类
- ✅ `arbitrage_strategy.py` - 套利策略
- 🚧 `strategy_status_pusher.py` - 策略状态推送器（已实现但未集成）
- ❌ `grid_strategy.py` - 网格策略
- ❌ `market_making_strategy.py` - 做市策略
- ❌ `trend_following_strategy.py` - 趋势跟踪策略

#### 3.5 市场数据
- ✅ `market_service.py` - 市场数据服务
- ✅ `realtime_market_service.py` - 实时市场数据服务
- ❌ `historical_data_service.py` - 历史数据服务（K线、深度历史）

#### 3.6 风险管理
- ✅ `risk_monitor.py` - 风险监控服务
- ✅ `trigger_manager.py` - 触发器管理（止损、止盈）
- ❌ `var_calculator.py` - VaR计算（风险价值）
- ❌ `stress_testing.py` - 压力测试

#### 3.7 系统服务
- ✅ `key_management.py` - 密钥管理服务
- ✅ `permission_cache.py` - 权限缓存
- ✅ `security_health_check.py` - 安全健康检查
- ❌ `notification_service.py` - 通知服务（邮件、短信、Telegram）
- ❌ `audit_log_service.py` - 审计日志服务

---

### 4. 后台任务 (`backend/app/tasks/`)

#### 4.1 数据广播
- ✅ `broadcast_tasks.py` - WebSocket广播任务
  - ✅ AccountBalanceStreamer（每10秒广播账户余额）
  - ✅ RiskMetricsStreamer（每30秒广播风险指标）
  - ❌ MT5ConnectionStreamer（MT5连接状态广播）

#### 4.2 市场数据
- ✅ `market_data.py` - 市场数据采集与推送
- ❌ `kline_aggregator.py` - K线数据聚合

#### 4.3 监控任务
- ✅ `redis_monitor.py` - Redis监控任务
- ❌ `database_cleanup.py` - 数据库清理任务（历史数据归档）
- ❌ `performance_monitor.py` - 性能监控任务

---

### 5. 数据模型 (`backend/app/models/`)

#### 5.1 用户与权限
- ✅ `user.py` - 用户模型
- ✅ `role.py` - 角色模型
- ✅ `permission.py` - 权限模型
- ✅ `role_permission.py` - 角色权限关联

#### 5.2 交易核心
- ✅ `account.py` - 账户模型
- ✅ `account_snapshot.py` - 账户快照
- ✅ `order.py` - 订单模型
- ✅ `position.py` - 持仓模型
- ✅ `platform.py` - 平台模型
- ✅ `strategy.py` - 策略模型
- ✅ `strategy_performance.py` - 策略绩效
- ✅ `arbitrage.py` - 套利记录

#### 5.3 市场数据
- ✅ `market_data.py` - 市场数据模型
- ❌ `kline.py` - K线数据模型
- ❌ `orderbook.py` - 订单簿模型

#### 5.4 风险管理
- ✅ `risk_alert.py` - 风险告警
- ✅ `risk_settings.py` - 风险设置
- ❌ `drawdown_record.py` - 回撤记录

#### 5.5 系统管理
- ✅ `notification.py` - 通知模型
- ✅ `security_component.py` - 安全组件
- ✅ `ssl_certificate.py` - SSL证书
- ❌ `audit_log.py` - 审计日志
- ❌ `system_config.py` - 系统配置

---

### 6. 数据模式 (`backend/app/schemas/`)

- ✅ `user.py` - 用户数据模式
- ✅ `account.py` - 账户数据模式
- ✅ `strategy.py` - 策略数据模式
- ✅ `market.py` - 市场数据模式
- ✅ `rbac.py` - RBAC数据模式
- ✅ `security.py` - 安全数据模式
- ✅ `ssl.py` - SSL数据模式
- ❌ `risk.py` - 风险数据模式
- ❌ `notification.py` - 通知数据模式

---

### 7. 中间件 (`backend/app/middleware/`)

- ✅ `permission_interceptor.py` - 权限拦截器
- ❌ `rate_limiter.py` - 速率限制器
- ❌ `request_logger.py` - 请求日志记录器

---

## 二、前端系统 (Frontend)

### 1. 视图层 (`frontend/src/views/`)

#### 1.1 核心页面
- ✅ `Login.vue` - 登录页面
- ✅ `Dashboard.vue` - 仪表盘（总览）
- ✅ `TradingDashboard.vue` - 交易仪表盘（主要交易界面）
- ✅ `Trading.vue` - 交易页面（旧版）
- ✅ `Strategies.vue` - 策略管理页面
- ✅ `Positions.vue` - 持仓管理页面
- ✅ `PendingOrders.vue` - 挂单管理页面
- ✅ `Accounts.vue` - 账户管理页面
- ✅ `Risk.vue` - 风险管理页面
- ✅ `System.vue` - 系统设置页面

#### 1.2 测试页面
- ✅ `BinanceTest.vue` - Binance测试页面
- ✅ `BybitTest.vue` - Bybit测试页面
- ✅ `System_test.vue` - 系统测试页面

#### 1.3 未实现页面
- ❌ `Performance.vue` - 绩效分析页面
- ❌ `History.vue` - 历史记录页面
- ❌ `Reports.vue` - 报表页面
- ❌ `Alerts.vue` - 告警中心页面
- ❌ `Settings.vue` - 个人设置页面

---

### 2. 组件层 (`frontend/src/components/`)

#### 2.1 交易组件 (`trading/`)
- ✅ `AccountStatusPanel.vue` - 账户状态面板
- ✅ `NavigationPanel.vue` - 导航面板（系统提醒）
- ✅ `MarketCards.vue` - 行情卡片（套利点差）
- ✅ `StrategyPanel.vue` - 策略面板
- ✅ `OrderMonitor.vue` - 订单监控
- ✅ `ManualTrading.vue` - 手动交易
- ✅ `EmergencyTrading.vue` - 紧急交易
- ✅ `EmergencyManualTrading.vue` - 紧急手动交易
- ✅ `RecentTrades.vue` - 最近成交
- ✅ `RecentTradingRecords.vue` - 最近交易记录
- ✅ `OpenOrders.vue` - 当前委托
- ✅ `SpreadDataTable.vue` - 点差数据表
- ✅ `RiskDashboard.vue` - 风险仪表盘
- ✅ `TradingChart.vue` - 交易图表
- ✅ `TradingForm.vue` - 交易表单
- ✅ `FloatingActionButtons.vue` - 浮动操作按钮
- ❌ `PositionAnalysis.vue` - 持仓分析组件
- ❌ `ProfitLossChart.vue` - 盈亏图表

#### 2.2 仪表盘组件 (`dashboard/`)
- ✅ `AssetDashboard.vue` - 资产仪表盘
- ✅ `RealTimePrices.vue` - 实时价格
- ✅ `SpreadHistory.vue` - 点差历史
- ❌ `PerformanceMetrics.vue` - 绩效指标
- ❌ `TradingVolume.vue` - 交易量统计

#### 2.3 模态框组件 (`modals/`)
- ✅ `BackupActionModal.vue` - 备份操作模态框
- ✅ `BackupSelectModal.vue` - 备份选择模态框
- ✅ `ChangePasswordModal.vue` - 修改密码模态框
- ✅ `EditProfileModal.vue` - 编辑个人信息模态框
- ✅ `TableDetailModal.vue` - 表格详情模态框
- ❌ `ConfirmModal.vue` - 确认模态框（通用）
- ❌ `AlertSettingsModal.vue` - 告警设置模态框

#### 2.4 系统组件 (`system/`)
- ✅ `WebSocketMonitor.vue` - WebSocket监控
- ❌ `SystemHealthMonitor.vue` - 系统健康监控
- ❌ `LogViewer.vue` - 日志查看器

#### 2.5 通用组件
- ✅ `Navbar.vue` - 导航栏
- ✅ `NotificationPopup.vue` - 通知弹窗
- ✅ `PermissionManagement.vue` - 权限管理
- ✅ `RolePermissionAssign.vue` - 角色权限分配
- ❌ `LoadingSpinner.vue` - 加载动画
- ❌ `ErrorBoundary.vue` - 错误边界

---

### 3. 状态管理 (`frontend/src/stores/`)

- ✅ `auth.js` - 认证状态（用户登录、Token）
- ✅ `market.js` - 市场数据状态（WebSocket、行情）
- ✅ `notification.js` - 通知状态（系统提醒、风险告警）
- ❌ `trading.js` - 交易状态（订单、持仓）
- ❌ `strategy.js` - 策略状态（策略列表、执行状态）
- ❌ `account.js` - 账户状态（余额、资金费率）

---

### 4. 组合式函数 (`frontend/src/composables/`)

- ✅ `useAlertMonitoring.js` - 告警监控（市场告警、账户告警）
- ✅ `useQuantityConverter.js` - 数量单位转换
- ✅ `useSpreadCalculator.js` - 点差计算
- ❌ `useWebSocket.js` - WebSocket连接管理
- ❌ `useOrderManagement.js` - 订单管理
- ❌ `usePositionTracking.js` - 持仓跟踪

---

### 5. 服务层 (`frontend/src/services/`)

- ✅ `api.js` - API请求封装（Axios实例）
- ❌ `websocket.js` - WebSocket服务
- ❌ `storage.js` - 本地存储服务
- ❌ `notification.js` - 通知服务

---

### 6. 工具函数 (`frontend/src/utils/`)

- ✅ `timeUtils.js` - 时间工具函数
- ❌ `formatters.js` - 格式化工具（数字、货币）
- ❌ `validators.js` - 验证工具（表单验证）
- ❌ `constants.js` - 常量定义

---

### 7. 路由 (`frontend/src/router/`)

- ✅ `index.js` - 路由配置
- ❌ `guards.js` - 路由守卫（权限检查）

---

## 三、WebSocket实时推送系统

### 1. 已实现的消息类型

#### 1.1 市场数据
- ✅ `market_data` - 实时市场数据（点差、价格）

#### 1.2 账户数据
- ✅ `account_balance` - 账户余额（每10秒广播）
- ✅ `risk_metrics` - 风险指标（每30秒广播）

#### 1.3 交易数据
- ✅ `order_update` - 订单更新（用户级推送）
- 🚧 `position_update` - 持仓更新（方法存在但未使用）
- 🚧 `strategy_status` - 策略状态（方法存在但未使用）
- 🚧 `strategy_position_change` - 策略持仓变化（未集成）

### 2. 未实现的消息类型

- ❌ `mt5_connection_status` - MT5连接状态
- ❌ `risk_alert` - 风险告警推送
- ❌ `system_notification` - 系统通知
- ❌ `trade_execution` - 交易执行通知
- ❌ `strategy_performance` - 策略绩效更新

---

## 四、定时轮询系统（待移除）

### 1. 当前使用定时器的组件

- 🚧 `useAlertMonitoring.js` - 30秒轮询账户数据、60秒轮询MT5状态
- 🚧 `NavigationPanel.vue` - 60秒轮询系统提醒
- 🚧 `OrderMonitor.vue` - 30秒轮询订单列表
- 🚧 `StrategyPanel.vue` - 30秒轮询持仓数据

### 2. 计划改造方案

根据 `parallel-waddling-lobster.md` 计划：
- Phase 1-4: 移除定时器，改用WebSocket
- Phase 5: 集成策略状态推送器
- Phase 6: 添加MT5状态WebSocket推送

---

## 五、数据库设计

### 1. 已实现的表

- ✅ users - 用户表
- ✅ roles - 角色表
- ✅ permissions - 权限表
- ✅ role_permissions - 角色权限关联表
- ✅ accounts - 账户表
- ✅ account_snapshots - 账户快照表
- ✅ orders - 订单表
- ✅ positions - 持仓表
- ✅ platforms - 平台表
- ✅ strategies - 策略表
- ✅ strategy_performances - 策略绩效表
- ✅ arbitrage_records - 套利记录表
- ✅ market_data - 市场数据表
- ✅ risk_alerts - 风险告警表
- ✅ risk_settings - 风险设置表
- ✅ notifications - 通知表
- ✅ security_components - 安全组件表
- ✅ ssl_certificates - SSL证书表

### 2. 未实现的表

- ❌ klines - K线数据表
- ❌ orderbooks - 订单簿表
- ❌ drawdown_records - 回撤记录表
- ❌ audit_logs - 审计日志表
- ❌ system_configs - 系统配置表
- ❌ trade_history - 交易历史表
- ❌ funding_rate_history - 资金费率历史表

---

## 六、关键功能模块状态总结

### ✅ 已完成模块（核心功能）

1. **用户认证与权限管理** - 完整的RBAC系统
2. **交易所连接** - Binance、Bybit、MT5客户端
3. **订单执行** - 订单下单、撤单、查询
4. **策略管理** - 策略创建、启停、配置
5. **账户管理** - 余额查询、持仓跟踪
6. **市场数据** - 实时行情、WebSocket推送
7. **风险监控** - 风险指标计算、告警
8. **WebSocket实时推送** - 账户余额、风险指标、订单更新
9. **安全机制** - 加密、签名、CSRF、IP白名单

### 🚧 部分实现模块（需要完善）

1. **策略状态推送** - 已实现但未集成到执行器
2. **持仓更新推送** - WebSocket方法存在但未使用
3. **定时轮询系统** - 需要改造为WebSocket推送
4. **MT5连接监控** - 需要添加WebSocket推送

### ❌ 未实现模块（未来扩展）

1. **智能路由** - 订单拆分、最优执行
2. **多策略支持** - 网格、做市、趋势跟踪
3. **历史数据服务** - K线、深度历史查询
4. **VaR计算** - 风险价值计算
5. **压力测试** - 策略压力测试
6. **通知服务** - 邮件、短信、Telegram
7. **审计日志** - 完整的操作审计
8. **数据备份与恢复** - 自动备份、一键恢复
9. **绩效分析** - 详细的策略绩效报表
10. **OKX交易所** - 新交易所接入

---

## 七、技术栈总结

### 后端技术栈
- **框架**: FastAPI
- **数据库**: PostgreSQL
- **缓存**: Redis
- **WebSocket**: FastAPI WebSocket
- **异步**: asyncio
- **ORM**: SQLAlchemy
- **加密**: cryptography

### 前端技术栈
- **框架**: Vue 3
- **状态管理**: Pinia
- **路由**: Vue Router
- **HTTP客户端**: Axios
- **WebSocket**: 原生WebSocket API
- **UI框架**: Tailwind CSS
- **图表**: 待定

### 部署与运维
- **容器化**: Docker
- **反向代理**: Nginx
- **进程管理**: PM2 / Supervisor
- **日志**: 文件日志 + 控制台输出
- **监控**: 待实现

---

## 八、优先级建议

### 高优先级（立即实施）
1. ✅ 移除定时轮询，改用WebSocket推送
2. 🚧 集成策略状态推送器到执行器
3. ❌ 实现MT5连接状态WebSocket推送
4. ❌ 完善风险告警WebSocket推送

### 中优先级（近期规划）
1. ❌ 实现历史数据服务（K线、深度）
2. ❌ 添加绩效分析页面
3. ❌ 实现通知服务（邮件、Telegram）
4. ❌ 添加审计日志功能

### 低优先级（长期规划）
1. ❌ 实现智能路由
2. ❌ 添加多策略支持（网格、做市）
3. ❌ 实现VaR计算和压力测试
4. ❌ 接入新交易所（OKX）

---

**文档版本**: v1.0
**更新日期**: 2026-03-05
**维护者**: 系统开发团队
