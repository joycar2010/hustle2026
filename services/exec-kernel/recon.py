"""exec-kernel shadow 对账 loop(V4.0 §6.2/§11.1)—— B 机运行,零下单,多所。
读 dcm_main 引擎声称持仓(期望)对比各所 RealVenue 交易所真相(实际),逐腿分类:
  MATCH / QTY_MISMATCH / SIDE_MISMATCH / ORPHAN_CLAIM(声称在管实盘平)/
  NAKED_EXCHANGE(实盘有仓内核不知=最危险)/ UNCHECKABLE(venue 无适配器)
已支持 venue:binance/bybit/gate/bitget(okx/HL 待补)。发布 dcm:exec:recon + 心跳。**只读。**
"""
import asyncio
import json
import os
import sys
import time

import asyncpg
import redis.asyncio as aioredis

sys.path.insert(0, "/home/ec2-user/dexcexmix")
from real_venue import venue_for  # noqa: E402

DCM_PG_DSN = os.environ.get("DCM_PG_DSN", "")
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_RECON_INTERVAL_SEC", "120"))
TOL_PCT = float(os.environ.get("DCM_RECON_TOL_PCT", "0.02"))
SUPPORTED = {"binance", "bybit", "gate", "bitget", "okx", "hyperliquid"}
# C3 保证金借币短腿(binance-margin):负债=空头。⚠️coin C3.S 引擎共用同一保证金账户,
# 所以只对 manager 声明的 C3 腿对账,**绝不做裸债全量扫描**(否则误报 coin 合法债务为 NAKED)。
MARGIN_VENUES = {"binance-margin"}
CHECK_VENUES = SUPPORTED | MARGIN_VENUES


def _venue_sym(venue, sym):
    """各所符号格式:gate=BASE_USDT / okx=BASE-USDT-SWAP / HL=BASE(币名);其余同 dcm(BASEUSDT)。"""
    if not sym.endswith("USDT"):
        return sym
    base = sym[:-4]
    if venue == "gate":
        return base + "_USDT"
    if venue == "okx":
        return base + "-USDT-SWAP"
    if venue == "hyperliquid":
        return base
    return sym


def _canon_sym(venue, vsym):
    """_venue_sym 的逆:把各所实盘符号规整回 dcm 规范 BASEUSDT(reaper 判'实盘有无该 symbol'用)。"""
    s = str(vsym or "")
    if venue == "gate" and s.endswith("_USDT"):
        return s[:-5] + "USDT"
    if venue == "okx" and s.endswith("-USDT-SWAP"):
        return s[:-10] + "USDT"
    if venue == "hyperliquid" and not s.endswith("USDT"):
        return s + "USDT"
    return s.upper()


async def _venue_positions(venue):
    v = venue_for(venue)
    if v is None or not hasattr(v, "all_positions"):
        return None
    r = await v.all_positions()
    return r.get("positions", {}) if r.get("ok") else None


