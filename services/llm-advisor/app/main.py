"""llm-advisor(顾问评审层):把市场全景喂 LLM,产出带理由与风险标注的排序意见。

定位(严守 coin/testgo 事故史铁律):**只读、只建议、绝不碰钱路**——
- 不写路由(dcm:route:assignments 只有 decision/carry-advisor 能写)、不下单、不改任何业务键;
- 唯一产物 = dcm:advisor:llm(供控制台展示)+ 心跳;
- LLM 幻觉最坏后果 = 产出一条被人忽略的建议,永远不能造成一笔交易。
与规则版 carry-advisor 的关系:规则顾问仍是唯一写路由的自动方;本层是"第二双眼睛",
对规则候选、当前 active 路由、shadow 战绩给自然语言评判和风险提示,人看了参考。

数据面纪律(与全系一致):
- 快照全部从已发布的总线键读(funding/lending/basis/dualperp/routes/pnl/risk),不自采不重算;
- 数据不新鲜照实标注喂给 LLM,由 LLM 自己权衡,本层不替它裁剪判断;
- LLM 输出**硬 schema 校验**:字段缺失/类型错/越界一律丢弃该条,坏响应整轮弃用(留上轮),
  绝不把未校验的模型输出直接落键(testgo 阶梯顾问铁律:LLM 出参必过硬校验才采信)。

未配 DCM_LLM_KEY → llm:unconfigured,不调用、不报错、心跳照常(shadow-first:先上线降级态,填 key 即武装)。
"""
import asyncio
import json
import logging
import os
import time

import httpx
import asyncpg
import redis.asyncio as aioredis

from dcm_common.heartbeat import Heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("llm-advisor")

REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
INTERVAL = int(os.environ.get("DCM_LLM_INTERVAL_SEC", "900"))     # 15min:LLM 调用不廉价,慢节奏
LLM_KEY = os.environ.get("DCM_LLM_KEY", "").strip()
# openai 兼容中转(qh 已验证 api.chesspnt.com);base_url 含 /v1,补 /chat/completions
LLM_BASE = os.environ.get("DCM_LLM_BASE_URL", "https://api.chesspnt.com/v1").rstrip("/")
LLM_MODEL = os.environ.get("DCM_LLM_MODEL", "gpt-5.5")
LLM_TIMEOUT = int(os.environ.get("DCM_LLM_TIMEOUT_SEC", "60"))
LLM_MAX_TOKENS = int(os.environ.get("DCM_LLM_MAX_TOKENS", "1500"))
# 中转站热配置(权威=mix_main.llm_relays,mix-backend 发布到此键;缺失=回落 env 单站)
CONFIG_KEY = "dcm:llm:config"
# 熔断器(testauto /infra 模式移植):整轮(所有中转站)失败连续 N 次 → 冷却 base×2^trips 指数退避;
# 状态在 Redis 供 mix 展示/手动重置(DEL 即恢复)。
BREAKER_KEY = "dcm:llm:breaker"
CB_THRESHOLD = int(os.environ.get("DCM_LLM_CB_THRESHOLD", "2"))
CB_BASE_COOLDOWN = int(os.environ.get("DCM_LLM_CB_BASE_COOLDOWN_SEC", "120"))
CB_MAX_COOLDOWN = int(os.environ.get("DCM_LLM_CB_MAX_COOLDOWN_SEC", "3600"))
FUNDING_FRESH_SEC = int(os.environ.get("DCM_LLM_FUNDING_FRESH_SEC", "1800"))
TOP_CANDIDATES = int(os.environ.get("DCM_LLM_TOP_CANDIDATES", "15"))
VENUES = ["binance", "okx", "bybit", "gate", "bitget", "hyperliquid"]

# 有效动作白名单:LLM 只能就三种角度发言,越界的动作字段丢弃该条(防"建议下单"类幻觉混入)
VALID_ACTIONS = {"endorse", "caution", "avoid", "watch"}


