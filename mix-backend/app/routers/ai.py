"""运维助手(主控台右下 AI 浮框) —— 走 LLM 中转站链路(与 llm-advisor 同源):
dcm:llm:config 主备自动降级;逐调用落 llm_usage_log(与每日消费明细同账);
上下文=实时系统快照(心跳/坑位/风控/收益),让助手用真数据答运维问题。
纪律:只答不动手——助手永远不能执行任何写操作,回答里指路对应页面/按钮。
"""
import json
import time
import logging

import httpx
from fastapi import APIRouter, Depends

from ..deps import require_viewer
from .. import datasources as ds

log = logging.getLogger("mix.ai")
router = APIRouter(tags=["ai"])

# 会话在进程内存(重启即失;运维问答短平快,不值得落库)
_convs: dict[str, list[dict]] = {}
_conv_ts: dict[str, float] = {}
_MAX_TURNS = 12
_CONV_TTL = 3600 * 6

SYSTEM_PROMPT = (
    "你是 HustleCoin Mix(多策略套利控制台)的运维助手,面向操作员回答系统运维/策略状态/数据口径问题。"
    "你只提供解答与指路,绝无任何执行权——涉及操作时告诉用户在哪个页面哪个按钮完成"
    "(主控台=/mix/dashboard,规则中心=/mix/rules,通知模块=/mix/notify,账户=/mix/accounts,"
    "运维面板=/system,LLM管理=/mix/llm,交易历史=/mix/history,资金收益=/mix/report)。"
    "六策略:S1单所期现基差/S2双合约期期(dcm引擎)/S3借币反向点差(coin引擎)/S4借贷利率/S5事件LST/S6费率飞轮(未建)。"
    "回答用中文,简洁直接,基于给你的实时系统快照说话;快照里没有的数据就说不知道,绝不编造数字。"
)


async def _live_context() -> dict:
    """实时系统快照(全部读已发布总线键/只读库,轻量)。"""
    out: dict = {"ts": int(time.time())}
    try:
        hbs = []
        r = ds.rds()
        if r is not None:
            keys = [k async for k in r.scan_iter(match="dcm:hb:*", count=100)]
            now = time.time()
            for k in keys[:40]:
                try:
                    d = json.loads(await r.get(k) or "{}")
                    hbs.append({"service": d.get("service") or k.split(":")[-1],
                                "age_sec": int(now - float(d.get("ts") or 0))})
                except Exception:  # noqa: BLE001
                    continue
        out["services_total"] = len(hbs)
        out["services_stale"] = [h["service"] for h in hbs if h["age_sec"] > 600]
    except Exception:  # noqa: BLE001
        pass
    for key, name in (("dcm:pnl:summary", "pnl"), ("dcm:risk:status", "risk_brief"),
                      ("dcm:advisor:llm", "llm_advisor")):
        try:
            d = await ds.get_json(key) or {}
            if name == "risk_brief":
                d = {"alerts_this_round": d.get("alerts_this_round"),
                     "net_exposure_breaches": (d.get("net_exposure") or {}).get("breaches"),
                     "waterline": d.get("waterline")}
            if name == "llm_advisor":
                d = {"status": d.get("status"), "model": d.get("model"),
                     "degraded": d.get("degraded"), "commentary": (d.get("commentary") or "")[:300]}
            out[name] = d
        except Exception:  # noqa: BLE001
            continue
    try:
        from .. import adapters
        rows = await adapters.position_rows(None)
        by = {}
        for x in rows:
            by.setdefault(x["strategyCode"], {"rows": 0, "holding": 0})
            by[x["strategyCode"]]["rows"] += 1
            by[x["strategyCode"]]["holding"] += int(x.get("positionCount") or 0)
        out["positions"] = by
    except Exception:  # noqa: BLE001
        pass
    return out