async def reconcile(pool, r) -> dict:
    # 期望:{venue: {venue_sym: {source, exp_qty, exp_sign}}}
    expected = {v: {} for v in CHECK_VENUES}
    unchecked = []

    def add(venue, sym, source, qty, sign):
        if venue in CHECK_VENUES:
            expected.setdefault(venue, {})[_venue_sym(venue, sym)] = {
                "source": source, "exp_qty": qty, "exp_sign": sign}
        else:
            unchecked.append({"type": "UNCHECKABLE", "symbol": sym, "venue": venue,
                              "note": f"{venue} 适配器未建"})

    # C1 basis:binance 永续空腿(-qty_base);现货腿是余额非持仓,暂不在此对账
    for row in await pool.fetch(
            "SELECT symbol, qty_base FROM basis_positions WHERE state NOT IN ('CLOSED','FAILED')"):
        add("binance", row["symbol"], f"C1:{row['symbol']}:perp_short", float(row["qty_base"] or 0), -1)

    # C2 dualperp:多腿 +qty / 空腿 -qty
    for row in await pool.fetch(
            "SELECT symbol, venue_long, venue_short, qty_base FROM dualperp_positions "
            "WHERE state NOT IN ('CLOSED','FAILED')"):
        q = float(row["qty_base"] or 0)
        add(row["venue_long"], row["symbol"], f"C2:{row['symbol']}:long", q, +1)
        add(row["venue_short"], row["symbol"], f"C2:{row['symbol']}:short", q, -1)

    # C3 coin:binance 主账户对冲腿(快照,无精确数量→只确认非平)
    try:
        snap = json.loads(await r.get("dcm:engine:coin:positions") or "{}")
        for p in (snap.get("positions") or []):
            if str(p.get("status")) in ("OPEN", "BORROWED_IDLE", "PENDING_REPAY"):
                expected["binance"].setdefault(str(p.get("symbol") or ""),
                                               {"source": f"C3:{p.get('symbol')}", "exp_qty": None, "exp_sign": 0})
    except Exception:  # noqa: BLE001
        pass

    # exec-manager 接管仓(引擎退役后 manager=owner-of-record,无引擎 DB 行):
    # 读 dcm:exec:manager 发布态(20s刷新EX300;manager 死→键消失→接管仓如实转 NAKED 告警,fail-loud)。
    # pairs 腿的 symbol 已是 venue 格式(manager 存的就是 venue_sym 结果),直接入 expected。
    try:
        mgr = json.loads(await r.get("dcm:exec:manager") or "{}")
        for s in (mgr.get("symbols") or []):   # C1 形态:binance 永续腿
            amt = float(s.get("perp_amt") or 0)
            if abs(amt) > 1e-12:
                expected["binance"][str(s.get("symbol") or "")] = {
                    "source": f"MGR:{s.get('symbol')}:perp", "exp_qty": abs(amt),
                    "exp_sign": 1 if amt > 0 else -1}
        for p in (mgr.get("pairs") or []):     # C2 形态:跨所双永续腿
            for lg in (p.get("legs") or []):
                amt = float(lg.get("amt") or 0)
                v = lg.get("venue")
                if abs(amt) > 1e-12 and v in CHECK_VENUES:
                    expected.setdefault(v, {})[str(lg.get("symbol") or "")] = {
                        "source": f"MGR:{p.get('pair')}:{v}", "exp_qty": abs(amt),
                        "exp_sign": 1 if amt > 0 else -1}
    except Exception:  # noqa: BLE001
        pass

    breaks = list(unchecked)
    matched = 0
    real_syms = set()       # 本轮实盘确有仓的规范 symbol(matched + naked),reaper 判'仓是否真没了'用
    read_fail_venues = []   # 本轮读失败的 venue——有失败则 reaper 保守跳过(不 increment miss),防抖动误平
    for venue in CHECK_VENUES:
        exp = expected.get(venue) or {}
        # 非 MARGIN venue 即使零声称仓也拉实盘扫裸仓——闭合"配置丢失/manager死致 venue 级孤儿"盲区
        # (2026-07-21 混沌演练发现:manager:config 被 wipe 后 expected 全空,旧逻辑 continue 跳过整个 venue,
        #  DEXEUSDT 裸在交易所却扫不到;R11 兜住但 recon 该做第二网)。
        # MARGIN venue 无声称仓仍跳过:coin C3.S 共用保证金账户,未声明债务是 coin 合法仓不越界扫。
        if not exp and venue in MARGIN_VENUES:
            continue
        actual = await _venue_positions(venue)
        if actual is None:
            read_fail_venues.append(venue)
            for sym, e in exp.items():
                breaks.append({"type": "VENUE_READ_FAIL", "venue": venue, "symbol": sym, "source": e["source"]})
            continue
        actual = dict(actual)
        for _vs, _amt in actual.items():   # 快照读到的所有非零实盘仓(在 .pop 消费前先归集规范 symbol)
            if abs(float(_amt or 0)) > 1e-12:
                real_syms.add(_canon_sym(venue, _vs))
        for sym, e in exp.items():
            amt = actual.pop(sym, None)
            if amt is None or abs(amt) < 1e-12:
                breaks.append({"type": "ORPHAN_CLAIM", "venue": venue, "symbol": sym, "source": e["source"],
                               "note": "引擎声称在管,实盘平"})
                continue
            if e["exp_sign"] and (amt > 0) != (e["exp_sign"] > 0):
                breaks.append({"type": "SIDE_MISMATCH", "venue": venue, "symbol": sym, "source": e["source"],
                               "actual_sign": "+" if amt > 0 else "-"})
                continue
            eq = e["exp_qty"]
            if eq is None:
                matched += 1
                continue
            if eq > 0 and abs(abs(amt) - eq) / eq > TOL_PCT:
                breaks.append({"type": "QTY_MISMATCH", "venue": venue, "symbol": sym, "source": e["source"],
                               "expected": eq, "actual": abs(amt), "diff_pct": round(abs(abs(amt) - eq) / eq * 100, 3)})
            else:
                matched += 1
        # 该所剩余实盘 = 裸露仓(内核不知)。
        # ⚠️binance-margin 除外:coin C3.S 引擎共用同一保证金账户,未声明债务是 coin 的合法仓,
        # 内核无从判断裸露(§21 不越界 coin),只对声明腿对账,不扫裸债。
        if venue not in MARGIN_VENUES:
            for sym, amt in actual.items():
                breaks.append({"type": "NAKED_EXCHANGE", "venue": venue, "symbol": sym, "actual": amt,
                               "note": "实盘有仓但引擎无声称"})

    summary = {"ts": int(time.time()), "matched": matched, "supported_venues": sorted(CHECK_VENUES),
               "breaks": breaks, "break_types": sorted({b["type"] for b in breaks}),
               "real_syms": sorted(real_syms), "read_fail_venues": sorted(read_fail_venues),
               "clean_read": not read_fail_venues}
    await r.set("dcm:exec:recon", json.dumps(summary, ensure_ascii=False), ex=max(INTERVAL * 3, 600))
    return summary