async def _get_json(r, key):
    try:
        raw = await r.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _best_pair(per_venue: dict):
    """最低日化=多腿, 最高日化=空腿, edge=差(与 carry-advisor 同口径)。"""
    if len(per_venue) < 2:
        return None
    lo = min(per_venue.items(), key=lambda kv: kv[1]["daily_pct"])
    hi = max(per_venue.items(), key=lambda kv: kv[1]["daily_pct"])
    if lo[0] == hi[0]:
        return None
    return lo[0], hi[0], round(float(hi[1]["daily_pct"]) - float(lo[1]["daily_pct"]), 5)


async def build_snapshot(r) -> dict:
    """从总线键组装市场全景(紧凑,控 token)。全部只读已发布键,不自采。"""
    now = time.time()
    # 资金费差候选(逐币最优对)
    funding: dict[str, dict] = {}
    for v in VENUES:
        try:
            raw = await r.hgetall(f"dcm:feed:funding:{v}")
        except Exception:
            continue
        for sym, js in raw.items():
            try:
                d = json.loads(js)
            except json.JSONDecodeError:
                continue
            if now - float(d.get("ts") or 0) > FUNDING_FRESH_SEC:
                continue
            funding.setdefault(sym, {})[v] = d
    cands = []
    for sym, per_venue in funding.items():
        bp = _best_pair(per_venue)
        if bp:
            cands.append({"symbol": sym, "long": bp[0], "short": bp[1], "edge_daily_pct": bp[2]})
    cands.sort(key=lambda c: -c["edge_daily_pct"])

    lending = await _get_json(r, "dcm:lending:ranking") or {}
    basis = await _get_json(r, "dcm:engine:basis:positions") or {}
    dp = await _get_json(r, "dcm:engine:dualperp:positions") or {}
    risk = await _get_json(r, "dcm:risk:status") or {}
    pnl = await _get_json(r, "dcm:pnl:summary") or {}
    try:
        routes_raw = await r.hgetall("dcm:route:assignments")
        routes = [json.loads(x) for x in routes_raw.values()]
    except Exception:
        routes = []
    active = [{"symbol": rt.get("symbol"), "engine": rt.get("engine"),
               "venues": f"{rt.get('venue_long')}/{rt.get('venue_short')}",
               "state": rt.get("state"), "target": rt.get("target_notional_usdt"),
               "by": rt.get("updated_by")}
              for rt in routes if rt.get("state") in ("active", "proposed")]
    # basis shadow would_open 摘要
    basis_wo = [{"symbol": s, "e_bps": v.get("e_bps"), "funding_daily": v.get("funding_daily")}
                for s, v in (basis.get("shadow") or {}).items()
                if v.get("decision") == "would_open"][:10]

    return {
        "ts": int(now),
        "funding_edge_top": cands[:TOP_CANDIDATES],
        "lending_top": (lending.get("top") or [])[:10],
        "lending_inversions": lending.get("inversions") or [],
        "basis_would_open": basis_wo,
        "dualperp_shadow_syms": list((dp.get("shadow") or {}).keys())[:15],
        "active_routes": active,
        "net_exposure_breaches": (risk.get("net_exposure") or {}).get("breaches") or [],
        "waterline": risk.get("waterline") or [],
        "pnl": {"net_total": pnl.get("net_total"), "net_today": pnl.get("net_today")},
        "alerts_this_round": risk.get("alerts_this_round", 0),
    }


SYSTEM_PROMPT = (
    "你是一个加密货币资金费套利(carry/basis)组合的风控与机会评审顾问。"
    "你只提供分析意见,绝无下单权——你的输出仅供人类操作员参考。"
    "给你的是一个多所(binance/okx/bybit/gate/bitget/hyperliquid)资金费差、"
    "理财利率、期现 basis、当前在场路由与盈亏的快照。"
    "请审视:①规则引擎挑出的高资金费差候选里,哪些看起来是真机会、哪些像是假信号"
    "(单所异常费率/低流动性长尾/即将结算的一次性尖峰);②当前 active 路由有无该警惕的;"
    "③理财利率倒挂等被忽略的角度。务必保守:拿不准就标 caution 或 avoid。"
    "严格只输出 JSON,不要任何解释性前后缀,格式:"
    '{"commentary":"一段总体市场判断(中文,≤200字)",'
    '"recommendations":[{"symbol":"币","action":"endorse|caution|avoid|watch",'
    '"reason":"简短理由(中文,≤80字)","risk_flags":["标签"],"confidence":0.0到1.0之间}]}'
    " action 含义:endorse=值得铺/看好, caution=可做但需盯风险, avoid=建议避开, watch=观察待定。"
    "recommendations 最多 12 条,按 confidence 降序。"
)


