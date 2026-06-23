# CrossArb P1 真金运维手册(dex.hustle2026.xyz)

单链 OP:BTC 真金套利验证。**目标**:7-10 天测真实兑现率/可捕获率(P0 永远测不到的变量)。

## 架构 / 凭证
- 机器:EC2 `i-085ce362c73e20789` @ ap-northeast-1(13.230.29.158),代码 `~/crossarb`,系统 python3。
- KMS 钱包 `0x7CB02F6746b69C4128A93fABFB6aBBc34d1074d0` @ Optimism;KMS key `002cffe4-...` @ ap-northeast-1。
- dex 机经 **EC2 IAM role**(instanceRole,带 kms:Sign/GetPublicKey)访问 KMS,凭证自动轮换不落地。
- 币安独立账户(IP 白名单 13.230.29.158,合约开/提现关,**双向持仓模式**)。
- 三档:`CROSSARB_EXEC_MODE` = dry-run / testnet / live(在 `~/crossarb/.env`)。

## 安全护栏(已实战验证)
- 顺序:先链上买入 → 再币安做空(防先空后买失败裸空)。
- 裸腿:做空失败→复核 clientOrderId→确认未成交才卖回止损。
- 数量:回执 Transfer 事件实测到账(非余额差);取整差额>$6 自动卖回;偏离报价>3% 拒绝。
- 链上超时:不放弃→终态查询;仍 pending 抛 PendingTxError→**停机待人工**(防双花)。
- 熔断:单数(20)/单日支出($3000)/连亏5笔/**连续3笔裸腿**→停机;**重启从 exec_log.csv 续算当日计数(不绕过)**。
- nonce:approve 回执后用 confirmed_nonce 派生 swap(防 L2 pending 滞后冲突)。
- 币安时钟同步(防 -1021);触发线 net>25bps;execute 名义额 `CROSSARB_EXEC_NOTIONAL_USD`。

## 部署
```bash
# 1) 安装服务
sudo cp ~/crossarb/deploy/crossarb-exec.service /etc/systemd/system/
sudo systemctl daemon-reload

# 2) 先 dry-run 观察(默认),确认决策正常
grep CROSSARB_EXEC_MODE ~/crossarb/.env   # 应 dry-run
sudo systemctl enable --now crossarb-exec
sudo journalctl -u crossarb-exec -f       # 看轮询/达标判断

# 3) 切 live(确认 dry-run 决策无误后)
sudo systemctl stop crossarb-exec
sed -i 's/^CROSSARB_EXEC_MODE=.*/CROSSARB_EXEC_MODE=live/' ~/crossarb/.env
sudo systemctl start crossarb-exec
```

## 日常监控
```bash
# 服务状态
sudo systemctl status crossarb-exec
# 实时日志
sudo journalctl -u crossarb-exec -f
# 成交记录(每笔尝试)
tail -20 ~/crossarb/data/exec_log.csv
# 当日成交统计
awk -F, 'NR>1{print $19}' ~/crossarb/data/exec_log.csv | sort | uniq -c
```

## 对账(每日至少一次)
```bash
cd ~/crossarb && PYTHONUTF8=1 python3 -c "
import sys; sys.path.insert(0,'.')
from app.chain_rpc import ChainRpc; from app.chains import chain_of
from app.binance_exec import BinanceExec, FUTURES_LIVE; from app.config import cfg
ch=chain_of('OP'); rpc=ChainRpc('https://mainnet.optimism.io',ch.chain_id)
W=cfg.exec_wallet_addr
wbtc=rpc.erc20_balance('0x68f180fcCe6836688e9084f035309E29Bf0A2095',W)/1e8
print('链上 WBTC:', wbtc, '| USDC:', rpc.erc20_balance(ch.stable,W)/1e6, '| ETH:', rpc.eth_balance(W)/1e18)
bn=BinanceExec(cfg.bn_api_key,cfg.bn_api_secret,FUTURES_LIVE); bn.sync_time()
pos=[p for p in bn._request('GET','/fapi/v2/positionRisk',{'symbol':'BTCUSDT'}) if float(p.get('positionAmt',0))!=0]
print('币安持仓:', pos or '无')
# 核心:两腿应大致匹配(链上WBTC ≈ 币安空头绝对值)。不匹配=有裸腿,排查!
"
```

## 应急
| 症状 | 处置 |
|---|---|
| 日志出现 `BUY_PENDING_HALT` | 链上买入状态未知。先 `git ...`查 tx 是否上链(Optimistic Explorer),再人工核对两腿,平掉裸腿后重启服务 |
| 日志出现 `卖回也失败,停机待人工` | 真裸多残留!立即手动 `python3 canary_close.py --yes` 或手动卖回 WBTC |
| `连续3笔裸腿` 停机 | 币安疑持续故障(API/IP/限频)。查币安连通性,修复后重启 |
| 余额异常/两腿不匹配 | 立即 stop 服务,对账,手动 canary_close 平干净 |
| 紧急全停 | `sudo systemctl stop crossarb-exec` + 手动平两腿 |

## 停止验证(7-10 天后)
```bash
sudo systemctl stop crossarb-exec
sudo systemctl disable crossarb-exec
# 平掉任何残留持仓
cd ~/crossarb && CROSSARB_EXEC_MODE=live PYTHONUTF8=1 python3 canary_close.py --yes
# 分析可捕获率:exec_log.csv 里 capture_ratio 列(realized_net / paper_net)
```

## 关键指标(验证产出)
- **兑现率**:OK 笔数 / EXECUTE 笔数(两腿都成交占比)
- **可捕获率**:capture_ratio 列均值(实际 net / 纸面 net,P0 高估多少)
- **滑移**:buy_eff_price vs 报价、short_avg_price vs bid
- **裸腿率**:SHORT_FAIL_NAKED 笔数(币安腿可靠性)
