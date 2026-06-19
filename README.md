# CrossArb P0 · 只读经济性验证(多市场)

回答一个问题:**在 Base 大池(Uniswap V3）买入 + 币安 USDT 永续做空,扣掉全部往返成本后
净基差 > 0.2% 的机会,在各标的上以多大频率/规模真实存在?**

**只读。零交易、零私钥、零生产接触。** 与生产 `hustlecoin-cex` 完全独立:
独立目录、独立 `CROSSARB_` 配置、独立端口 8100、可选独立 `crossarb:*` Redis 命名空间。

## 获取代码(测试机)

托管于 GitHub `joycar2010/hustle2026`,分支 **`dex`**(本分支仅含本项目)。在独立东京测试机上:

```bash
git clone -b dex https://github.com/joycar2010/hustle2026.git crossarb
cd crossarb
# 之后按下面"跑起来",或直接用"测试机一键部署"
```

后续更新拉取:`git pull origin dex`。

## 跑起来

```bash
python -m pip install -r requirements.txt
cp config.example.env .env          # 多市场强烈建议把 RPC 换成 Alchemy
python smoke.py                     # 一次性自检:逐市场打印一拍算账
python -m app.main                  # 起多市场并行采集 + 看板 http://127.0.0.1:8100
```
Windows 本机调试加 `PYTHONUTF8=1`。测试机一键部署见下。

## 监控的市场(默认,已链上核实)

| key | 标的/池 | 费档 | 币安 |
|---|---|---|---|
| BASE:ETH | WETH/USDC | 0.05% | ETHUSDT |
| BASE:BTC | cbBTC/USDC | 0.05% | BTCUSDT |
| BASE:VIRTUAL | VIRTUAL/USDC | 0.3% | VIRTUALUSDT(波动大/低效,最可能出错位) |

加标的**不改代码**:项目根放 `markets.json`(见 `markets.example.json`)覆盖默认集。

## 口径(全部 bps = 万分之一)

- `gross` 原始基差 =(币安 bid − DEX 含费滑点买价)/ 买价
- `net_entry` 入场净 = gross − taker − gas − recycle(**仅参考,易高估**)
- `net` **往返净(主指标,驱动机会判定)** = gross − 2×taker − 2×gas − 现货卖回 − recycle
- 机会 = `net > CROSSARB_MIN_NET_BPS`(默认 20bps = 0.2%)
- **gas 实时**:L2 执行费(eth_gasPrice)+ **L1 data 费(Base GasPriceOracle 实时 `getL1Fee`)**,
  按 ETH/USD(WETH/USDC 参考价)折美元;oracle 失败回退 `CROSSARB_L1_FEE_USD`。

资金费是持仓期另算现金流,不计入入场基差。

## 测试机一键部署(Amazon Linux 2,独立实例)

```bash
# 在已 clone/scp 到测试机的 crossarb 目录内:
CROSSARB_DOMAIN=crossarb.hustle2026.xyz CROSSARB_TLS=1 bash deploy/setup_testbox.sh
```
脚本只装 python venv + systemd 常驻(`crossarb-p0`)+ nginx 反代(+可选 certbot)。
**自带隔离自检**:若检测到本机有生产 `cex-*` 服务会拒绝部署(强调独立实例)。
看板进程只听 127.0.0.1,经 nginx 子域名对外。日志 `journalctl -u crossarb-p0 -f`。

## 已知边界(P0 可接受)

- L1 费实时(GasPriceOracle),用代表性 ~336B swap 字节估算,精确到字节无意义(<~1bps@$2500)。
- 现货卖回成本用入场滑点对称近似;要更准可接反向 quote。
- 公共 RPC 并发限频(429)会丢采样——多市场务必用 Alchemy/QuickNode 并把 `CROSSARB_RPC_CONCURRENCY` 调到 8。

## 数据

每拍逐市场追加 `data/ticks.csv`(全字段含 `market` 列),看板读 `/api/stats` 逐市场滚动统计。
影子跑 2-4 周后,用 CSV 算各市场机会频率/规模分布,作为是否进 P1 的依据。