def _validate(obj: dict) -> dict | None:
    """硬 schema 校验:结构/类型/枚举/越界全过才采信;坏条丢弃,整体不合规返回 None。"""
    if not isinstance(obj, dict):
        return None
    commentary = obj.get("commentary")
    recs_in = obj.get("recommendations")
    if not isinstance(commentary, str) or not isinstance(recs_in, list):
        return None
    clean = []
    for rec in recs_in[:12]:
        if not isinstance(rec, dict):
            continue
        sym = rec.get("symbol")
        action = rec.get("action")
        reason = rec.get("reason")
        conf = rec.get("confidence")
        if not isinstance(sym, str) or not sym:
            continue
        if action not in VALID_ACTIONS:
            continue
        if not isinstance(reason, str):
            reason = ""
        try:
            conf = float(conf)
        except (TypeError, ValueError):
            conf = 0.0
        conf = max(0.0, min(1.0, conf))
        flags = rec.get("risk_flags")
        if not isinstance(flags, list):
            flags = []
        flags = [str(f)[:40] for f in flags][:6]
        clean.append({"symbol": sym[:20], "action": action, "reason": reason[:200],
                      "risk_flags": flags, "confidence": round(conf, 2)})
    clean.sort(key=lambda x: -x["confidence"])
    return {"commentary": commentary[:600], "recommendations": clean}


async def load_relays(r) -> list[dict]:
    """中转站清单:Redis 热配置优先(主站在前),缺失回落 env 单站。只返回 enabled 且有 key 的。"""
    cfg = await _get_json(r, CONFIG_KEY) or {}
    relays = [x for x in (cfg.get("relays") or [])
              if x.get("enabled") and str(x.get("api_key") or "").strip()]
    relays.sort(key=lambda x: 0 if x.get("role") == "primary" else 1)
    if relays:
        return relays
    if LLM_KEY:
        return [{"name": "env", "base_url": LLM_BASE, "api_key": LLM_KEY,
                 "model": LLM_MODEL, "role": "primary", "enabled": True}]
    return []


async def _log_usage(pool, relay: str, model: str, usage: dict, latency_ms: int,
                     ok: bool, error: str = ""):
    """逐调用用量落账(0013 llm_usage_log)——每日消费明细数据源。失败只警告。"""
    if pool is None:
        return
    try:
        await pool.execute(
            "INSERT INTO llm_usage_log(relay,model,tokens_in,tokens_out,latency_ms,ok,error)"
            " VALUES($1,$2,$3,$4,$5,$6,$7)",
            relay, model, int((usage or {}).get("prompt_tokens") or 0),
            int((usage or {}).get("completion_tokens") or 0), latency_ms, ok, error[:300])
    except Exception as e:
        log.warning("usage log failed: %r", e)


