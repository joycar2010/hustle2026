import asyncio
import logging
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_UP

from app.db.session import SessionLocal
from engine.models import Position, TradeLog
from engine.config_loader import GlobalRulesSnapshot
from engine.spread_feed import SpreadFeed, SpreadSnapshot
from engine.trading.binance_trading import BinanceTradingClient, BinanceAPIError
from engine.trading.quantity_calc import usdt_to_quantity, round_to_step
from engine.notify.feishu_sender import FeishuSender

logger = logging.getLogger(__name__)

# 子账户→归属用户 缓存(归属不可变,进程级缓存;未命中查 DB 后回填)。
# 用于给 TradeLog 补 user_id —— 历史上 _log_trade 漏写该字段致流水「用户」列全空。
_uid_cache: dict[int, int | None] = {}


def _resolve_user_id(db, sub_account_id: int):
    if sub_account_id in _uid_cache:
        return _uid_cache[sub_account_id]
    uid = None
    try:
        from app.db.models import SubAccount
        uid = db.query(SubAccount.user_id).filter(SubAccount.id == sub_account_id).scalar()
    except Exception:
        return None  # 解析失败不缓存,下次再试;绝不因补 user_id 影响下单/记账
    _uid_cache[sub_account_id] = uid
    return uid


def _publish_balance_refresh(user_id):
    """借/还币成功后请求 BalancePusher 对该用户做一次「写后即时余额刷新」(事件驱动,绕开 10s 轮询),
    让 dashboard 子账户行的现币/借币/利息秒级刷新(问题4)。同步轻量 publish(与本模块 -3045 冷却同款);
    失败静默——余额最终仍由 10s 轮询兜底,绝不因刷新影响已成功的借/还币。"""
    if user_id is None:
        return
    try:
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.publish("balance:refresh", str(user_id))
        rc.close()
    except Exception:
        pass


def _publish_position(position, user_id):
    """状态机推进(借到币/对冲/还币)后把 position 实时推给前端(position:updates),让 dashboard
    子账户行不等 15s REST 轮询就切换成真实持仓行 —— 修复"手推借到币后黄框列(现-期/最大可借/
    现币/借币/保证金/净值)要手动刷新才出"。sub_account_id 用 int(与前端 balanceMap 的 account_id
    同类型,get 才命中)。失败静默,持仓最终仍由轮询兜底。"""
    if user_id is None:
        return
    try:
        import json as _json
        import redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.publish("position:updates", _json.dumps({
            "id": position.id,
            "user_id": int(user_id),
            "sub_account_id": int(position.sub_account_id),
            "symbol": position.symbol,
            "status": position.status,
            "borrow_qty": str(position.borrow_qty or "0"),
        }))
        rc.close()
    except Exception:
        pass


TAKER_FEE_RATE = Decimal("0.00075")
FEE_BUFFER = Decimal("1.0015")
BORROW_FRESH_MS = 3000   # 借币二次确认: 点差快照超此毫秒数视为陈旧,不在已死/过期点差上完成借币


def _compute_net_expect(spread_short_pct, notional_usdt: float, interest_rate_daily,
                        hold_hours: float, f_spot, f_fut, buffer_pct) -> tuple[float, dict]:
    """开仓前净期望收益 E(USDT,统一绝对值口径)。所有输入折成 USDT 再比较,避免 %/币/分数混算。
      E = 点差捕获 − 利息(持有期) − 4腿手续费 − tick/滑点摩擦
    - 点差捕获 = spread_short(%)/100 × 名义额。本策略借币→卖现货→多合约,收敛即赚这段基差。
    - 利息 = 日利率 × 名义额 × 持有小时/24。持有小时取"预期最短持仓"(≥1,币安按小时头计息)。
    - 4腿手续费 = (现卖+现买)×f_spot + (期开+期平)×f_fut = 2×名义×(f_spot+f_fut)。
    - tick摩擦 = open_spread_buffer(%)/100 × 名义额(近似腿间滑点/tick 步进,现状唯一摩擦旋钮)。
    资金费预期第一版不计入(短持有常跨不到8h结算,且可正可负):作为已知保守偏差,E 偏低=宁可少开。
    返回 (E, 分项dict)。E≤0 = 结构性亏损,不该开。"""
    n = float(notional_usdt or 0)
    cap = float(spread_short_pct or 0) / 100.0 * n
    interest = float(interest_rate_daily or 0) * n * max(1.0, hold_hours) / 24.0
    fee = 2.0 * n * (float(f_spot or 0) + float(f_fut or 0))
    tick = float(buffer_pct or 0) / 100.0 * n
    e = cap - interest - fee - tick
    return e, {
        "notional_usdt": round(n, 4), "spread_capture": round(cap, 4),
        "interest_cost": round(interest, 4), "fee_cost": round(fee, 4),
        "tick_cost": round(tick, 4), "funding_expect": 0.0, "E": round(e, 4),
    }


def _publish_net_eval(user_id, symbol: str, e: float, br: dict, decision: str, gate_mode: str):
    """把开仓净期望评估写 Redis(供 coinadmin market-monitor 实时 E 榜)。
    键 engine:{uid}:neteval:{SYMBOL},60s TTL 保鲜;失败静默,绝不影响借币主流程。"""
    if user_id is None:
        return
    try:
        import json as _json, time as _t, redis as _r
        from app.config import settings as _s
        rc = _r.from_url(_s.redis_url, decode_responses=True)
        rc.setex(f"engine:{user_id}:neteval:{symbol}", 60, _json.dumps({
            **br, "decision": decision, "gate_mode": gate_mode, "ts": int(_t.time() * 1000),
        }))
        rc.close()
    except Exception:
        pass


async def _get_asset_debt(client: BinanceTradingClient, asset: str) -> tuple[Decimal, Decimal]:
    margin_info = await client.get_margin_account()
    for a in margin_info.get("userAssets", []):
        if a["asset"] == asset:
            borrowed = Decimal(str(a.get("borrowed", "0")))
            interest = Decimal(str(a.get("interest", "0")))
            return borrowed + interest, interest
    return Decimal("0"), Decimal("0")


def _fc_symbol_lock(fc, symbol: str) -> asyncio.Lock:
    """Per-symbol lock attached to the futures client. hedge_via_master 下该 client 被
    全部 worker 共享 —— 同 symbol 的开/平在共享净仓上必须串行,避免 reduceOnly 拒单/过量平仓。
    (子账户自有 client 时各 worker 各一份锁表,无跨账户竞争,加锁无副作用。)"""
    locks = getattr(fc, "_symbol_locks", None)
    if locks is None:
        locks = {}
        fc._symbol_locks = locks
    return locks.setdefault(symbol, asyncio.Lock())


_precheck_warn_ts: dict[str, float] = {}
_topup_ts: dict[str, float] = {}


def _load_fund_floor_and_sources() -> tuple[Decimal, list[str]]:
    """读全局 FundRules:(源钱包留底 base_margin_amount, 给合约钱包供资的源顺序)。
    源取 transfer_order 中的非 futures 项(spot/margin),空则默认 [spot, margin]。同步,to_thread 调。"""
    db = SessionLocal()
    try:
        from app.db.models import FundRules
        fr = db.query(FundRules).first()
        floor = Decimal(str(fr.base_margin_amount)) if fr and fr.base_margin_amount is not None else Decimal("0")
        raw = (fr.transfer_order if fr and fr.transfer_order else "spot,margin")
        sources = [s.strip() for s in raw.split(",") if s.strip() in ("spot", "margin")]
        if not sources:
            sources = ["spot", "margin"]
        return floor, sources
    finally:
        db.close()


async def _topup_master_futures(fc, symbol: str, deficit: Decimal) -> bool:
    """hedge_via_master 主账户合约钱包欠资时,从主账户 spot/margin 钱包**账户内**划入 USDT
    (fc.transfer,非跨账户),让对冲能继续。源钱包留底 base_margin_amount,按 transfer_order
    顺序累计补足 deficit;30s/币种 节流防循环。任一笔成功返回 True。
    任何异常静默(不抛),调用方据再查结果决定放行或回退 hold —— 绝不因补给失败把持仓推入回滚空转。"""
    now = time.monotonic()
    if now - _topup_ts.get(symbol, 0) < 30:
        return False
    _topup_ts[symbol] = now
    try:
        floor, sources = await asyncio.to_thread(_load_fund_floor_and_sources)
        remaining = deficit.quantize(Decimal("0.01"), rounding=ROUND_UP)
        moved = Decimal("0")
        for src in sources:
            if remaining <= 0:
                break
            try:
                if src == "spot":
                    acct = await fc.get_spot_account()
                    free = next((Decimal(str(b.get("free", "0"))) for b in acct.get("balances", [])
                                 if b.get("asset") == "USDT"), Decimal("0"))
                    ttype = "MAIN_UMFUTURE"
                else:  # margin
                    acct = await fc.get_margin_account()
                    free = next((Decimal(str(a.get("free", "0"))) for a in acct.get("userAssets", [])
                                 if a.get("asset") == "USDT"), Decimal("0"))
                    ttype = "MARGIN_UMFUTURE"
                pullable = free - floor
                amt = min(remaining, pullable).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                if amt <= 0:
                    continue
                await fc.transfer(ttype, "USDT", amt)
                moved += amt
                remaining -= amt
                logger.info(f"hedge_via_master topup: {amt} USDT {src}->futures (master) for {symbol}")
            except Exception as e:
                logger.warning(f"hedge_via_master topup {src}->futures failed ({symbol}): {e}")
                continue
        return moved > 0
    except Exception as e:
        logger.warning(f"hedge_via_master topup failed {symbol}: {e}")
        return False


