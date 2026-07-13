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

_PROMPT_BASE = (
    "你是 HustleCoin Mix(多策略套利控制台)的运维助手,面向操作员回答系统运维/策略状态/数据口径问题。"
    "你只提供解答与指路,绝无任何执行权——涉及操作时告诉用户在哪个页面哪个按钮完成"
    "(主控台=/mix/dashboard,规则中心=/mix/rules,通知模块=/mix/notify,账户=/mix/accounts,"
    "运维面板=/system,LLM管理=/mix/llm,交易历史=/mix/history,资金收益=/mix/report)。"
    "六策略:S1期现收费(单所期现对冲收资金费)/S2跨所费差(双合约跨所费率差,dcm引擎)/S3借币点差(借币做空吃现-期点差,coin引擎)/S4三率利差(资金费+理财-借币利率)/S5事件折价/S6做量降费(未建)。"
    "回答用中文,简洁直接,基于给你的实时系统快照说话;快照里没有的数据就说不知道,绝不编造数字。"
)
# 回答范围由 /mix/llm「AI 智能体接入」的 chat_scope 决定(site=限本站/open=无限制),对话时热读
SYSTEM_PROMPT = _PROMPT_BASE + (
    "你只回答与本系统(套利策略/运维/数据/页面操作)相关的问题;无关话题礼貌说明"
    "「运维助手当前限定本站话题(管理员可在 /mix/llm 切换为无限制)」并把话题拉回系统。"
)
SYSTEM_PROMPT_OPEN = _PROMPT_BASE + (
    "除系统运维问题外,你也可以自由回答任何话题(市场观点/技术/闲聊均可),"
    "但涉及本系统数据时仍只依据快照,绝不编造;任何话题下都没有执行权。"
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


@router.get("/ai/models")
async def ai_models(_who=Depends(require_viewer)):
    """可切换的模型/地址清单(主账号+备用账号所有启用地址)——供运维助手「无限制」模式的
    模型切换按钮;chat_scope 也一并返回,前端据此决定是否显示切换按钮。"""
    cfg = await ds.get_json("dcm:llm:config") or {}
    agents = cfg.get("agents") or {}
    out = []
    for x in (cfg.get("relays") or []):
        if not x.get("enabled"):
            continue
        host = str(x.get("base_url") or "").replace("https://", "").replace("http://", "").split("/")[0]
        out.append({"id": x.get("id"), "name": x.get("name"), "role": x.get("role"),
                    "model": x.get("model"), "host": host})
    return {"scope": agents.get("chat_scope", "site"),
            "ops_chat_enabled": agents.get("ops_chat_enabled", True), "models": out}


@router.post("/ai/chat")
async def ai_chat(body: dict, who=Depends(require_viewer)):
    """运维助手对话:中转站主备降级(与 advisor 同配置源),失败诚实报错不装聋。
    可选 relay_id:无限制模式下用户指定某个启用地址,优先用它(仍保留其余站兜底)。"""
    raw_msg = str(body.get("message") or "").strip()
    msg = raw_msg[:4000]
    truncated = len(raw_msg) > 4000
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
    agents = cfg.get("agents") or {}
    if agents.get("ops_chat_enabled") is False:
        return {"reply": "运维助手已被管理员停用——在 /mix/llm「AI 智能体接入」处可重新开启。",
                "conversation_id": cid}
    relays = [x for x in (cfg.get("relays") or [])
              if x.get("enabled") and str(x.get("api_key") or "").strip()]
    relays.sort(key=lambda x: 0 if x.get("role") == "primary" else 1)
    if not relays:
        return {"reply": "LLM 中转站未配置——到 /mix/llm 中转站管理里添加。", "conversation_id": cid}
    # 无限制模式:用户从模型切换按钮选定某地址→优先用它(排到队首),其余站仍兜底
    pin_id = body.get("relay_id")
    if pin_id is not None and agents.get("chat_scope") == "open":
        pinned = [x for x in relays if x.get("id") == pin_id]
        if pinned:
            relays = pinned + [x for x in relays if x.get("id") != pin_id]

    ctx = await _live_context()
    sys_prompt = SYSTEM_PROMPT_OPEN if agents.get("chat_scope") == "open" else SYSTEM_PROMPT
    messages = ([{"role": "system", "content": sys_prompt},
                 {"role": "system", "content": "实时系统快照:" + json.dumps(ctx, ensure_ascii=False)}]
                + hist[-_MAX_TURNS:] + [{"role": "user", "content": msg}])

    # 超时/重试预算:chesspnt 会间歇性单连接卡死(正常 2-3s,偶发挂到 30s+),
    # 而主/备是同一 provider——降级到备用无冗余意义。对策=每站用「全新连接」尝试,
    # 单次 28s 超时(正常远快于此,超时即判定连接卡死而非模型慢),超时/网络错自动
    # 换新连接重试 1 次(换连接常绕开被挂住的旧连接)。总最坏 = 站数×2×28 + 开销,
    # 双站≈112s < 前端 150s < nginx 180s(层级顺序不倒挂)。
    ATTEMPT_TIMEOUT = 28.0
    RETRY_PER_RELAY = 1  # 每站失败后换新连接重试次数

    async def _one_call(relay, timeout):
        base = str(relay.get("base_url") or "").rstrip("/")
        model = str(relay.get("model") or "")
        t0 = time.time()
        # 每次尝试独立 client=独立连接池,不复用可能已卡死的连接
        async with httpx.AsyncClient(timeout=timeout) as cli:
            resp = await cli.post(f"{base}/chat/completions",
                                  json={"model": model, "messages": messages,
                                        "temperature": 0.3, "max_tokens": 900},
                                  headers={"Authorization": f"Bearer {relay.get('api_key')}"})
        lat = int((time.time() - t0) * 1000)
        if resp.status_code != 200:
            return None, f"http {resp.status_code}: {resp.text[:120]}", lat, model, {}
        data = resp.json()
        return data["choices"][0]["message"]["content"], None, lat, model, (data.get("usage") or {})

    reply, used, last_err = None, None, ""
    for relay in relays:   # 主站在前,失败逐站降级
        name = str(relay.get("name") or "")
        for attempt in range(RETRY_PER_RELAY + 1):
            try:
                r_reply, err, lat, model, usage = await _one_call(relay, ATTEMPT_TIMEOUT)
            except Exception as e:  # noqa: BLE001  (超时/网络=换新连接重试的目标)
                last_err = repr(e)[:120]
                await _log_usage(name, str(relay.get("model") or ""), {}, int(ATTEMPT_TIMEOUT * 1000),
                                 False, f"try{attempt + 1} {last_err}")
                continue   # 换新连接再来一次(同站),用完重试次数才降级到下一站
            if err:
                last_err = err
                await _log_usage(name, model, {}, lat, False, err)
                break      # HTTP 非超时错(如模型不存在/价格未配)重试无益,直接降级下一站
            reply, used = r_reply, relay
            await _log_usage(name, model, usage, lat, True)
            break
        if reply is not None:
            break
    if reply is None:
        friendly = "所有中转站暂时无响应(可能是上游临时拥塞)——请稍等片刻重试;若持续,到 /mix/llm 看服务健康或切换主站模型。"
        return {"reply": f"{friendly}\n（诊断:{last_err}）", "conversation_id": cid}
    hist.append({"role": "user", "content": msg})
    hist.append({"role": "assistant", "content": reply})
    del hist[:-_MAX_TURNS * 2]
    if truncated:
        reply += "\n\n(提示:你的输入超过4000字,已截断处理——超长内容建议分段问)"
    return {"reply": reply, "conversation_id": cid,
            "model": used.get("model"), "relay": used.get("name"),
            "relay_id": used.get("id"),
            "degraded": used.get("role") != "primary"}
