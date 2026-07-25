"""通知中心（QH 通知模块适配 Mix 版）—— 权威=mix_main 自有域，发送管道对齐 dcm 契约。
子模块：网站维护/公告(site_notices,含原网站通知合并)、通知模板(notify_templates)、
发送日志(notify_logs)、手动广播(跑马灯=publish dcm:notify:broadcast 同 dcm_common 报文契约;
飞书=notify_settings.feishu_webhook)。邮件通道=配置留位,未接 SMTP 前诚实 501。
纪律：dcm 服务侧告警链路(alerts_log/Notifier)零改动,本模块只管 mix 主动发出的通知。"""
import json
import logging
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException

from ..deps import require_viewer, require_operator
from .. import datasources as ds
from .. import proxy

log = logging.getLogger("mix.notify")
router = APIRouter(tags=["notify-center"])

MARQUEE_CHANNEL = "dcm:notify:broadcast"
EMAIL_REDIS_KEY = "dcm:notify:email"   # SMTP 配置分发键(dcm_common email_sender 消费,P0 邮件通道)


# ── 邮件(SMTP)真发送(2026-07-25 补齐:此前配置留位不真发) ──────────────────────
_EMAIL_KEYS = ("host", "port", "user", "sender", "password", "to")


async def _email_conf(pool) -> dict:
    row = await pool.fetchrow("SELECT email_conf FROM notify_settings WHERE id=1")
    conf = row["email_conf"] if row else {}
    if isinstance(conf, str):
        conf = json.loads(conf or "{}")
    return conf or {}


def _email_ready(conf: dict) -> bool:
    return bool(conf.get("host") and conf.get("user") and conf.get("password") and conf.get("to"))


