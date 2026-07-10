"""armed 执行器:双合约配对建仓/平仓状态机(testgo 蓝本落地)。

双重门闸(两个都满足才真下单):MODE=armed 且 symbol ∈ DCM_DP_ARM_SYMBOLS。
默认 arm_symbols 空 → 即便 MODE=armed 也不下任何单(canary 逐币显式放行)。

money-safety 核心(每条学费背书):
- 先进薄盘口腿:两腿中深度较薄一侧先下,成交确认后再补厚腿(厚腿易成,回滚代价小);
- HTTP 200 ≠ 成交:每腿下单后 fetch_order 轮询到 FILLED 才算数,超时即撤;
- 单腿超时/失败回滚:已成腿立即反向平掉,绝不留裸腿过夜(裸空安全网的执行版);
- 残差轧平:两腿成交量不等 → 净 delta 超粉尘即在实盘轧平,收敛到中性;
- 防重入三道:inflight 内存标志 + Redis 单飞锁 NX+TTL + DB 非终态行拦截;
- 硬顶:单腿名义 DCM_DP_MAX_NOTIONAL_HARD 兜底,配置错也下不出大单;
- 崩溃恢复:启动扫 DB 非终态行,实盘对账,裸腿平掉/配对续跑。
只支持 binance+bybit(canary venues),其余 venue 的 armed 路由告警跳过。
"""
import asyncio
import json
import logging
import os
import time
from decimal import Decimal

import httpx

from dcm_common.exchange_trade import TRADE_CLIENTS

log = logging.getLogger("engine-dualperp.armed")

ARM_SYMBOLS = {s.strip().upper() for s in os.environ.get("DCM_DP_ARM_SYMBOLS", "").split(",") if s.strip()}
MAX_NOTIONAL_HARD = Decimal(os.environ.get("DCM_DP_MAX_NOTIONAL_HARD", "25"))
# 组合级敞口闸(多币并跑防线):全组合在场名义总额上限
MAX_PORTFOLIO_NOTIONAL = Decimal(os.environ.get("DCM_DP_MAX_PORTFOLIO_NOTIONAL", "80"))
# 逐所保证金预算:单所在场名义 ≤ 该所权益 × 此系数(保守杠杆上限,防单所过度占用)
VENUE_LEV_FACTOR = Decimal(os.environ.get("DCM_DP_VENUE_LEV_FACTOR", "3"))
LEG_TIMEOUT = int(os.environ.get("DCM_DP_LEG_TIMEOUT_SEC", "15"))
CROSS_BPS = Decimal(os.environ.get("DCM_DP_CROSS_BPS", "15"))       # marketable limit 穿价幅度
MAX_SLIP_BPS = Decimal(os.environ.get("DCM_DP_MAX_SLIP_BPS", "40"))  # 穿价超此拒下(滑点保护)
DUST_USDT = Decimal(os.environ.get("DCM_DP_DUST_USDT", "1"))
SUPPORTED = {"binance", "bybit"}