# ── 缺陷③ config-less 孤儿 saga GC(shadow 先行)──────────────────────────────
# 缺陷②(manager flat 收尾)只能收 manager **仍在 watch-list** 的 saga。若 operator 从
# dcm:exec:manager:config 删掉某 pair,manager 再不巡它→其 OPEN saga 永远孤儿,缺陷②够不着。
# 本 GC 补这个洞:saga OPEN **且** symbol 不在 watch-list **且** recon 本轮实盘无该仓 **且**
# 本轮无 venue 读失败 → 连续 REAP_MISS_ROUNDS 轮达标才动。
# 铁律:①shadow 先行(默认只发提案 dcm:exec:reaper,不改库);DCM_REAP_ENFORCE=true 才真收。
#       ②有 venue 读失败的轮次整轮跳过(不 increment)——抖动的所不能驱动误平。
#       ③实盘有该 symbol 任何仓(matched/naked)→ reset:裸仓是要暴露的真风险,不是要藏的幽灵。
#       ④仅 UPDATE 已存在行,绝不 INSERT 幽灵行。
import re as _re
REAP_MISS_ROUNDS = int(os.environ.get("DCM_REAP_MISS_ROUNDS", "5"))   # 5×120s≈10min 连续无仓才收
REAP_ENFORCE = os.environ.get("DCM_REAP_ENFORCE", "").lower() == "true"
_REAP_SYM_RE = _re.compile(r"[A-Z0-9]{2,}(?:USDT|USDC|USD|BUSD)")


def _sym_from_saga_id(saga_id):
    m = _REAP_SYM_RE.search(str(saga_id or "").upper())
    return m.group(0) if m else None


async def _watched_symbols(r):
    """manager 当前 watch-list 的 symbol 集合(config pairs+symbols ∪ 发布态)。
    在这里面的 saga 归 manager 管(缺陷②收),reaper 不碰;不在=config-less 孤儿候选。"""
    w = set()
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        for pid, pc in (cfg.get("pairs") or {}).items():
            w.add((pc.get("symbol") or pid).upper())
        for s in (cfg.get("symbols") or {}):
            w.add(str(s).upper())
    except Exception:  # noqa: BLE001
        pass
    try:
        mg = json.loads(await r.get("dcm:exec:manager") or "{}")
        for p in (mg.get("pairs") or []):
            if p.get("symbol"):
                w.add(str(p["symbol"]).upper())
        for s in (mg.get("symbols") or []):
            if s.get("symbol"):
                w.add(str(s["symbol"]).upper())
    except Exception:  # noqa: BLE001
        pass
    return {x for x in w if x}


