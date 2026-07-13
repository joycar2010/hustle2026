"""S4 借贷利率套利 armed 执行器 —— 借币(全仓杠杆)→杠杆卖出→永续多头对冲。

经济结构(带符号,修正 advisor |资金费| 口径缺陷):
  收益/天 = (-funding_daily)            # 多头永续只在负费率时收钱;正费率是成本,绝不取绝对值
           - borrow_daily               # 借币日利率
  (v1 不做理财腿:卖出所得 USDT 留杠杆账户作担保,不计 earn 收益=保守口径)

双门闸:DCM_LEND_MODE=armed 且 coin∈DCM_LEND_ARM_SYMBOLS,默认全空=永不下单。
学费全套编码:防重入三道(内存/Redis单飞锁/DB非终态)/OPENING预占组合闸/穿价方向性取价
(BUY 从 ask、SELL 从 bid)/单腿超时回滚平已成腿/还币按活负债现查/崩溃 reconcile 认领/
失败冷却 600s/裸债检测 fatal。
"""
import asyncio
import json
import logging
import os
import time
from decimal import Decimal

import httpx

import sys
sys.path.insert(0, os.path.expanduser("~/dexcexmix/src/packages/dcm-common"))
from dcm_common.exchange_trade import BinanceMarginTrade, BinanceTrade, _round_step  # noqa: E402
from dcm_common.notify import Notifier, feishu_from_env  # noqa: E402

log = logging.getLogger("engine-lending.armed")

MODE = os.environ.get("DCM_LEND_MODE", "shadow")
ARM_SYMBOLS = {s.strip().upper() for s in os.environ.get("DCM_LEND_ARM_SYMBOLS", "").split(",") if s.strip()}
MAX_NOTIONAL_HARD = Decimal(os.environ.get("DCM_LEND_MAX_NOTIONAL_HARD", "25"))
MAX_PORTFOLIO = Decimal(os.environ.get("DCM_LEND_MAX_PORTFOLIO", "100"))
ARM_MIN_NET_PCT = float(os.environ.get("DCM_LEND_ARM_MIN_NET_PCT", "0.5"))   # 带符号净差入场地板 %/d
ARM_EXIT_NET_PCT = float(os.environ.get("DCM_LEND_ARM_EXIT_NET_PCT", "0.1"))  # 带符号净差退出线 %/d
EXIT_STRIKES = int(os.environ.get("DCM_LEND_ARM_EXIT_STRIKES", "3"))
CROSS_BPS = Decimal(os.environ.get("DCM_LEND_CROSS_BPS", "15"))
LEG_TIMEOUT = int(os.environ.get("DCM_LEND_LEG_TIMEOUT_SEC", "45"))
FAIL_COOLDOWN = int(os.environ.get("DCM_LEND_FAIL_COOLDOWN_SEC", "600"))
L1_STALE_SEC = int(os.environ.get("DCM_LEND_L1_STALE_SEC", "15"))
DUST_USDT = Decimal("1")


def _cross(price: Decimal, side: str) -> Decimal:
    """穿价参考价必须取对手侧(B3 残腿学费):BUY 从 ask 上穿,SELL 从 bid 下穿。"""
    bps = CROSS_BPS / Decimal("10000")
    return price * ((Decimal("1") + bps) if side == "BUY" else (Decimal("1") - bps))