async def _master_margin_precheck(fc, symbol, qty, spread, notifier, account_note) -> Decimal | None:
    """hedge_via_master: 对冲前查主账户合约可用余额(按该 symbol 当前杠杆估算所需保证金,
    留 10% 缓冲)。带账户级预留(挂在共享 client 上的 in-flight 计数,锁内比较+占用),
    防止多 worker 并发用同一余额各自通过。通过返回预留额(调用方 finally 归还)。
    欠资时先尝试主账户内自动补给(spot/margin→futures)再复检一次;仍不足或查询异常 → None,
    调用方把持仓留在 BORROWED_IDLE 等下轮 —— 绝不进入「卖出→合约失败→回滚」的空转。"""
    try:
        price = spread.fut_ask if (getattr(spread, "fut_ask", None) and spread.fut_ask > 0) else spread.spot_ask
        pr = await fc.futures_position_risk(symbol)
        lev = Decimal(str((pr or {}).get("leverage") or "20"))
        if lev <= 0:
            lev = Decimal("20")
        need = (qty * price / lev) * Decimal("1.1")

        rlock = getattr(fc, "_reserve_lock", None)
        if rlock is None:
            rlock = asyncio.Lock()
            fc._reserve_lock = rlock
        async with rlock:
            acct = await fc.get_futures_account()
            avail = Decimal(str(acct.get("availableBalance", "0")))
            reserved = getattr(fc, "_margin_reserved", Decimal("0"))
            if avail - reserved >= need:
                fc._margin_reserved = reserved + need
                return need
            deficit = need - (avail - reserved)

        # 欠资 → 主账户内自动补给(锁外做转账/查询,避免占用 reserve 锁阻塞其他 worker),再复检一次
        if await _topup_master_futures(fc, symbol, deficit):
            async with rlock:
                acct = await fc.get_futures_account()
                avail = Decimal(str(acct.get("availableBalance", "0")))
                reserved = getattr(fc, "_margin_reserved", Decimal("0"))
                if avail - reserved >= need:
                    fc._margin_reserved = reserved + need
                    logger.info(f"hedge_via_master: {symbol} 自动补给后合约保证金已满足(need≈{need:.4f})")
                    return need

        now = time.monotonic()
        if now - _precheck_warn_ts.get(symbol, 0) > 300:
            _precheck_warn_ts[symbol] = now
            logger.warning(f"hedge_via_master: master avail insufficient for {symbol} (need≈{need:.4f}); hold BORROWED_IDLE")
            await notifier.notify_error(
                account_note, f"hedge {symbol}",
                f"主账户合约可用余额不足(需≈{need:.2f} USDT),自动补给未能补足,持仓停在待对冲",
            )
        return None
    except Exception as e:
        logger.warning(f"hedge_via_master: precheck failed {symbol}: {e}; hold BORROWED_IDLE")
        return None


def _release_margin_reserve(fc, amount: Decimal):
    if fc is None or amount is None:
        return
    try:
        fc._margin_reserved = max(Decimal("0"), getattr(fc, "_margin_reserved", Decimal("0")) - amount)
    except Exception:
        pass


def _ensure_avg_price(o: dict) -> dict:
    """executedQty>0 但 avgPrice<=0 时,用 cumQuote/executedQty 兜底算成交均价并回写。
    币安合约 MARKET RESULT 应答的 avgPrice 偶发填充滞后(executedQty 已>0 却 avgPrice=0),
    直接落库会让 futures_long_price/futures_close_price=0 → 合约腿 PnL 恒算 0(漏算整条合约腿)。"""
    try:
        eq = Decimal(str(o.get("executedQty", "0") or "0"))
        ap = Decimal(str(o.get("avgPrice", "0") or "0"))
        if eq > 0 and ap <= 0:
            cq = Decimal(str(o.get("cumQuote", "0") or "0"))
            if cq > 0:
                o = dict(o)
                o["avgPrice"] = str(cq / eq)
    except Exception:
        pass
    return o


async def _confirm_futures_result(fc, symbol: str, result: dict) -> dict:
    """市价单应答补齐:executedQty==0 → 轮询终态;executedQty>0 但 avgPrice<=0(RESULT 均价/cumQuote
    填充滞后)→ 先 cumQuote/executedQty 兜底,仍缺则回查订单。每次查询【独立 try】(下单瞬间 -2013
    订单查不到 / 网络瞬时错 不再中断整轮回查),窗口放宽到 ~3.2s 覆盖币安成交聚合延迟。
    否则合约腿价落 0 → realized_pnl 漏算整条合约腿(实测 futures_long_price=0 致 pnl 虚高 +19.8)。"""
    def _avg(o):
        try:
            return Decimal(str((o or {}).get("avgPrice", "0") or "0"))
        except Exception:
            return Decimal("0")
    try:
        eq0 = Decimal(str(result.get("executedQty", "0") or "0"))
        oid = result.get("orderId")
        if eq0 > 0:
            result = _ensure_avg_price(result)
            if _avg(result) > 0 or not oid:
                return result
            for _ in range(8):
                await asyncio.sleep(0.4)
                try:
                    o = _ensure_avg_price(await fc.futures_get_order(symbol, str(oid)))
                except Exception:
                    continue
                if _avg(o) > 0:
                    return o
            return result
        if not oid:
            return result
        for _ in range(8):
            await asyncio.sleep(0.4)
            try:
                o = await fc.futures_get_order(symbol, str(oid))
            except Exception:
                continue
            if Decimal(str(o.get("executedQty", "0") or "0")) > 0 or \
               o.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                return _ensure_avg_price(o)
        return result
    except Exception:
        return result


async def _query_filled_by_client_id(fc, symbol: str, coid: str) -> Decimal:
    """下单响应丢失(超时/5xx「状态未知」)后,按 clientOrderId 复核实际成交量。
    -2013(订单不存在)= 未送达 → 0;查询连续失败按 0 计但留告警日志。"""
    for _ in range(3):
        try:
            o = await fc.futures_get_order_by_client_id(symbol, coid)
            return Decimal(str(o.get("executedQty", "0")))
        except BinanceAPIError as e:
            if e.api_code == -2013:
                return Decimal("0")
        except Exception:
            pass
        await asyncio.sleep(0.5)
    logger.error(f"ambiguous futures order unresolved: {symbol} clientOrderId={coid} — verify manually")
    return Decimal("0")


def _log_trade(db, position_id: int, sub_account_id: int, action: str, symbol: str,
               side: str = None, quantity: Decimal = None, price: Decimal = None,
               order_id: str = None, status: str = "SUCCESS", error: str = None, latency: int = None):
    db.add(TradeLog(
        position_id=position_id,
        sub_account_id=sub_account_id,
        user_id=_resolve_user_id(db, sub_account_id),   # 按子账户归属补 user_id(流水用户列依赖此)
        action=action,
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        order_id=order_id,
        status=status,
        error_message=error,
        latency_ms=latency,
    ))
    db.commit()


SPOT_MAKER_WAIT_SEC = 3.0    # maker 挂单最长等待成交,超时撤单转市价兜底
SPOT_MAKER_POLL_SEC = 0.4


