# 体育市场 Paper 模块

`bot.sports_markets`、`bot.sports_data`、`bot.sports_strategy` 和
`bot.sports_main` 构成一条独立的体育纸面链路。它只读取 Gamma 的公开
`/markets` 数据，筛选带有 sports 标签或体育 slug/question 的二元市场，
解析赛事、联赛、开赛/结束时间、outcomes、`clobTokenIds`、`negRisk`、tick、
流动性以及结算规则。

概率源通过 `SportsDataSource.probabilities(market)` 协议注入。默认
`MarketImpliedSource` 对 CLOB 价格归一化；`StaticSportsDataSource` 便于
回放与测试；`poisson_win_probability` 可作为足球、冰球模型的基础先验。
生产系统可替换为外部数据源，但数据源必须只读。

`SportsPaperService.run_once()` 执行发现、模型评分和保守风控（价格、edge、
最大纸面敞口），在内存中记录 `decisions` 和 `paper_simulated` orders。其
`snapshot()` 可直接作为 Dashboard 的实时摘要。`run_cycle(..., live=True)`
会抛出异常；模块没有 CLOB client、私钥或下单调用，因而不会影响 BTC/ETH
实盘。启用开关默认关闭：

```env
SPORTS_ENABLED=false
SPORTS_MAX_DAYS_AHEAD=30
SPORTS_MIN_EDGE=0.05
SPORTS_MIN_ENTRY_PRICE=0.05
SPORTS_MAX_ENTRY_PRICE=0.95
SPORTS_MAX_EXPOSURE_USD=5
SPORTS_ORDER_SIZE=1
SPORTS_CONFIRM_CHECKS=1
```

充分积累纸面决策和结算回放后，若要设计 live 适配器，应在单独的受审模块
中复用现有钱包/CLOB 凭据，并保持本模块的 `live=True` 拒绝不变。
