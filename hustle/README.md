# Hustle XAU点差对冲搬砖系统

## 系统概述

本系统旨在利用币安 (Binance) 的 XAUUSDT 永续合约与 Bybit 的 XAUUSD+ TradFi 合约之间的价格差异进行自动化点差对冲套利。系统通过实时监控两个平台的金价，并在发现有利可图的点差时，自动执行买卖操作，以期锁定无风险或低风险利润。

## 核心功能

- **点差套利 (Spread Arbitrage):** 当两个平台之间 XAU/USD 的价格差异足以覆盖交易成本时，系统将同时在低价平台买入并在高价平台卖出。
- **资金费率/隔夜利息套利:** 考虑币安永续合约的资金费率和 Bybit TradFi 合约的隔夜利息，在费率差异有利时建立对冲头寸。
- **风险控制:** 内置周末休市跳空风险处理、滑点控制、API 稳定性保障和资金管理建议。

## 系统要求

- Python 3.8+
- 币安 API Key 和 Secret (需开通期货交易权限)
- Bybit API Key 和 Secret (需开通 TradFi 交易权限)

## 安装指南

### 1. 克隆项目

```bash
git clone <repository-url>
cd hustle
```

### 2. 安装依赖项

使用提供的安装脚本：

```bash
python install_deps.py
```

或手动安装：

```bash
pip install ccxt pybit pytz
```

### 3. 配置 API Key

编辑 `arbitrage_system.py` 文件，将以下配置替换为您的实际 API Key：

```python
config = {
    'binance': {
        'api_key': 'YOUR_BINANCE_KEY',
        'api_secret': 'YOUR_BINANCE_SECRET'
    },
    'bybit': {
        'api_key': 'YOUR_BYBIT_KEY',
        'api_secret': 'YOUR_BYBIT_SECRET'
    },
    # 其他配置参数...
}
```

### 4. 调整策略参数

根据您的风险偏好和市场情况，调整以下参数：

- `min_spread`: 最小入场点差阈值 (USDT)
- `exit_spread`: 出场点差阈值 (USDT)
- `trade_size_xau`: 每次交易的 XAU 数量
- `interval`: 价格检查间隔 (秒)

### 5. 启动系统

在 `arbitrage_system.py` 文件中，取消注释最后一行：

```python
# 注意：取消下面一行的注释以运行系统
system.run()
```

然后运行系统：

```bash
python arbitrage_system.py
```

## 风险控制

1. **周末休市跳空风险:** 系统会在 Bybit TradFi 周末休市前自动平仓所有 Bybit 头寸。
2. **滑点控制:** 优先使用限价单，并设置最大滑点容忍度。
3. **API 稳定性:** 采用健壮的错误处理和重试机制。
4. **资金管理:** 建议设置合理的交易量和杠杆，实时监控账户保证金率。

## 日志记录

系统运行时，所有操作和日志信息将输出到：
- 控制台
- `arbitrage.log` 文件

## 注意事项

- **API Key 安全:** 绝不将您的 API Key 和 Secret 泄露给他人。建议使用 IP 白名单限制 API 访问。
- **资金安全:** 自动化交易存在风险，请确保您充分了解并能承受潜在的资金损失。
- **市场波动:** 极端市场条件下，即使是对冲策略也可能面临风险。
- **Bybit TradFi 交易时间:** Bybit TradFi 在周末和某些节假日休市。
- **定期监控:** 定期检查 `arbitrage.log` 文件，了解系统运行状态和交易详情。

## 常见问题

### Q: 系统报错 `APIError` 或 `Authentication failed`
A: 请检查您的 API Key 和 Secret 是否正确，以及是否已开通了相应的交易权限。

### Q: 系统没有执行交易
A: 检查 `arbitrage.log` 文件，查看是否有错误信息。确认当前点差是否满足 `min_spread` 入场条件。确保 `system.run()` 行已取消注释。

## 技术架构

- **ExchangeConnector:** 负责与币安和 Bybit 交易所的 API 通信。
- **RiskManager:** 负责风险控制，包括周末休市处理、滑点控制等。
- **Strategy:** 负责实现套利策略，包括点差计算、下单执行等。
- **ArbitrageSystem:** 系统主类，协调各个模块的运行。

## 免责声明

本系统仅供学习和参考使用，不构成任何投资建议。使用本系统进行交易所产生的所有风险和损失由用户自行承担。请在充分了解市场风险的情况下谨慎使用。
