# MT5 Microservice

MT5 微服务，提供 MetaTrader5 连接和交易功能。

## 功能

- MT5 连接管理（自动重连）
- 持仓查询
- 账户余额查询
- 订单执行
- API Key 认证

## 安装

```bash
pip install -r requirements.txt
```

## 配置

编辑 `.env` 文件：

```
BYBIT_MT5_ID=2325036
BYBIT_MT5_SERVER=Bybit-Live-2
BYBIT_MT5_PASSWORD=xY!800212
API_KEY=OQ6bUimHZDmXEZzJKE
PORT=8001
```

## 启动

Windows:
```bash
start.bat
```

或手动启动:
```bash
python app/main.py
```

服务将在 `http://localhost:8001` 启动。

## API 文档

启动后访问：`http://localhost:8001/docs`

### 主要端点

- `GET /health` - 健康检查
- `GET /mt5/connection/status` - 连接状态
- `POST /mt5/connection/reconnect` - 重新连接
- `GET /mt5/positions` - 获取持仓
- `GET /mt5/account/balance` - 账户余额
- `POST /mt5/order` - 下单

### 认证

所有 MT5 相关端点需要在 Header 中提供 API Key：

```
X-API-Key: OQ6bUimHZDmXEZzJKE
```

## 测试

```bash
# 健康检查
curl http://localhost:8001/health

# 连接状态（需要 API Key）
curl -H "X-API-Key: OQ6bUimHZDmXEZzJKE" http://localhost:8001/mt5/connection/status

# 获取持仓
curl -H "X-API-Key: OQ6bUimHZDmXEZzJKE" http://localhost:8001/mt5/positions
```
