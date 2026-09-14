import asyncio
import logging
from decimal import Decimal, ROUND_UP

from engine.config_loader import FundRulesSnapshot
from engine.trading.binance_trading import BinanceTradingClient
from engine.trading.quantity_calc import round_to_step
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

# dust→BNB 单资产名义上限(USDT 估值不直接拿,用 toBNB 字段;此处仅作"只扫小额"语义说明):
# 币安 dust-btc 接口本身只返回可兑换的小额资产,故无需再设阈值;但排除主动交易币的残券由
# debt_converter 负责(那是"欠款",这里是"正余额小额"),两者互补不重叠。
# dust→BNB 跳过集:BNB 本身 + 所有稳定币(USDT 是套利本位/操作币,绝不能兑成 BNB)。
# 主动交易币的"欠款"残券由 debt_converter 负责(那是负债),这里只扫"正余额小额非稳定币"。
_DUST_SKIP = {"BNB", "USDT", "BUSD", "USDC", "FDUSD", "TUSD", "DAI"}


async def run_bnb_check(
    client: BinanceTradingClient,
    rules: FundRulesSnapshot,
    notifier: FeishuSender,
    account_note: str,
    bnb_burn_enabled: bool | None = None,
):
    """周期 BNB 维护(每 bnb_convert_interval_sec 调一次):
    1) 按开关下发 BNB 抵扣手续费;
    2) BNB 余额低于「数量×触发%」→ 买入 bnb_buy_amount 补足;
    3) BNB 欠款 > 阈值 → 还款(持有不足则买入补足再还,对齐 UI「买入并还款」);
    4) 小额资产兑换 BNB(dust→BNB,对齐 UI「小额兑换BNB间隔」)。
    """
    try:
        # 1) BNB 抵扣开关:仅显式开启时下发 on,关闭/默认不动账户现状
        if bnb_burn_enabled:
            try:
                await client.set_bnb_burn(spot=True, interest=True)
            except Exception as be:
                logger.warning(f"set_bnb_burn(on) failed for {account_note}: {be}")

        # 2) BNB 低额自动补:free < 数量 且 ≤ 数量×触发%  → 买入固定数量
        balances = await client.get_bnb_balance()
        bnb_free = balances.get("margin", Decimal("0"))
        trigger = rules.bnb_min_quantity * rules.bnb_buy_trigger_pct / 100
        if bnb_free <= trigger and rules.bnb_buy_amount > 0:
            logger.info(f"BNB low ({bnb_free} ≤ {trigger}), buying {rules.bnb_buy_amount}")
            try:
                await client.spot_market_buy_qty("BNBUSDT", rules.bnb_buy_amount)
                await notifier.send("BNB购买", f"账户: {account_note}\n购买: {rules.bnb_buy_amount} BNB",
                                    throttle_key=f"bnbbuy:{account_note}")
            except Exception as be:
                logger.warning(f"BNB top-up buy failed {account_note}: {be}")

        # 3) BNB 欠款自动还款(持有不足则买入补足再还)
        if rules.bnb_debt_auto_repay:
            await _repay_bnb_debt(client, rules, notifier, account_note)

        # 4) 小额资产兑换 BNB(dust→BNB)
        await _convert_dust_to_bnb(client, notifier, account_note)

    except Exception as e:
        logger.warning(f"BNB manager error: {e}")


async def _repay_bnb_debt(client, rules, notifier, account_note):
    """BNB 欠款 > 阈值 → 还清。持有 free ≥ 欠款直接还;不足则用 USDT 买入缺口(NO_SIDE_EFFECT,
    不再借)再还,对齐 UI「买入并还款」。买入向上取整到 lot 以确保覆盖整笔欠款。"""
    try:
        margin_info = await client.get_margin_account()
    except Exception as e:
        logger.warning(f"BNB debt check get_margin_account failed {account_note}: {e}")
        return
    bnb = next((a for a in margin_info.get("userAssets", []) if a.get("asset") == "BNB"), None)
    if not bnb:
        return
    borrowed = Decimal(str(bnb.get("borrowed", "0"))) + Decimal(str(bnb.get("interest", "0")))
    if borrowed <= rules.bnb_debt_threshold:
        return
    free = Decimal(str(bnb.get("free", "0")))

    # 持有不足 → 买入缺口(向上取整到 lot,小幅缓冲覆盖买入滑点/利息累积)
    if free < borrowed:
        shortfall = borrowed - free
        try:
            lot = await client.get_lot_size("BNBUSDT", "spot")
            step = lot["stepSize"]
            # 向上取整到 step + 1 档缓冲
            buy_qty = round_to_step(shortfall, step) + Decimal(step)
            if buy_qty < shortfall:  # 取整后仍小于(理论不会)→ 再补一档
                buy_qty += Decimal(step)
            await client.spot_market_buy_qty("BNBUSDT", buy_qty)
            await asyncio.sleep(2)  # 杠杆户买入到账秒级延迟
            # 重读 free,按实际可还
            margin_info = await client.get_margin_account()
            bnb = next((a for a in margin_info.get("userAssets", []) if a.get("asset") == "BNB"), bnb)
            free = Decimal(str(bnb.get("free", "0")))
            borrowed = Decimal(str(bnb.get("borrowed", "0"))) + Decimal(str(bnb.get("interest", "0")))
        except Exception as be:
            logger.warning(f"BNB debt buy-to-cover failed {account_note}: {be}")

    repay_amount = min(borrowed, free)
    if repay_amount > 0:
        try:
            await client.margin_repay("BNB", repay_amount)
            logger.info(f"BNB debt repaid: {repay_amount} ({account_note})")
            await notifier.send("BNB还款", f"账户: {account_note}\n还款: {repay_amount} BNB",
                                throttle_key=f"bnbrepay:{account_note}")
        except Exception as re:
            logger.warning(f"BNB repay failed {account_note}: {re}")


async def _convert_dust_to_bnb(client, notifier, account_note):
    """现货钱包小额资产一次性兑换成 BNB(币安 dust→BNB)。空清单跳过;币安频控/失败吞掉。"""
    try:
        info = await client.get_dust_assets()
    except Exception as e:
        logger.debug(f"dust list failed {account_note}: {e}")
        return
    details = info.get("details", []) if isinstance(info, dict) else []
    assets = [d.get("asset") for d in details if d.get("asset") and d.get("asset") not in _DUST_SKIP]
    if not assets:
        return
    try:
        res = await client.dust_to_bnb(assets)
        total_bnb = res.get("totalTransfered") or res.get("totalServiceCharge") or ""
        logger.info(f"dust→BNB converted {len(assets)} assets ({account_note}): {assets}")
        await notifier.send("小额兑换BNB",
                            f"账户: {account_note}\n兑换 {len(assets)} 个小额资产为 BNB: {','.join(assets)}",
                            throttle_key=f"dust:{account_note}")
    except Exception as e:
        # 频控(每资产~6h)/无可换 → 正常,debug 即可
        logger.debug(f"dust→BNB convert skipped {account_note}: {e}")
