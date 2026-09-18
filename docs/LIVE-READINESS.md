# Polymarket 实盘与 AI 接入说明

## 当前状态

- 服务器运行 `polymarket-paper.service` 与 `polymarket-weather-paper.service`，均没有 `--live` 参数。
- 交易钱包查询地址是 `FUNDER_ADDRESS` / `DEPOSIT_WALLET_ADDRESS`，当前 pUSD 约 12.99，持仓市值为 0。
- 系统设置中的模型 API 是 OpenAI 兼容接口。裸域名会自动规范为 `/v1`，API Key 只以掩码返回。
- `api.liaryai.com` 网关响应可能需要 15–30 秒，服务器当前已将测试超时调为 60 秒。
- 当前模型调用只提供模型列表探测和只读连接测试，不会进入策略或调用下单函数。

## 交易全链路

1. Gamma `/events` 发现当前 BTC/ETH 5 分钟市场并解析 token、时间、tick size 和 negRisk。
2. CLOB `/book` 提供买一/卖一；RTDS TWAP 提供价格差，必要时使用 Chainlink candle 回退。
3. 策略根据价格区间、净优势、Delta 过滤、确认次数、时间窗口和单边/加仓规则生成决策。
4. 风控检查 pUSD 余额、订单频率、未结算持仓、每日盈亏和连续亏损后才允许下单。
5. 实盘使用 CLOB API 凭据创建 FOK 买单；卖出使用 FOK/FAK，提交超时会通过近期成交回查并记录为待确认。
6. SQLite 保存订单/决策；市场关闭后由 Gamma outcomePrices 判定结果并回写 PnL。无效或平局结果会保持未结算。
7. 天气扫描是独立的 Open-Meteo ensemble → Gamma → CLOB 路径，当前服务为 paper。

## AI 辅助边界

系统设置中的“AI 只读顾问”用于配置未来的分析接入。安全接入方式是将行情、盘口、信号和风控状态作为上下文发送给模型，由模型返回建议供人工审核；最终的 `place_buy_*` / `place_sell_*` 仍由确定性策略和风控函数控制。不要把私钥、CLOB 密钥或签名权限发送给模型，也不要让模型直接调用下单工具。

启用 AI 前先在“系统设置”中保存 Base URL、模型和 API Key，再点击“拉取模型”和“测试连接”。当前服务器已经验证 `api.liaryai.com/v1/models` 和 `gpt-6-astra` 测试成功。

## 实盘前置条件

执行 `scripts/run_live.sh` 前必须满足：

- `scripts/verify_setup.py` 通过，确认 Polygon、Deposit Wallet、余额、CLOB 凭据和 allowance。
- 使用与 Polymarket 账户 Deposit Wallet 所属账户一致的签名钱包；当前服务器的 signer 与 0x7608 Deposit Wallet 归属尚未通过验证。
- 已执行 `scripts/derive_api_creds.py`，并配置 `CLOB_API_KEY`、`CLOB_API_SECRET`、`CLOB_API_PASSPHRASE`。
- 先用 paper 模式长时间验证；实盘风险参数必须是保守值（单笔风险不超过 5%、正净优势、至少一次确认、余额和每日亏损上限均启用）。
- `scripts/live_preflight.py` 和 `scripts/verify_setup.py` 都通过后，`run_live.sh` 才会创建 BTC/ETH 实盘进程；ETH 还要求 `ETH_TRADING_ENABLED=true`。

当前 paper 调参使用了接近全仓的测试参数，实盘预检会主动拒绝这些参数。