class ArmedExecutor:
    def __init__(self, redis, pool, notifier, cfg: dict):
        self.r = redis
        self.pool = pool
        self.notifier = notifier
        self.clients = {v: TRADE_CLIENTS[v](cfg[v]) for v in SUPPORTED if cfg.get(v, {}).get("key")}
        self.open_syms: set[str] = set()
        self.inflight: set[str] = set()
        self._filters_loaded: set[tuple[str, str]] = set()

    def armed_for(self, sym: str) -> bool:
        return sym in ARM_SYMBOLS and self.clients.keys() >= SUPPORTED

    async def _alert(self, key, title, content, level="warn"):
        try:
            await asyncio.to_thread(self.notifier.fire, key, title, content, level=level, marquee=True,
                                    color="#ef4444")
        except Exception as e:
            log.error("alert failed %s: %r", key, e)
        log.warning("ARMED_ALERT[%s] %s | %s", key, title, content)

    async def _ensure_filter(self, cli, venue, symbol):
        if (venue, symbol) not in self._filters_loaded:
            await self.clients[venue].load_filter(cli, symbol)
            self._filters_loaded.add((venue, symbol))

    async def _band(self, venue, symbol, side_key) -> float:
        raw = await self.r.get(f"dcm:depth:{venue}:perp:{symbol}")
        if not raw:
            return 0.0
        return float(json.loads(raw).get(side_key) or 0)

    async def _exposure(self, exclude_sym: str | None = None):
        """当前在场敞口:(全组合名义, {venue: 该所名义})。每配对名义计入其两腿所各一次。"""
        rows = await self.pool.fetch(
            "SELECT symbol,venue_long,venue_short,notional_usdt FROM dualperp_positions "
            "WHERE state IN ('OPEN','OPENING')")
        total = Decimal("0")
        per_venue: dict[str, Decimal] = {}
        for row in rows:
            if exclude_sym and row["symbol"] == exclude_sym:
                continue
            n = Decimal(str(row["notional_usdt"] or 0))
            total += n
            per_venue[row["venue_long"]] = per_venue.get(row["venue_long"], Decimal("0")) + n
            per_venue[row["venue_short"]] = per_venue.get(row["venue_short"], Decimal("0")) + n
        return total, per_venue

    async def _venue_equity(self, venue: str) -> Decimal:
        raw = await self.r.get(f"dcm:account:{venue}")
        if not raw:
            return Decimal("0")
        d = json.loads(raw)
        return Decimal(str(d.get("equity_usdt") or 0)) if d.get("ok") else Decimal("0")

    async def _place_confirm(self, cli, venue, symbol, side, qty: Decimal, ref_px: Decimal):
        """marketable limit 穿价下单 + 轮询实盘成交。返回 (filled_base, avg_px, order_id) 或 (0,..)。"""
        tc = self.clients[venue]
        if side in ("BUY", "Buy"):
            px = ref_px * (Decimal("1") + CROSS_BPS / 10000)
        else:
            px = ref_px * (Decimal("1") - CROSS_BPS / 10000)
        ok, res = await tc.place_limit(cli, symbol, side, qty, px)
        if not ok:
            log.warning("place %s %s %s failed: %s", venue, symbol, side, res.get("err"))
            return Decimal("0"), Decimal("0"), ""
        oid = res["order_id"]
        deadline = time.time() + LEG_TIMEOUT
        while time.time() < deadline:
            await asyncio.sleep(0.7)
            ok2, st = await tc.fetch_order(cli, symbol, oid)
            if ok2 and st.get("status") in ("FILLED", "Filled"):
                return (Decimal(str(st.get("filled") or 0)),
                        Decimal(str(st.get("avg") or 0)), oid)
        # 超时:撤单,取实际已成(可能部分)
        await tc.cancel(cli, symbol, oid)
        await asyncio.sleep(0.5)
        ok3, st = await tc.fetch_order(cli, symbol, oid)
        filled = Decimal(str(st.get("filled") or 0)) if ok3 else Decimal("0")
        return filled, Decimal(str(st.get("avg") or 0)) if ok3 else Decimal("0"), oid

    async def _flatten(self, cli, venue, symbol, signed_qty: Decimal, ref_px: Decimal):
        """反向平掉 signed_qty(>0 平多→SELL, <0 平空→BUY),reduce 语义用穿价确保成交。"""
        if abs(signed_qty) <= 0:
            return
        side = "SELL" if signed_qty > 0 else "BUY"
        if venue == "bybit":
            side = "Sell" if signed_qty > 0 else "Buy"
        filled, _, _ = await self._place_confirm(cli, venue, symbol, side, abs(signed_qty), ref_px)
        log.info("flatten %s %s %s qty=%s filled=%s", venue, symbol, side, abs(signed_qty), filled)

    async def open_pair(self, cli, route: dict, target_usdt: Decimal, l1_long: dict, l1_short: dict):
        sym = route["symbol"]
        vl, vs = route["venue_long"], route["venue_short"]
        if not (vl in SUPPORTED and vs in SUPPORTED):
            await self._alert(f"unsupported:{sym}", "armed 路由含不支持 venue",
                              f"{sym} {vl}/{vs} 暂只支持 binance+bybit", "warn")
            return
        # 硬顶(单腿)
        target_usdt = min(target_usdt, MAX_NOTIONAL_HARD)

        # 组合级敞口闸 + 逐所保证金预算闸(多币并跑防线)
        total, per_venue = await self._exposure(exclude_sym=sym)
        if total + target_usdt > MAX_PORTFOLIO_NOTIONAL:
            log.info("open %s skipped: 组合敞口 %s+%s > 上限 %s", sym, total, target_usdt, MAX_PORTFOLIO_NOTIONAL)
            return
        for v in (vl, vs):
            eq = await self._venue_equity(v)
            budget = eq * VENUE_LEV_FACTOR
            used = per_venue.get(v, Decimal("0"))
            if used + target_usdt > budget:
                log.info("open %s skipped: %s 所名义 %s+%s > 预算 %s(权益%s×%s)",
                         sym, v, used, target_usdt, budget, eq, VENUE_LEV_FACTOR)
                return

        mid_long = (Decimal(str(l1_long["bid"])) + Decimal(str(l1_long["ask"]))) / 2
        mid_short = (Decimal(str(l1_short["bid"])) + Decimal(str(l1_short["ask"]))) / 2
        if mid_long <= 0 or mid_short <= 0:
            return
        qty = target_usdt / mid_long

        # 单飞锁(跨重启防重入)
        lock = f"dcm:dp:lock:{sym}"
        if not await self.r.set(lock, str(os.getpid()), nx=True, ex=max(LEG_TIMEOUT * 4, 90)):
            log.info("open %s skipped: single-flight lock held", sym)
            return
        self.inflight.add(sym)
        try:
            await self._ensure_filter(cli, vl, sym)
            await self._ensure_filter(cli, vs, sym)
            # 双保险防重复开仓:开仓前实盘预检,任一腿已有仓 → 认领为持仓,不再开
            # (open_syms 内存态可能因重启丢失,实盘才是真相——双开根因的确定性防线)
            pre_l = await self.clients[vl].fetch_position(cli, sym)
            pre_s = await self.clients[vs].fetch_position(cli, sym)
            if abs(pre_l) > 0 or abs(pre_s) > 0:
                self.open_syms.add(sym)
                log.warning("open %s aborted: 实盘已有仓 long=%s short=%s → 认领不重开", sym, pre_l, pre_s)
                return
            row_id = await self.pool.fetchval(
                "INSERT INTO dualperp_positions(symbol,venue_long,market_long,venue_short,market_short,"
                "account_long,account_short,notional_usdt,state) "
                "VALUES($1,$2,'perp',$3,'perp','sub','main',$4,'OPENING') RETURNING id",
                sym, vl, vs, float(target_usdt))

            # 先进薄盘口腿:比较两腿将吃那一侧的 band 深度
            long_depth = await self._band(vl, sym, "ask_usdt")   # 多腿吃 ask
            short_depth = await self._band(vs, sym, "bid_usdt")  # 空腿吃 bid
            long_first = long_depth <= short_depth
            legs = [("long", vl, "BUY", mid_long), ("short", vs, "SELL", mid_short)]
            if not long_first:
                legs = legs[::-1]

            # 腿1(薄)
            leg1 = legs[0]
            side1 = leg1[2] if leg1[1] == "binance" else ({"BUY": "Buy", "SELL": "Sell"}[leg1[2]])
            f1, avg1, oid1 = await self._place_confirm(cli, leg1[1], sym, side1, qty, leg1[3])
            if f1 <= 0:
                await self.pool.execute("UPDATE dualperp_positions SET state='FAILED',"
                                        "error_message='leg1 no fill',updated_at=now() WHERE id=$1", row_id)
                log.info("open %s aborted: thin leg no fill (clean, no exposure)", sym)
                return

            # 腿2(厚),数量对齐腿1实际成交(保持中性)
            leg2 = legs[1]
            side2 = leg2[2] if leg2[1] == "binance" else ({"BUY": "Buy", "SELL": "Sell"}[leg2[2]])
            f2, avg2, oid2 = await self._place_confirm(cli, leg2[1], sym, side2, f1, leg2[3])

            # 残差:两腿成交 base 之差
            residual = f1 - f2
            if abs(residual) * mid_long > DUST_USDT:
                if f2 <= 0:
                    # 腿2 全废 → 回滚腿1(平掉已成)
                    signed = f1 if leg1[2] == "BUY" else -f1
                    await self._flatten(cli, leg1[1], sym, signed, leg1[3])
                    await self.pool.execute("UPDATE dualperp_positions SET state='ROLLBACK',"
                                            "error_message='leg2 no fill, leg1 flattened',updated_at=now() "
                                            "WHERE id=$1", row_id)
                    await self._alert(f"rollback:{sym}", "配对回滚(单腿未成)",
                                      f"{sym} 腿2({leg2[1]})未成,已平腿1({leg1[1]}) {f1}", "fatal")
                    return
                # 部分残差 → 在腿1 venue 轧平净敞口
                signed_res = residual if leg1[2] == "BUY" else -residual
                await self._flatten(cli, leg1[1], sym, signed_res, leg1[3])
                await self._alert(f"residual:{sym}", "配对残差已轧平",
                                  f"{sym} 腿差 {residual} base 已轧平", "warn")

            await self.pool.execute(
                "UPDATE dualperp_positions SET state='OPEN',qty_base=$2,long_order_id=$3,short_order_id=$4,"
                "opened_at=now(),updated_at=now() WHERE id=$1",
                row_id, float(min(f1, f2)),
                oid1 if long_first else oid2, oid2 if long_first else oid1)
            self.open_syms.add(sym)
            log.info("OPEN %s qty=%s long_avg=%s short_avg=%s", sym, min(f1, f2),
                     avg1 if long_first else avg2, avg2 if long_first else avg1)
        except Exception as e:
            log.exception("open_pair %s crashed", sym)
            await self._alert(f"open-crash:{sym}", "配对建仓异常", f"{sym}: {e!r}", "fatal")
        finally:
            self.inflight.discard(sym)
            await self.r.delete(lock)

    async def close_pair(self, cli, sym: str):
        """平对腿:两腿实盘净持仓反向平掉,收敛到 0。"""
        lock = f"dcm:dp:lock:{sym}"
        if not await self.r.set(lock, str(os.getpid()), nx=True, ex=max(LEG_TIMEOUT * 4, 90)):
            return
        self.inflight.add(sym)
        try:
            row = await self.pool.fetchrow(
                "SELECT id,venue_long,venue_short FROM dualperp_positions "
                "WHERE symbol=$1 AND state='OPEN' ORDER BY id DESC LIMIT 1", sym)
            if not row:
                return
            await self.pool.execute("UPDATE dualperp_positions SET state='CLOSING',updated_at=now() "
                                    "WHERE id=$1", row["id"])
            for venue in (row["venue_long"], row["venue_short"]):
                await self._ensure_filter(cli, venue, sym)
                net = await self.clients[venue].fetch_position(cli, sym)
                if abs(net) > 0:
                    l1 = await self.r.hget(f"dcm:feed:{venue}:perp", sym)
                    ref = Decimal(str(json.loads(l1)["bid"])) if l1 else Decimal("0")
                    if ref > 0:
                        await self._flatten(cli, venue, sym, net, ref)
            # 平后复核
            resid = Decimal("0")
            for venue in (row["venue_long"], row["venue_short"]):
                resid += abs(await self.clients[venue].fetch_position(cli, sym))
            if resid * Decimal("1") > 0 and resid > 0:
                await self._alert(f"close-resid:{sym}", "平仓后仍有残仓",
                                  f"{sym} 两腿净残 {resid} base,需人工核", "fatal")
            # 平掉该币全部 OPEN/CLOSING 行(双开留下多行时一并收口,net 已按实盘平净)
            await self.pool.execute("UPDATE dualperp_positions SET state='CLOSED',closed_at=now(),"
                                    "updated_at=now() WHERE symbol=$1 AND state IN ('OPEN','CLOSING')", sym)
            self.open_syms.discard(sym)
            log.info("CLOSED %s", sym)
        except Exception as e:
            log.exception("close_pair %s crashed", sym)
            await self._alert(f"close-crash:{sym}", "配对平仓异常", f"{sym}: {e!r}", "fatal")
        finally:
            self.inflight.discard(sym)
            await self.r.delete(lock)

    async def reconcile_startup(self, cli):
        """崩溃恢复:含 OPEN 的所有非终态行 vs 实盘。**必须加载 OPEN 进 open_syms**——
        否则重启后引擎忘记持仓,would_open 会重复开仓(双开根因)。裸腿平掉,双腿齐→OPEN,皆无→FAILED。"""
        rows = await self.pool.fetch(
            "SELECT id,symbol,venue_long,venue_short FROM dualperp_positions "
            "WHERE state IN ('OPENING','OPEN','CLOSING','ROLLBACK')")
        seen: set[str] = set()
        for row in rows:
            sym = row["symbol"]
            if sym in seen:  # 同币多行(双开历史),实盘已在首行认领,跳过重复
                continue
            try:
                await self._ensure_filter(cli, row["venue_long"], sym)
                await self._ensure_filter(cli, row["venue_short"], sym)
                nl = await self.clients[row["venue_long"]].fetch_position(cli, sym)
                ns = await self.clients[row["venue_short"]].fetch_position(cli, sym)
                if abs(nl) > 0 and abs(ns) > 0:
                    seen.add(sym)
                    await self.pool.execute("UPDATE dualperp_positions SET state='OPEN',updated_at=now() "
                                            "WHERE id=$1", row["id"])
                    self.open_syms.add(sym)
                    log.info("reconcile: %s both legs present long=%s short=%s -> OPEN(adopted)", sym, nl, ns)
                elif abs(nl) > 0 or abs(ns) > 0:
                    # 裸腿:平掉
                    for venue, net in ((row["venue_long"], nl), (row["venue_short"], ns)):
                        if abs(net) > 0:
                            l1 = await self.r.hget(f"dcm:feed:{venue}:perp", sym)
                            ref = Decimal(str(json.loads(l1)["bid"])) if l1 else Decimal("0")
                            if ref > 0:
                                await self._flatten(cli, venue, sym, net, ref)
                    await self.pool.execute("UPDATE dualperp_positions SET state='FAILED',"
                                            "error_message='reconcile: naked leg flattened',updated_at=now() "
                                            "WHERE id=$1", row["id"])
                    await self._alert(f"recon-naked:{sym}", "启动对账发现裸腿(已平)",
                                      f"{sym} 单腿残仓已平,原状态非终态", "fatal")
                else:
                    await self.pool.execute("UPDATE dualperp_positions SET state='FAILED',"
                                            "error_message='reconcile: no positions',updated_at=now() "
                                            "WHERE id=$1", row["id"])
            except Exception:
                log.exception("reconcile %s crashed", sym)
