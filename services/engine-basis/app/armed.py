"""basis armed 执行器:币安现货多+永续空 配对状态机(dualperp armed 蓝本,单所双腿简化)。

双重门闸:DCM_BASIS_MODE=armed 且 symbol ∈ DCM_BASIS_ARM_SYMBOLS(默认空=armed 也不下单)。

money-safety(dualperp 学费逐条移植):
- 现货腿先行:先买现货(持币无强平风险),永续空失败 → 卖回现货回滚,绝不留裸空;
- HTTP 200 ≠ 成交:每腿 fetch_order 轮询到 FILLED,超时撤单;
- 双腿 qty 对齐两边 stepSize(现货/永续步长不同,取先粗后细两次向下取整);
- 防重入三道:inflight 内存 + Redis NX 单飞锁 + DB 非终态行;
- 硬顶 DCM_BASIS_MAX_NOTIONAL_HARD 兜底;
- 崩溃恢复:启动认领 OPEN 行进 open_syms(防重启失忆双开——dualperp canary 真 bug),
  OPENING/CLOSING/ROLLBACK 残行按实盘定论。
平仓触发:资金费日化 ≤ CLOSE_FUNDING(体制消失) 或 symbol 被解除武装(drain 语义)。
"""
import asyncio
import json
import logging
import os
import time
from decimal import Decimal

import httpx

from dcm_common.exchange_trade import BinanceSpotTrade, BinanceTrade, _round_step

log = logging.getLogger("engine-basis.armed")

MODE = os.environ.get("DCM_BASIS_MODE", "shadow")
ARM_SYMBOLS = {s.strip().upper() for s in os.environ.get("DCM_BASIS_ARM_SYMBOLS", "").split(",") if s.strip()}
TARGET_USDT = Decimal(os.environ.get("DCM_BASIS_TARGET_USDT", "8"))
MAX_NOTIONAL_HARD = Decimal(os.environ.get("DCM_BASIS_MAX_NOTIONAL_HARD", "12"))
CLOSE_FUNDING = Decimal(os.environ.get("DCM_BASIS_CLOSE_FUNDING", "0"))
CROSS_BPS = Decimal(os.environ.get("DCM_BASIS_CROSS_BPS", "15"))
LEG_TIMEOUT = int(os.environ.get("DCM_BASIS_LEG_TIMEOUT_SEC", "15"))
DUST_USDT = Decimal(os.environ.get("DCM_BASIS_DUST_USDT", "1"))
# PM 质押(底仓层双份收益):现货多腿申购币安活期理财,平仓前赎回。
# 只做活期(实时赎回);赎回确认→现货到位→再卖 两段式;无产品的长尾币静默跳过。
EARN_ENABLED = os.environ.get("DCM_BASIS_EARN", "false").lower() == "true"
EARN_REDEEM_TIMEOUT = int(os.environ.get("DCM_BASIS_EARN_REDEEM_TIMEOUT_SEC", "60"))


