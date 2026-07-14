"""三闸收编 shadow 对比(ADR-002 阶段A)——只记录,不影响任何真钱行为。

现有三类割裂门控(调用点清单,2026-07-14 盘点):
  G-A 策略运行阶段闸:engine_config(dualperp/lending).mode=shadow|armed + arm_symbols/arm_mode
      (消费点:engine-lending armed.py livecfg、退役 dualperp armed.py、manager pairs cfg.mode)
  G-B 全局急停:gateway POST /api/admin/kill → engine_config 置 shadow+清白名单
      (语义=人工全局冻结,物理上与 G-A 同载体,收编时须单独建 global_system_mode 输入维)
  G-C KMS/cred-agent 安全闸 + venue_armed(arm_symbols) place 白名单
      (不可变安全不变量:提现/划转/API管理永久 deny——**不收编**,永远叠加)
新聚合器 = risk-ledger EffectiveRiskPolicy(capabilities.CAN_OPEN)。

阶段A:每轮对比 old_allow(G-A/G-B 阶段是否武装+数据健康)vs new_allow(policy CAN_OPEN),
变化时落 gate_shadow_diff。NEW_LOOSER=新权威单独放行而旧闸拦(阶段E 移除旧闸前必须把该语义
收编为聚合器输入);NEW_STRICTER=新权威更严(安全方向)。连续 7 天审查零危险放宽→阶段C。
"""
import json
import time

_prev: dict = {}   # venue -> (old_allow, new_allow) 上轮判定(只在变化时落库)


async def snapshot_and_diff(pool, r, pol) -> dict:
    if pool is None or not pol:
        return {"note": "pool缺失,shadow对比跳过"}
    # G-A/G-B 输入:engine_config 武装阶段(kill=置shadow,同载体)
    armed_engines = []
    try:
        for row in await pool.fetch(
                "SELECT engine, cval FROM engine_config WHERE ckey='mode'"):
            if row["cval"] == "armed":
                armed_engines.append(row["engine"])
    except Exception:  # noqa: BLE001
        pass
    # manager pair 级武装(cfg.mode=armed 的 pair 涉及的 venue)
    armed_pair_venues = set()
    try:
        cfg = json.loads(await r.get("dcm:exec:manager:config") or "{}")
        for pc in (cfg.get("pairs") or {}).values():
            if pc.get("mode") == "armed":
                for lg in (pc.get("legs") or []):
                    armed_pair_venues.add(lg.get("venue"))
    except Exception:  # noqa: BLE001
        pass
    # 数据健康维(feed 心跳):旧世界里 feed 死=引擎自然停;新聚合器还未收编此维→记录进 inputs
    try:
        hb = json.loads(await r.get("dcm:hb:feed-cex") or "{}")
        data_ok = time.time() - float(hb.get("ts") or 0) < 120
    except Exception:  # noqa: BLE001
        data_ok = False

    stage_armed = bool(armed_engines)
    inputs = {"armed_engines": armed_engines, "armed_pair_venues": sorted(armed_pair_venues),
              "data_ok": data_ok}
    new_rows = 0
    for v, vd in (pol.get("venues") or {}).items():
        old_allow = (stage_armed or v in armed_pair_venues) and data_ok
        new_allow = bool((vd.get("capabilities") or {}).get("CAN_OPEN"))
        if _prev.get(v) == (old_allow, new_allow):
            continue
        _prev[v] = (old_allow, new_allow)
        if old_allow == new_allow:
            continue
        direction = "NEW_LOOSER" if new_allow and not old_allow else "NEW_STRICTER"
        try:
            await pool.execute(
                "INSERT INTO gate_shadow_diff(venue, old_allow, new_allow, direction, inputs) "
                "VALUES($1,$2,$3,$4,$5::jsonb)",
                v, old_allow, new_allow, direction,
                json.dumps({**inputs, "mode": vd.get("mode"), "reason": str(vd.get("reason"))[:150]}))
            new_rows += 1
        except Exception:  # noqa: BLE001
            pass
    return {"armed_engines": armed_engines, "data_ok": data_ok, "new_diffs": new_rows}