async def _spot_maker_fill(client, symbol: str, side: str, qty: Decimal, spread,
                           spot_lot: dict, is_margin: bool = True) -> dict:
    """现货腿 maker 成交(P1 现货 maker 化):挂 post-only 限价(LIMIT_MAKER)做挂单方省手续费;
    最长等 SPOT_MAKER_WAIT_SEC,未全成 → 撤单 → 剩余市价兜底,保证必成交、绝不留单腿。
    返回结构兼容市价单:{executedQty, orderId, _avg}(_avg=成交均价)。post-only 若会穿越盘口被币安
    -2010 拒单,直接市价兜底(此刻点差已收窄,做 taker 也认)。"""
    filters = await client._get_spot_filters(symbol)
    tick = filters["tick"]
    if side == "SELL":
        px = round_to_step(spread.spot_ask, tick) if getattr(spread, "spot_ask", 0) else None
        maker_fn = client.spot_limit_maker_sell
        market_fn = client.spot_market_sell
    else:
        px = round_to_step(spread.spot_bid, tick) if getattr(spread, "spot_bid", 0) else None
        maker_fn = client.spot_limit_maker_buy
        market_fn = client.spot_market_buy_qty
    filled = Decimal("0"); value = Decimal("0"); oid = ""
    if px and px > 0:
        try:
            r = await maker_fn(symbol, qty, px, is_margin)
            oid = str(r["orderId"])
            waited = 0.0; done = False
            while waited < SPOT_MAKER_WAIT_SEC:
                await asyncio.sleep(SPOT_MAKER_POLL_SEC); waited += SPOT_MAKER_POLL_SEC
                o = await client.spot_query_order(symbol, oid, is_margin)
                if o.get("status") == "FILLED":
                    filled = Decimal(str(o.get("executedQty", "0")))
                    value = Decimal(str(o.get("cummulativeQuoteQty", "0")))
                    done = True; break
            if not done:
                try:
                    c = await client.spot_cancel_order(symbol, oid, is_margin)
                    filled = Decimal(str(c.get("executedQty", "0")))
                    value = Decimal(str(c.get("cummulativeQuoteQty", "0")))
                except Exception:
                    o = await client.spot_query_order(symbol, oid, is_margin)
                    filled = Decimal(str(o.get("executedQty", "0")))
                    value = Decimal(str(o.get("cummulativeQuoteQty", "0")))
        except BinanceAPIError as e:
            if getattr(e, "api_code", None) != -2010 and "-2010" not in str(e):
                raise   # 非"会立即成交被拒",真错误上抛
    # 剩余市价兜底(必成交,不留单腿)
    remaining = round_to_step(qty - filled, spot_lot["stepSize"])
    if remaining > 0:
        mr = await market_fn(symbol, remaining, is_margin)
        mq = Decimal(str(mr.get("executedQty", "0")))
        filled += mq
        value += mq * _avg_fill_price(mr)
        oid = str(mr.get("orderId", oid))
    avg = (value / filled) if filled > 0 else Decimal("0")
    return {"executedQty": str(filled), "orderId": oid, "_avg": avg}


