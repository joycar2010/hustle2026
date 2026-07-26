from __future__ import annotations
"""
c3s_writer — V6 C3.S 影子写路 S2:绞杀者命令传输(dry-run,不武装)。

纪律(与 dcm-coin-bridge / batch-H 切写边界一致):
  * V6 决策器的【写者权威】由注册表 product_code='C3.S.V6' 门控,默认 SHADOW。
    ⚠ 注意:注册表里 'C3.S'=ACTIVE_WRITE 说的是【产品可写】,写者仍是老 coin 引擎;
    'C3.S.V6' 是新引入的【V6 自主写者】维度,与产品 flag 正交,默认 SHADOW。
  * 双钥武装(两把都需盯盘放行,本模块永不自行拨动任何一把):
      钥1 注册表 C3.S.V6 == ACTIVE_WRITE
      钥2 Redis  dcm:c3s:v6:armed == "1"
    两者皆真 → 才真入队 rpush dcm:coin:cmd;否则一律【只记录意图,绝不入队】。
  * 信封结构 1:1 复刻 dcmbridge CMD_WHITELIST(manual_open/close/repay/hedge);
    coin 状态机+护栏(借币闸/还币闸/50U 保护)仍在 coin 侧原样权威;
    桥本地铸 JWT(coin 密钥永不离 coin 机)。本模块只产信封,不铸任何凭证。
  * 传输存活 = dcm:coin:panel.ts 新鲜度(桥每 ~60s 发布);超龄=桥不活,dry-run 也如实标注。

用法:
  python c3s_writer.py ensure       # 建影子意图表 + 注册 C3.S.V6=SHADOW + armed=0(幂等)
  python c3s_writer.py selfcheck    # dry-run 自检:构信封→emit→断言未入队+队列长度不变+校验拦非法
  python c3s_writer.py status       # 打印双钥状态 + 桥存活 + 最近意图
"""
import argparse
import asyncio
import json
import re
import sys
import time

sys.path.insert(0, "/data/mix/backend/app")
try:
    import c3s_shadow as S   # 复用 mix_dsn()/_load_env()
except Exception:            # 本地静态检查兜底
    S = None

CMD_QUEUE = "dcm:coin:cmd"
V6_WRITER_CODE = "C3.S.V6"
ARMED_KEY = "dcm:c3s:v6:armed"
PANEL_KEY = "dcm:coin:panel"
BRIDGE_MAX_AGE = 180.0   # 秒;panel 每 ~60s 发布,3× 容差

# 写动作信封契约(镜像 dcmbridge CMD_WHITELIST 的写子集;真相源仍是桥,这里仅做产出端校验)
#   action -> (必填 params 键集合, 说明)
WRITE_ACTIONS = {
    "manual_open":  ({"symbol", "sub_account_id", "amount"}, "手动开仓"),
    "manual_close": ({"position_id"}, "平仓(coin 仅 OPEN 态放行)"),
    "manual_repay": ({"position_id"}, "还币(coin 仅 PENDING_REPAY 态放行)"),
    "manual_hedge": ({"position_id"}, "对冲(coin 仅 BORROWED_IDLE 态放行)"),
    "partial_repay": ({"position_id"}, "部分还币(ratio/amount 之一)"),
}


def _mix_dsn() -> str:
    return S.mix_dsn()


def _redis_url() -> str:
    return S._load_env(S.MIX_ENV).get("MIX_REDIS_URL") or S._load_env(S.MIX_ENV).get("MIX_REDIS")


# ── 信封构造 + 校验(纯函数) ─────────────────────────────────────────────────
def build_envelope(action: str, params: dict, user_id: int = 1) -> tuple[dict | None, str | None]:
    """产出 dcm:coin:cmd 信封 {id,action,params,user_id};校验失败返回 (None, err)。"""
    if action not in WRITE_ACTIONS:
        return None, f"action 不在 V6 写子集: {action}"
    need, _ = WRITE_ACTIONS[action]
    p = dict(params or {})
    missing = [k for k in need if p.get(k) in (None, "")]
    if missing:
        return None, f"缺必填参数: {missing}"
    if "symbol" in p:
        sym = str(p["symbol"]).upper()
        if not re.fullmatch(r"[A-Z0-9]{1,20}", sym):
            return None, "symbol 非法"
        p["symbol"] = sym
    if "position_id" in p:
        try:
            p["position_id"] = int(p["position_id"])
        except (TypeError, ValueError):
            return None, "position_id 必须为整数"
    if "amount" in p:
        try:
            amt = float(p["amount"])
        except (TypeError, ValueError):
            return None, "amount 必须为数值"
        if amt <= 0:
            return None, "amount 必须 > 0"
        p["amount"] = amt
    if "sub_account_id" in p:
        try:
            p["sub_account_id"] = int(p["sub_account_id"])
        except (TypeError, ValueError):
            return None, "sub_account_id 必须为整数"
    env = {"id": f"c3sv6-{int(time.time()*1000)}", "action": action,
           "params": p, "user_id": int(user_id)}
    return env, None