async def reap_orphans(pool, r, recon_summary):
    """基于 recon 本轮实盘态,GC config-less 孤儿 saga。返回提案 dict(published 到 dcm:exec:reaper)。"""
    if not recon_summary.get("clean_read"):
        # 有 venue 读失败:整轮跳过,连计数都不动(保守——抖动不驱动误平)
        prop = {"ts": int(time.time()), "enforce": REAP_ENFORCE, "skipped": "unclean_read",
                "read_fail_venues": recon_summary.get("read_fail_venues", []), "proposals": [], "reaped": []}
        await r.set("dcm:exec:reaper", json.dumps(prop, ensure_ascii=False), ex=max(INTERVAL * 3, 600))
        return prop
    real = set(recon_summary.get("real_syms") or [])
    watched = await _watched_symbols(r)
    rows = await pool.fetch("SELECT saga_id FROM exec_saga WHERE state='OPEN'")
    proposals, reaped = [], []
    seen_saga = set()
    for row in rows:
        sid = row["saga_id"]
        seen_saga.add(sid)
        sym = _sym_from_saga_id(sid)
        mk = f"dcm:exec:reaper:miss:{sid}"
        if not sym or sym in watched or sym in real:
            # 归 manager 管 / 实盘确有仓 → 不是孤儿,清计数
            await r.delete(mk)
            continue
        # config-less 孤儿本轮命中:miss +1
        try:
            n = await r.incr(mk)
            await r.expire(mk, INTERVAL * REAP_MISS_ROUNDS * 6)   # 断链自然过期清零
        except Exception:  # noqa: BLE001
            n = 1
        item = {"saga_id": sid, "symbol": sym, "miss_rounds": int(n), "threshold": REAP_MISS_ROUNDS}
        if n < REAP_MISS_ROUNDS:
            item["action"] = "watching"
            proposals.append(item)
            continue
        # 达阈:shadow 只提案;enforce 才真收(UPDATE-only)
        if REAP_ENFORCE:
            try:
                res = await pool.execute(
                    "UPDATE exec_saga SET state='CLOSED', saga_version=saga_version+1, updated_at=now() "
                    "WHERE saga_id=$1 AND state='OPEN'", sid)
                if res.endswith(" 1"):
                    item["action"] = "REAPED→CLOSED"
                    reaped.append(item)
                    await r.delete(mk)
                else:
                    item["action"] = "enforce_noop(已非OPEN)"
            except Exception as e:  # noqa: BLE001
                item["action"] = f"enforce_err({repr(e)[:60]})"
        else:
            item["action"] = "WOULD_REAP(shadow;设DCM_REAP_ENFORCE=true才真收)"
        proposals.append(item)
    prop = {"ts": int(time.time()), "enforce": REAP_ENFORCE, "clean_read": True,
            "watched_count": len(watched), "open_saga_count": len(seen_saga),
            "proposals": proposals, "reaped": reaped}
    await r.set("dcm:exec:reaper", json.dumps(prop, ensure_ascii=False), ex=max(INTERVAL * 3, 600))
    return prop


async def main():
    if not DCM_PG_DSN:
        print("DCM_PG_DSN 未设"); return
    pool = await asyncpg.create_pool(DCM_PG_DSN, min_size=1, max_size=2, command_timeout=10)
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    once = "--once" in sys.argv
    while True:
        try:
            s = await reconcile(pool, r)
            nb = len(s["breaks"])
            print(f"recon: matched={s['matched']} breaks={nb} " + (json.dumps(s["break_types"]) if nb else "全绿"))
            try:
                rp = await reap_orphans(pool, r, s)
                nprop, nreap = len(rp.get("proposals", [])), len(rp.get("reaped", []))
                if nprop or nreap:
                    print(f"reaper: enforce={rp.get('enforce')} proposals={nprop} reaped={nreap} "
                          + json.dumps([f"{p['symbol']}:{p['miss_rounds']}/{p['threshold']}:{p['action']}"
                                        for p in rp.get('proposals', [])], ensure_ascii=False))
            except Exception as e:  # noqa: BLE001
                print("reaper err:", repr(e)[:150])
            await r.set("dcm:hb:exec-recon", json.dumps({"ts": int(time.time()), "pid": os.getpid(),
                        "service": "exec-recon", "breaks": nb}), ex=300)
        except Exception as e:  # noqa: BLE001
            print("recon err:", repr(e)[:150])
        if once:
            break
        await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