async def call_llm(cli: httpx.AsyncClient, snapshot: dict, relay: dict, pool=None) -> dict | None:
    """调 openai 兼容 chat/completions(指定中转站)。失败/坏响应返回 None(由上层降级下一站)。"""
    base = str(relay.get("base_url") or "").rstrip("/")
    model = str(relay.get("model") or "")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    t0 = time.time()
    try:
        resp = await cli.post(f"{base}/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {relay.get('api_key')}"})
    except Exception as e:
        log.warning("llm request failed relay=%s: %r", relay.get("name"), e)
        await _log_usage(pool, str(relay.get("name") or ""), model, {},
                         int((time.time() - t0) * 1000), False, repr(e))
        return None
    lat = int((time.time() - t0) * 1000)
    if resp.status_code != 200:
        log.warning("llm http %d relay=%s: %s", resp.status_code, relay.get("name"), resp.text[:200])
        await _log_usage(pool, str(relay.get("name") or ""), model, {}, lat, False,
                         f"http {resp.status_code}: {resp.text[:200]}")
        return None
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        usage = resp.json().get("usage", {})
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        log.warning("llm response shape bad: %r", e)
        await _log_usage(pool, str(relay.get("name") or ""), model, {}, lat, False, f"bad shape {e!r}")
        return None
    await _log_usage(pool, str(relay.get("name") or ""), model, usage, lat, True)
    # content 可能被包在 markdown ```json 里,剥一层
    txt = content.strip()
    if txt.startswith("```"):
        txt = txt.split("```", 2)[1] if "```" in txt[3:] else txt
        txt = txt.removeprefix("json").strip().strip("`").strip()
    try:
        parsed = json.loads(txt)
    except json.JSONDecodeError:
        log.warning("llm content not JSON: %s", txt[:200])
        return None
    validated = _validate(parsed)
    if validated is None:
        log.warning("llm output failed schema validation, discarding round")
        return None
    validated["_usage"] = usage
    return validated