async def execute_borrow(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    spread_feed: SpreadFeed = None,
    min_spread: Decimal = None,
    user_id: int = None,
) -> int | None:
    """Phase 1: borrow the coin and hold it idle in the margin account (BORROWED_IDLE).
    Net-flat (owe coin, hold coin) — no directional exposure. Returns position id or None."""
    base_asset = symbol.replace("USDT", "")
    confirm_spread = rules.open_spread if min_spread is None else min_spread
    db = SessionLocal()
    position = Position(
        sub_account_id=sub_account_id,
        symbol=symbol,
        base_asset=base_asset,
        status="PENDING_BORROW",
        user_id=user_id,
    )
    db.add(position)
    db.commit()
    db.refresh(position)
    pos_id = position.id

    try:
        # interest-rate filter
        t0 = time.monotonic()
        interest_rate = await client.get_margin_interest_rate(base_asset)
        latency = int((time.monotonic() - t0) * 1000)
        if interest_rate > rules.interest_filter / 100:
            position.status = "FAILED"
            position.error_message = f"Interest rate {interest_rate} too high"
            db.commit()
            db.close()
            return None
        position.borrow_interest_rate = interest_rate

        # delay + re-confirm spread still above the borrow threshold(含 ts 新鲜度,防陈旧缓存)
        # 负阈值(挂单差<0)=任何点差都借的囤券意图,点差质量/新鲜度与借币决策无关 → 跳过两道确认闸。
        # 否则冷门币(bookTicker 仅价/量变才推,常几十秒~分钟无 tick)会在「睡 borrow_delay_sec 后
        # 要求快照 ≤BORROW_FRESH_MS(3s) 新鲜」上反复 FAILED,借币落地被拖成分钟级随机延迟。
        skip_confirm = confirm_spread is not None and confirm_spread < 0
        # 负阈值零等待:确认闸已跳过时,borrow_delay_sec 的唯一意义(睡后复核点差)不复存在,
        # 这 3s 纯属死等 → 连同省去,借币立即执行。正阈值路径行为不变。
        if not skip_confirm:
            await asyncio.sleep(rules.borrow_delay_sec)
        if spread_feed:
            current = spread_feed.get_symbol(symbol)
            if skip_confirm:
                if current:
                    spread = current   # 有新快照就用(仅用于数量换算),陈旧也不拦
            else:
                now_ms = int(time.time() * 1000)
                fresh = bool(current and getattr(current, "ts", 0) and now_ms - int(current.ts) <= BORROW_FRESH_MS)
                if not fresh or current.spread_short <= confirm_spread:
                    position.status = "FAILED"
                    position.error_message = (
                        f"Spread degraded/stale after delay: "
                        f"{current.spread_short if current else 'N/A'}% <= {confirm_spread}% 或快照陈旧"
                    )
                    db.commit()
                    db.close()
                    return None
                spread = current

        # quantity
        lot_info = await client.get_lot_size(symbol, "spot")
        price = spread.spot_ask
        from app.db.models import SymbolRule, AccountSymbolRule, SubAccount
        # 「金额限制」(借币金额上限,USDT)解析: 账户单币 → 单币通用 → 子账户全局
        cap_usdt = None
        asr = db.query(AccountSymbolRule).filter(
            AccountSymbolRule.sub_account_id == sub_account_id,
            AccountSymbolRule.symbol.in_([symbol, base_asset]),
        ).first()
        if asr and asr.max_borrow_amount is not None:
            cap_usdt = asr.max_borrow_amount
        if cap_usdt is None and user_id is not None:
            sr = db.query(SymbolRule).filter(
                SymbolRule.user_id == user_id, SymbolRule.symbol.in_([symbol, base_asset]),
            ).first()
            if sr and sr.max_borrow_amount is not None:
                cap_usdt = sr.max_borrow_amount
        if cap_usdt is None:
            sa = db.query(SubAccount).get(sub_account_id)
            if sa and sa.max_borrow_amount is not None:
                cap_usdt = sa.max_borrow_amount

        # 借币方式: 新枚举 borrow_mode 优先(config_loader 已归一化);兜底由旧 bool 推导。
        borrow_mode = getattr(rules, "borrow_mode", None) or ("otoco" if getattr(rules, "borrow_via_otoco", False) else "repay")
        # otoco/single/multi 三种都按「金额限制∩maxBorrowable×抵押率」借满;repay 维持单笔 order_amount。
        if borrow_mode in ("otoco", "single", "multi") and cap_usdt is not None and Decimal(str(cap_usdt)) > 0:
            # 挂单借币: 借满「金额限制」∩ maxBorrowable(币捏手上,后续按单笔分批对冲)
            try:
                mb = await client.get_max_borrowable(base_asset)
                # get_max_borrowable 返回 {"amount":Decimal,"borrowLimit":Decimal};取实际可借 amount
                max_borrowable = mb["amount"] if isinstance(mb, dict) else mb
            except Exception:
                max_borrowable = Decimal("0")
            cap_qty = Decimal(str(cap_usdt)) / price if price > 0 else Decimal("0")
            # collateral_ratio 安全垫:不借满 maxBorrowable,按比例留出抵押冗余(1=借满,旧行为)
            ratio = Decimal(str(getattr(rules, "collateral_ratio", 1) or 1))
            if ratio <= 0 or ratio > 1:
                ratio = Decimal("1")
            eff_max = max_borrowable * ratio
            target = min(cap_qty, eff_max) if eff_max > 0 else cap_qty
            qty = round_to_step(target, lot_info["stepSize"])
        else:
            # 单笔金额(order_amount)优先级: 单币规则(SymbolRule) > 子账户(single_order_amount) > 全局
            eff_amount = rules.order_amount
            sa_ord = db.query(SubAccount).get(sub_account_id)
            if sa_ord and getattr(sa_ord, "single_order_amount", None):
                eff_amount = sa_ord.single_order_amount
            if user_id is not None:
                sr2 = db.query(SymbolRule).filter(
                    SymbolRule.user_id == user_id, SymbolRule.symbol.in_([symbol, base_asset]),
                ).first()
                if sr2 and sr2.order_amount is not None:
                    eff_amount = sr2.order_amount
            qty = usdt_to_quantity(eff_amount, price, lot_info["stepSize"], lot_info["minQty"])
        if qty <= 0:
            position.status = "FAILED"
            position.error_message = "Order amount too small for lot size"
            db.commit()
            db.close()
            return None

        # min_borrow_usdt 下限:名义低于此跳过,不做尘埃单(0=不启用)
        min_usdt = Decimal(str(getattr(rules, "min_borrow_usdt", 0) or 0))
        if min_usdt > 0 and qty * price < min_usdt:
            position.status = "FAILED"
            position.error_message = f"Borrow notional {float(qty * price):.2f} < min_borrow_usdt {float(min_usdt)}"
            db.commit()
            db.close()
            return None

        # ── P0-1 净期望收益闸(成本线) ── 借币前评估这笔套利的净期望 E(USDT);此刻所有成本变量齐全
        # (点差/名义/利率/费率/缓冲)且尚未真花钱。shadow=只记录不拦(先跑一周看会拦掉多少);
        # enforce=E≤0 直接放弃(结构性亏损不开);off=不评估。评估结果写 Redis 供 market-monitor E 榜。
        gate_mode = getattr(rules, "net_gate_mode", "shadow") or "shadow"
        expected_e = None
        e_break = None
        if gate_mode != "off":
            hold_hours = float(getattr(rules, "repay_ban_minutes", 30) or 30) / 60.0
            expected_e, e_break = _compute_net_expect(
                spread_short_pct=float(getattr(spread, "spread_short", 0) or 0),
                notional_usdt=float(qty * price),
                interest_rate_daily=float(interest_rate or 0),
                hold_hours=hold_hours,
                f_spot=float(getattr(rules, "taker_fee_spot", TAKER_FEE_RATE) or TAKER_FEE_RATE),
                f_fut=float(getattr(rules, "taker_fee_futures", TAKER_FEE_RATE) or TAKER_FEE_RATE),
                buffer_pct=float(getattr(rules, "open_spread_buffer", 0) or 0),
            )
            decision = "borrow" if (gate_mode == "shadow" or expected_e > 0) else "reject"
            _publish_net_eval(user_id, symbol, expected_e, e_break, decision, gate_mode)
            if gate_mode == "enforce" and expected_e <= 0:
                position.status = "FAILED"
                position.error_message = (f"净期望闸拒开: E={expected_e:.4f}U≤0 "
                                          f"(点差捕获{e_break['spread_capture']:.4f}−利息{e_break['interest_cost']:.4f}"
                                          f"−手续费{e_break['fee_cost']:.4f}−摩擦{e_break['tick_cost']:.4f})")
                logger.info(f"Net-expect gate REJECT {symbol}: {position.error_message}")
                db.commit()
                db.close()
                return None
            if expected_e is not None and expected_e <= 0:
                logger.info(f"[shadow] Net-expect≤0 {symbol}: E={expected_e:.4f}U (借币仍继续, gate={gate_mode})")

        # 借币前最终二次确认: 算 qty 期间(get_lot_size / maxBorrowable REST)又过去若干 ms,
        # 重读最新点差,确认仍新鲜且 ≥ 阈值 → 否则放弃,减少在已消失点差上完成 ~160ms 借币。
        # 负阈值同上跳过(囤券不依赖点差存活)。
        if spread_feed and not skip_confirm:
            latest = spread_feed.get_symbol(symbol)
            now_ms = int(time.time() * 1000)
            fresh = bool(latest and getattr(latest, "ts", 0) and now_ms - int(latest.ts) <= BORROW_FRESH_MS)
            if not fresh or latest.spread_short <= confirm_spread:
                position.status = "FAILED"
                position.error_message = (
                    f"Spread vanished/stale before borrow: "
                    f"{latest.spread_short if latest else 'N/A'} (需 >{confirm_spread}, 新鲜<{BORROW_FRESH_MS}ms)"
                )
                db.commit()
                db.close()
                return None

        # borrow → idle
        # 借币方式分支(borrow_mode,见上方归一化):
        #   single        → 单腿裸 MARGIN_BUY(order-count 仅1笔,最省额度,~10/s)
        #   multi         → 多账户并联,单账户借币动作用单腿(协调在 worker 层)
        #   otoco+legs=1  → 等同单腿
        #   otoco+legs2/3 → IOC OTO/OTOCO(2/3单撤,币留手上)
        #   repay         → borrow-repay 直接借(默认,不改变现网行为)
        legs = int(getattr(rules, "otoco_legs", 2) or 2)
        bid = Decimal(str(getattr(spread, "spot_bid", 0) or 0))
        t0 = time.monotonic()
        if borrow_mode in ("single", "multi") or (borrow_mode == "otoco" and legs == 1):
            await client.margin_borrow_single(symbol, qty, bid=bid if bid > 0 else None)
        elif borrow_mode == "otoco":
            await client.margin_borrow_otoco(symbol, qty, legs=max(2, legs))
        else:
            await client.margin_borrow(base_asset, qty)
        latency = int((time.monotonic() - t0) * 1000)
        position.status = "BORROWED_IDLE"
        position.borrow_qty = qty
        # 记开仓预期净收益 E + 分项(事后与 round_net_pnl 校准闸的准度)
        if expected_e is not None:
            position.expected_e = Decimal(str(round(expected_e, 4)))
            try:
                import json as _j
                position.e_breakdown = _j.dumps(e_break)
            except Exception:
                pass
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, quantity=qty, status="SUCCESS", latency=latency)
        logger.info(f"Borrowed (idle): {symbol} qty={qty}")
        # 写后即时刷新:借到币 → 让该用户 dashboard 现币/借币列秒级更新,不等 10s 轮询
        _uid = user_id if user_id is not None else _resolve_user_id(db, sub_account_id)
        _publish_balance_refresh(_uid)
        # 持仓实时推送:让前端 positions 立即含这条 BORROWED_IDLE(切换成真实持仓行),不等 15s 轮询 →
        # 修复"手推借到币后子账户行整块(现-期/最大可借/现币/借币/保证金/净值)要手动刷新才出"
        _publish_position(position, _uid)
        try:
            await notifier.notify_new_borrow(account_note, symbol, qty, qty * price)
        except Exception as e:
            logger.debug(f"notify_new_borrow failed: {e}")
        return pos_id

    except BinanceAPIError as e:
        logger.error(f"Borrow failed: {e}")
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "BORROW", symbol, status="FAILED", error=str(e))
        # -3045 = 币安杠杆池该币无可借库存。这是相当稳定的市场状态(一个币池子空,常持续数小时),
        # 故冷却设 30 分钟:半小时重试一次足够捕捉库存恢复,又避免每 5 分钟重试一波刷高错误率/SAPI。
        # 注:不再自动拉黑——「无券」是临时供给状态,不等于「币本身坏」;仅做冷却(自动失效自动恢复),
        # 黑名单回归人工维护。库存恢复后冷却 key 到期即自然恢复推送/显示。
        if "-3045" in str(e):
            try:
                import redis as _r
                from app.config import settings as _s
                rc = _r.from_url(_s.redis_url, decode_responses=True)
                rc.set(f"engine:noinv:{symbol}", "1", ex=1800)
                rc.close()
            except Exception:
                pass
        else:
            await notifier.notify_error(account_note, f"borrow {symbol}", str(e))
        return None
    except Exception as e:
        logger.error(f"Borrow failed unexpectedly: {e}", exc_info=True)
        position.status = "FAILED"
        position.error_message = str(e)
        db.commit()
        return None
    finally:
        db.close()