async def _log_usage(relay: str, model: str, usage: dict, latency_ms: int, ok: bool, error: str = ""):
    pool = await ds.pg()
    if pool is None:
        return
    try:
        await pool.execute(
            "INSERT INTO llm_usage_log(relay,model,tokens_in,tokens_out,latency_ms,ok,error)"
            " VALUES($1,$2,$3,$4,$5,$6,$7)",
            relay, model, int((usage or {}).get("prompt_tokens") or 0),
            int((usage or {}).get("completion_tokens") or 0), latency_ms, ok, error[:300])
    except Exception as e:  # noqa: BLE001
        log.warning("chat usage log failed: %s", e)


@router.post("/ai/chat")
async def ai_chat(body: dict, who=Depends(require_viewer)):
    """运维助手对话:中转站主备降级(与 advisor 同配置源),失败诚实报错不装聋。"""
    msg = str(body.get("message") or "").strip()[:2000]
    if not msg:
        return {"reply": "请输入问题。", "conversation_id": body.get("conversation_id")}
    cid = str(body.get("conversation_id") or f"c{int(time.time()*1000)}")
    # 过期会话清理
    now = time.time()
    for k in [k for k, t in _conv_ts.items() if now - t > _CONV_TTL]:
        _convs.pop(k, None); _conv_ts.pop(k, None)
    hist = _convs.setdefault(cid, [])
    _conv_ts[cid] = now

    cfg = await ds.get_json("dcm:llm:config") or {}
    relays = [x for x in (cfg.get("relays") or [])
              if x.get("enabled") and str(x.get("api_key") or "").strip()]
    relays.sort(key=lambda x: 0 if x.get("role") == "primary" else 1)
    if not relays:
        return {"reply": "LLM 中转站未配置——到 /mix/llm 中转站管理里添加。", "conversation_id": cid}

    ctx = await _live_context()
    messages = ([{"role": "system", "content": SYSTEM_PROMPT},
                 {"role": "system", "content": "实时系统快照:" + json.dumps(ctx, ensure_ascii=False)}]
                + hist[-_MAX_TURNS:] + [{"role": "user", "content": msg}])

    reply, used, last_err = None, None, ""
    async with httpx.AsyncClient(timeout=60) as cli:
        for relay in relays:   # 主站在前,失败逐站降级(与 llm-advisor 同语义)
            base = str(relay.get("base_url") or "").rstrip("/")
            model = str(relay.get("model") or "")
            t0 = time.time()
            try:
                resp = await cli.post(f"{base}/chat/completions",
                                      json={"model": model, "messages": messages,
                                            "temperature": 0.3, "max_tokens": 900},
                                      headers={"Authorization": f"Bearer {relay.get('api_key')}"})
            except Exception as e:  # noqa: BLE001
                last_err = repr(e)[:120]
                await _log_usage(str(relay.get("name") or ""), model, {},
                                 int((time.time() - t0) * 1000), False, last_err)
                continue
            lat = int((time.time() - t0) * 1000)
            if resp.status_code != 200:
                last_err = f"http {resp.status_code}: {resp.text[:120]}"
                await _log_usage(str(relay.get("name") or ""), model, {}, lat, False, last_err)
                continue
            try:
                data = resp.json()
                reply = data["choices"][0]["message"]["content"]
                await _log_usage(str(relay.get("name") or ""), model,
                                 data.get("usage") or {}, lat, True)
                used = relay
                break
            except Exception as e:  # noqa: BLE001
                last_err = f"bad shape {e!r}"[:120]
                await _log_usage(str(relay.get("name") or ""), model, {}, lat, False, last_err)
                continue
    if reply is None:
        return {"reply": f"LLM 全部中转站调用失败({last_err})——看 /mix/llm 服务健康。",
                "conversation_id": cid}
    hist.append({"role": "user", "content": msg})
    hist.append({"role": "assistant", "content": reply})
    del hist[:-_MAX_TURNS * 2]
    return {"reply": reply, "conversation_id": cid,
            "model": used.get("model"), "relay": used.get("name"),
            "degraded": used.get("role") != "primary"}
