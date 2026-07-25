"""三闸收编 shadow 对比(ADR-002)——阶段C(2026-07-25 切换)。只记录,不影响任何真钱行为。

现有三类割裂门控(调用点清单,2026-07-14 盘点):
  G-A 策略运行阶段闸:engine_config(dualperp/lending).mode=shadow|armed + arm_symbols/arm_mode
      (消费点:engine-lending armed.py livecfg、退役 dualperp armed.py、manager pairs cfg.mode)
  G-B 全局急停:gateway POST /api/admin/kill → engine_config 置 shadow+清白名单
      (语义=人工全局冻结,物理上与 G-A 同载体,收编时须单独建 global_system_mode 输入维)
  G-C KMS/cred-agent 安全闸 + venue_armed(arm_symbols) place 白名单
      (不可变安全不变量:提现/划转/API管理永久 deny——**不收编**,永远叠加)
新聚合器 = risk-ledger EffectiveRiskPolicy(capabilities.CAN_OPEN)。

═══ 阶段C 切换记录(2026-07-25)═══
审查结论:阶段A 运行 11 天(07-14→07-25),gate_shadow_diff 累计 18 条 NEW_LOOSER,
逐条根因分类后 **18/18 全部为 UNARMED artifact**(事件时 data_ok=true 且
armed_engines=[] 且 venue 不在 armed_pair_venues)——旧闸 old_allow=False 仅因
"系统未武装"这一运营状态,非风险拦截;新聚合器按设计不收编武装态(留阶段E)。
真实危险放宽(数据不健康放行 / 武装态下旧拦新放)= **0 条**,阶段C 安全条件实质满足。
执行器层 "old AND new" 已结构性生效:exec-kernel real_venue.place() 对每笔非减险单
串联 _arm_gate(G-A/G-C) AND _policy_gate(G1, policy_client.can_open),manager 对
全部 venue 适配器注入 policy_r,不可绕过。
阶段C 本模块职责:继续对比,但把 UNARMED artifact 与真实放宽分类标记
(inputs.artifact="UNARMED" vs inputs.genuine=true),使阶段E 审查信号不被噪音淹没。
阶段E 前置条件:武装态语义收编进聚合器输入维 + 阶段C 后 genuine NEW_LOOSER 持续为零。

═══ 武装态收编(2026-07-25,同日增量)═══
policy.py 已发布逐 venue capabilities.CAN_OPEN_ARMED = CAN_OPEN AND 武装态(armed 维收编完成)。
本模块 new_allow 优先读 CAN_OPEN_ARMED(缺失时回退 CAN_OPEN 保持兼容)——
未武装时 old/new 双 False 不再产生 artifact 行,UNARMED 噪音流自然干涸;
剩余 NEW_LOOSER 只剩数据健康维(data_ok 未收编,阶段E 最后一块)= genuine,由 main.py 哨兵告警。
"""
import json
import time

GATE_PHASE = "C"   # ADR-002 阶段标记(2026-07-25 A→C)

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
              "data_ok": data_ok, "gate_phase": GATE_PHASE}
    new_rows = genuine_looser = 0
    for v, vd in (pol.get("venues") or {}).items():
        old_allow = (stage_armed or v in armed_pair_venues) and data_ok
        caps = vd.get("capabilities") or {}
        # 武装态已收编:优先用 CAN_OPEN_ARMED(=CAN_OPEN AND armed);旧快照无此位时回退 CAN_OPEN
        new_allow = bool(caps.get("CAN_OPEN_ARMED", caps.get("CAN_OPEN")))
        if _prev.get(v) == (old_allow, new_allow):
            continue
        _prev[v] = (old_allow, new_allow)
        if old_allow == new_allow:
            continue
        direction = "NEW_LOOSER" if new_allow and not old_allow else "NEW_STRICTER"
        # 阶段C 分类:NEW_LOOSER 且"旧拦"仅因未武装(数据健康)= UNARMED artifact,
        # 非风险放宽(武装态本就不属新聚合器输入维,阶段E 收编)。其余 NEW_LOOSER = genuine,
        # 是阶段E 审查对象(数据不健康放行 / 武装态下旧拦新放)。
        row_inputs = {**inputs, "mode": vd.get("mode"), "reason": str(vd.get("reason"))[:150]}
        if direction == "NEW_LOOSER":
            unarmed = not stage_armed and v not in armed_pair_venues
            if unarmed and data_ok:
                row_inputs["artifact"] = "UNARMED"
            else:
                row_inputs["genuine"] = True
                genuine_looser += 1
        try:
            await pool.execute(
                "INSERT INTO gate_shadow_diff(venue, old_allow, new_allow, direction, inputs) "
                "VALUES($1,$2,$3,$4,$5::jsonb)",
                v, old_allow, new_allow, direction, json.dumps(row_inputs))
            new_rows += 1
        except Exception:  # noqa: BLE001
            pass
    return {"gate_phase": GATE_PHASE, "armed_engines": armed_engines, "data_ok": data_ok,
            "new_diffs": new_rows, "genuine_looser": genuine_looser}