async def execute_hedge(
    position: Position,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
    user_id: int = None,
):
    """Phase 2: sell the borrowed coin on spot (short) + futures long (hedge).
    BORROWED_IDLE → SPOT_SOLD → OPEN. Full rollback on failure.
    futures_client: hedge_via_master 时传主账户 client(合约腿);None=合约同子账户(原行为)。"""
    fc = futures_client if futures_client is not None else client
    db = SessionLocal()
    # 跨进程互斥(API 手动对冲 vs 引擎自动): DB 级 CAS 认领,只有一方能推进
    claimed = db.query(Position).filter(
        Position.id == position.id, Position.status == "BORROWED_IDLE",
    ).update({"status": "HEDGING"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    pos = db.query(Position).get(position.id)
    symbol = pos.symbol
    sub_account_id = pos.sub_account_id

    # 每币种执行质量覆盖(slippage_pct / follow_type): 账户·币种 → 单币种 → 全局,空则跟随上层
    try:
        import dataclasses
        from app.db.models import SymbolRule as _SR, AccountSymbolRule as _ASR
        _base = symbol.replace("USDT", "")
        ov_slip = ov_follow = None
        _asr = db.query(_ASR).filter(
            _ASR.sub_account_id == sub_account_id, _ASR.symbol.in_([symbol, _base]),
        ).first()
        if _asr is not None:
            ov_slip, ov_follow = _asr.slippage_pct, _asr.follow_type
        if (ov_slip is None or not ov_follow) and user_id is not None:
            _sr = db.query(_SR).filter(
                _SR.user_id == user_id, _SR.symbol.in_([symbol, _base]),
            ).first()
            if _sr is not None:
                if ov_slip is None:
                    ov_slip = _sr.slippage_pct
                if not ov_follow:
                    ov_follow = _sr.follow_type
        _repl = {}
        if ov_slip is not None:
            _repl["slippage_pct"] = ov_slip
        if ov_follow:
            _repl["follow_type"] = ov_follow
        if _repl:
            rules = dataclasses.replace(rules, **_repl)
            logger.debug(f"per-symbol exec override {symbol}: {_repl}")
    except Exception as _e:
        logger.debug(f"per-symbol override resolve failed {symbol}: {_e}")
    pos_id = pos.id
    qty = pos.borrow_qty

    # 主账户模式: 卖出前先预检+预留合约保证金,欠资不动现货(回到 BORROWED_IDLE 重试)
    reserved = None
    if futures_client is not None:
        reserved = await _master_margin_precheck(futures_client, symbol, qty, spread, notifier, account_note)
        if reserved is None:
            pos.status = "BORROWED_IDLE"
            db.commit()
            db.close()
            return

    fut_filled = {"qty": Decimal("0")}   # 合约腿已成交量(失败时平残腿用)
    try:
        # Step 1: spot sell (short leg) —— 按「单笔挂单」(order_amount) 分批卖出降低冲击;
        # 合约腿仍按实际卖出总量一次性对冲(回滚逻辑不变)。借量≤单笔时退化为单批=原行为。
        spot_lot = await client.get_lot_size(symbol, "spot")
        order_amt = Decimal(str(getattr(rules, "order_amount", 0) or 0))
        price_ref = spread.spot_ask if (spread.spot_ask and spread.spot_ask > 0) else Decimal("0")
        per_batch = round_to_step(order_amt / price_ref, spot_lot["stepSize"]) if (order_amt > 0 and price_ref > 0) else qty
        if per_batch <= 0:
            per_batch = qty
        total_sold = Decimal("0"); total_value = Decimal("0"); last_oid = ""
        remaining = qty
        first = True
        while remaining > 0:
            b = round_to_step(per_batch if remaining > per_batch else remaining, spot_lot["stepSize"])
            if b <= 0:
                break
            # 尾批名义额低于现货 NOTIONAL 下限(5U)会被 -1013 拒掉并触发整单回滚 ——
            # 已卖出部分时直接收尾,剩余借币留在账户(净持平,还币时按全部负债买回)
            if total_sold > 0 and price_ref > 0 and b * price_ref < Decimal("5.5"):
                logger.info(f"Hedge {symbol}: tail batch {b} below min notional, selling stops at {total_sold}")
                break
            t0 = time.monotonic()
            # 现货腿 maker 化:spot_order_mode=maker 时挂 post-only 省手续费(超时撤单+市价兜底)
            _spot_mode = getattr(rules, "spot_order_mode", "market") or "market"
            if _spot_mode == "maker":
                sell_result = await _spot_maker_fill(client, symbol, "SELL", b, spread, spot_lot)
                fqty = Decimal(str(sell_result["executedQty"]))
                fprice = sell_result["_avg"]
            else:
                sell_result = await client.spot_market_sell(symbol, b)
                fqty = Decimal(str(sell_result["executedQty"]))
                fprice = _avg_fill_price(sell_result)
            latency = int((time.monotonic() - t0) * 1000)
            total_sold += fqty
            total_value += fqty * fprice
            last_oid = str(sell_result["orderId"])
            if first:
                pos.status = "SPOT_SOLD"; first = False
            pos.spot_sell_qty = total_sold
            pos.spot_sell_price = (total_value / total_sold) if total_sold > 0 else fprice
            pos.spot_sell_order_id = last_oid
            db.commit()
            _log_trade(db, pos_id, sub_account_id, "SPOT_SELL", symbol, "SELL",
                        fqty, fprice, last_oid, "SUCCESS", latency=latency)
            remaining = round_to_step(qty - total_sold, spot_lot["stepSize"])
        if total_sold <= 0:
            raise BinanceAPIError(0, 0, "spot sell filled 0")
        qty = total_sold  # 合约按实际卖出量对冲

        # Stabilize before hedging (desktop parity)
        stabilize = float(getattr(rules, "stabilize_sec", 0) or 0)
        if stabilize > 0:
            await asyncio.sleep(min(stabilize, 10))

        # Step 2: futures long (hedge) — market (default) or marketable-limit/tiered
        # fc=master(hedge_via_master) 或子账户自身;同 symbol 在共享净仓上串行(per-symbol 锁)
        futures_lot = await fc.get_lot_size(symbol, "futures")
        futures_qty = round_to_step(qty, futures_lot["stepSize"])
        t0 = time.monotonic()
        async with _fc_symbol_lock(fc, symbol):
            if (getattr(rules, "follow_type", "market") or "market") == "limit":
                long_result = await _futures_entry_limit(
                    fc, symbol, futures_qty, rules, futures_lot, db, pos, sub_account_id,
                    fill_tracker=fut_filled,
                )
            else:
                # 带 clientOrderId: 响应丢失(超时/5xx 状态未知)时可复核实际成交量,
                # 保证失败回滚的残腿平仓拿到真实已成交量而非 0
                coid = f"hx{pos_id}t{int(time.time() * 1000) % 10**10}"
                try:
                    long_result = await fc.futures_market_long(symbol, futures_qty,
                                                               new_client_order_id=coid)
                    long_result = await _confirm_futures_result(fc, symbol, long_result)
                    fut_filled["qty"] = Decimal(str(long_result.get("executedQty", "0")))
                except BinanceAPIError as fe:
                    if fe.api_code == -1007 or fe.http_code >= 500:
                        fut_filled["qty"] = await _query_filled_by_client_id(fc, symbol, coid)
                    raise
        latency = int((time.monotonic() - t0) * 1000)
        pos.status = "OPEN"
        pos.hedge_account = "master" if futures_client is not None else "sub"
        pos.futures_long_qty = Decimal(str(long_result["executedQty"]))
        pos.futures_long_price = Decimal(str(long_result.get("avgPrice", "0")))
        pos.futures_long_order_id = str(long_result["orderId"])
        pos.open_spread = spread.spread_short
        pos.open_usdt_amount = pos.spot_sell_qty * pos.spot_sell_price
        pos.opened_at = datetime.now(timezone.utc)
        db.commit()
        _log_trade(db, pos_id, sub_account_id, "FUTURES_LONG", symbol, "BUY",
                    pos.futures_long_qty, pos.futures_long_price, pos.futures_long_order_id, "SUCCESS", latency=latency)

        logger.info(f"Position opened: {symbol} qty={qty} spread={spread.spread_short}%")
        await notifier.notify_position_opened(
            account_note, symbol, spread.spread_short, qty, pos.open_usdt_amount,
        )

    except BinanceAPIError as e:
        logger.error(f"Hedge failed at {pos.status}: {e}")
        await _handle_hedge_failure(db, pos, client, e, sub_account_id, symbol, notifier, account_note,
                                    futures_client=futures_client, futures_filled=fut_filled["qty"])
    except Exception as e:
        # 非 API 异常同样走回滚(可能已卖出现货/已部分成交合约,只置 FAILED 会裸留敞口)
        logger.error(f"Hedge failed unexpectedly: {e}", exc_info=True)
        await _handle_hedge_failure(db, pos, client, e, sub_account_id, symbol, notifier, account_note,
                                    futures_client=futures_client, futures_filled=fut_filled["qty"])
    finally:
        _release_margin_reserve(futures_client, reserved)
        db.close()


async def _handle_hedge_failure(db, pos, client, error, sub_account_id, symbol, notifier, account_note,
                                futures_client=None, futures_filled: Decimal = Decimal("0")):
    current = pos.status
    if current in ("BORROWED_IDLE", "HEDGING"):
        # spot sell failed — repay borrow
        try:
            await client.margin_repay(pos.base_asset, pos.borrow_qty)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol,
                        quantity=pos.borrow_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, status="FAILED", error=str(re))
        pos.status = "FAILED"
        pos.error_message = f"Spot sell failed: {error}. Borrow rolled back."
        db.commit()
    elif current == "SPOT_SOLD":
        # futures long failed — close any partial futures fill first (master 残腿不平会污染共享净仓),
        # then buy back spot + repay
        if futures_filled and futures_filled > 0:
            fcr = futures_client if futures_client is not None else client
            try:
                async with _fc_symbol_lock(fcr, symbol):
                    await fcr.futures_market_close(symbol, futures_filled)
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_FUTURES_CLOSE", symbol, "SELL",
                            futures_filled, status="SUCCESS")
            except Exception as re:
                _log_trade(db, pos.id, sub_account_id, "ROLLBACK_FUTURES_CLOSE", symbol,
                            status="FAILED", error=str(re))
        rollback_qty = pos.spot_sell_qty if pos.spot_sell_qty else pos.borrow_qty
        try:
            await client.spot_market_buy_qty(symbol, rollback_qty)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol, "BUY", rollback_qty, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_SPOT_BUY", symbol, status="FAILED", error=str(re))
        try:
            total_debt, _ = await _get_asset_debt(client, pos.base_asset)
            repay_amount = total_debt if total_debt > 0 else pos.borrow_qty
            await client.margin_repay(pos.base_asset, repay_amount)
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, quantity=repay_amount, status="SUCCESS")
        except Exception as re:
            _log_trade(db, pos.id, sub_account_id, "ROLLBACK_REPAY", symbol, status="FAILED", error=str(re))
        # 复核回滚是否真清账:上面买回/还币任一静默失败 → 现货已卖+债务仍在 = 裸空。
        # 不再无条件标 "Rolled back";残债显著则发红色裸空告警,并保持 FAILED(终态)让 0.5s guard 兜底收口。
        pos.status = "FAILED"
        try:
            residual_debt, _ = await _get_asset_debt(client, pos.base_asset)
            if residual_debt > (pos.borrow_qty or Decimal("0")) * Decimal("0.02"):
                pos.error_message = (f"Futures long failed: {error}. 回滚未清账(残留债务 "
                                     f"{residual_debt} {pos.base_asset})— 裸空,guard 收口中")
                logger.error(f"NAKED SHORT after rollback {symbol}: residual debt {residual_debt} {pos.base_asset}")
                try:
                    await notifier.notify_naked_short(account_note, symbol, residual_debt, Decimal("0"), futures_filled)
                except Exception:
                    pass
            else:
                pos.error_message = f"Futures long failed: {error}. Rolled back."
        except Exception as _ve:
            pos.error_message = f"Futures long failed: {error}. 回滚结果未核实({_ve}),guard 将复核"
        db.commit()
    else:
        pos.status = "FAILED"
        pos.error_message = str(error)
        db.commit()
    await notifier.notify_error(account_note, f"hedge {symbol} (rollback from {current})", str(error))