class BasisExecutor:
    def __init__(self, redis, pool, cfg: dict):
        self.r = redis
        self.pool = pool
        self.spot = BinanceSpotTrade(cfg)
        self.perp = BinanceTrade(cfg)
        from dcm_common.binance_earn import BinanceEarn
        self.earn = BinanceEarn(cfg)
        self.open_syms: set[str] = set()
        self.inflight: set[str] = set()
        self._filters: set[str] = set()
        self._cooldown: dict[str, float] = {}  # 开仓失败冷却(无退避重试洪水=testgo -2015 学费)

    def armed_for(self, sym: str) -> bool:
        return MODE == "armed" and sym in ARM_SYMBOLS

    async def _ensure_filters(self, cli, sym: str):
        if sym not in self._filters:
            await self.spot.load_filter(cli, sym)
            await self.perp.load_filter(cli, sym)
            self._filters.add(sym)

    async def _place_confirm(self, tc, cli, sym, side, qty: Decimal, ref_px: Decimal, reduce_only=False):
        """marketable limit 穿价 + 轮询实盘成交。返回 (filled, avg_px, order_id)。"""
        px = ref_px * (Decimal("1") + CROSS_BPS / 10000) if side == "BUY" \
            else ref_px * (Decimal("1") - CROSS_BPS / 10000)
        ok, res = await tc.place_limit(cli, sym, side, qty, px, reduce_only=reduce_only)
        if not ok:
            log.warning("place %s %s %s failed: %s", sym, side, qty, res.get("err"))
            return Decimal("0"), Decimal("0"), ""
        oid = res["order_id"]
        deadline = time.time() + LEG_TIMEOUT
        while time.time() < deadline:
            await asyncio.sleep(0.7)
            ok2, st = await tc.fetch_order(cli, sym, oid)
            if ok2 and st.get("status") == "FILLED":
                return Decimal(str(st.get("filled") or 0)), Decimal(str(st.get("avg") or 0)), oid
        await tc.cancel(cli, sym, oid)
        ok3, st3 = await tc.fetch_order(cli, sym, oid)
        filled = Decimal(str(st3.get("filled") or 0)) if ok3 else Decimal("0")
        avg = Decimal(str(st3.get("avg") or 0)) if ok3 else Decimal("0")
        log.warning("leg timeout %s %s: filled=%s (canceled)", sym, side, filled)
        return filled, avg, oid

    async def reconcile_startup(self, cli):
        """崩溃恢复:OPEN 行认领防双开;其余非终态按实盘定论。"""
        rows = await self.pool.fetch(
            "SELECT id,symbol,base_asset,qty_base,state FROM basis_positions "
            "WHERE state NOT IN ('CLOSED','FAILED')")
        for row in rows:
            sym, st = row["symbol"], row["state"]
            if st == "OPEN":
                self.open_syms.add(sym)
                log.info("RECONCILE claim OPEN %s qty=%s", sym, row["qty_base"])
                continue
            # OPENING/CLOSING/ROLLBACK 残行:实盘查证
            await self._ensure_filters(cli, sym)
            perp_pos = await self.perp.fetch_position(cli, sym)
            base_a = row["base_asset"] or sym.replace("USDT", "")
            spot_bal = await self.spot.fetch_position(cli, base_a)
            if EARN_ENABLED:
                try:  # 质押中的现货腿计入(否则被误判缺腿)
                    spot_bal += Decimal(str(await self.earn.position(cli, base_a)))
                except Exception as e:
                    log.warning("earn position read failed %s: %r", base_a, e)
            if abs(perp_pos) < Decimal("1e-9") and spot_bal < Decimal("1e-9"):
                await self.pool.execute(
                    "UPDATE basis_positions SET state='FAILED',error_message='reconcile: 实盘无腿,置败',"
                    "updated_at=now() WHERE id=$1", row["id"])
                log.info("RECONCILE %s %s -> FAILED(实盘无腿)", sym, st)
            else:
                self.open_syms.add(sym)  # 有腿=认领,人工/close 路径处置
                log.error("RECONCILE_FATAL %s %s 实盘有腿(perp=%s spot=%s),认领待处置",
                          sym, st, perp_pos, spot_bal)

    async def open_pair(self, cli, sym: str, spot_l1: dict, perp_l1: dict,
                        e_bps: str, funding_daily: Decimal) -> bool:
        if sym in self.inflight or sym in self.open_syms:
            return False
        if time.time() < self._cooldown.get(sym, 0):
            return False
        lock = f"dcm:basis:lock:{sym}"
        if not await self.r.set(lock, str(os.getpid()), nx=True, ex=60):
            return False
        self.inflight.add(sym)
        try:
            n = await self.pool.fetchval(
                "SELECT count(*) FROM basis_positions WHERE symbol=$1 AND state NOT IN ('CLOSED','FAILED')", sym)
            if n:
                self.open_syms.add(sym)
                return False
            await self._ensure_filters(cli, sym)
            spot_ask = Decimal(str(spot_l1["ask"]))
            perp_bid = Decimal(str(perp_l1["bid"]))
            notional = min(TARGET_USDT, MAX_NOTIONAL_HARD)
            # 现货余额预检:free USDT 不够名义(含穿价+费缓冲)→冷却 5min,不下注定失败的单
            usdt_free = await self.spot.fetch_position(cli, "USDT")
            if usdt_free < notional * Decimal("1.02"):
                self._cooldown[sym] = time.time() + 300
                log.info("open %s skip: 现货 USDT %.2f < 需 %.2f,冷却 5min",
                         sym, float(usdt_free), float(notional * Decimal("1.02")))
                return False
            qty = notional / spot_ask
            # 双 stepSize 对齐:先粗后细(两边格点都满足)
            step_s = self.spot.step.get(sym, Decimal("0.001"))
            step_p = self.perp.step.get(sym, Decimal("0.001"))
            qty = _round_step(_round_step(qty, max(step_s, step_p)), min(step_s, step_p))
            if qty <= 0 or qty * spot_ask < max(self.spot.min_notional.get(sym, Decimal("5")),
                                                self.perp.min_notional.get(sym, Decimal("5"))):
                log.info("open %s skip: qty=%s 低于最小名义", sym, qty)
                return False
            base = sym.replace("USDT", "")
            row_id = await self.pool.fetchval(
                "INSERT INTO basis_positions(symbol,base_asset,qty_base,notional_usdt,state,open_e_bps,funding_daily)"
                " VALUES($1,$2,$3,$4,'OPENING',$5,$6) RETURNING id",
                sym, base, qty, qty * spot_ask, Decimal(e_bps), funding_daily)
            log.info("OPEN_PAIR %s qty=%s notional=%.2f e=%sbps fund=%s%%/d",
                     sym, qty, float(qty * spot_ask), e_bps, funding_daily)
            # 腿1:现货买(持币无强平风险,先行)
            f_spot, avg_s, oid_s = await self._place_confirm(self.spot, cli, sym, "BUY", qty, spot_ask)
            if f_spot <= 0:
                await self.pool.execute(
                    "UPDATE basis_positions SET state='FAILED',error_message='spot 腿未成',updated_at=now()"
                    " WHERE id=$1", row_id)
                self._cooldown[sym] = time.time() + 300
                return False
            # 腿2:永续空,qty 对齐现货实际成交
            q_perp = _round_step(f_spot, step_p)
            f_perp, avg_p, oid_p = await self._place_confirm(self.perp, cli, sym, "SELL", q_perp, perp_bid)
            if f_perp <= 0:
                # 回滚:卖回现货,绝不留单腿
                log.error("ROLLBACK %s: perp 腿未成,卖回现货 %s", sym, f_spot)
                await self._place_confirm(self.spot, cli, sym, "SELL", f_spot,
                                          Decimal(str(spot_l1["bid"])))
                await self.pool.execute(
                    "UPDATE basis_positions SET state='ROLLBACK',error_message='perp 腿未成,现货已回滚',"
                    "spot_order_id=$2,updated_at=now() WHERE id=$1", row_id, oid_s)
                self._cooldown[sym] = time.time() + 300
                return False
            # 残差轧平:现货成交 > 永续成交 → 卖掉现货多余(低于粉尘留标注)
            resid = f_spot - f_perp
            if resid * avg_s > DUST_USDT:
                await self._place_confirm(self.spot, cli, sym, "SELL", _round_step(resid, step_s),
                                          Decimal(str(spot_l1["bid"])))
            await self.pool.execute(
                "UPDATE basis_positions SET state='OPEN',qty_base=$2,notional_usdt=$3,"
                "spot_order_id=$4,perp_order_id=$5,opened_at=now(),updated_at=now() WHERE id=$1",
                row_id, f_perp, f_perp * avg_s, oid_s, oid_p)
            self.open_syms.add(sym)
            log.info("OPEN_OK %s spot=%s@%s perp=%s@%s", sym, f_spot, avg_s, f_perp, avg_p)
            if EARN_ENABLED:
                asyncio.create_task(self._earn_subscribe(cli, base))
            return True
        finally:
            self.inflight.discard(sym)
            await self.r.delete(lock)

    async def _earn_subscribe(self, cli, base: str):
        """现货多腿 → 活期理财(best-effort:无产品/失败只留日志,绝不影响持仓)。"""
        try:
            prod = await self.earn.flexible_product(cli, base)
            if not prod:
                log.info("earn: %s 无活期产品,跳过", base)
                return
            free = await self.earn.spot_free(cli, base)
            if free <= 0:
                return
            ok, res = await self.earn.subscribe(cli, prod["productId"], f"{free:.8f}".rstrip("0").rstrip("."))
            log.info("earn subscribe %s amount=%s -> %s %s", base, free, ok, str(res)[:120])
        except Exception as e:
            log.warning("earn subscribe %s failed: %r", base, e)

    async def _earn_redeem_wait(self, cli, base: str):
        """赎回全部活期并等现货到位(超时如实放行,卖出量按实际 free 定,不会超卖)。"""
        try:
            amt = await self.earn.position(cli, base)
            if amt <= 0:
                return
            prod = await self.earn.flexible_product(cli, base)
            if not prod:
                log.warning("earn redeem %s: 有持仓但查不到产品,人工核", base)
                return
            ok, res = await self.earn.redeem_all(cli, prod["productId"])
            log.info("earn redeem %s amt=%s -> %s %s", base, amt, ok, str(res)[:120])
            deadline = time.time() + EARN_REDEEM_TIMEOUT
            while time.time() < deadline:
                free = float(await self.spot.fetch_position(cli, base))
                if free >= amt * 0.99:
                    return
                await asyncio.sleep(2)
            log.warning("earn redeem %s 超时未全部到账(继续按实际 free 卖出)", base)
        except Exception as e:
            log.warning("earn redeem %s failed: %r", base, e)

    async def close_pair(self, cli, sym: str, spot_l1: dict, perp_l1: dict, reason: str):
        if sym in self.inflight:
            return
        self.inflight.add(sym)
        try:
            await self._ensure_filters(cli, sym)
            base = sym.replace("USDT", "")
            await self.pool.execute(
                "UPDATE basis_positions SET state='CLOSING',updated_at=now()"
                " WHERE symbol=$1 AND state='OPEN'", sym)
            # 永续平空(实盘净持仓定量,reduce_only)
            perp_pos = await self.perp.fetch_position(cli, sym)
            if perp_pos < 0:
                await self._place_confirm(self.perp, cli, sym, "BUY", -perp_pos,
                                          Decimal(str(perp_l1["ask"])), reduce_only=True)
            # PM 质押赎回:理财在管即先赎回,轮询现货到位再卖(绝不带着理财仓卖现货)
            if EARN_ENABLED:
                await self._earn_redeem_wait(cli, base)
            # 现货卖出全部 free(留格点粉尘)
            spot_bal = await self.spot.fetch_position(cli, base)
            step_s = self.spot.step.get(sym, Decimal("0.001"))
            q_sell = _round_step(spot_bal, step_s)
            if q_sell * Decimal(str(spot_l1["bid"])) > DUST_USDT:
                await self._place_confirm(self.spot, cli, sym, "SELL", q_sell,
                                          Decimal(str(spot_l1["bid"])))
            # 定论
            perp_after = await self.perp.fetch_position(cli, sym)
            spot_after = await self.spot.fetch_position(cli, base)
            if abs(perp_after) < Decimal("1e-9"):
                await self.pool.execute(
                    "UPDATE basis_positions SET state='CLOSED',closed_at=now(),"
                    "error_message=$2,updated_at=now() WHERE symbol=$1 AND state='CLOSING'",
                    sym, f"close: {reason}; spot残余={spot_after}")
                self.open_syms.discard(sym)
                log.info("CLOSE_OK %s (%s) perp=0 spot残余=%s", sym, reason, spot_after)
            else:
                log.error("CLOSE_INCOMPLETE %s perp=%s spot=%s,下轮重试", sym, perp_after, spot_after)
        finally:
            self.inflight.discard(sym)

    async def manage(self, cli, sym: str, spot_l1, perp_l1, funding_daily: Decimal):
        """持仓管理:体制消失或解除武装 → 平仓。"""
        if sym not in self.open_syms:
            return
        if funding_daily <= CLOSE_FUNDING:
            await self.close_pair(cli, sym, spot_l1, perp_l1, f"funding {funding_daily}%/d ≤ {CLOSE_FUNDING}")
        elif not self.armed_for(sym):
            await self.close_pair(cli, sym, spot_l1, perp_l1, "disarmed(drain)")