# ── 双钥 + 桥存活 ─────────────────────────────────────────────────────────────
async def writer_authority(pool) -> str:
    """读 C3.S.V6 写者权威;缺行=fail-safe 视为 SHADOW。"""
    try:
        v = await pool.fetchval(
            "SELECT capability FROM product_capability_registry WHERE product_code=$1", V6_WRITER_CODE)
        return v or "SHADOW"
    except Exception:  # noqa: BLE001
        return "SHADOW"


async def armed_flag(rds) -> bool:
    v = await rds.get(ARMED_KEY)
    return str(v) == "1"


async def bridge_liveness(rds) -> dict:
    try:
        raw = await rds.get(PANEL_KEY)
        if not raw:
            return {"alive": False, "age_sec": None, "note": "无 dcm:coin:panel(桥未发布)"}
        d = json.loads(raw)
        age = time.time() - float(d.get("ts") or 0)
        return {"alive": age <= BRIDGE_MAX_AGE, "age_sec": round(age, 1),
                "note": "" if age <= BRIDGE_MAX_AGE else "panel 超龄=桥可能不活"}
    except Exception as e:  # noqa: BLE001
        return {"alive": False, "age_sec": None, "note": f"读桥存活失败:{type(e).__name__}"}


DDL_INTENT = """
CREATE TABLE IF NOT EXISTS c3s_shadow_write_intent (
  id            bigserial PRIMARY KEY,
  cmd_id        text,
  action        text,
  envelope      jsonb,
  capability    text,          -- emit 时 C3.S.V6 权威
  armed         boolean,       -- emit 时 dcm:c3s:v6:armed
  would_send    boolean,       -- 双钥皆真?
  sent          boolean,       -- 是否真入队(dry-run 恒 false)
  dry_run       boolean,
  validation    text,          -- 信封校验错(null=通过)
  bridge_alive  boolean,
  bridge_age    numeric,
  result        jsonb,         -- 真入队时的桥回执(dry-run 为 null)
  source        text,
  created_at    timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_c3s_wi_action ON c3s_shadow_write_intent(action);
CREATE INDEX IF NOT EXISTS ix_c3s_wi_created ON c3s_shadow_write_intent(created_at);
"""

UPSERT_REG = """
INSERT INTO product_capability_registry(product_code,capability,note,updated_by)
VALUES ($1,'SHADOW','V6 C3.S 自主写者:影子写路 S2 传输已铺,双钥未武装(需盯盘放行)',$2)
ON CONFLICT (product_code) DO NOTHING
"""


async def emit(pool, rds, action: str, params: dict, *, user_id: int = 1,
               source: str = "manual", arm=None) -> dict:
    """守卫式发射器 —— 影子写路的唯一出口。
    唯一真入队路径:cap==ACTIVE_WRITE AND armed(双钥)AND 信封合法 AND 桥存活。
    否则一律【只记录意图,不入队】。arm=None → 由 Redis 双钥自动判定(dry-run 默认走这条)。"""
    cap = await writer_authority(pool)
    armed = await armed_flag(rds) if arm is None else bool(arm)
    env, verr = build_envelope(action, params, user_id)
    live = await bridge_liveness(rds)
    would_send = (cap == "ACTIVE_WRITE") and armed
    do_send = would_send and (verr is None) and live["alive"]

    sent = False
    result = None
    if do_send:
        # ⚠ 唯一触碰生产的分支;仅当双钥皆真才可达。dry-run 阶段两钥皆关,永不进入。
        cid = env["id"]
        await rds.rpush(CMD_QUEUE, json.dumps(env, ensure_ascii=False))
        deadline = time.time() + 25.0
        rk = f"dcm:coin:cmd:result:{cid}"
        while time.time() < deadline:
            rr = await rds.get(rk)
            if rr:
                result = json.loads(rr)
                break
            await asyncio.sleep(0.5)
        sent = True

    await pool.execute(
        "INSERT INTO c3s_shadow_write_intent(cmd_id,action,envelope,capability,armed,would_send,"
        "sent,dry_run,validation,bridge_alive,bridge_age,result,source) "
        "VALUES($1,$2,$3::jsonb,$4,$5,$6,$7,$8,$9,$10,$11,$12::jsonb,$13)",
        (env or {}).get("id"), action, json.dumps(env, ensure_ascii=False) if env else None,
        cap, armed, would_send, sent, not sent, verr, live["alive"], live["age_sec"],
        json.dumps(result, ensure_ascii=False) if result else None, source)

    return {"sent": sent, "dry_run": not sent, "would_send": would_send,
            "capability": cap, "armed": armed, "envelope": env,
            "validation": verr, "bridge": live, "result": result}


async def ensure(pool, rds):
    await pool.execute(DDL_INTENT)
    await pool.execute(UPSERT_REG, V6_WRITER_CODE, "c3s_writer.ensure")
    # 显式落地 armed=0(若不存在)——不覆盖既有值
    if await rds.get(ARMED_KEY) is None:
        await rds.set(ARMED_KEY, "0")