async def execute_open(
    sub_account_id: int,
    symbol: str,
    spread: SpreadSnapshot,
    rules: GlobalRulesSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    spread_feed: SpreadFeed = None,
    futures_client: BinanceTradingClient = None,
    user_id: int = None,
):
    """Atomic open (borrow + hedge in one shot) — used by manual-open and as a fallback."""
    pos_id = await execute_borrow(
        sub_account_id, symbol, spread, rules, client, notifier, account_note,
        spread_feed=spread_feed, min_spread=rules.open_spread, user_id=user_id,
    )
    if pos_id is None:
        return
    db = SessionLocal()
    pos = db.query(Position).get(pos_id)
    db.close()
    if pos and pos.status == "BORROWED_IDLE":
        cur = spread_feed.get_symbol(symbol) if spread_feed else None
        await execute_hedge(pos, cur or spread, rules, client, notifier, account_note,
                            futures_client=futures_client)


async def execute_unhedge(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
    spot_order_mode: str = "market",   # 现货买回腿:market/maker(post-only省手续费)
):
    """Phase 1 of close: close the futures long + buy back the spot, leaving the coin
    in the margin account awaiting repay. OPEN → PENDING_REPAY (net-flat, no exposure).
    合约腿按开仓归属(pos.hedge_account)选 client —— master 开的仓必须用 master 平,
    与全局开关当前值无关;master client 缺失时不动仓位,留 OPEN 等重试。"""
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status != "OPEN":
        db.close()
        return
    on_master = getattr(pos, "hedge_account", None) == "master"
    if on_master and futures_client is None:
        logger.warning(f"Unhedge {pos.symbol}: hedged on master but master client unavailable; retry later")
        db.close()
        return
    fc = futures_client if on_master else client

    # 跨进程互斥(API 手动平仓 vs 引擎自动): DB 级 CAS 认领 —— master 共享净仓下
    # 双平会误吃其他子账户的对冲腿,留下账面无感知的裸现货空头
    claimed = db.query(Position).filter(
        Position.id == pos.id, Position.status == "OPEN",
    ).update({"status": "CLOSING_FUTURES"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    db.refresh(pos)

    try:
        # Step 1: close futures
        t0 = time.monotonic()
        async with _fc_symbol_lock(fc, pos.symbol):
            close_result = await fc.futures_market_close(pos.symbol, pos.futures_long_qty)
            close_result = await _confirm_futures_result(fc, pos.symbol, close_result)
        latency = int((time.monotonic() - t0) * 1000)
        pos.futures_close_price = Decimal(str(close_result.get("avgPrice", "0")))
        pos.futures_close_order_id = str(close_result["orderId"])
        pos.status = "FUTURES_CLOSED"
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "FUTURES_CLOSE", pos.symbol, "SELL",
                    pos.futures_long_qty, pos.futures_close_price,
                    pos.futures_close_order_id, "SUCCESS", latency=latency)

        # Step 2: buy back the borrowed coin (cover the short) — keep it for manual repay
        # 按仓分配债务:用本仓借量×利息缓冲作买回目标,不查账户级总债。
        # 多仓并存时账户总债会被首个平仓的仓"全额买回",后续仓 spot_buy_qty 少记 → PnL 虚高。
        # borrow_qty 是本仓实际借量；FEE_BUFFER(1.0015)覆盖利息+手续费扣币缺口。
        target = pos.borrow_qty * FEE_BUFFER
        spot_lot = await client.get_lot_size(pos.symbol, "spot")
        buy_qty = round_to_step(target, spot_lot["stepSize"])
        # 现货手续费从收到的币里扣 —— 向下取整会吃掉 FEE_BUFFER(实收<负债,还币 -3041),
        # 不足目标时向上多凑一个步长
        if buy_qty < target:
            buy_qty += Decimal(str(spot_lot["stepSize"]))

        pos.status = "CLOSING_SPOT"
        db.commit()
        t0 = time.monotonic()
        # 现货买回腿 maker 化(超时撤单+市价兜底,必足量买回以还币)
        if (spot_order_mode or "market") == "maker":
            buy_result = await _spot_maker_fill(client, pos.symbol, "BUY", buy_qty, spread, spot_lot)
            pos.spot_buy_qty = Decimal(str(buy_result["executedQty"]))
            pos.spot_buy_price = buy_result["_avg"]
        else:
            buy_result = await client.spot_market_buy_qty(pos.symbol, buy_qty)
            pos.spot_buy_qty = Decimal(str(buy_result["executedQty"]))
            pos.spot_buy_price = _avg_fill_price(buy_result)
        latency = int((time.monotonic() - t0) * 1000)
        pos.spot_buy_order_id = str(buy_result["orderId"])
        pos.close_spread = spread.spread_short
        pos.status = "PENDING_REPAY"   # coin held; awaiting manual/auto repay
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "SPOT_BUY", pos.symbol, "BUY",
                    pos.spot_buy_qty, pos.spot_buy_price,
                    pos.spot_buy_order_id, "SUCCESS", latency=latency)

        logger.info(f"Unhedged (pending repay): {pos.symbol}")

    except BinanceAPIError as e:
        logger.error(f"Unhedge failed at {pos.status}: {e}")
        pos.error_message = str(e)
        pos.retry_count = (pos.retry_count or 0) + 1
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "CLOSE_ERROR", pos.symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"unhedge {pos.symbol}", str(e))
    except Exception as e:
        logger.error(f"Unhedge failed unexpectedly: {e}", exc_info=True)
        pos.error_message = str(e)
        db.commit()
        await notifier.notify_error(account_note, f"unhedge {pos.symbol}", str(e))
    finally:
        db.close()


async def sell_residual_spot(client: BinanceTradingClient, symbol: str, base_asset: str, qty) -> tuple[Decimal, str]:
    """把杠杆户 base_asset 现币残留市价卖回 USDT(NO_SIDE_EFFECT,不借币)。残留来源=平仓买回按
    FEE_BUFFER 超买/开仓尾批不足额,还清债务后无人消费。qty 向下对齐 stepSize;名义 < minNotional
    时币安不接单,如实返回原因。返回 (实际卖出数量, 说明)。
    ⚠调用方必须自行保证: 该账户该币债务已清 且 无其它非终态持仓 —— 否则会把别的仓等待还币的
    买回币卖掉,制造裸债。(engine_api 手动「卖回」与 execute_repay 自动卖回共用此实现)"""
    q = Decimal(str(qty))
    info = await client._request("GET", "https://api.binance.com/api/v3/exchangeInfo",
                                 {"symbol": symbol}, signed=False)
    sp = info.get("symbols", [{}])[0]
    flt = {f["filterType"]: f for f in sp.get("filters", [])}
    step = str(flt.get("LOT_SIZE", {}).get("stepSize", "0.01") or "0.01")
    min_notional = Decimal(str(flt.get("NOTIONAL", {}).get("minNotional", "5") or "5"))
    tkr = await client._request("GET", "https://api.binance.com/api/v3/ticker/price",
                                {"symbol": symbol}, signed=False)
    price = Decimal(str(tkr.get("price", 0) or 0))
    if price <= 0:
        return Decimal("0"), "取价失败,稍后重试"
    sell_qty = round_to_step(q, step)
    if sell_qty <= 0 or sell_qty * price < min_notional:
        return Decimal("0"), (f"残留 {q:.6f} 名义价值 {float(q * price):.2f}U "
                              f"低于币安最小卖出额 {min_notional}U,暂留账")
    await client._request(
        "POST", "https://api.binance.com/sapi/v1/margin/order",
        {"symbol": symbol, "side": "SELL", "type": "MARKET",
         "quantity": f"{sell_qty:.8f}", "sideEffectType": "NO_SIDE_EFFECT", "isIsolated": "FALSE"},
    )
    return sell_qty, f"已卖回 {sell_qty:.6f} {base_asset}"


