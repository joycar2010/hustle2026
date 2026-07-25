#!/usr/bin/env python3
"""lab_redemption —— 赎回模型框架(LAB G1 解锁工程,2026-07-25 开工,无死线)。

铁律(承 LP0"诚实不假解锁"原则):
  ① DRAFT 随便建,**VERIFIED 只能由 verify 全查通过晋级**——绝无手工置 VERIFIED 入口;
  ② 每项检查必须基于**真实链上数据**(RPC 实读),适配器硬编码值只能当"预期值"被核对,
     不能当证据;缺 RPC/缺合约地址=检查 FAIL(诚实失败),绝不跳过;
  ③ model_hash=全量规范化 sha256,VERIFIED 后模型内容不可变(改=新 DRAFT 走全套);
  ④ 检查通过时落 lab_evidence(D2 四类:CONTRACT_IDENTITY/EXCHANGE_RATE/
     REDEEM_STATUS/TARGET_QUOTE)——G1 的证据闸与模型闸同源同时解锁。

用法:
  python3 lab_redemption.py draft     # 从 pt_cusd_adapter 生成/更新 DRAFT(幂等 by hash)
  python3 lab_redemption.py verify <model_id>   # 跑全套检查,全过才晋级 VERIFIED
  python3 lab_redemption.py list
当前缺口(verify 会逐项报):RPC provider(env LAB_ETH_RPC)+ PT/SY/cUSD 合约地址
(env LAB_PT_ADDR/LAB_SY_ADDR/LAB_CUSD_ADDR)——填入并核对后检查才可能通过。
"""
import hashlib
import json
import os
import sqlite3
import sys
import time

DB = os.path.expanduser("~/dexlab/dexlab.db")


