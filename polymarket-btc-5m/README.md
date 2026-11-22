# Polymarket BTC 5 分钟自动量化程序

针对 [Polymarket](https://polymarket.com) 的 **Bitcoin Up or Down 5m** 市场（`series_slug=btc-up-or-down-5m`）的自动交易机器人。

默认 **纸面交易（paper）**，不会下真单。实盘需同时满足：`--live` + `.env` 中 `LIVE_TRADING_ENABLED=true`（仅 `late_edge`）。

## P0 → P10（v1.10.0）

- **A/B/C BTC 5m**：行为冻结；默认 `SERIES_SLUG=btc-up-or-down-5m`  
- **P6 C**：join-touch 双边 + 残仓 SLA  
- **P7 / P7.1**：BTC 15m + ATP/CS sports_mm + 审计修复  
- **P8**  
  1. ETH 5m / SOL 5m — paper `late_edge` A（独立账本 + 资产信号）  
  2. NBA / NFL — OddsAPI fair MM（moneyline 主盘；spread 树仍延后）  
  3. Dota / Soccer-UNL — 主盘-only paper（live/道具过滤；无 OddsAPI 时不开 mock 仓）  
  4. `ODDS_API_KEY` 仅走环境变量 / secrets，禁止入库  
- **P9**：C merge 现金落盘 + `repair-split`；B 从未配对则 `UNPAIRED_ABORT`；eth/sol dashboard DB 路由  
- **P10**：XRP/BNB/DOGE/HYPE 5m paper late_edge（SOL bp 标定；独立 `paper_*5m.db`）  

```bash
python -m btc5m --mode split_sell                    # BTC 5m C
python -m btc5m --series btc15m --mode split_sell    # BTC 15m C
python -m btc5m --series eth5m --mode late_edge      # ETH 5m A
python -m btc5m --series sol5m --mode late_edge      # SOL 5m A
python -m btc5m --series xrp5m --mode late_edge      # XRP 5m paper
python -m btc5m --series bnb5m --mode late_edge      # BNB 5m paper
python -m btc5m --series doge5m --mode late_edge     # DOGE 5m paper
python -m btc5m --series hype5m --mode late_edge     # HYPE 5m paper
python -m btc5m --series atp --mode sports_mm        # ATP 主盘 paper
python -m btc5m --series nba --mode sports_mm        # NBA（需 ODDS_API_KEY）
python -m btc5m repair-split [--dry-run]             # C merge 账本回填
python -m btc5m products
python -m btc5m report
python -m btc5m heartbeat
```

部署（含 systemd **C**）：`PEM=... HOST=ec2-user@18.179.50.168 bash scripts/deploy_polydex.sh`  
详见 `ops/P5_NOTES.md` · `ops/P6_NOTES.md` · `ops/P7_NOTES.md` · `ops/P8_NOTES.md` · `ops/P9_MERGE_UNPAIRED_ROUTING.md` · `ops/P10_ALT_CRYPTO_5M.md`。

## 两种模式

### 1) `maker`（推荐纸面主路径）— 双边做市

对齐 X / 公开成交研究中更常见的赚钱形态：

1. 窗口开始后短暂延迟，在 Up/Down **两侧挂虚拟买单**
2. 约束 `up_bid + down_bid ≤ MAKER_PAIR_COST_MAX`（默认 0.98）
3. 纸面成交模型：盘口穿越（`ask ≤ bid`）或挂在 touch 持续 `MAKER_TOUCH_FILL_SEC` 秒
4. 库存失衡时减挂重仓侧；收盘前 `MAKER_STOP_BEFORE_END_SEC` 停止挂单，持有到结算
5. 结算：成对部分赚 `1 - pair_cost`，残仓按胜负方向记账；**maker 手续费 = 0**

```bash
python -m btc5m --mode maker          # 持续
python -m btc5m --mode maker --once -v
bash scripts/run_maker_paper.sh
```

数据写入 `data/maker_paper.db`。

### 2) `late_edge` — 尾盘边缘收敛（taker）

收盘前窗口内，在扣费后仍有 `net_edge` 时 FOK 买入一侧并持有到结算。会按 `crypto_fees_v2` 记 **taker fee**。

```bash
python -m btc5m --mode late_edge
# 或 MODE=late_edge
```

## 费后审计报表（方案 1）

每笔 fill / position / maker session 记录名义、手续费、毛利、净利：

```bash
python -m btc5m report --mode maker
python -m btc5m report --mode late_edge
python -m btc5m report --day 2026-11-13
```

示例输出字段：`notional / gross / fees / rebate≈ / net / WR / ROI`。

## 快速开始

```bash
cd polymarket-btc-5m
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

cp .env.example .env   # 默认 MODE=maker
python -m btc5m --mode maker --once -v
```

## Maker 配置

| 变量 | 默认 | 含义 |
|------|------|------|
| `MAKER_PAIR_COST_MAX` | 0.98 | 双边挂单价之和上限 |
| `MAKER_QUOTE_SHARES` | 10 | 每侧挂单股数 |
| `MAKER_START_DELAY_SEC` | 15 | 开窗后等待再报价 |
| `MAKER_STOP_BEFORE_END_SEC` | 45 | 收盘前停止挂单 |
| `MAKER_TOUCH_FILL_SEC` | 8 | touch 持续多久视为纸面成交 |
| `MAKER_MAX_IMBALANCE_SHARES` | 20 | 库存失衡上限 |

## 实盘（仅 late_edge）

Maker 引擎本版 **仅纸面**。`late_edge` 实盘：

1. 填 `.env` 钱包与 API（`python scripts/derive_api_creds.py`）
2. `LIVE_TRADING_ENABLED=true`
3. `python -m btc5m --mode late_edge --live`

注意地理限制与本金风险；公开数据显示多数 taker 长期亏损。

## 测试

```bash
pytest -q
```

## 免责声明

研究与自动化实验用途。预测市场有亏损风险；纸面成交模型无法等价真实 queue；策略不保证收益。