async def execute_repay(
    position: Position,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    fee_spot: Decimal = None,
    fee_futures: Decimal = None,
):
    """Phase 2 of close: repay the margin debt and finalize PnL. PENDING_REPAY → CLOSED.
    fee_spot/fee_futures: 可配双腿吃单费率(仅影响 PnL 口径);None 时回退 TAKER_FEE_RATE,保留旧行为。"""
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    if not pos or pos.status != "PENDING_REPAY":
        db.close()
        return
    # 跨进程互斥: CAS 认领,防手动还币与引擎自动还币双发(双倍 repay 会动用账户其他资产)
    claimed = db.query(Position).filter(
        Position.id == pos.id, Position.status == "PENDING_REPAY",
    ).update({"status": "REPAYING"}, synchronize_session=False)
    db.commit()
    if not claimed:
        db.close()
        return
    db.refresh(pos)

    try:
        # 买回的币入杠杆账户有结算延迟 —— 轮询等 free 覆盖负债(最长 ~8s),
        # 再决定全额还/按 free 封顶,避免把settlement-lag误判成粉尘留下整笔欠债
        async def _read_debt_free():
            mi = await client.get_margin_account()
            for a in mi.get("userAssets", []):
                if a["asset"] == pos.base_asset:
                    return (Decimal(str(a.get("borrowed", "0"))) + Decimal(str(a.get("interest", "0"))),
                            Decimal(str(a.get("interest", "0"))),
                            Decimal(str(a.get("free", "0"))))
            return Decimal("0"), Decimal("0"), Decimal("0")

        total_debt, interest_amount, free_bal = await _read_debt_free()
        pos_owed = pos.borrow_qty * FEE_BUFFER   # 本仓应还额(先算,等待循环用)
        for _ in range(6):
            if total_debt <= 0 or free_bal >= pos_owed:
                break
            await asyncio.sleep(1.3)
            total_debt, interest_amount, free_bal = await _read_debt_free()
        # 按仓分配债务:本仓应还 = 本仓借量 × FEE_BUFFER(覆盖利息+扣币),与 unhedge 买回口径一致。
        # 多仓并存时 total_debt 是账户总债,会被首个还币的仓"全额还清",后续仓 repay_qty=0 记账失真。
        # min(pos_owed, total_debt) 防止最后一仓超还(前面仓已归还部分,剩余 < pos_owed 时封顶)。
        repay_amount = min(pos_owed, total_debt) if total_debt > 0 else pos.borrow_qty
        # 等满后 free 仍不足(手续费扣币的真实小额缺口): 按 free 封顶,真·粉尘留账
        if Decimal("0") < free_bal < repay_amount:
            logger.warning(f"Repay {pos.symbol}: free {free_bal} < debt {repay_amount} after settle wait, "
                           f"repaying free (dust {repay_amount - free_bal} stays)")
            repay_amount = free_bal
        t0 = time.monotonic()
        # 买回后立即还币会踩杠杆账户结算延迟(-3041 Balance is not enough)—— 重试等结算
        for attempt in range(4):
            try:
                await client.margin_repay(pos.base_asset, repay_amount)
                break
            except BinanceAPIError as re_err:
                if re_err.api_code == -3041 and attempt < 3:
                    await asyncio.sleep(1.5)
                    continue
                raise
        latency = int((time.monotonic() - t0) * 1000)
        pos.repay_qty = repay_amount
        pos.repay_interest = interest_amount
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol,
                    quantity=repay_amount, status="SUCCESS", latency=latency)

        # Finalize PnL (fees + interest)
        spot_pnl = (pos.spot_sell_qty * pos.spot_sell_price) - (pos.spot_buy_qty * pos.spot_buy_price)
        futures_pnl = (pos.futures_close_price - pos.futures_long_price) * pos.futures_long_qty
        spot_sell_notional = pos.spot_sell_qty * pos.spot_sell_price
        spot_buy_notional = pos.spot_buy_qty * pos.spot_buy_price
        futures_open_notional = pos.futures_long_qty * pos.futures_long_price
        futures_close_notional = pos.futures_long_qty * pos.futures_close_price
        # 双腿吃单费率(可配): 现货腿与合约腿分开,None 回退硬编码常量(旧行为)
        f_spot = Decimal(str(fee_spot)) if fee_spot is not None else TAKER_FEE_RATE
        f_fut = Decimal(str(fee_futures)) if fee_futures is not None else TAKER_FEE_RATE
        total_fee = (spot_sell_notional + spot_buy_notional) * f_spot \
            + (futures_open_notional + futures_close_notional) * f_fut
        interest_cost = interest_amount * pos.spot_buy_price if interest_amount else Decimal("0")
        pos.fee_total = total_fee + interest_cost
        pos.realized_pnl = spot_pnl + futures_pnl - total_fee - interest_cost
        # P0-3 逐回路净损益:realized_pnl 不含资金费(资金费单独落 cumulative_funding_fee),
        # 本回路真实净 = realized + 已结算资金费。这是"这一轮开平到底赚没赚"的唯一真值,
        # 与 expected_e(开仓预期)同 USDT 口径,供 dashboard/admin 历史逐笔展示 + 事后校准 E 闸准度。
        _funding = pos.cumulative_funding_fee or Decimal("0")
        pos.round_net_pnl = pos.realized_pnl + _funding
        pos.closed_at = datetime.now(timezone.utc)
        pos.status = "CLOSED"
        db.commit()

        logger.info(f"Position closed (repaid): {pos.symbol} pnl={pos.realized_pnl}")

        # 自动卖回本轮残留零头:买回按 FEE_BUFFER 超买、还币只还 min(pos_owed,债务),差额
        # 无人消费会永久躺在"现币"列。护栏(缺一不卖):
        #   ① 该账户该币无其它非终态持仓 —— 多仓并存时 free 里是别的仓等待还币的买回币,卖了=裸债;
        #   ② 还后实测债务已为 0 —— 部分还(pos_owed<总债)说明还有仓欠着,零头要留给后续还币。
        # 只卖本轮算术零头 min(free_bal-repay_amount, 当前free),不碰账户里其它来源的持币。
        # best-effort:任何失败只记日志,不影响已完成的平仓。
        try:
            leftover = free_bal - repay_amount
            if leftover > 0:
                others = db.query(Position).filter(
                    Position.sub_account_id == pos.sub_account_id,
                    Position.symbol == pos.symbol,
                    Position.id != pos.id,
                    Position.status.notin_(["CLOSED", "FAILED"]),
                ).count()
                if others == 0:
                    debt_now, _i2, free_now = await _read_debt_free()
                    if debt_now <= 0 and free_now > 0:
                        sold, note = await sell_residual_spot(
                            client, pos.symbol, pos.base_asset, min(leftover, free_now))
                        if sold > 0:
                            logger.info(f"Repay {pos.symbol}: residual sold back {sold} ({account_note})")
                        else:
                            logger.info(f"Repay {pos.symbol}: residual not sold — {note}")
        except Exception as se:
            logger.warning(f"Repay {pos.symbol}: residual sell-back skipped: {se}")

        # 写后即时刷新:还币平仓(引擎自动 / manual-repay 端点都走此函数)→ 该用户余额秒级刷新
        _publish_balance_refresh(
            pos.user_id if getattr(pos, "user_id", None) is not None
            else _resolve_user_id(db, pos.sub_account_id))
        await notifier.notify_position_closed(account_note, pos.symbol, pos.realized_pnl, pos.close_spread or Decimal("0"))

    except BinanceAPIError as e:
        logger.error(f"Repay failed: {e}")
        pos.status = "PENDING_REPAY"   # 回退可重试态(REPAYING 无人消费会永久卡死)
        pos.error_message = str(e)
        pos.retry_count = (pos.retry_count or 0) + 1
        db.commit()
        _log_trade(db, pos.id, pos.sub_account_id, "REPAY", pos.symbol, status="FAILED", error=str(e))
        await notifier.notify_error(account_note, f"repay {pos.symbol}", str(e))
    except Exception as e:
        logger.error(f"Repay failed unexpectedly: {e}", exc_info=True)
        pos.error_message = str(e)
        db.commit()
        await notifier.notify_error(account_note, f"repay {pos.symbol}", str(e))
    finally:
        db.close()


