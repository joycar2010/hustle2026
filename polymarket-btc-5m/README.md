# Polymarket BTC 5 分钟自动量化程序

针对 [Polymarket](https://polymarket.com) 的 **Bitcoin Up or Down 5m** 市场（`series_slug=btc-up-or-down-5m`）的自动交易机器人。

默认 **纸面交易（paper）**，不会下真单。实盘需同时满足：`--live` + `.env` 中 `LIVE_TRADING_ENABLED=true`。

## 策略概要

**尾盘边缘收敛（late-window edge scalp）**

1. 按 slug `btc-updown-5m-<unix_start>` 定位当前 5 分钟窗口  
2. 轮询 CLOB Up/Down 盘口  
3. 用 OKX / Coinbase / Kraken 现货相对窗口开盘价的 Δ，过滤方向  
4. 在收盘前 `ENTRY_WINDOW_SEC`～`MIN_T_REMAINING_SEC` 秒内：  
   - 一侧 ask 落在 `[MIN_ENTRY_PRICE, MAX_ENTRY_PRICE]`  
   - `net_edge = 1 - ask - fee` 且 `fee = 0.07 × ask × (1-ask)` ≥ `MIN_NET_EDGE`  
   - 连续确认 `CONFIRM_CHECKS` 次  
   → FOK 买入该侧，持有到结算  

风控：单笔名义上限、每日亏损熔断、每窗最多一仓。

> 结算真源是 Chainlink BTC/USD TWAP。本程序现货 Δ 只是方向过滤器，不保证盈利。

## 快速开始（纸面）

```bash
cd polymarket-btc-5m
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 单次决策
python -m btc5m --once -v

# 持续纸面运行
bash scripts/run_paper.sh
# 或: python -m btc5m
```

决策与持仓写入 `data/paper.db`。

## 实盘准备

1. 新建专用钱包，在 polymarket.com 登录并充值（CLOB V2 / pUSD）  
2. 复制配置：

```bash
cp .env.example .env
# 填入 PRIVATE_KEY、FUNDER_ADDRESS（deposit wallet）
```

3. 派生 API 凭证：

```bash
python scripts/derive_api_creds.py
# 把打印的 API_KEY / API_SECRET / API_PASSPHRASE 写入 .env
```

4. 开启实盘开关并启动：

```bash
# .env
LIVE_TRADING_ENABLED=true

bash scripts/run_live.sh
```

注意：Polymarket 有地理限制；不要用 VPN 规避。实盘有本金风险，建议先小额。

## 配置要点（`.env`）

| 变量 | 默认 | 含义 |
|------|------|------|
| `ENTRY_WINDOW_SEC` | 60 | 距收盘多少秒内开始观察 |
| `MIN_T_REMAINING_SEC` | 12 | 距收盘少于此秒数不再开仓 |
| `MIN_ENTRY_PRICE` / `MAX_ENTRY_PRICE` | 0.75 / 0.95 | 可买 ask 区间 |
| `MIN_NET_EDGE` | 0.02 | 扣费后最低净边缘 |
| `UP_MIN_DELTA_USD` | 15 | 买 Up 所需现货涨幅 |
| `DOWN_MAX_DELTA_USD` | -15 | 买 Down 所需现货跌幅 |
| `ORDER_SHARES` | 10 | 下单股数（交易所最小 5） |
| `MAX_ORDER_USD` | 15 | 单笔名义上限 |
| `DAILY_LOSS_LIMIT_USD` | 40 | 日亏损熔断 |

## 测试

```bash
pip install pytest
pytest -q
```

## 目录

```
polymarket-btc-5m/
  btc5m/          # 核心代码
  scripts/        # 启停与派生凭证
  tests/
  data/           # 运行时 SQLite
  .env.example
```

## 免责声明

本程序仅供研究与自动化实验。预测市场与加密交易有显著亏损风险；策略不保证收益；请遵守当地法律与 Polymarket 服务条款。