async def _journal(pool, out: dict):
    """建议逐条落库(shadow 对照账本)。失败只警告,绝不影响顾问主流程。"""
    if pool is None:
        return
    try:
        recs = out.get("recommendations") or []
        for rec in recs:
            await pool.execute(
                "INSERT INTO llm_advice_log(model,snapshot_ts,latency_ms,tokens,symbol,action,domain,reason,raw)"
                " VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                out.get("model") or "", int(out.get("snapshot_ts") or 0),
                int(out.get("latency_ms") or 0),
                int((out.get("usage") or {}).get("total_tokens") or 0),
                str(rec.get("symbol") or ""), str(rec.get("action") or ""),
                str(rec.get("domain") or rec.get("scope") or ""),
                str(rec.get("reason") or "")[:500], json.dumps(rec, ensure_ascii=False))
    except Exception as e:
        log.warning("advice journal failed: %r", e)


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    pool = None
    try:
        dsn = os.environ.get("DCM_PG_DSN", "")
        if dsn:
            pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    except Exception as e:
        log.warning("pg pool unavailable (journal disabled): %r", e)
    hb = Heartbeat(REDIS_URL, "llm-advisor", interval_sec=min(INTERVAL, 60), ttl_sec=max(INTERVAL * 2, 300))
    asyncio.create_task(hb.run_forever())
    log.info("llm-advisor up interval=%ss env_model=%s env_base=%s cb=%d次→%ds×2^n",
             INTERVAL, LLM_MODEL, LLM_BASE, CB_THRESHOLD, CB_BASE_COOLDOWN)

    def _health(relays: list[dict], breaker: dict, now: float) -> dict:
        """健康字段(testauto /llm-health 口径,随快照一起发)。"""
        primary = next((x for x in relays if x.get("role") == "primary"), None)
        backups = [x for x in relays if x.get("role") != "primary"]
        trips = int(breaker.get("trips") or 0)
        return {
            "primary_model": (primary or {}).get("model"),
            "primary_relay": (primary or {}).get("name"),
            "fallback_model": backups[0].get("model") if backups else None,
            "circuit_open": now < float(breaker.get("open_until") or 0),
            "open_until": breaker.get("open_until"),
            "recent_failures": int(breaker.get("fails") or 0),
            "failure_threshold": CB_THRESHOLD,
            "consecutive_trips": trips,
            "current_cooldown_s": min(CB_BASE_COOLDOWN * (2 ** max(0, trips - 1)), CB_MAX_COOLDOWN),
        }

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as cli:
        while True:
            t0 = time.time()
            try:
                relays = await load_relays(r)
                breaker = await _get_json(r, BREAKER_KEY) or {}
                if not relays:
                    await r.set("dcm:advisor:llm", json.dumps(
                        {"ts": int(time.time()), "status": "unconfigured",
                         "note": "无可用中转站——mixadmin /mix/llm 中转站管理里添加,或配 DCM_LLM_KEY",
                         **_health([], breaker, time.time())}, ensure_ascii=False),
                        ex=max(INTERVAL * 3, 3600))
                    hb.extra = {"status": "unconfigured"}
                    await asyncio.sleep(INTERVAL)
                    continue
                if time.time() < float(breaker.get("open_until") or 0):
                    # 熔断中:不调用,保留上轮建议,只刷健康态(手动恢复=mix DEL breaker 键)
                    prev = await _get_json(r, "dcm:advisor:llm") or {}
                    prev.update({"status": "circuit_open", "ts": int(time.time()),
                                 **_health(relays, breaker, time.time())})
                    await r.set("dcm:advisor:llm", json.dumps(prev, ensure_ascii=False),
                                ex=max(INTERVAL * 3, 3600))
                    hb.extra = {"status": "circuit_open"}
                    log.warning("circuit open until %s, skipping round", breaker.get("open_until"))
                    await asyncio.sleep(INTERVAL)
                    continue

                snap = await build_snapshot(r)
                result, used = None, None
                for relay in relays:   # 主站在前,失败逐站降级(testauto 主从自动切换)
                    result = await call_llm(cli, snap, relay, pool)
                    if result is not None:
                        used = relay
                        break
                if result is not None:
                    if float(breaker.get("open_until") or 0) or breaker.get("fails") or breaker.get("trips"):
                        await r.delete(BREAKER_KEY)   # 成功即完全复位
                        breaker = {}
                    usage = result.pop("_usage", {})
                    out = {"ts": int(time.time()), "status": "ok",
                           "model": used.get("model"), "relay": used.get("name"),
                           "degraded": bool(used.get("role") != "primary"),
                           "latency_ms": int((time.time() - t0) * 1000),
                           "snapshot_ts": snap["ts"], "usage": usage,
                           **_health(relays, breaker, time.time()), **result}
                    await r.set("dcm:advisor:llm", json.dumps(out, ensure_ascii=False),
                                ex=max(INTERVAL * 3, 3600))
                    hb.extra = {"status": "ok", "model": used.get("model"),
                                "recs": len(result.get("recommendations", [])),
                                "tokens": usage.get("total_tokens")}
                    log.info("LLM_OK relay=%s model=%s recs=%d latency=%dms tokens=%s%s",
                             used.get("name"), used.get("model"),
                             len(result.get("recommendations", [])),
                             out["latency_ms"], usage.get("total_tokens"),
                             " (降级备用站)" if out["degraded"] else "")
                    await _journal(pool, out)
                else:
                    # 整轮全站失败 → 熔断计数(阈值触发冷却,指数退避)
                    fails = int(breaker.get("fails") or 0) + 1
                    trips = int(breaker.get("trips") or 0)
                    nb = {"fails": fails, "trips": trips, "open_until": 0, "updated": int(time.time())}
                    if fails >= CB_THRESHOLD:
                        cooldown = min(CB_BASE_COOLDOWN * (2 ** trips), CB_MAX_COOLDOWN)
                        nb = {"fails": 0, "trips": trips + 1,
                              "open_until": time.time() + cooldown, "updated": int(time.time())}
                        log.warning("circuit TRIPPED (%d连败) cooldown=%ds trips=%d",
                                    fails, cooldown, trips + 1)
                    await r.set(BREAKER_KEY, json.dumps(nb), ex=86400)
                    prev = await _get_json(r, "dcm:advisor:llm") or {}
                    prev.update({"status": "bad_round", "ts": int(time.time()),
                                 **_health(relays, nb, time.time())})
                    await r.set("dcm:advisor:llm", json.dumps(prev, ensure_ascii=False),
                                ex=max(INTERVAL * 3, 3600))
                    hb.extra = {"status": "bad_round"}
                    log.warning("LLM round produced no valid output on all relays (keeping previous)")
            except Exception:
                log.exception("llm-advisor round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