async def execute_close(
    position: Position,
    spread: SpreadSnapshot,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    futures_client: BinanceTradingClient = None,
):
    """Atomic close (unhedge + repay in one shot) — used by manual-close / tail cleanup."""
    await execute_unhedge(position, spread, client, notifier, account_note,
                          futures_client=futures_client)
    db = SessionLocal()
    pos = db.query(Position).get(position.id)
    db.close()
    if pos and pos.status == "PENDING_REPAY":
        await execute_repay(pos, client, notifier, account_note)


async def execute_borrow_only_repay(
    sub_account_id: int,
    symbol: str,
    client: BinanceTradingClient,
    notifier: FeishuSender,
    account_note: str,
    user_id: int = None,
):
    """C6: Repay a borrow-only position (never opened) and record interest in history."""
    base_asset = symbol.replace("USDT", "")
    db = SessionLocal()
    try:
        total_debt, interest_amount = await _get_asset_debt(client, base_asset)
        if total_debt <= 0:
            return

        await client.margin_repay(base_asset, total_debt)

        position = Position(
            sub_account_id=sub_account_id,
            symbol=symbol,
            base_asset=base_asset,
            status="CLOSED",
            user_id=user_id,
            borrow_qty=total_debt - interest_amount,
            repay_qty=total_debt,
            repay_interest=interest_amount,
            cumulative_interest=interest_amount,
            realized_pnl=-interest_amount,
            fee_total=interest_amount,
            opened_at=datetime.now(timezone.utc),
            closed_at=datetime.now(timezone.utc),
            error_message="borrow-only repay (no position opened)",
        )
        db.add(position)
        db.commit()

        _log_trade(db, position.id, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                    quantity=total_debt, status="SUCCESS")

        logger.info(f"Borrow-only repay: {symbol} debt={total_debt} interest={interest_amount}")
        await notifier.send(
            "借币还币记录",
            f"账户: {account_note}\n币种: {symbol}\n借币: {total_debt - interest_amount}\n利息: {interest_amount}",
        )
    except Exception as e:
        logger.error(f"Borrow-only repay failed {symbol}: {e}")
        _log_trade(db, None, sub_account_id, "BORROW_ONLY_REPAY", symbol,
                    status="FAILED", error=str(e))
    finally:
        db.close()


def _avg_fill_price(order_result: dict) -> Decimal:
    fills = order_result.get("fills", [])
    if not fills:
        return Decimal(str(order_result.get("price", "0")))
    total_qty = sum(Decimal(f["qty"]) for f in fills)
    if total_qty == 0:
        return Decimal("0")
    weighted = sum(Decimal(f["price"]) * Decimal(f["qty"]) for f in fills)
    return weighted / total_qty


# ─── Limit / tiered futures entry (hedge-safe: always reconciles to full hedge) ───

LIMIT_WAIT_SEC = 2.0       # max wait per limit tranche before fallback
LIMIT_POLL_SEC = 0.3


def _parse_tiers(tier_ratios: str) -> list[tuple[Decimal, Decimal]]:
    """Parse "0.5:30,0.8:30,1.2:40" -> [(offset_pct, qty_pct), ...].
    Returns [] when empty/invalid (caller falls back to a single tranche)."""
    if not tier_ratios or not tier_ratios.strip():
        return []
    out: list[tuple[Decimal, Decimal]] = []
    try:
        for part in tier_ratios.split(","):
            off, q = part.split(":")
            out.append((Decimal(off.strip()), Decimal(q.strip())))
    except Exception:
        return []
    total = sum(q for _, q in out)
    if total <= 0:
        return []
    return out


async def _poll_fill(client: BinanceTradingClient, symbol: str, order_id: str,
                     timeout: float) -> tuple[Decimal, Decimal]:
    """Poll a futures order until FILLED or timeout. Returns (executedQty, avgPrice)."""
    waited = 0.0
    eq, ap = Decimal("0"), Decimal("0")
    while waited < timeout:
        try:
            o = await client.futures_get_order(symbol, order_id)
            eq = Decimal(str(o.get("executedQty", "0")))
            ap = Decimal(str(o.get("avgPrice", "0")))
            if o.get("status") in ("FILLED", "CANCELED", "EXPIRED", "REJECTED"):
                break
        except Exception:
            pass
        await asyncio.sleep(LIMIT_POLL_SEC)
        waited += LIMIT_POLL_SEC
    return eq, ap


async def _futures_entry_limit(client: BinanceTradingClient, symbol: str, total_qty: Decimal,
                               rules, futures_lot: dict, db, pos, sub_account_id,
                               fill_tracker: dict = None) -> dict:
    """Marketable-limit (+ optional tiered) futures long, capping slippage but
    ALWAYS reconciling any unfilled remainder with a market order so the spot leg
    is never left unhedged. Returns a dict shaped like a market-order result."""
    step = futures_lot["stepSize"]
    min_qty = Decimal(str(futures_lot.get("minQty", "0")))
    slippage = (rules.slippage_pct or Decimal("0.1")) / Decimal("100")

    # fresh ask for accurate limit pricing
    try:
        book = await client.futures_book_ticker(symbol)
        ask = Decimal(str(book.get("askPrice") or book.get("a") or "0"))
    except Exception:
        ask = Decimal("0")
    tick = await client.get_futures_tick_size(symbol)

    tiers = _parse_tiers(rules.tier_ratios)
    if not tiers:
        tiers = [(rules.slippage_pct or Decimal("0.1"), Decimal("100"))]

    fills: list[tuple[Decimal, Decimal]] = []
    filled = Decimal("0")

    if ask > 0:
        for offset_pct, qty_pct in tiers:
            qty_i = round_to_step(total_qty * qty_pct / Decimal("100"), step)
            if qty_i <= 0:
                continue
            # marketable limit: ask uplifted by max(offset, slippage cap)
            uplift = max(offset_pct / Decimal("100"), slippage)
            price = round_to_step(ask * (Decimal("1") + uplift), tick)
            try:
                res = await client.futures_limit_long(symbol, qty_i, price)
                oid = str(res["orderId"])
                eq, ap = await _poll_fill(client, symbol, oid, LIMIT_WAIT_SEC)
                if eq < qty_i:
                    try:
                        cres = await client.futures_cancel_order(symbol, oid)
                        eq = Decimal(str(cres.get("executedQty") or eq))
                        ap = Decimal(str(cres.get("avgPrice") or ap))
                    except Exception:
                        pass
                    # 最后一次轮询与撤单生效之间可能有新成交 —— 以订单终态为准,
                    # 否则 filled 低估 → 市价兜底超买 + 回滚平不净(master 共仓残腿)
                    for _ in range(3):
                        try:
                            o = await client.futures_get_order(symbol, oid)
                            eq = Decimal(str(o.get("executedQty", "0")))
                            ap = Decimal(str(o.get("avgPrice", "0")))
                            break
                        except Exception:
                            await asyncio.sleep(0.3)
                if eq > 0:
                    fills.append((eq, ap)); filled += eq
                    if fill_tracker is not None:
                        fill_tracker["qty"] = filled
                    _log_trade(db, pos.id, sub_account_id, "FUTURES_LIMIT_FILL", symbol, "BUY",
                                eq, ap, oid, "SUCCESS")
            except Exception as e:
                logger.warning(f"Limit tranche failed {symbol} {qty_i}@{price}: {e}")

    # Reconcile to full hedge with a market order (safety invariant).
    remaining = round_to_step(total_qty - filled, step)
    last_id = None
    if remaining >= min_qty and remaining > 0:
        mres = await client.futures_market_long(symbol, remaining)
        meq = Decimal(str(mres.get("executedQty", "0")))
        map_ = Decimal(str(mres.get("avgPrice", "0")))
        last_id = str(mres.get("orderId", ""))
        if meq > 0:
            fills.append((meq, map_)); filled += meq
            if fill_tracker is not None:
                fill_tracker["qty"] = filled
            _log_trade(db, pos.id, sub_account_id, "FUTURES_MARKET_FALLBACK", symbol, "BUY",
                        meq, map_, last_id, "SUCCESS")

    avg = (sum(q * p for q, p in fills) / filled) if filled > 0 else Decimal("0")
    return {
        "executedQty": str(filled),
        "avgPrice": str(avg),
        "orderId": last_id or (str(int(pos.id)) if not fills else "limit"),
    }