def _smtp_send_sync(conf: dict, subject: str, body_text: str):
    """同步 SMTP 发送(465=SSL / 其他=STARTTLS),timeout=10s。返回 (ok, detail)。"""
    import smtplib
    import ssl as _ssl
    from email.mime.text import MIMEText
    from email.utils import formatdate
    host = str(conf.get("host") or "").strip()
    port = int(conf.get("port") or 465)
    user = str(conf.get("user") or "").strip()
    pw = str(conf.get("password") or "")
    to = [x.strip() for x in str(conf.get("to") or "").split(",") if x.strip()]
    sender_disp = str(conf.get("sender") or "").strip()
    frm = f"{sender_disp} <{user}>" if sender_disp else user
    if not (host and user and pw and to):
        return False, "SMTP 未配置齐(host/user/授权码/收件人)"
    msg = MIMEText(body_text, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate(localtime=True)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=_ssl.create_default_context()) as s:
                s.login(user, pw)
                s.sendmail(user, to, msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                s.starttls(context=_ssl.create_default_context())
                s.login(user, pw)
                s.sendmail(user, to, msg.as_string())
        return True, "sent"
    except Exception as e:  # noqa: BLE001
        return False, repr(e)[:200]


async def _smtp_send(conf: dict, subject: str, body_text: str):
    import asyncio as _aio
    return await _aio.to_thread(_smtp_send_sync, conf, subject, body_text)


async def _publish_email_conf(conf: dict):
    """把 SMTP 配置分发到 Redis(dcm_common email_sender 双机消费=P0 fatal 邮件升级通道)。"""
    r = ds.rds()
    if r is None:
        return
    try:
        await r.set(EMAIL_REDIS_KEY, json.dumps(
            {k: conf.get(k, "") for k in _EMAIL_KEYS}, ensure_ascii=False))
    except Exception as e:  # noqa: BLE001
        log.warning("email conf redis publish: %s", e)


async def _pool():
    pool = await ds.pg_main()
    if pool is None:
        raise HTTPException(503, "mix_main 未配置")
    return pool


async def _log_send(pool, channel, target, title, body, ok, detail, operator):
    try:
        await pool.execute(
            "INSERT INTO notify_logs(channel,target,title,body,ok,detail,operator) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)", channel, target, title, body[:2000], ok, detail[:400], operator)
    except Exception as e:  # noqa: BLE001
        log.warning("notify_logs insert: %s", e)


# ---------------- 网站维护 / 公告（网站通知已并入,kind 区分） ----------------
@router.get("/site/notices")
async def notices_list(_who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch("SELECT * FROM site_notices ORDER BY updated_at DESC LIMIT 50")
    return [{**dict(r),
             "starts_at": r["starts_at"].isoformat() if r["starts_at"] else None,
             "ends_at": r["ends_at"].isoformat() if r["ends_at"] else None,
             "updated_at": r["updated_at"].strftime("%m-%d %H:%M")} for r in rows]


@router.get("/site/notices/active")
async def notices_active():
    """开放读：用户端横幅/维护蒙层消费（enabled 且在时间窗内）。"""
    pool = await ds.pg_main()
    if pool is None:
        return []
    rows = await pool.fetch(
        "SELECT kind, title, content FROM site_notices WHERE enabled "
        "AND (starts_at IS NULL OR starts_at <= now()) AND (ends_at IS NULL OR ends_at >= now()) "
        "ORDER BY kind DESC LIMIT 5")
    return [dict(r) for r in rows]


@router.put("/site/notices")
async def notices_put(body: dict, op=Depends(require_operator)):
    pool = await _pool()
    kind = body.get("kind") if body.get("kind") in ("notice", "maintenance") else "notice"

    def _ts(v):
        if not v:
            return None
        try:
            return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except ValueError:
            return None
    if body.get("id"):
        await pool.execute(
            "UPDATE site_notices SET kind=$2, title=$3, content=$4, enabled=$5, starts_at=$6, "
            "ends_at=$7, updated_by=$8, updated_at=now() WHERE id=$1",
            int(body["id"]), kind, str(body.get("title") or "")[:200], str(body.get("content") or "")[:4000],
            bool(body.get("enabled")), _ts(body.get("starts_at")), _ts(body.get("ends_at")), op["operator"])
    else:
        await pool.execute(
            "INSERT INTO site_notices(kind,title,content,enabled,starts_at,ends_at,updated_by) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)",
            kind, str(body.get("title") or "")[:200], str(body.get("content") or "")[:4000],
            bool(body.get("enabled")), _ts(body.get("starts_at")), _ts(body.get("ends_at")), op["operator"])
    await proxy.audit(op["operator"], op["role"], "notice.put", body.get("title", ""), body, "saved")
    return {"saved": True}


@router.delete("/site/notices/{nid}")
async def notices_del(nid: int, op=Depends(require_operator)):
    pool = await _pool()
    await pool.execute("DELETE FROM site_notices WHERE id=$1", nid)
    await proxy.audit(op["operator"], op["role"], "notice.del", str(nid), {}, "deleted")
    return {"deleted": True}


# ---------------- 通知模板 ----------------
@router.get("/notify/templates")
async def templates_list(_who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch("SELECT * FROM notify_templates ORDER BY tkey")
    return [{**dict(r), "channels": json.loads(r["channels"]) if isinstance(r["channels"], str) else r["channels"],
             "updated_at": r["updated_at"].strftime("%m-%d %H:%M")} for r in rows]


@router.put("/notify/templates")
async def templates_put(body: dict, op=Depends(require_operator)):
    tkey = str(body.get("tkey") or "").strip()
    if not tkey:
        raise HTTPException(400, "tkey required")
    level = body.get("level") if body.get("level") in ("info", "warn", "fatal") else "info"
    pool = await _pool()
    await pool.execute(
        "INSERT INTO notify_templates(tkey,title,body,level,channels,enabled,updated_by,updated_at,"
        "category,sound_key,color,blink) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,now(),$8,$9,$10,$11) ON CONFLICT (tkey) DO UPDATE SET "
        "title=$2, body=$3, level=$4, channels=$5, enabled=$6, updated_by=$7, updated_at=now(), "
        "category=$8, sound_key=$9, color=$10, blink=$11",
        tkey, str(body.get("title") or "")[:200], str(body.get("body") or "")[:4000], level,
        json.dumps(body.get("channels") or ["marquee"]), bool(body.get("enabled", True)), op["operator"],
        str(body.get("category") or "system")[:40], str(body.get("sound_key") or "")[:40],
        str(body.get("color") or "")[:20], bool(body.get("blink")))
    await proxy.audit(op["operator"], op["role"], "template.put", tkey, body, "saved")
    return {"saved": True}


@router.delete("/notify/templates/{tid}")
async def templates_del(tid: int, op=Depends(require_operator)):
    pool = await _pool()
    await pool.execute("DELETE FROM notify_templates WHERE id=$1", tid)
    await proxy.audit(op["operator"], op["role"], "template.del", str(tid), {}, "deleted")
    return {"deleted": True}


# ---------------- 发送日志 ----------------
@router.get("/notify/logs")
async def logs_list(_who=Depends(require_viewer)):
    pool = await _pool()
    rows = await pool.fetch("SELECT * FROM notify_logs ORDER BY ts DESC LIMIT 100")
    return [{**dict(r), "ts": r["ts"].strftime("%m-%d %H:%M:%S")} for r in rows]


# ---------------- 手动广播（跑马灯契约=dcm_common Notifier 同报文;飞书=webhook） ----------------
LEVEL_COLOR = {"info": "#3b82f6", "warn": "#F0B90B", "fatal": "#F6465D"}


async def _send_feishu(webhook: str, title: str, text: str) -> tuple[bool, str]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(webhook, json={"msg_type": "text", "content": {"text": f"{title}\n{text}"}})
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code == 200 and (j.get("code") in (0, None) or j.get("StatusCode") == 0)
            return ok, str(j)[:200]
    except Exception as e:  # noqa: BLE001
        return False, repr(e)[:200]


@router.post("/notify/broadcast")
async def broadcast(body: dict, op=Depends(require_operator)):
    """手动广播：channels ⊆ {marquee, feishu, email}。跑马灯走 Redis publish（mix-ws-hub 中继到端），
    飞书走 notify_settings.feishu_webhook，邮件未接 SMTP 前 501 语义按渠道降级为失败记录。"""
    title = str(body.get("title") or "系统通知")[:120]
    text = str(body.get("text") or body.get("content") or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    level = body.get("level") if body.get("level") in ("info", "warn", "fatal") else "info"
    channels = [c for c in (body.get("channels") or ["marquee"]) if c in ("marquee", "feishu", "email")]
    if not channels:
        raise HTTPException(400, "channels 必须含 marquee/feishu/email 至少一项")
    pool = await _pool()
    results = {}
    if "marquee" in channels:
        r = ds.rds()
        if r is None:
            results["marquee"] = "redis 未配置"
            await _log_send(pool, "marquee", "all", title, text, False, "redis 未配置", op["operator"])
        else:
            try:
                await r.publish(MARQUEE_CHANNEL, json.dumps({
                    "service": "mixadmin", "title": title, "content": text,
                    "level": level, "color": str(body.get("color") or LEVEL_COLOR[level]),
                    "blink": bool(body.get("blink")) or level == "fatal",
                    "sound_key": str(body.get("sound_key") or ""),
                }, ensure_ascii=False))
                results["marquee"] = "sent"
                await _log_send(pool, "marquee", "all", title, text, True, "published", op["operator"])
            except Exception as e:  # noqa: BLE001
                results["marquee"] = f"error: {e}"
                await _log_send(pool, "marquee", "all", title, text, False, repr(e), op["operator"])
    if "feishu" in channels:
        row = await pool.fetchrow("SELECT feishu_webhook FROM notify_settings WHERE id=1")
        hook = (row["feishu_webhook"] if row else "") or ""
        if not hook:
            results["feishu"] = "未配置 webhook（通知模块→渠道设置）"
            await _log_send(pool, "feishu", "-", title, text, False, "webhook 未配置", op["operator"])
        else:
            ok, detail = await _send_feishu(hook, f"mixadmin|{title}", text)
            results["feishu"] = "sent" if ok else detail
            await _log_send(pool, "feishu", hook[-18:], title, text, ok, detail, op["operator"])
    if "email" in channels:
        conf = await _email_conf(pool)
        if not _email_ready(conf):
            results["email"] = "SMTP 未配置齐(通知模块→邮件(SMTP) 填主机/账号/授权码/收件人)"
            await _log_send(pool, "email", "-", title, text, False, "SMTP 未配置齐", op["operator"])
        else:
            ok, detail = await _smtp_send(conf, f"[Mix {level.upper()}] {title}", text)
            results["email"] = "sent" if ok else detail
            await _log_send(pool, "email", str(conf.get("to"))[:60], title, text, ok, detail, op["operator"])
    await proxy.audit(op["operator"], op["role"], "notify.broadcast", ",".join(channels),
                      {"title": title, "level": level}, str(results)[:200])
    return {"results": results}


# ---------------- 网站维护 / 一键全停（停自动策略=gateway Kill Switch,权威门闸,用户已拍板映射） ----------------
MAINT_KEY = "mix:maintenance"


async def _maint_row(pool):
    return await pool.fetchrow("SELECT * FROM maintenance WHERE id=1")


def _maint_payload(row) -> dict:
    return {"enabled": row["enabled"], "stop_strategy": row["stop_strategy"],
            "block_trading": row["block_trading"], "block_login": row["block_login"],
            "title": row["title"], "content": row["content"],
            "until_at": row["until_at"].isoformat() if row["until_at"] else None,
            "updated_by": row["updated_by"]}


async def maintenance_state() -> dict:
    """给鉴权/写代理层用的活状态(Redis 优先,库兜底)。"""
    d = await ds.get_json(MAINT_KEY)
    if d is not None:
        return d
    pool = await ds.pg_main()
    if pool is None:
        return {}
    row = await _maint_row(pool)
    return _maint_payload(row) if row else {}


@router.get("/system/maintenance")
async def maintenance_get(_who=Depends(require_viewer)):
    pool = await _pool()
    row = await _maint_row(pool)
    return _maint_payload(row)


async def _apply_maintenance(pool, r, body: dict, op, one_click=False):
    import datetime as _dt

    def _ts(v):
        try:
            return _dt.datetime.fromisoformat(str(v).replace("Z", "+00:00")) if v else None
        except ValueError:
            return None
    enabled = bool(body.get("enabled"))
    vals = {
        "enabled": enabled,
        "stop_strategy": bool(body.get("stop_strategy", True)),
        "block_trading": bool(body.get("block_trading", True)),
        "block_login": bool(body.get("block_login", False)),
        "title": str(body.get("title") or "系统维护中")[:120],
        "content": str(body.get("content") or "")[:2000],
        "until_at": _ts(body.get("until_at")),
    }
    await pool.execute(
        "UPDATE maintenance SET enabled=$1, stop_strategy=$2, block_trading=$3, block_login=$4, "
        "title=$5, content=$6, until_at=$7, updated_by=$8, updated_at=now() WHERE id=1",
        *vals.values(), op["operator"])
    payload = {**{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in vals.items()},
               "updated_by": op["operator"]}
    if r is not None:
        await r.set(MAINT_KEY, json.dumps(payload, ensure_ascii=False))
    results = {"saved": True}
    # 停自动策略 → gateway Kill Switch(全组合置 shadow+清白名单;权威闸,不发明第三套)
    if enabled and vals["stop_strategy"]:
        token = op.get("token") or ""
        st, data = await proxy.gateway_kill(token)
        results["kill_switch"] = data if st < 400 else {"error": data, "status": st}
        await _log_send(pool, "kill", "gateway", "维护全停", "Kill Switch", st < 400, str(data)[:200], op["operator"])
    # 维护公告 → 跑马灯 + site_notices(kind=maintenance,用户端蒙层/横幅消费)
    if r is not None:
        try:
            await r.publish(MARQUEE_CHANNEL, json.dumps({
                "service": "mixadmin", "title": vals["title"],
                "content": (vals["content"] or vals["title"]) if enabled else "维护已解除,系统恢复正常",
                "level": "warn" if enabled else "info",
                "color": "#F0B90B", "blink": enabled}, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            results["marquee"] = repr(e)[:120]
    await pool.execute(
        "INSERT INTO site_notices(kind,title,content,enabled,ends_at,updated_by) "
        "VALUES('maintenance',$1,$2,$3,$4,$5) "
        "ON CONFLICT DO NOTHING", vals["title"], vals["content"], enabled, vals["until_at"], op["operator"])
    await pool.execute(
        "UPDATE site_notices SET title=$1, content=$2, enabled=$3, ends_at=$4, updated_by=$5, updated_at=now() "
        "WHERE kind='maintenance'", vals["title"], vals["content"], enabled, vals["until_at"], op["operator"])
    await proxy.audit(op["operator"], op["role"], "maintenance.allstop" if one_click else "maintenance.set",
                      "维护开关", payload, str(results)[:180])
    return {**results, "state": payload}


@router.put("/system/maintenance")
async def maintenance_put(body: dict, op=Depends(require_operator)):
    pool = await _pool()
    return await _apply_maintenance(pool, ds.rds(), body, op)


@router.post("/system/maintenance/all-stop")
async def maintenance_all_stop(body: dict, op=Depends(require_operator)):
    """一键维护全停=维护开+停策略(Kill)+禁下单三档全开(禁登录按传入)。"""
    pool = await _pool()
    row = await _maint_row(pool)
    merged = {**_maint_payload(row), **body,
              "enabled": True, "stop_strategy": True, "block_trading": True}
    return await _apply_maintenance(pool, ds.rds(), merged, op, one_click=True)


# ---------------- 声音人设（浏览器端 TTS:speechSynthesis 按人设调参朗读,零后端算力） ----------------
@router.get("/notify/personas")
async def personas_list(_who=Depends(require_viewer)):
    pool = await _pool()
    return [dict(r) for r in await pool.fetch(
        "SELECT id, skey, name, voice, style, rate_pct, pitch_pct, sample FROM sound_personas ORDER BY id")]


@router.put("/notify/personas")
async def personas_put(body: dict, op=Depends(require_operator)):
    skey = str(body.get("skey") or "").strip()
    if not skey:
        raise HTTPException(400, "skey required")
    pool = await _pool()
    await pool.execute(
        "INSERT INTO sound_personas(skey,name,voice,style,rate_pct,pitch_pct,sample,updated_by,updated_at) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,$8,now()) ON CONFLICT (skey) DO UPDATE SET "
        "name=$2, voice=$3, style=$4, rate_pct=$5, pitch_pct=$6, sample=$7, updated_by=$8, updated_at=now()",
        skey, str(body.get("name") or "")[:60], str(body.get("voice") or "zh-CN-XiaoxiaoNeural")[:80],
        str(body.get("style") or "")[:80], int(body.get("rate_pct") or 0), int(body.get("pitch_pct") or 0),
        str(body.get("sample") or "")[:300], op["operator"])
    await proxy.audit(op["operator"], op["role"], "persona.put", skey, body, "saved")
    return {"saved": True}


@router.delete("/notify/personas/{pid}")
async def personas_del(pid: int, op=Depends(require_operator)):
    pool = await _pool()
    await pool.execute("DELETE FROM sound_personas WHERE id=$1", pid)
    return {"deleted": True}


# ---------------- edge-tts 真人声合成（甜妹/御姐等神经音;QH 方案落地 Mix） ----------------
# 缓存键=(voice,rate,pitch,text) 哈希,重复文本零成本;edge-tts 缺席/失败时 5xx,前端回落浏览器 TTS。
TTS_DIR = "/data/mix/tts_cache"
_TTS_FALLBACK_VOICE = "zh-CN-XiaoxiaoNeural"


@router.get("/notify/tts")
async def notify_tts(text: str, persona: str = "", voice: str = "",
                     rate_pct: int | None = None, pitch_pct: int | None = None,
                     _who=Depends(require_viewer)):
    """真人声试听/播报:persona=sound_personas.skey(取其 voice/rate/pitch);
    voice/rate_pct/pitch_pct 显式传入时覆盖(人设编辑框'试听当前设置'不用先保存)。"""
    try:
        import edge_tts
    except ImportError:
        raise HTTPException(501, "edge-tts 未安装(服务器 venv: pip install edge-tts)")
    import os
    import hashlib
    import asyncio
    from fastapi.responses import FileResponse

    text = (text or "").strip()[:300]
    if not text:
        raise HTTPException(400, "text 必填")
    v, r_pct, p_pct = "", 0, 0
    if persona:
        pool = await _pool()
        row = await pool.fetchrow("SELECT voice, rate_pct, pitch_pct FROM sound_personas WHERE skey=$1", persona)
        if row:
            v = row["voice"] or ""
            r_pct = int(row["rate_pct"] or 0)
            p_pct = int(row["pitch_pct"] or 0)
    if voice:
        v = voice
    if rate_pct is not None:
        r_pct = int(rate_pct)
    if pitch_pct is not None:
        p_pct = int(pitch_pct)
    v = (v or _TTS_FALLBACK_VOICE)[:80]
    r_pct = max(-50, min(50, r_pct))
    p_pct = max(-50, min(50, p_pct))
    key = hashlib.sha1(f"{v}|{r_pct}|{p_pct}|{text}".encode()).hexdigest()
    os.makedirs(TTS_DIR, exist_ok=True)
    path = os.path.join(TTS_DIR, f"{key}.mp3")
    if not os.path.exists(path):
        # edge-tts 语法:rate="+10%" / pitch="+20Hz"(pct 直接映射 Hz,±50 内听感线性)
        rate = f"{'+' if r_pct >= 0 else ''}{r_pct}%"
        pitch = f"{'+' if p_pct >= 0 else ''}{p_pct}Hz"
        tmp = f"{path}.{os.getpid()}.tmp"
        try:
            await asyncio.wait_for(
                edge_tts.Communicate(text, v, rate=rate, pitch=pitch).save(tmp), timeout=25)
            if not os.path.getsize(tmp):
                raise RuntimeError("合成产物为空")
            os.replace(tmp, path)
        except HTTPException:
            raise
        except Exception as e:  # noqa: BLE001
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise HTTPException(502, f"edge-tts 合成失败:{e}")
    return FileResponse(path, media_type="audio/mpeg", filename="tts.mp3")


def _tpl_speech_text(title: str, body: str) -> str:
    """模板朗读文本:标题+正文,剥 {var} 占位,空白折叠——与前端 tplSpeech 同一口径(命中同一缓存键)。"""
    import re
    t = re.sub(r"\{[^}]*\}", "", f"{title or ''}，{body or ''}")
    return re.sub(r"\s+", " ", t).strip()[:300]


@router.post("/notify/tts/pregen")
async def notify_tts_pregen(op=Depends(require_operator)):
    """全部启用模板 × 声音人设 批量预合成提示音(落盘缓存,重复文本零成本)。
    模板绑定 sound_key 用其人设;未绑定=每个人设各合成一份。文本变更=新缓存键,自动重合成。"""
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        raise HTTPException(501, "edge-tts 未安装(服务器 venv: pip install edge-tts)")
    import os
    import hashlib
    import asyncio

    pool = await _pool()
    tpls = await pool.fetch("SELECT tkey, title, body, sound_key FROM notify_templates WHERE enabled")
    pers = {r["skey"]: r for r in await pool.fetch("SELECT skey, voice, rate_pct, pitch_pct FROM sound_personas")}
    if not pers:
        raise HTTPException(409, "无声音人设,先在「声音人设」页建甜妹/御姐")
    jobs = []
    for t in tpls:
        text = _tpl_speech_text(t["title"], t["body"])
        if not text:
            continue
        keys = [t["sound_key"]] if t["sound_key"] in pers else list(pers)
        for sk in keys:
            p = pers[sk]
            jobs.append((t["tkey"], sk, text, (p["voice"] or _TTS_FALLBACK_VOICE)[:80],
                         max(-50, min(50, int(p["rate_pct"] or 0))), max(-50, min(50, int(p["pitch_pct"] or 0)))))
    os.makedirs(TTS_DIR, exist_ok=True)
    sem = asyncio.Semaphore(4)
    done, cached, failed = 0, 0, []

    async def synth(tkey, sk, text, voice, r_pct, p_pct):
        nonlocal done, cached
        key = hashlib.sha1(f"{voice}|{r_pct}|{p_pct}|{text}".encode()).hexdigest()
        path = os.path.join(TTS_DIR, f"{key}.mp3")
        if os.path.exists(path):
            cached += 1
            return
        tmp = f"{path}.{os.getpid()}.tmp"
        rate = f"{'+' if r_pct >= 0 else ''}{r_pct}%"
        pitch = f"{'+' if p_pct >= 0 else ''}{p_pct}Hz"
        async with sem:
            try:
                import edge_tts as _et
                await asyncio.wait_for(_et.Communicate(text, voice, rate=rate, pitch=pitch).save(tmp), timeout=25)
                if not os.path.getsize(tmp):
                    raise RuntimeError("合成产物为空")
                os.replace(tmp, path)
                done += 1
            except Exception as e:  # noqa: BLE001
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                failed.append(f"{tkey}×{sk}:{e}")

    await asyncio.gather(*(synth(*j) for j in jobs))
    await proxy.audit(op["operator"], op["role"], "tts.pregen", "notify_templates",
                      {"jobs": len(jobs)}, f"gen={done} cached={cached} fail={len(failed)}")
    return {"templates": len(tpls), "jobs": len(jobs), "generated": done, "cached": cached, "failed": failed[:10]}


# ---------------- 渠道设置（飞书 webhook / 邮件配置留位;节流主体仍在 /settings/notifications） ----------------
@router.get("/notify/channels")
async def channels_get(_who=Depends(require_viewer)):
    import os
    pool = await _pool()
    row = await pool.fetchrow("SELECT feishu_webhook, email_conf, feishu_conf FROM notify_settings WHERE id=1")
    email = row["email_conf"] if row else {}
    if isinstance(email, str):
        email = json.loads(email or "{}")
    fconf = row["feishu_conf"] if row else {}
    if isinstance(fconf, str):
        fconf = json.loads(fconf or "{}")
    hook = (row["feishu_webhook"] if row else "") or ""
    # App ID：库配置优先，回落 DexCexMix 自建应用 env（已在岗，手机号→open_id 用它）
    app_id = fconf.get("app_id") or os.environ.get("DCM_FEISHU_APP_ID", "")
    return {"feishuWebhook": (hook[:38] + "…" + hook[-6:]) if len(hook) > 50 else hook,
            "feishuConfigured": bool(hook),
            "feishuAppId": app_id,
            "feishuAppConfigured": bool(app_id),
            "feishuOpenId": fconf.get("open_id") or os.environ.get("DCM_FEISHU_OPEN_ID", ""),
            "email": {k: email.get(k, "") for k in ("host", "port", "user", "sender", "to")},
            "emailPasswordSet": bool(email.get("password")),
            "emailNote": ("邮件通道已配置(fatal级风险告警+广播真发送)" if _email_ready(email)
                          else "待补齐:" + "/".join(lbl for k, lbl in
                               (("host", "主机"), ("user", "账号"), ("password", "授权码"), ("to", "收件人"))
                               if not email.get(k)))}


# ---------------- AI 客服（浮动球主动弹窗：重要通知推给前端 AI 助手） ----------------
_AI_DEFAULT = {"enabled": True, "min_level": "fatal", "speak": False,
               "persona": "", "interpret": False}


@router.get("/notify/ai")
async def ai_conf_get(_who=Depends(require_viewer)):
    """AI 客服弹窗配置（Layout 浮动球启动时读取；viewer 可读）。"""
    pool = await _pool()
    row = await pool.fetchrow("SELECT ai_conf FROM notify_settings WHERE id=1")
    conf = row["ai_conf"] if row else {}
    if isinstance(conf, str):
        conf = json.loads(conf or "{}")
    return {**_AI_DEFAULT, **(conf or {})}


@router.put("/notify/ai")
async def ai_conf_put(body: dict, op=Depends(require_operator)):
    conf = {"enabled": bool(body.get("enabled", True)),
            "min_level": body.get("min_level") if body.get("min_level") in ("warn", "fatal") else "fatal",
            "speak": bool(body.get("speak")), "persona": str(body.get("persona") or "")[:40],
            "interpret": bool(body.get("interpret"))}
    pool = await _pool()
    await pool.execute("UPDATE notify_settings SET ai_conf=$1::jsonb, updated_by=$2, updated_at=now() WHERE id=1",
                       json.dumps(conf), op["operator"])
    await proxy.audit(op["operator"], op["role"], "notify.ai", "notify_settings", conf, "saved")
    return {"saved": True, **conf}


@router.post("/notify/ai/test")
async def ai_conf_test(body: dict, op=Depends(require_operator)):
    """发一条测试告警到跑马灯频道（level 默认 fatal）——AI 客服弹窗端到端验证。"""
    r = ds.rds()
    if r is None:
        raise HTTPException(503, "redis 未配置")
    level = body.get("level") if body.get("level") in ("warn", "fatal") else "fatal"
    await r.publish(MARQUEE_CHANNEL, json.dumps({
        "service": "exec-manager", "title": str(body.get("title") or "AI客服弹窗测试")[:120],
        "content": str(body.get("content") or f"这是一条 {level} 级测试告警，AI 客服应主动弹窗提示。")[:300],
        "level": level, "color": LEVEL_COLOR.get(level, "#F6465D"), "blink": level == "fatal",
    }, ensure_ascii=False))
    return {"sent": True, "level": level}


@router.put("/notify/channels")
async def channels_put(body: dict, op=Depends(require_operator)):
    pool = await _pool()
    sets, args = [], []
    if "feishuWebhook" in body and "…" not in str(body["feishuWebhook"]):
        args.append(str(body["feishuWebhook"] or "").strip())
        sets.append(f"feishu_webhook=${len(args)}")
    if isinstance(body.get("feishuConf"), dict):
        fc = {k: str(body["feishuConf"].get(k, ""))[:160] for k in ("app_id", "secret", "open_id")}
        args.append(json.dumps({k: v for k, v in fc.items() if v}))
        sets.append(f"feishu_conf=${len(args)}::jsonb")
    new_email = None
    if isinstance(body.get("email"), dict):
        # 授权码留空=保留旧值(UI 不回显密码,重存不清空)
        cur = await _email_conf(pool)
        new_email = {k: str(body["email"].get(k, ""))[:120] for k in _EMAIL_KEYS}
        if not new_email.get("password"):
            new_email["password"] = str(cur.get("password") or "")
        args.append(json.dumps(new_email))
        sets.append(f"email_conf=${len(args)}::jsonb")
    if not sets:
        return {"saved": False, "note": "无变更"}
    await pool.execute(f"UPDATE notify_settings SET {', '.join(sets)}, updated_by='{op['operator']}', "
                       "updated_at=now() WHERE id=1", *args)
    if new_email is not None:
        await _publish_email_conf(new_email)   # 分发 Redis → dcm P0 邮件通道双机即取
    await proxy.audit(op["operator"], op["role"], "notify.channels", "notify_settings",
                      {k: body[k] for k in body if k != "email"}, "saved")
    return {"saved": True}


@router.post("/notify/channels/email_test")
async def channels_email_test(op=Depends(require_operator)):
    """发送测试邮件(用已保存 SMTP 配置)——端到端验证通道。"""
    pool = await _pool()
    conf = await _email_conf(pool)
    if not _email_ready(conf):
        raise HTTPException(400, "SMTP 未配置齐(主机/账号/授权码/收件人)")
    ok, detail = await _smtp_send(
        conf, "[Mix] 邮件通道测试",
        f"这是一封测试邮件——mixadmin 通知模块邮件(SMTP)通道端到端验证。\n"
        f"操作员: {op['operator']}\n时间: {dt.datetime.now().isoformat()}\n"
        f"该通道同时服务: 手动广播(勾选邮件) + DCM 风控 fatal 级告警自动升级。")
    await _log_send(pool, "email", str(conf.get("to"))[:60], "邮件通道测试", "test", ok, detail, op["operator"])
    return {"status": "sent" if ok else "failed", "detail": detail, "to": conf.get("to")}
