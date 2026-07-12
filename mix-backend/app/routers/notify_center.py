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
        "INSERT INTO notify_templates(tkey,title,body,level,channels,enabled,updated_by,updated_at) "
        "VALUES($1,$2,$3,$4,$5,$6,$7,now()) ON CONFLICT (tkey) DO UPDATE SET "
        "title=$2, body=$3, level=$4, channels=$5, enabled=$6, updated_by=$7, updated_at=now()",
        tkey, str(body.get("title") or "")[:200], str(body.get("body") or "")[:4000], level,
        json.dumps(body.get("channels") or ["marquee"]), bool(body.get("enabled", True)), op["operator"])
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
                    "level": level, "color": LEVEL_COLOR[level], "blink": level == "fatal",
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
        results["email"] = "邮件通道未接 SMTP（配置留位,不假发送）"
        await _log_send(pool, "email", "-", title, text, False, "SMTP 未接线", op["operator"])
    await proxy.audit(op["operator"], op["role"], "notify.broadcast", ",".join(channels),
                      {"title": title, "level": level}, str(results)[:200])
    return {"results": results}


# ---------------- 渠道设置（飞书 webhook / 邮件配置留位;节流主体仍在 /settings/notifications） ----------------
@router.get("/notify/channels")
async def channels_get(_who=Depends(require_viewer)):
    pool = await _pool()
    row = await pool.fetchrow("SELECT feishu_webhook, email_conf FROM notify_settings WHERE id=1")
    email = row["email_conf"] if row else {}
    if isinstance(email, str):
        email = json.loads(email or "{}")
    hook = (row["feishu_webhook"] if row else "") or ""
    return {"feishuWebhook": (hook[:38] + "…" + hook[-6:]) if len(hook) > 50 else hook,
            "feishuConfigured": bool(hook),
            "email": {k: email.get(k, "") for k in ("host", "port", "user", "sender")},
            "emailNote": "邮件通道未接 SMTP,保存仅留位"}


@router.put("/notify/channels")
async def channels_put(body: dict, op=Depends(require_operator)):
    pool = await _pool()
    sets, args = [], []
    if "feishuWebhook" in body and "…" not in str(body["feishuWebhook"]):
        args.append(str(body["feishuWebhook"] or "").strip())
        sets.append(f"feishu_webhook=${len(args)}")
    if isinstance(body.get("email"), dict):
        args.append(json.dumps({k: str(body["email"].get(k, ""))[:120]
                                for k in ("host", "port", "user", "sender", "password")}))
        sets.append(f"email_conf=${len(args)}::jsonb")
    if not sets:
        return {"saved": False, "note": "无变更"}
    await pool.execute(f"UPDATE notify_settings SET {', '.join(sets)}, updated_by='{op['operator']}', "
                       "updated_at=now() WHERE id=1", *args)
    await proxy.audit(op["operator"], op["role"], "notify.channels", "notify_settings",
                      {k: body[k] for k in body if k != "email"}, "saved")
    return {"saved": True}