def _db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def canonical_hash(model: dict) -> str:
    return hashlib.sha256(json.dumps(model, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def build_draft_from_adapter() -> dict:
    """从 pt_cusd_adapter 抽取结构(标注 provenance=adapter-static,链上未证)。"""
    sys.path.insert(0, os.path.expanduser("~/dexlab"))
    from pt_cusd_adapter import PTcUSDAdapter
    a = PTcUSDAdapter()
    asset_graph = {
        "nodes": [{"symbol": "PT-cUSD", "decimals": 18}, {"symbol": "SY-cUSD", "decimals": 18},
                  {"symbol": "cUSD", "decimals": 18}, {"symbol": "USDC", "decimals": 6}],
        "edges": [{"from": "PT-cUSD", "to": "SY-cUSD", "op": "redeemPY(到期1:1)"},
                  {"from": "SY-cUSD", "to": "cUSD", "op": "SY.redeem(exchangeRate)"},
                  {"from": "cUSD", "to": "USDC", "op": "pool swap(近平价)"}],
        "provenance": {"source": "adapter-static", "onchain_verified": False},
    }
    call_graph = {
        "steps": [
            {"n": 1, "contract": "PendleRouter", "fn": "redeemPyToSy", "addr_env": "LAB_PT_ADDR"},
            {"n": 2, "contract": "SY-cUSD", "fn": "redeem", "addr_env": "LAB_SY_ADDR"},
            {"n": 3, "contract": "cUSD/USDC pool", "fn": "swap", "addr_env": "LAB_CUSD_ADDR"},
        ],
        "provenance": {"source": "adapter-static", "onchain_verified": False},
    }
    unit_conversion = {
        "PT-cUSD->SY-cUSD": {"factor": "1.0", "basis": "到期赎回1:1(Pendle-v2语义,待链上证)"},
        "SY-cUSD->cUSD": {"factor": "exchangeRate(live)", "basis": "适配器硬编码1.02=预期值非证据"},
        "cUSD->USDC": {"factor": "~0.9995", "basis": "池价快照,待实读"},
        "decimals": {"PT-cUSD": 18, "SY-cUSD": 18, "cUSD": 18, "USDC": 6},
    }
    return {"instrument_version": a.instrument_version, "protocol_version": "Pendle-v2",
            "asset_graph": asset_graph, "call_graph": call_graph,
            "unit_conversion": unit_conversion}


# ── 验证检查注册表:每项返回 (passed: bool, evidence_type: str|None, detail: str) ──

def _check_rpc_ready():
    rpc = os.environ.get("LAB_ETH_RPC", "")
    if not rpc:
        return False, None, "缺 LAB_ETH_RPC(链上验证的前提,未配置=诚实失败)"
    try:
        import urllib.request
        req = urllib.request.Request(rpc, data=json.dumps(
            {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}).encode(),
            headers={"Content-Type": "application/json"})
        blk = json.loads(urllib.request.urlopen(req, timeout=10).read()).get("result")
        return bool(blk), None, f"RPC可达 block={blk}"
    except Exception as e:  # noqa: BLE001
        return False, None, f"RPC不可达:{repr(e)[:80]}"


def _check_contract_identity(model):
    """PT/SY 合约身份链上核对(bytecode 非空+地址来源核对)。"""
    ok, _t, d = _check_rpc_ready()
    if not ok:
        return False, None, f"前置RPC失败:{d}"
    missing = [e for e in ("LAB_PT_ADDR", "LAB_SY_ADDR") if not os.environ.get(e)]
    if missing:
        return False, None, f"缺合约地址 {missing}(须人工从Pendle官方登记核对后填入)"
    return False, None, "地址已配但bytecode/身份核对未实现(下一步:eth_getCode+官方registry比对)"


def _check_exchange_rate(model):
    """SY exchangeRate 实读 vs 模型预期(硬编码1.02只是预期,实读才是证据)。"""
    ok, _t, d = _check_rpc_ready()
    if not ok:
        return False, None, f"前置RPC失败:{d}"
    return False, None, "exchangeRate eth_call 未实现(下一步:SY.exchangeRate() 实读+入证据)"


def _check_unit_roundtrip(model):
    """单位换算自洽性(纯数学,可离线过):decimals 声明与转换路径一致。"""
    uc = model.get("unit_conversion") or {}
    dec = uc.get("decimals") or {}
    nodes = {n["symbol"]: n["decimals"] for n in (model.get("asset_graph") or {}).get("nodes", [])}
    if dec and nodes and all(dec.get(k) == v for k, v in nodes.items()):
        return True, None, f"decimals 声明自洽 {nodes}"
    return False, None, f"decimals 不一致 graph={nodes} vs conv={dec}"


def _check_redeem_status(model):
    ok, _t, d = _check_rpc_ready()
    if not ok:
        return False, None, f"前置RPC失败:{d}"
    return False, None, "赎回开关/到期状态链上读未实现(下一步:PT expiry+isExpired 实读)"


CHECKS = [
    ("unit_roundtrip", _check_unit_roundtrip, None),
    ("contract_identity", _check_contract_identity, "CONTRACT_IDENTITY"),
    ("exchange_rate_live", _check_exchange_rate, "EXCHANGE_RATE"),
    ("redeem_status", _check_redeem_status, "REDEEM_STATUS"),
]


def cmd_draft():
    m = build_draft_from_adapter()
    h = canonical_hash(m)
    mid = f"rm-{m['instrument_version']}-{h[:12]}"
    c = _db()
    try:
        row = c.execute("SELECT model_id, verification_status FROM lab_redemption_models "
                        "WHERE model_hash=?", (h,)).fetchone()
        if row:
            print(f"已存在(幂等): {row['model_id']} status={row['verification_status']}")
            return
        c.execute(
            "INSERT INTO lab_redemption_models(model_id, instrument_version, protocol_version, "
            "asset_graph_json, call_graph_json, unit_conversion_json, model_hash, "
            "verification_status) VALUES(?,?,?,?,?,?,?,'DRAFT')",
            (mid, m["instrument_version"], m["protocol_version"],
             json.dumps(m["asset_graph"], ensure_ascii=False),
             json.dumps(m["call_graph"], ensure_ascii=False),
             json.dumps(m["unit_conversion"], ensure_ascii=False), h))
        c.commit()
        print(f"DRAFT 已建: {mid} hash={h[:16]}… (G1 仍锁:须 verify 全过才 VERIFIED)")
    finally:
        c.close()


def cmd_verify(model_id):
    c = _db()
    try:
        row = c.execute("SELECT * FROM lab_redemption_models WHERE model_id=?", (model_id,)).fetchone()
        if not row:
            print(f"无此模型: {model_id}"); return 1
        model = {"instrument_version": row["instrument_version"],
                 "protocol_version": row["protocol_version"],
                 "asset_graph": json.loads(row["asset_graph_json"]),
                 "call_graph": json.loads(row["call_graph_json"]),
                 "unit_conversion": json.loads(row["unit_conversion_json"])}
        results, all_pass = [], True
        for name, fn, ev_type in CHECKS:
            try:
                passed, _ev, detail = fn(model)
            except Exception as e:  # noqa: BLE001
                passed, detail = False, f"check crashed: {repr(e)[:80]}"
            results.append((name, passed, detail))
            all_pass = all_pass and passed
            print(f"  [{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        if all_pass:
            c.execute("UPDATE lab_redemption_models SET verification_status='VERIFIED', "
                      "verified_at=?, verified_by='lab_redemption.verify', updated_at=? "
                      "WHERE model_id=? AND verification_status='DRAFT'",
                      (int(time.time()), int(time.time()), model_id))
            c.commit()
            print(f"全过 → {model_id} 晋级 VERIFIED(G1 模型闸解锁;证据闸另计)")
        else:
            fails = [n for n, p, _d in results if not p]
            print(f"未晋级(诚实失败): {len(fails)}/{len(results)} 检查未过 {fails}")
            print("解锁路径: 填 LAB_ETH_RPC + LAB_PT_ADDR/LAB_SY_ADDR(人工从Pendle官方核对)"
                  " → 实现三项链上检查 → 重跑 verify")
        return 0 if all_pass else 2
    finally:
        c.close()


def cmd_list():
    c = _db()
    try:
        for r in c.execute("SELECT model_id, instrument_version, verification_status, "
                           "verified_at FROM lab_redemption_models"):
            print(dict(r))
    finally:
        c.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "draft":
        cmd_draft()
    elif cmd == "verify":
        sys.exit(cmd_verify(sys.argv[2]))
    else:
        cmd_list()
