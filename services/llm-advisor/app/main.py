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


async def call_llm(cli: httpx.AsyncClient, snapshot: dict) -> dict | None:
    """调 openai 兼容 chat/completions。返回校验后的建议,失败/坏响应返回 None(整轮弃用)。"""
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(snapshot, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = await cli.post(f"{LLM_BASE}/chat/completions", json=body,
                              headers={"Authorization": f"Bearer {LLM_KEY}"})
    except Exception as e:
        log.warning("llm request failed: %r", e)
        return None
    if resp.status_code != 200:
        log.warning("llm http %d: %s", resp.status_code, resp.text[:200])
        return None
    try:
        content = resp.json()["choices"][0]["message"]["content"]
        usage = resp.json().get("usage", {})
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        log.warning("llm response shape bad: %r", e)
        return None
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


async def main():
    r = aioredis.from_url(REDIS_URL, decode_responses=True)
    hb = Heartbeat(REDIS_URL, "llm-advisor", interval_sec=min(INTERVAL, 60), ttl_sec=max(INTERVAL * 2, 300))
    asyncio.create_task(hb.run_forever())
    configured = bool(LLM_KEY)
    log.info("llm-advisor up interval=%ss model=%s base=%s configured=%s",
             INTERVAL, LLM_MODEL, LLM_BASE, configured)
    if not configured:
        # 降级态:不调 LLM,写一条 unconfigured 状态供面板显示,心跳照常
        while True:
            await r.set("dcm:advisor:llm", json.dumps(
                {"ts": int(time.time()), "status": "unconfigured",
                 "note": "DCM_LLM_KEY 未配置——填 key 并重启即武装"}, ensure_ascii=False),
                ex=max(INTERVAL * 3, 3600))
            hb.extra = {"status": "unconfigured"}
            await asyncio.sleep(INTERVAL)

    async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as cli:
        while True:
            t0 = time.time()
            try:
                snap = await build_snapshot(r)
                result = await call_llm(cli, snap)
                if result is not None:
                    usage = result.pop("_usage", {})
                    out = {"ts": int(time.time()), "status": "ok", "model": LLM_MODEL,
                           "latency_ms": int((time.time() - t0) * 1000),
                           "snapshot_ts": snap["ts"], "usage": usage, **result}
                    await r.set("dcm:advisor:llm", json.dumps(out, ensure_ascii=False),
                                ex=max(INTERVAL * 3, 3600))
                    hb.extra = {"status": "ok", "recs": len(result.get("recommendations", [])),
                                "tokens": usage.get("total_tokens")}
                    log.info("LLM_OK recs=%d latency=%dms tokens=%s",
                             len(result.get("recommendations", [])),
                             out["latency_ms"], usage.get("total_tokens"))
                else:
                    hb.extra = {"status": "bad_round"}
                    log.warning("LLM round produced no valid output (keeping previous)")
            except Exception:
                log.exception("llm-advisor round crashed (continuing)")
            await asyncio.sleep(INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
