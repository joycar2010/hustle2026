"""dcm-coin-bridge:coin 挂号收编旁车(P1.5,零侵入)。

部署在 coin 业务机,用**只读 DB 账号(dcm_ro)**读 positions/engine_state,
按 DexCexMix 总线契约写到 A 机 Redis。coin 现有两个服务(cex-business/cex-arb-engine)
一行代码不动:桥挂了 coin 无感,coin 挂了桥如实上报(engine_state.last_heartbeat 停走)。

键契约(risk-ledger 消费):
- dcm:hb:coin-bridge          桥自身心跳(EX 120)——只证明桥活,不假冒引擎活性
- dcm:engine:coin:state       engine_state 全行(EX 180)——引擎活性由消费者按 last_heartbeat 判断
- dcm:engine:coin:positions   非终态仓位原始字段快照(EX 180)——"coin 引擎声称的在管仓位"(意图账),
                              实盘真相由 risk-ledger 直拉交易所只读 API 另行核对,绝不采信单侧

字段按 DB 原样透传(Decimal→str 保精度),数据面纪律:只采集归一不判断。
兼容 py3.7+(coin 机 Python 版本未知,不用新语法)。
"""
import json
import logging
import os
import re
import time

import psycopg2
import psycopg2.extras
import redis as redis_sync

COIN_PG_DSN = os.environ.get(
    "COIN_PG_DSN", "dbname=cex_trading user=dcm_ro host=127.0.0.1")
DCM_REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_BRIDGE_INTERVAL_SEC", "30"))
# 跨引擎同币仲裁出价中继(契约权威=dcm_common/arb_contract.py,此处内联保持单文件部署):
# coin 引擎评估开仓时写自己 Redis 的 engine:{uid}:neteval:{SYM}(60s TTL,事件驱动),
# 本桥归一成 e_daily_pct(%/天)转发 dcm:arb:coin_e;无 neteval=coin 无意愿=不出价。
COIN_REDIS_URL = os.environ.get("COIN_REDIS_URL", "redis://10.0.1.95:6379/0")
ARB_KEY_COIN = "dcm:arb:coin_e"
ARB_STALE_SEC = 900
ARB_DEFAULT_HOLD_H = float(os.environ.get("DCM_ARB_DEFAULT_HOLD_HOURS", "4"))
ARB_COIN_UID = os.environ.get("DCM_ARB_COIN_UID", "1")  # 引擎权威行=user1
# 代理式操作合并(绞杀者第二步):gateway 把审计过的命令写 dcm:coin:cmd,本桥消费→
# 本地铸 JWT(密钥永不离开 coin 机)→调 coin localhost FastAPI(coin 逻辑仍权威)
# 注:coin 的 CEX_JWT_SECRET 配在 systemd unit 的 Environment= 行(非 .env),unit 644 可读
COIN_ENV = os.environ.get("COIN_ENV_PATH", "/etc/systemd/system/cex-business.service")
COIN_API = os.environ.get("COIN_API_BASE", "http://127.0.0.1:8000")
CMD_QUEUE = "dcm:coin:cmd"
# 白名单:action → (method, path)。v1 只放最安全的引擎启停;扩 manual-close 等须逐个评审
# engine_status 为零副作用只读探针:验证 JWT铸造→coin鉴权→执行→回执 全链路,不动生产状态
# P2 写代理:黑名单增删(coin 逻辑权威;{symbol} 路径参数经正则白名单校验后代入)
CMD_WHITELIST = {
    "engine_status": ("GET", "/api/engine/workers/status", {}),
    "engine_start": ("POST", "/api/engine/workers/start", {}),
    "engine_stop": ("POST", "/api/engine/workers/stop", {}),
    "blacklist_add": ("POST", "/api/blacklist/", {}),
    "blacklist_remove": ("DELETE", "/api/blacklist/{symbol}", {}),
    # 干预菜单（coin 状态机权威:manual_close 仅 OPEN/manual_repay 仅 PENDING_REPAY/
    # manual_hedge 仅 BORROWED_IDLE,还币闸等护栏在 coin 侧原样生效;桥只做 position_id 整数校验）
    "manual_close": ("POST", "/api/engine/manual-close", {}),
    "manual_repay": ("POST", "/api/engine/manual-repay", {}),
    "manual_hedge": ("POST", "/api/engine/manual-hedge", {}),
    "push_symbol": ("POST", "/api/engine/push-symbol/{symbol}", {}),
    # S3 规则写(coin 权威:schema 校验+审计+30s 热重载在 coin 侧原样生效;body=params 透传)
    "rules_update": ("PUT", "/api/global-rules/", {}),
    # 单一规则(某币的 SymbolRule 基线,coin schema 权威):读+写
    "symbol_rule_get": ("GET", "/api/symbol-rules/{symbol}", {}),
    "symbol_rule_put": ("PUT", "/api/symbol-rules/{symbol}", {}),
    # coin 右键菜单 1:1（币种行/账户行/持仓行操作,coin 状态机+护栏原样生效）
    "remove_slot": ("DELETE", "/api/engine/push-symbol/{symbol}", {}),      # 移除币种(50U保护在 coin 侧)
    "resume_slot": ("DELETE", "/api/engine/repay-hold/{symbol}", {}),       # 恢复下单(解还币冻结)
    "manual_open": ("POST", "/api/engine/manual-open", {}),                 # 手动开仓(body: symbol,sub_account_id,amount)
    "manual_force_close": ("POST", "/api/engine/manual-close", {}),        # 强制平仓(body: position_id)
    "partial_repay": ("POST", "/api/engine/partial-repay", {}),             # 部分还币(body: position_id,ratio/amount)
    "batch_remove_empty": ("POST", "/api/blacklist/bulk", {}),             # 批量移除无持仓(body: symbols[])
    "account_symbol_rule_get": ("GET", "/api/account-symbol-rules/{sub}/{symbol}", {}),
    "account_symbol_rule_put": ("PUT", "/api/account-symbol-rules/{sub}/{symbol}", {}),
    "account_symbol_rule_batch": ("POST", "/api/account-symbol-rules/batch", {}),  # S3 批量子账户单一规则
    "max_borrowable": ("GET", "/api/engine/accounts/{sub}/max-borrowable/{symbol}", {}),  # 刷新可借
    "account_transfer": ("POST", "/api/engine/accounts/{sub}/transfer", {}),        # 划转资金
    "transfer_cross": ("POST", "/api/engine/accounts/{sub}/transfer-cross", {}),    # 跨账户万向划转
    # 通用规则「自动划转+账户资金参数表」(coin RulesPage 数据面 1:1;写侧 coin schema 权威)
    "fund_rules_get": ("GET", "/api/fund-rules/", {}),
    "fund_rules_put": ("PUT", "/api/fund-rules/", {}),
    "fund_params_patch": ("PATCH", "/api/sub-accounts/{sub}/fund-params", {}),
    "sub_accounts_get": ("GET", "/api/sub-accounts/", {}),
    "master_balance": ("GET", "/api/master-account/balance", {}),
}
# S3 面板快照发布周期(dcm:coin:panel);原料=coin 引擎自己维护的缓存键+blacklist API,
# 绝不直打交易所 REST(IP 权重预算课)
PANEL_INTERVAL = int(os.environ.get("DCM_PANEL_INTERVAL_SEC", "60"))