async def _sample_open_decision(pool) -> dict | None:
    """从地面账本挑一条可构 OPEN 的近期持仓(有 symbol/sub_account/amount)。"""
    r = await pool.fetchrow(
        "SELECT symbol, sub_account_id, open_usdt_amount FROM c3s_ground_truth "
        "WHERE sub_account_id IS NOT NULL AND open_usdt_amount > 0 "
        "ORDER BY created_at DESC LIMIT 1")
    if not r:
        return None
    return {"symbol": r["symbol"], "sub_account_id": r["sub_account_id"],
            "amount": float(r["open_usdt_amount"])}


async def selfcheck(pool, rds) -> dict:
    """dry-run 自检:证明传输已铺且被双钥关死。
    ①真 OPEN 信封 emit → 断言 sent=False + 队列长度不变;
    ②非法 action → 校验拦下;
    ③汇报双钥状态。"""
    await ensure(pool, rds)
    out = {"keys": {}, "checks": []}
    cap = await writer_authority(pool)
    armed = await armed_flag(rds)
    live = await bridge_liveness(rds)
    out["keys"] = {"C3.S.V6_capability": cap, "armed_flag": armed,
                   "bridge_alive": live["alive"], "bridge_age_sec": live["age_sec"],
                   "double_key_armed": (cap == "ACTIVE_WRITE") and armed}

    qlen0 = await rds.llen(CMD_QUEUE)
    samp = await _sample_open_decision(pool)
    if samp:
        res = await emit(pool, rds, "manual_open", samp, source="selfcheck")
        qlen1 = await rds.llen(CMD_QUEUE)
        out["checks"].append({
            "name": "OPEN dry-run 不入队",
            "envelope_action": (res["envelope"] or {}).get("action"),
            "envelope_params": (res["envelope"] or {}).get("params"),
            "would_send": res["would_send"], "sent": res["sent"], "dry_run": res["dry_run"],
            "queue_len_before": qlen0, "queue_len_after": qlen1,
            "PASS": (res["sent"] is False and qlen1 == qlen0)})
    else:
        out["checks"].append({"name": "OPEN dry-run 不入队", "PASS": None,
                              "note": "无可采样持仓(账本空)"})

    # 非法 action 校验
    bad_env, bad_err = build_envelope("evil_action", {"x": 1})
    out["checks"].append({"name": "非法 action 被校验拦下",
                          "err": bad_err, "PASS": (bad_env is None and bad_err is not None)})
    # 缺参校验
    miss_env, miss_err = build_envelope("manual_open", {"symbol": "BTCUSDT"})
    out["checks"].append({"name": "缺必填参数被拦下",
                          "err": miss_err, "PASS": (miss_env is None and miss_err is not None)})
    # 合法 OPEN 信封结构
    ok_env, ok_err = build_envelope("manual_open",
                                    {"symbol": "abcusdt", "sub_account_id": "9", "amount": "12.5"})
    out["checks"].append({"name": "合法 OPEN 信封成形",
                          "envelope": ok_env, "err": ok_err,
                          "PASS": (ok_env is not None and ok_env["params"]["symbol"] == "ABCUSDT"
                                   and ok_env["params"]["sub_account_id"] == 9)})

    out["all_pass"] = all(c.get("PASS") is not False for c in out["checks"])
    return out


async def status(pool, rds) -> dict:
    cap = await writer_authority(pool)
    armed = await armed_flag(rds)
    live = await bridge_liveness(rds)
    recent = await pool.fetch(
        "SELECT created_at::text, action, would_send, sent, dry_run, validation, source "
        "FROM c3s_shadow_write_intent ORDER BY id DESC LIMIT 10")
    n = await pool.fetchval("SELECT count(*) FROM c3s_shadow_write_intent")
    return {"C3.S.V6_capability": cap, "armed_flag": armed,
            "double_key_armed": (cap == "ACTIVE_WRITE") and armed,
            "bridge": live, "intent_rows": n,
            "recent": [dict(r) for r in recent]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ensure", "selfcheck", "status"])
    args = ap.parse_args()
    import asyncpg
    import redis.asyncio as R
    pool = await asyncpg.connect(_mix_dsn(), timeout=10)
    rds = R.from_url(_redis_url(), decode_responses=True)
    try:
        if args.cmd == "ensure":
            await ensure(pool, rds)
            print("ensure OK: c3s_shadow_write_intent + C3.S.V6=SHADOW + armed=0")
        elif args.cmd == "selfcheck":
            print(json.dumps(await selfcheck(pool, rds), ensure_ascii=False, indent=2, default=str))
        elif args.cmd == "status":
            print(json.dumps(await status(pool, rds), ensure_ascii=False, indent=2, default=str))
    finally:
        await pool.close()
        await rds.aclose()


if __name__ == "__main__":
    asyncio.run(main())