class LendingExecutor:
    def __init__(self, r, pool, cfg: dict):
        self.r = r
        self.pool = pool
        self.margin = BinanceMarginTrade(cfg)
        self.perp = BinanceTrade(cfg)
        self.open_syms: set[str] = set()
        self.inflight: set[str] = set()
        self._cooldown: dict[str, float] = {}
        self._exit_strikes: dict[str, int] = {}
        self._filters_loaded: set[str] = set()
        self.notify = Notifier(os.environ.get("DCM_REDIS_URL", ""), "engine-lending", feishu_from_env())

    def armed_for(self, coin: str) -> bool:
        return MODE == "armed" and coin.upper() in ARM_SYMBOLS

    # ---------- 行情/经济学 ----------
    async def _l1(self, symbol: str) -> dict | None:
        raw = await self.r.hget("dcm:feed:binance:perp", symbol)
        if not raw:
            return None
        d = json.loads(raw)
        ts = int(d.get("recv_ts") or d.get("ts") or 0) / (1000 if int(d.get("recv_ts") or d.get("ts") or 0) > 10**12 else 1)
        if time.time() - ts > L1_STALE_SEC:
            return None   # 消费端新鲜度判定:stale 腿绝不定价
        return d

    async def signed_net_daily(self, coin: str, borrow_pct: float | None) -> tuple[float | None, str]:
        """带符号净差 %/d = (-funding_daily) - borrow。funding 缺失/超龄→None(绝不开仓)。"""
        raw = await self.r.hget("dcm:feed:funding:binance", f"{coin.upper()}USDT")
        if not raw:
            return None, "funding 缺失"
        f = json.loads(raw)
        if time.time() - int(f.get("ts") or 0) > 1800:
            return None, "funding 超龄"
        funding_daily = float(f.get("daily_pct") or 0)
        if borrow_pct is None:
            return None, "borrow 利率缺失"
        net = (-funding_daily) - float(borrow_pct)
        return net, f"funding={funding_daily:+.4f}%/d borrow={borrow_pct:.4f}%/d"

    async def _ensure_filters(self, cli, symbol: str):
        if symbol in self._filters_loaded:
            return
        await self.margin.load_filter(cli, symbol)
        await self.perp.load_filter(cli, symbol)
        self._filters_loaded.add(symbol)

    # ---------- 腿执行(穿价 limit + 轮询 FILLED,超时撤单返回已成量) ----------
    async def _leg(self, client, cli, symbol: str, side: str, qty: Decimal,
                   ref_price: Decimal, reduce_only=False) -> tuple[Decimal, str]:
        ok, res = await client.place_limit(cli, symbol, side, qty, _cross(ref_price, side), reduce_only)
        if not ok:
            return Decimal("0"), f"place: {res.get('err')}"
        oid = res["order_id"]
        deadline = time.time() + LEG_TIMEOUT
        while time.time() < deadline:
            await asyncio.sleep(1.5)
            ok2, st = await client.fetch_order(cli, symbol, oid)
            if ok2 and st.get("status") == "FILLED":
                return Decimal(str(st["filled"])), ""
        await client.cancel(cli, symbol, oid)
        ok3, st3 = await client.fetch_order(cli, symbol, oid)
        filled = Decimal(str(st3.get("filled") or 0)) if ok3 else Decimal("0")
        return filled, f"timeout(filled={filled})"

    # ---------- 开仓 ----------
    async def open_position(self, cli, coin: str, target_usdt: Decimal, ranking_row: dict) -> bool:
        coin = coin.upper()
        symbol = f"{coin}USDT"
        if coin in self.inflight or coin in self.open_syms:
            return False
        if time.time() < self._cooldown.get(coin, 0):
            return False
        lock = f"dcm:lend:lock:{coin}"
        if not await self.r.set(lock, str(os.getpid()), nx=True, ex=90):
            return False
        self.inflight.add(coin)
        row_id = None
        try:
            # DB 非终态防重
            n = await self.pool.fetchval(
                "SELECT count(*) FROM lending_positions WHERE coin=$1 AND state NOT IN ('CLOSED','FAILED')", coin)
            if n:
                self.open_syms.add(coin)
                return False
            # 带符号经济学闸(修 advisor abs 缺陷)
            net, detail = await self.signed_net_daily(coin, ranking_row.get("borrow"))
            if net is None or net < ARM_MIN_NET_PCT:
                log.info("open %s skip: 带符号净差不过闸 net=%s (%s)", coin, net, detail)
                self._cooldown[coin] = time.time() + 300
                return False
            l1 = await self._l1(symbol)
            if not l1:
                log.info("open %s skip: perp L1 缺失/超龄", coin)
                return False
            await self._ensure_filters(cli, symbol)
            bid, ask = Decimal(str(l1["bid"])), Decimal(str(l1["ask"]))
            notional = min(target_usdt, MAX_NOTIONAL_HARD)
            step = max(self.margin.step.get(symbol, Decimal("0.001")), self.perp.step.get(symbol, Decimal("0.001")))
            qty = _round_step(notional / bid, step)
            if qty <= 0 or qty * bid < max(self.margin.min_notional.get(symbol, Decimal("5")),
                                           self.perp.min_notional.get(symbol, Decimal("5"))):
                log.info("open %s skip: qty=%s 低于最小名义", coin, qty)
                return False
            # 组合闸(OPENING 预占,并发竞态课)
            in_field = await self.pool.fetchval(
                "SELECT coalesce(sum(notional_usdt),0) FROM lending_positions WHERE state NOT IN ('CLOSED','FAILED')")
            if Decimal(str(in_field)) + notional > MAX_PORTFOLIO:
                log.info("open %s skip: 组合闸 %s+%s>%s", coin, in_field, notional, MAX_PORTFOLIO)
                return False
            # 可借额度预检
            borrowable = await self.margin.max_borrowable(cli, coin)
            if borrowable < qty * Decimal("1.01"):
                log.info("open %s skip: 可借 %s < 需 %s,冷却", coin, borrowable, qty)
                self._cooldown[coin] = time.time() + FAIL_COOLDOWN
                return False
            row_id = await self.pool.fetchval(
                "INSERT INTO lending_positions(coin,symbol,qty_base,borrow_qty,notional_usdt,net_daily_pct,state) "
                "VALUES($1,$2,$3,0,$4,$5,'OPENING') RETURNING id", coin, symbol, qty, notional, net)

            # ① 借币
            ok, res = await self.margin.borrow(cli, coin, qty)
            if not ok:
                await self._fail(row_id, coin, f"borrow: {res.get('err')}")
                return False
            # ② 杠杆卖出(SELL 从 bid 下穿)
            sold, err = await self._leg(self.margin, cli, symbol, "SELL", qty, bid)
            if sold <= 0:
                # 卖出零成交:还币回滚(负债须归零)
                await self._repay_all(cli, coin, f"open 卖出失败({err})回滚")
                await self._fail(row_id, coin, f"margin sell: {err}")
                return False
            # ③ 永续多头对冲(按实际卖出量,BUY 从 ask 上穿)
            hedged, err2 = await self._leg(self.perp, cli, symbol, "BUY", sold, ask)
            if hedged < sold * Decimal("0.9"):
                # 对冲失败/严重不足:全链回滚——平已成对冲腿+买回+还币
                if hedged > 0:
                    await self._leg(self.perp, cli, symbol, "SELL", hedged, bid, reduce_only=True)
                bought, _e = await self._leg(self.margin, cli, symbol, "BUY", sold, ask)
                await self._repay_all(cli, coin, "open 对冲失败回滚")
                await self._fail(row_id, coin, f"hedge: {err2}; 回滚买回 {bought}/{sold}")
                await self.notify.send("lend-rollback", f"S4 {coin} 开仓回滚",
                                       f"卖出 {sold} 对冲仅 {hedged},已回滚。残差请核对账户。",
                                       level="fatal")
                return False
            # 残差轧平(对冲多于卖出不可能;少量缺口 ≤10% 补齐到 sold)
            gap = sold - hedged
            if gap * ask > DUST_USDT:
                extra, _e = await self._leg(self.perp, cli, symbol, "BUY", gap, ask)
                hedged += extra
            await self.pool.execute(
                "UPDATE lending_positions SET qty_base=$2, borrow_qty=$3, state='OPEN', updated_at=now() WHERE id=$1",
                row_id, sold, qty)
            self.open_syms.add(coin)
            log.info("OPEN_OK %s qty=%s notional≈%sU net=%.3f%%/d (%s)", coin, sold, notional, net, detail)
            return True
        except Exception as e:  # noqa: BLE001
            log.exception("open %s crashed", coin)
            self._cooldown[coin] = time.time() + FAIL_COOLDOWN   # 崩溃路径同样冷却(crash-loop 课)
            if row_id:
                await self._fail(row_id, coin, f"crash: {e!r}")
            return False
        finally:
            self.inflight.discard(coin)
            try:
                await self.r.delete(lock)
            except Exception:  # noqa: BLE001
                pass

    async def _fail(self, row_id, coin, msg):
        self._cooldown[coin] = time.time() + FAIL_COOLDOWN
        await self.pool.execute(
            "UPDATE lending_positions SET state='FAILED', error_message=$2, closed_at=now(), updated_at=now() "
            "WHERE id=$1", row_id, msg[:300])
        log.warning("OPEN_FAIL %s: %s", coin, msg)

    async def _repay_all(self, cli, coin, why) -> bool:
        """按活负债全额还币(开仓快照不可信);还不掉=裸债 fatal。"""
        try:
            debt = await self.margin.debt(cli, coin)
            if debt <= 0:
                return True
            free = await self.margin.free(cli, coin)
            ok, res = await self.margin.repay(cli, coin, min(debt, free) if free < debt else debt)
            if ok:
                return True
            await self.notify.send("lend-naked-debt", f"S4 {coin} 还币失败",
                                   f"{why}: debt={debt} free={free} err={res.get('err')}", level="fatal")
            return False
        except Exception as e:  # noqa: BLE001
            await self.notify.send("lend-naked-debt", f"S4 {coin} 还币异常", f"{why}: {e!r}", level="fatal")
            return False

    # ---------- 平仓 ----------
    async def close_position(self, cli, coin: str, why: str) -> bool:
        coin = coin.upper()
        symbol = f"{coin}USDT"
        rows = await self.pool.fetch(
            "SELECT id FROM lending_positions WHERE coin=$1 AND state IN ('OPEN','CLOSING')", coin)
        if not rows:
            self.open_syms.discard(coin)
            return True
        await self.pool.execute(
            "UPDATE lending_positions SET state='CLOSING', updated_at=now() "
            "WHERE coin=$1 AND state='OPEN'", coin)
        try:
            await self._ensure_filters(cli, symbol)
            # ① 平永续多头(按实盘余量逐次重试,残腿课)
            for _i in range(3):
                pos = await self.perp.fetch_position(cli, symbol)
                if pos <= 0:
                    break
                l1 = await self._l1(symbol)
                bid = Decimal(str(l1["bid"])) if l1 else None
                if bid is None:
                    log.warning("close %s: L1 缺失,暂缓平对冲", coin)
                    return False
                await self._leg(self.perp, cli, symbol, "SELL", pos, bid, reduce_only=True)
            # ② 买回负债(活口径×1.002 覆盖利息滚动)+③ 还币
            debt = await self.margin.debt(cli, coin)
            if debt > 0:
                free = await self.margin.free(cli, coin)
                need = debt * Decimal("1.002") - free
                if need > 0:
                    l1 = await self._l1(symbol)
                    ask = Decimal(str(l1["ask"])) if l1 else None
                    if ask is None:
                        return False
                    step = self.margin.step.get(symbol, Decimal("0.001"))
                    buy_qty = _round_step(need, step) + step
                    bought, err = await self._leg(self.margin, cli, symbol, "BUY", buy_qty, ask)
                    if bought <= 0:
                        log.warning("close %s: 买回失败 %s", coin, err)
                        return False
                if not await self._repay_all(cli, coin, f"close({why})"):
                    return False
            # 终态校验:负债 0 + 对冲 0
            final_pos = await self.perp.fetch_position(cli, symbol)
            final_debt = await self.margin.debt(cli, coin)
            if abs(final_pos) > 0 or final_debt > 0:
                log.warning("close %s: 未净空 pos=%s debt=%s,下轮重试", coin, final_pos, final_debt)
                return False
            await self.pool.execute(
                "UPDATE lending_positions SET state='CLOSED', closed_at=now(), updated_at=now() "
                "WHERE coin=$1 AND state='CLOSING'", coin)
            self.open_syms.discard(coin)
            self._exit_strikes.pop(coin, None)
            log.info("CLOSE_OK %s (%s)", coin, why)
            return True
        except Exception:  # noqa: BLE001
            log.exception("close %s crashed", coin)
            return False

    # ---------- 每轮持仓管理(无论 mode 都执行——持仓管理不受门闸约束) ----------
    async def manage(self, cli, ranking_by_coin: dict):
        for coin in sorted(self.open_syms):
            rk = ranking_by_coin.get(coin) or {}
            net, detail = await self.signed_net_daily(coin, rk.get("borrow"))
            if net is None:
                log.info("manage %s: 经济学数据缺失(%s),持有", coin, detail)
                continue
            if net < ARM_EXIT_NET_PCT:
                self._exit_strikes[coin] = self._exit_strikes.get(coin, 0) + 1
                if self._exit_strikes[coin] >= EXIT_STRIKES:
                    await self.close_position(cli, coin, f"净差 {net:.3f}%/d < {ARM_EXIT_NET_PCT} 连续{EXIT_STRIKES}轮")
            else:
                self._exit_strikes.pop(coin, None)

    # ---------- 崩溃恢复 ----------
    async def reconcile_startup(self, cli):
        rows = await self.pool.fetch(
            "SELECT id, coin, symbol, state, qty_base FROM lending_positions "
            "WHERE state NOT IN ('CLOSED','FAILED')")
        for row in rows:
            coin, st = row["coin"], row["state"]
            if st == "OPEN":
                self.open_syms.add(coin)
                log.info("RECONCILE claim OPEN %s qty=%s", coin, row["qty_base"])
                continue
            # OPENING/CLOSING/ROLLBACK 残行:按实盘定论
            symbol = row["symbol"]
            try:
                pos = await self.perp.fetch_position(cli, symbol)
                debt = await self.margin.debt(cli, coin)
            except Exception as e:  # noqa: BLE001
                log.warning("reconcile %s 实盘查证失败: %r,保留残行", coin, e)
                continue
            if abs(pos) < Decimal("1e-9") and debt <= 0:
                await self.pool.execute(
                    "UPDATE lending_positions SET state='FAILED', error_message='reconcile: 实盘无腿无债,置败', "
                    "closed_at=now(), updated_at=now() WHERE id=$1", row["id"])
                log.info("RECONCILE %s %s -> FAILED(无腿无债)", coin, st)
            else:
                self.open_syms.add(coin)
                log.error("RECONCILE_FATAL %s %s 实盘有腿/债(pos=%s debt=%s),认领待处置", coin, st, pos, debt)
                await self.notify.send("lend-reconcile", f"S4 {coin} 残行认领",
                                       f"state={st} pos={pos} debt={debt},认领后按 close 路径处置",
                                       level="fatal")


def make_executor(r, pool):
    """有 key 即常驻构造(reconcile 认领);下单按 MODE+ARM_SYMBOLS 双门闸。"""
    key = os.environ.get("BINANCE_KEY", "")
    secret = os.environ.get("BINANCE_SECRET", "")
    if not (key and secret and pool is not None):
        return None
    return LendingExecutor(r, pool, {"key": key, "secret": secret})