def _coin_jwt_secret() -> str | None:
    try:
        m = re.search(r"CEX_JWT_SECRET=([^\s\"']+)", open(COIN_ENV).read())
        return m.group(1) if m else None
    except Exception as e:
        log.warning("read coin jwt secret failed: %r", e)
        return None


def _mint_jwt(secret: str, user_id: int = 1) -> str:
    import datetime
    import jwt
    payload = {"sub": "dcm-proxy", "user_id": user_id, "role": "SUPER_ADMIN",
               "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=5)}
    return jwt.encode(payload, secret, algorithm="HS256")


def _exec_command(cmd: dict) -> dict:
    """执行一条白名单命令,调 coin 本地 FastAPI。返回结果 dict。"""
    import requests
    action = cmd.get("action")
    if action not in CMD_WHITELIST:
        return {"ok": False, "err": f"action 不在白名单: {action}"}
    secret = _coin_jwt_secret()
    if not secret:
        return {"ok": False, "err": "coin jwt secret 不可读"}
    method, path, base_body = CMD_WHITELIST[action]
    params = dict(cmd.get("params") or {})
    consumed = set()
    if "{symbol}" in path:
        sym = str(params.get("symbol", "")).upper()
        if not re.fullmatch(r"[A-Z0-9]{1,20}", sym):
            return {"ok": False, "err": "symbol 非法"}
        path = path.replace("{symbol}", sym)
        consumed.add("symbol")
    if "{sub}" in path:
        sub = str(params.get("sub", ""))
        if not re.fullmatch(r"[0-9]{1,12}", sub):
            return {"ok": False, "err": "sub(子账户 id) 非法"}
        path = path.replace("{sub}", sub)
        consumed.add("sub")
    # 路径参数消费后,body 取剩余 params(PUT/POST 带字段;GET/DELETE body 被 coin 忽略无害)
    body = {**base_body, **{k: v for k, v in params.items() if k not in consumed}}
    # position_id 整数校验:仅需要它的动作(manual_open/partial_repay 用 sub_account_id+symbol 不需要)
    if action in ("manual_close", "manual_repay", "manual_hedge", "manual_force_close"):
        try:
            body["position_id"] = int(body.get("position_id"))
        except (TypeError, ValueError):
            return {"ok": False, "err": "position_id 必须为整数"}
    try:
        tok = _mint_jwt(secret, int(cmd.get("user_id", 1)))
        resp = requests.request(method, f"{COIN_API}{path}", json=body,
                                headers={"Authorization": f"Bearer {tok}"}, timeout=10)
        return {"ok": resp.status_code < 400, "status": resp.status_code,
                "body": resp.json() if resp.headers.get("content-type", "").startswith("application/json") else resp.text[:300]}
    except Exception as e:
        return {"ok": False, "err": repr(e)[:200]}


# ── 路由互斥另一半(M4):decision 路由给非 coin 引擎且 active/draining 的币,
# 写进 coin user1 blacklist(只拦新开仓,存量自然退出);路由解除后删除。
# 所有权纪律:只增删 reason 前缀 dcm-route: 且 user_id=1 的行;
# 人工行/全局系统行(user_id NULL)绝不碰——同币已被人工拉黑则跳过不认领。
# 显式开关 DCM_ROUTE_MUTEX(默认关,部署 .env 显式开)。写路径走 coin FastAPI(coin 逻辑权威)。
ROUTE_MUTEX = os.environ.get("DCM_ROUTE_MUTEX", "0") == "1"
MUTEX_PREFIX = "dcm-route:"
MUTEX_MAX_OPS = 50  # 单轮增删上限,防路由表异常时血洗黑名单


def sync_route_mutex(r) -> dict:
    """对账一轮。返回 {desired, owned, added, removed} 计数(进心跳)。"""
    counts = {"desired": 0, "owned": 0, "added": 0, "removed": 0}
    desired = {}
    for sym, raw in r.hgetall("dcm:route:assignments").items():
        try:
            rt = json.loads(raw)
        except Exception:
            continue
        if rt.get("engine") not in ("coin", "none", "") and \
                rt.get("state") in ("active", "draining"):
            desired[sym.upper()] = rt.get("engine")
    counts["desired"] = len(desired)
    secret = _coin_jwt_secret()
    if not secret:
        return counts
    import requests
    headers = {"Authorization": "Bearer " + _mint_jwt(secret)}
    cur = requests.get(f"{COIN_API}/api/blacklist/", headers=headers, timeout=10)
    cur.raise_for_status()
    rows = cur.json()
    owned = {row["symbol"].upper() for row in rows
             if row.get("user_id") == 1 and (row.get("reason") or "").startswith(MUTEX_PREFIX)}
    all_syms = {row["symbol"].upper() for row in rows}
    counts["owned"] = len(owned)
    ops = 0
    for sym, eng in sorted(desired.items()):
        if sym in all_syms or ops >= MUTEX_MAX_OPS:
            continue  # 已在黑名单(本人或全局)则不重复也不认领
        resp = requests.post(f"{COIN_API}/api/blacklist/", headers=headers, timeout=10,
                             json={"symbol": sym, "reason": MUTEX_PREFIX + eng})
        ops += 1
        if resp.status_code < 400:
            counts["added"] += 1
            log.info("ROUTE_MUTEX add %s (engine=%s)", sym, eng)
        else:
            log.warning("ROUTE_MUTEX add %s failed %s %s", sym, resp.status_code, resp.text[:120])
    for sym in sorted(owned - set(desired)):
        if ops >= MUTEX_MAX_OPS:
            break
        resp = requests.delete(f"{COIN_API}/api/blacklist/{sym}", headers=headers, timeout=10)
        ops += 1
        if resp.status_code < 400:
            counts["removed"] += 1
            log.info("ROUTE_MUTEX del %s (路由解除)", sym)
        else:
            log.warning("ROUTE_MUTEX del %s failed %s %s", sym, resp.status_code, resp.text[:120])
    return counts


def consume_commands(r):
    """消费 dcm:coin:cmd(lpop),执行并把结果写 dcm:coin:cmd:result:{id}(EX60)。"""
    for _ in range(20):  # 每轮最多处理 20 条防饥饿
        raw = r.lpop(CMD_QUEUE)
        if not raw:
            break
        try:
            cmd = json.loads(raw)
        except Exception:
            continue
        cid = cmd.get("id", "")
        log.info("COIN_CMD exec id=%s action=%s by=%s", cid, cmd.get("action"), cmd.get("operator"))
        result = _exec_command(cmd)
        result["ts"] = int(time.time())
        result["action"] = cmd.get("action")
        if cid:
            r.set(f"dcm:coin:cmd:result:{cid}", json.dumps(result, default=str), ex=60)
        log.info("COIN_CMD done id=%s ok=%s", cid, result.get("ok"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("coin-bridge")

SQL_POSITIONS = """
SELECT id, sub_account_id, user_id, symbol, base_asset, status, hedge_account,
       borrow_qty, spot_sell_qty, spot_buy_qty, futures_long_qty, repay_qty,
       open_usdt_amount,
       EXTRACT(EPOCH FROM opened_at)::bigint  AS opened_ts,
       EXTRACT(EPOCH FROM updated_at)::bigint AS updated_ts
FROM positions
WHERE status NOT IN ('CLOSED', 'FAILED')
ORDER BY id
"""

SQL_ENGINE_STATE = """
SELECT scope, status, pid, user_id, active_positions, total_cycles,
       EXTRACT(EPOCH FROM last_heartbeat)::bigint AS heartbeat_ts,
       EXTRACT(EPOCH FROM updated_at)::bigint     AS updated_ts
FROM engine_state
"""


def fetch(dsn):
    conn = psycopg2.connect(dsn)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(SQL_POSITIONS)
            positions = [dict(r) for r in cur.fetchall()]
            cur.execute(SQL_ENGINE_STATE)
            states = [dict(r) for r in cur.fetchall()]
        return positions, states
    finally:
        conn.close()


_last_mutex = {"desired": 0, "owned": 0, "added": 0, "removed": 0}


def publish_state(r):
    positions, states = fetch(COIN_PG_DSN)
    now = int(time.time())
    r.set("dcm:engine:coin:positions", json.dumps(
        {"ts": now, "source": "coin-db-bridge", "venue": "binance",
         "count": len(positions), "positions": positions}, default=str), ex=180)
    r.set("dcm:engine:coin:state", json.dumps(
        {"ts": now, "engine_state": states}, default=str), ex=180)
    r.set("dcm:hb:coin-bridge", json.dumps(
        {"service": "coin-bridge", "ts": now, "pid": os.getpid(),
         "positions_open": len(positions), "engine_scopes": len(states),
         "proxy": "on", "route_mutex": ("on" if ROUTE_MUTEX else "off"),
         "mutex": _last_mutex}), ex=120)
    log.info("BRIDGE_OK positions=%d engine_scopes=%d", len(positions), len(states))


_coin_redis = None


def _get_coin_redis():
    global _coin_redis
    if _coin_redis is None:
        _coin_redis = redis_sync.from_url(
            COIN_REDIS_URL, decode_responses=True,
            socket_timeout=5, socket_connect_timeout=5)
    return _coin_redis


def sync_arb_bids(r):
    """coin neteval → dcm:arb:coin_e 出价中继(60s 一轮)。
    归一:e_daily_pct = E/notional × 24/max(1,hold_hours) × 100。
    同时清理超龄字段(neteval 60s TTL 自灭,出价 900s 后也视为无意愿)。"""
    rc = _get_coin_redis()
    now = int(time.time())
    published = 0
    pat = "engine:%s:neteval:*" % ARB_COIN_UID
    for key in rc.scan_iter(match=pat, count=200):
        try:
            raw = rc.get(key)
            if not raw:
                continue
            d = json.loads(raw)
            n = float(d.get("notional_usdt") or 0)
            if n <= 0:
                continue
            e = float(d.get("E") or 0)
            hold_h = max(1.0, float(d.get("hold_hours") or ARB_DEFAULT_HOLD_H))
            sym = key.rsplit(":", 1)[-1]
            e_daily_pct = e / n * (24.0 / hold_h) * 100.0
            r.hset(ARB_KEY_COIN, sym, json.dumps({
                "v": 1, "src": "coin", "sym": sym,
                "e_daily_pct": round(e_daily_pct, 5),
                "raw": {"E_usdt": e, "notional_usdt": n, "hold_hours": hold_h,
                        "decision": d.get("decision"), "gate_mode": d.get("gate_mode")},
                "ts": now}, ensure_ascii=False))
            published += 1
        except Exception as ex:
            log.warning("arb bid relay failed for %s: %r", key, ex)
    # 超龄清理
    try:
        drop = []
        for sym, s in (r.hgetall(ARB_KEY_COIN) or {}).items():
            try:
                if now - json.loads(s).get("ts", 0) > ARB_STALE_SEC:
                    drop.append(sym)
            except Exception:
                drop.append(sym)
        if drop:
            r.hdel(ARB_KEY_COIN, *drop)
    except Exception as ex:
        log.warning("arb bid reap failed: %r", ex)
    return published


def _blacklist_rows():
    """GET coin blacklist(与 route_mutex 同一鉴权链路)。失败返回 None(消费端如实降级)。"""
    secret = _coin_jwt_secret()
    if not secret:
        return None
    import requests
    headers = {"Authorization": "Bearer " + _mint_jwt(secret)}
    resp = requests.get(f"{COIN_API}/api/blacklist/", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _coin_rules():
    """GET coin user1 全局规则(S3 模板真源;coin schema 权威)。失败返回 None。"""
    secret = _coin_jwt_secret()
    if not secret:
        return None
    import requests
    headers = {"Authorization": "Bearer " + _mint_jwt(secret)}
    resp = requests.get(f"{COIN_API}/api/global-rules/", headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.json()


SQL_CLOSED = """
SELECT id, sub_account_id, user_id, symbol, base_asset, status, hedge_account,
       borrow_qty, spot_sell_qty, spot_buy_qty, futures_long_qty, repay_qty,
       open_usdt_amount,
       EXTRACT(EPOCH FROM opened_at)::bigint AS opened_ts,
       EXTRACT(EPOCH FROM closed_at)::bigint AS closed_ts
FROM positions
WHERE status IN ('CLOSED', 'FAILED') AND closed_at > now() - interval '7 days'
ORDER BY closed_at DESC LIMIT 500
"""


def publish_closed(r):
    """S3 终态仓透传(近7天)→ dcm:coin:closed(EX 900)。mix 交易历史落库的进料口。"""
    conn = psycopg2.connect(COIN_PG_DSN)
    try:
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(SQL_CLOSED)
            rows = [dict(x) for x in cur.fetchall()]
    finally:
        conn.close()
    r.set("dcm:coin:closed", json.dumps(
        {"ts": int(time.time()), "count": len(rows), "positions": rows}, default=str), ex=900)
    return len(rows)


def publish_panel(r):
    """S3 借币面板快照 → dcm:coin:panel(EX 300)。
    原料全部来自 coin 引擎已维护的缓存(coin Redis balance:latest/uid_weight/spreads/
    interest_rates/pushed)+ blacklist API —— 零新增交易所 REST 调用。
    symbol_margin 只保留相关币(pushed ∪ 有余额/借款/利息的币),控制载荷体积。"""
    rc = _get_coin_redis()
    now = int(time.time())

    def gj(key, default=None):
        try:
            raw = rc.get(key)
            return json.loads(raw) if raw else default
        except Exception:
            return default

    balances = gj("balance:latest:%s" % ARB_COIN_UID)
    uid_weight = gj("engine:uid_weight:by_account")
    weight = gj("engine:weight:latest")
    pushed = list(gj("engine:pushed_symbols", []) or [])
    pushed += list(gj("engine:%s:pushed_symbols" % ARB_COIN_UID, []) or [])
    pushed = sorted({str(s).upper() for s in pushed})

    relevant = set(pushed)
    slim_balances = None
    if isinstance(balances, dict):
        for acct in balances.get("balances", []):
            for sym, d in (acct.get("symbol_margin") or {}).items():
                try:
                    if any(float(d.get(f) or 0) != 0 for f in ("free", "borrowed", "interest")):
                        relevant.add(sym.upper())
                except Exception:
                    pass
        slim_balances = {k: v for k, v in balances.items() if k != "balances"}
        slim_balances["balances"] = []
        for acct in balances.get("balances", []):
            a2 = {k: v for k, v in acct.items() if k != "symbol_margin"}
            a2["symbol_margin"] = {s: d for s, d in (acct.get("symbol_margin") or {}).items()
                                   if s.upper() in relevant}
            slim_balances["balances"].append(a2)

    ir = gj("market:interest_rates", {}) or {}
    bases = {s[:-4] if s.endswith("USDT") else s for s in relevant}
    interest = {b: ir[b] for b in bases if b in ir}
    spreads = {}
    for sym in relevant:
        try:
            v = rc.hget("spreads", sym if sym.endswith("USDT") else sym + "USDT")
            if v:
                spreads[sym] = json.loads(v)
        except Exception:
            pass
    blacklist = None
    try:
        blacklist = _blacklist_rows()
    except Exception as e:
        log.warning("panel blacklist fetch failed: %r", e)
    rules = None
    try:
        rules = _coin_rules()
    except Exception as e:
        log.warning("panel rules fetch failed: %r", e)

    raw = json.dumps({"ts": now, "source": "coin-bridge-panel",
                      "balances": slim_balances, "uid_weight": uid_weight, "weight": weight,
                      "pushed": pushed, "interest_rates": interest,
                      "spreads": spreads, "blacklist": blacklist, "rules": rules}, default=str)
    r.set("dcm:coin:panel", raw, ex=300)
    global _rt_relevant
    _rt_relevant = sorted(relevant)   # 实时点差快线的币集(随 panel 60s 更新)
    log.info("PANEL_OK bytes=%d pushed=%d relevant=%d bl=%s", len(raw), len(pushed),
             len(relevant), (len(blacklist) if isinstance(blacklist, list) else "n/a"))


# 实时点差快线:coin rust 引擎持续维护 spreads hash(逐 tick 更新),panel 60s 太钝。
# 每个主循环 tick(2s) HMGET 相关币透传 dcm:coin:spreads_rt —— 载荷 ~几KB,coin 本机 Redis 零压力。
_rt_relevant = []


def publish_spreads_rt(r):
    if not _rt_relevant:
        return
    rc = _get_coin_redis()
    keys = [s if s.endswith("USDT") else s + "USDT" for s in _rt_relevant]
    vals = rc.hmget("spreads", keys)
    out = {}
    for sym, raw in zip(_rt_relevant, vals):
        if not raw:
            continue
        try:
            out[sym] = json.loads(raw)
        except Exception:
            pass
    if out:
        r.set("dcm:coin:spreads_rt", json.dumps(
            {"ts": int(time.time()), "spreads": out}, default=str), ex=30)


def main():
    global _last_mutex
    r = redis_sync.from_url(DCM_REDIS_URL, decode_responses=True)
    log.info("coin-bridge up interval=%ss redis=%s proxy_whitelist=%s route_mutex=%s",
             INTERVAL, DCM_REDIS_URL, list(CMD_WHITELIST), ROUTE_MUTEX)
    last_state = 0.0
    last_mutex_ts = 0.0
    last_arb_ts = 0.0
    last_panel_ts = 0.0
    while True:
        try:
            consume_commands(r)              # 命令消费(~2s 响应)
            try:
                publish_spreads_rt(r)        # 实时点差快线(每 tick ~2s)
            except Exception as e:
                log.warning("spreads_rt round failed: %r", e)
            if time.time() - last_panel_ts >= PANEL_INTERVAL:
                try:
                    publish_panel(r)         # S3 面板快照(60s)
                except Exception as e:
                    log.warning("panel round failed: %r", e)
                try:
                    publish_closed(r)        # 终态仓透传(交易历史进料口)
                except Exception as e:
                    log.warning("closed round failed: %r", e)
                last_panel_ts = time.time()
            if ROUTE_MUTEX and time.time() - last_mutex_ts >= 60:
                try:
                    _last_mutex = sync_route_mutex(r)   # 路由互斥对账(60s)
                except Exception as e:
                    log.warning("route mutex round failed: %r", e)
                last_mutex_ts = time.time()
            if time.time() - last_arb_ts >= 60:
                try:
                    sync_arb_bids(r)         # 仲裁出价中继(60s)
                except Exception as e:
                    log.warning("arb bids round failed: %r", e)
                last_arb_ts = time.time()
            if time.time() - last_state >= INTERVAL:
                publish_state(r)             # 状态发布(INTERVAL)
                last_state = time.time()
        except Exception as e:
            log.warning("bridge round failed: %r", e)
        time.sleep(2)


if __name__ == "__main__":
    main()
