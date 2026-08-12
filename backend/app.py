# Quant Hedge 后端骨架 (FastAPI)
# 架构: testgo 式服务端中心 — 引擎+数据在服务端，凭证留用户 MT 终端（本服务绝不接收/存储 MT 凭证）
# api2trade 预留：连接器接口空实现，当前走用户侧 MT5 bridge
import os, json, datetime, time, contextvars, math, bisect as _bisect, inspect as _inspect
from fastapi import FastAPI, HTTPException, Depends, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, conint
from typing import Optional
import psycopg2, psycopg2.extras, redis
from trade_queue import RedisTradeQueue, TERMINAL_STATES as TRADE_QUEUE_TERMINAL_STATES

QH_BUILD_ID = "hedge-pro-mt5-five-stage-latency-20260812.41"

# P0.1: 全链路追踪模块
from qh_command_tracer import (
    init_tracer,
    get_tracer,
    CommandType,
    CommandStatus,
    TraceTimestamp,
    set_api_received,
    reset_api_received,
)

DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))
R = redis.Redis(host="127.0.0.1", port=6379, db=3, decode_responses=True)

# P0.1: 初始化全链路追踪器
init_tracer(R)

RNS = "qh:"
TRADE_QUEUE = RedisTradeQueue(R, RNS+"tradeq:")
_TRADE_QUEUE_OWNER = "%s:%s" % (os.uname().nodename if hasattr(os,"uname") else "qh", os.getpid())
_QUEUE_PROOF_PROCESS_NONCE = os.urandom(16).hex()
_TRADE_QUEUE_DISPATCH_LIMIT = max(1, min(32, int(os.environ.get(
    "QH_TRADE_QUEUE_DISPATCH_CONCURRENCY", "20"
))))
_TRADE_QUEUE_TASKS = {}
_TRADE_QUEUE_WAKE = None
_TRADE_QUEUE_LOOP_TASK = None
_OPEN_SAGA_RECOVERY_TASKS = {}
_CLOSE_REVIEW_RECOVERY_TASKS = {}
_OPEN_SAGA_FINALIZER_LEASE_TTL = 180
_CLOSE_REVIEW_FINALIZER_LEASE_TTL = 180
_AUTO_SINGLE_LEG_CLOSE_LEASE_TTL = 45
_PENDING_FINALIZER_TRUTH_BUDGET_SEC = max(0.25, min(5.0, float(os.environ.get(
    "QH_PENDING_FINALIZER_TRUTH_BUDGET_SEC", "1.5"
))))
try:
    _MANUAL_TRADE_BURST_WINDOW_SEC = max(0.05, min(0.75, float(
        os.environ.get("QH_MANUAL_TRADE_BURST_WINDOW_MS", "300")) / 1000.0))
except (TypeError, ValueError):
    _MANUAL_TRADE_BURST_WINDOW_SEC = 0.30
_MANUAL_TRADE_BURST_TTL_SEC = max(2, int(math.ceil(
    _MANUAL_TRADE_BURST_WINDOW_SEC * 2.0 + 1.0)))

def _user_alert_key(username):
    return RNS+"alerts:user:"+str(username or "").strip()

def _push_alert(level, message, username=None, **fields):
    """Keep an admin audit stream and a separate user-visible stream."""
    payload={"ts":datetime.datetime.utcnow().isoformat(),"lv":level,"msg":message}
    if username: payload["username"]=str(username)
    payload.update(fields)
    raw=json.dumps(payload,ensure_ascii=False,default=str)
    try:
        pipe=R.pipeline(transaction=True)
        pipe.lpush(RNS+"alerts",raw); pipe.ltrim(RNS+"alerts",0,199)
        if username:
            pipe.lpush(_user_alert_key(username),raw); pipe.ltrim(_user_alert_key(username),0,49)
        pipe.execute()
    except Exception:
        pass
    return payload

def _read_user_alerts(username, limit=20):
    if not username: return []
    try: raw=R.lrange(_user_alert_key(username),0,max(0,int(limit)-1)) or []
    except Exception: return []
    out=[]
    for item in raw:
        try:
            payload=json.loads(item)
            if payload.get("username")==username: out.append(payload)
        except Exception:
            continue
    return out


def _alert_usernames_from_templates(templates):
    """Return distinct, non-empty principals represented by an eval cycle."""
    users = set()
    for template in templates or ():
        if not isinstance(template, dict):
            continue
        username = str(template.get("username") or "").strip()
        if username:
            users.add(username)
    return sorted(users)

# ---- GeoIP 离线解析(DB-IP/GeoLite2 mmdb, 懒加载单例, 缺库则降级为空) ----
GEOIP_DB = os.environ.get("QH_GEOIP_DB", "/opt/quanthedge/geoip/dbip-country.mmdb")
_geoip_reader = None; _geoip_tried = False
def _geoip(ip):
    """返回 (iso_code, zh_name) 或 (None,None)。缺库/私网/解析失败均静默降级。"""
    global _geoip_reader, _geoip_tried
    if not ip or ip.startswith(("10.","192.168.","172.","127.")): return (None,None)
    if not _geoip_tried:
        _geoip_tried = True
        try:
            import geoip2.database
            _geoip_reader = geoip2.database.Reader(GEOIP_DB)
        except Exception as e:
            print("geoip disabled:", e); _geoip_reader = None
    if not _geoip_reader: return (None,None)
    try:
        r = _geoip_reader.country(ip)
        return (r.country.iso_code, r.country.names.get("zh-CN") or r.country.name)
    except Exception:
        return (None,None)

app = FastAPI(title="Quant Hedge API", version="0.1.0")

@app.middleware("http")
async def observe_trade_state_latency(request: Request, call_next):
    """Expose application time and retain evidence when trade-state reads stall."""
    started = time.perf_counter()
    ingress_token=set_api_received(_dt.datetime.utcnow().isoformat())
    try:
        response = await call_next(request)
    finally:
        reset_api_received(ingress_token)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    response.headers["Server-Timing"] = "qhapp;dur=%.1f" % elapsed_ms
    path = request.url.path
    if path.startswith("/api/trade_queue/"):
        response.headers["Cache-Control"] = "no-store"
    if elapsed_ms >= 250 and (path == "/api/engine/legs" or path.startswith("/api/trade_queue/")):
        print(json.dumps({
            "event": "qh_api_slow",
            "path": path,
            "method": request.method,
            "status": response.status_code,
            "elapsed_ms": round(elapsed_ms, 1),
        }, separators=(",", ":")), flush=True)
    return response

def db():
    c = psycopg2.connect(**DB); c.autocommit = True; return c

# User API authentication is defined before route registration so both the
# membership routes near the top of this module and trading routes can share
# the same ownership checks.
_LIC_USER_CACHE: dict = {}  # license_key -> (username, status, ts)
_LICENSE_PRINCIPAL = contextvars.ContextVar("qh_license_principal", default=None)
def _license_identity(license_key: str):
    import time as _time_mod
    cached = _LIC_USER_CACHE.get(license_key)
    if cached and (_time_mod.time() - cached[2]) < 30:
        return cached[0], cached[1]
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT username,status FROM users WHERE license_key=%s",(license_key,))
        row=cur.fetchone(); c.close()
        if not row: return None
        ident=(row[0],row[1])
        _LIC_USER_CACHE[license_key]=(ident[0],ident[1],_time_mod.time())
        return ident
    except Exception:
        return None

def require_license(x_license: str = Header(default="")):
    if not x_license:
        raise HTTPException(403, "缺少用户密钥")
    ident=_license_identity(x_license)
    if not ident:
        raise HTTPException(403, "密钥无效")
    if ident[1] in ("banned","disabled"):
        raise HTTPException(403, "账户已停用/封禁")
    # The dependency-validated header remains authoritative for route code
    # that also accepts a legacy body-level license_key.
    _LICENSE_PRINCIPAL.set(ident[0])
    return ident[0]

_FRONTEND_TELEMETRY_EVENTS={
    "client_started",
    "frontend_queue_state_received",
    "frontend_position_refresh_done",
}
_FRONTEND_TELEMETRY_MAX_EVENTS=16

class FrontendTelemetryBatch(BaseModel):
    events:list[dict]

def _frontend_telemetry_values(value, limit=20, max_len=128):
    values=value if isinstance(value,list) else [value]
    out=[]
    for item in values[:limit]:
        text=str(item or "")[:max_len]
        if text and text not in out:
            out.append(text)
    return out

def _frontend_received_at():
    return datetime.datetime.utcnow().isoformat()

def _frontend_pending_key(username, client_request_id):
    return (RNS+"telemetry:frontend:pending:"+str(username or "")+":"+
            str(client_request_id or ""))

def _frontend_batch_command_ids(batch):
    commands=[]
    for collection in (batch.get("jobs"),batch.get("job_specs")):
        for job in collection or ():
            if not isinstance(job,dict):
                continue
            command_id=str(job.get("command_id") or "")[:128]
            if command_id and command_id not in commands:
                commands.append(command_id)
    return commands

def _frontend_telemetry_context(username, raw):
    """Resolve telemetry against authoritative account, batch, and command data."""
    batch_ids=_frontend_telemetry_values(raw.get("batch_ids") or raw.get("batch_id"))
    command_ids=_frontend_telemetry_values(raw.get("command_ids"))
    client_request_id=str(raw.get("client_request_id") or "")[:96]
    if raw.get("event")=="client_started":
        if (command_ids or len(batch_ids)!=1 or batch_ids[0]!=client_request_id or
                not 16<=len(client_request_id)<=64 or
                not client_request_id.isalnum()):
            return None
        try:
            batch=TRADE_QUEUE.batch_status(client_request_id)
        except Exception:
            return None
        if batch:
            if str(batch.get("username") or "")!=str(username):
                return None
        else:
            try:
                lease_raw=R.get(RNS+"tradeq:admission:"+client_request_id)
                lease=json.loads(lease_raw) if lease_raw else None
            except Exception:
                return None
            if lease and str(lease.get("username") or "")!=str(username):
                return None
        return {"batch_ids":batch_ids,"command_ids":[],"client_started":True}

    if not batch_ids:
        return None
    batches=[]
    authoritative={}
    for batch_id in batch_ids:
        try:
            batch=TRADE_QUEUE.batch_status(batch_id)
        except Exception:
            return None
        if not batch or str(batch.get("username") or "")!=str(username):
            return None
        batches.append(batch)
        for command_id in _frontend_batch_command_ids(batch):
            existing=authoritative.get(command_id)
            if existing and existing!=batch_id:
                return None
            authoritative[command_id]=batch_id
    if not authoritative or any(command_id not in authoritative
                                for command_id in command_ids):
        return None
    for command_id,batch_id in authoritative.items():
        try:
            command=get_tracer().get_command(command_id)
        except Exception:
            return None
        if (not command or str(command.get("username") or "")!=str(username) or
                str(command.get("batch_id") or "")!=str(batch_id)):
            return None
    return {"batch_ids":batch_ids,"command_ids":list(authoritative),
            "client_started":False}

def _frontend_telemetry_owned(username, raw):
    return _frontend_telemetry_context(username,raw) is not None

def _frontend_elapsed_ms(value):
    try:
        elapsed=float(value)
    except (TypeError,ValueError):
        return None
    return elapsed if 0<=elapsed<=86_400_000 else None

def _trace_frontend_event(context, raw, received_at):
    event=raw.get("event")
    field=(TraceTimestamp.FRONTEND_QUEUE_STATE_RECEIVED
           if event=="frontend_queue_state_received"
           else TraceTimestamp.FRONTEND_POSITION_REFRESH_DONE)
    elapsed_field=("frontend_queue_elapsed_ms"
                   if event=="frontend_queue_state_received"
                   else "frontend_position_refresh_elapsed_ms")
    elapsed=_frontend_elapsed_ms(raw.get("elapsed_ms"))
    tracer=get_tracer()
    for command_id in context.get("command_ids") or ():
        _record_trace_timestamp_value_once(tracer,command_id,field,received_at)
        if elapsed is not None:
            _record_trace_timestamp_value_once(
                tracer,command_id,elapsed_field,"%.3f"%elapsed)
        for batch_id in context.get("batch_ids") or ():
            try:
                pending_raw=R.get(_frontend_pending_key(
                    str((tracer.get_command(command_id) or {}).get("username") or ""),
                    batch_id))
                pending=json.loads(pending_raw) if pending_raw else None
            except Exception:
                pending=None
            if not isinstance(pending,dict):
                continue
            started_at=pending.get("server_received_at")
            if started_at:
                _record_trace_timestamp_value_once(
                    tracer,command_id,
                    TraceTimestamp.FRONTEND_CLIENT_STARTED_RECEIVED,started_at)
            if pending.get("client_ts") is not None:
                _record_trace_timestamp_value_once(
                    tracer,command_id,"frontend_client_epoch_ms",
                    pending.get("client_ts"))

def _store_frontend_telemetry(username, events):
    """Persist bounded browser evidence off the request/event-loop thread."""
    rows=[]
    accepted=0
    for raw in (events or [])[:_FRONTEND_TELEMETRY_MAX_EVENTS]:
        if not isinstance(raw,dict) or raw.get("event") not in _FRONTEND_TELEMETRY_EVENTS:
            continue
        context=_frontend_telemetry_context(username,raw)
        if context is None:
            continue
        received_at=_frontend_received_at()
        row={
            "event":raw["event"],"username":username,
            "ts":round(time.time(),6),
            "server_received_at":received_at,
            "client_ts":raw.get("epoch_ms"),
            "session_id":str(raw.get("session_id") or "")[:96],
            "client_request_id":str(raw.get("client_request_id") or "")[:96],
            "batch_ids":context["batch_ids"],
            "command_ids":context["command_ids"],
            "slots":[int(v) for v in ((raw.get("slots") if isinstance(raw.get("slots"),list) else [])[:20])
                     if str(v).isdigit() and 0<int(v)<=20],
        }
        for key in ("scope","kind","path","elapsed_ms","server_ts"):
            if key in raw:
                row[key]=raw[key]
        for key in ("depths","counts","trust"):
            value=raw.get(key)
            if isinstance(value,dict):
                row[key]={str(k)[:64]:v for k,v in list(value.items())[:20]}
        encoded=json.dumps(row,separators=(",",":"),default=str)
        if len(encoded)>8192:
            continue
        if context.get("client_started"):
            try:
                R.setex(_frontend_pending_key(username,row["client_request_id"]),300,encoded)
                accepted+=1
            except Exception:
                pass
            continue
        rows.append(encoded)
        accepted+=1
        try:
            _trace_frontend_event(context,raw,received_at)
        except Exception:
            pass
        for batch_id in context.get("batch_ids") or ():
            try:
                R.delete(_frontend_pending_key(username,batch_id))
            except Exception:
                pass
    if not rows:
        return accepted
    try:
        pipe=R.pipeline(transaction=False)
        for row in rows:
            pipe.lpush(RNS+"telemetry:frontend:"+username,row)
        pipe.ltrim(RNS+"telemetry:frontend:"+username,0,999)
        pipe.execute()
    except Exception:
        pass
    return accepted

@app.post("/api/telemetry/frontend")
async def frontend_telemetry(batch:FrontendTelemetryBatch, principal:str=Depends(require_license)):
    # Authentication supplies principal; the body cannot select another user.
    events=[dict(event) for event in list(batch.events or [])[:_FRONTEND_TELEMETRY_MAX_EVENTS]
            if isinstance(event,dict)]
    try:
        loop=__import__('asyncio').get_running_loop()
        loop.run_in_executor(None,_store_frontend_telemetry,principal,events)
    except Exception:
        pass
    return {"ok":True,"queued":len(events)}
def _license_to_username(license_key: str) -> str | None:
    ident=_license_identity(license_key)
    return ident[0] if ident else None

def _assert_subject(request_username: str, x_license: str) -> None:
    """Reject cross-user reads/writes even when the caller has a valid key."""
    if not request_username:
        return
    header_principal=_LICENSE_PRINCIPAL.get()
    body_principal=_license_to_username(x_license) if x_license else None
    # A request may omit the legacy body key, but a supplied body key must
    # identify the same account as the authenticated header.  Internal calls
    # without a dependency context still require a valid body key.
    principal_username=header_principal or body_principal
    if principal_username is None:
        raise HTTPException(403, "缺少或无效的用户密钥")
    if header_principal and body_principal and header_principal != body_principal:
        raise HTTPException(403, "SUBJECT_CREDENTIAL_MISMATCH")
    if principal_username != request_username:
        raise HTTPException(403,
            f"SUBJECT_RESOURCE_MISMATCH: 密钥归属用户({principal_username})"
            f"与请求用户({request_username})不一致，已拒绝")

def _user_is_valid(username: str) -> bool:
    """Return whether an account may arm subscription-scoped automation."""
    c=None
    try:
        c=db(); cur=c.cursor()
        cur.execute("""SELECT status,expire_at FROM users WHERE username=%s""",(username,))
        row=cur.fetchone()
        if not row or str(row[0] or "").lower() in ("banned","disabled"):
            return False
        expire_at=row[1]
        if expire_at is None:
            return True
        if expire_at.tzinfo is None:
            expire_at=expire_at.replace(tzinfo=datetime.timezone.utc)
        return expire_at>=datetime.datetime.now(datetime.timezone.utc)
    except Exception:
        return False
    finally:
        try:
            if c is not None: c.close()
        except Exception: pass

def _assert_user_valid(username: str) -> None:
    if not _uid(username):
        raise HTTPException(404,"user not found")
    if not _user_is_valid(username):
        raise HTTPException(403,"账户已停用或到期，无法武装自动进单/平仓")

def _auto_validity_latch_key(kind: str, username: str) -> str:
    return RNS+"auto_%s:validity_latch:"%kind+username

def _auto_validity_disarm(kind: str, username: str, mode: str) -> None:
    """Fail closed and require an explicit re-arm after validity is restored."""
    R.set(RNS+"auto_%s:"%kind+username,"off")
    R.set(_auto_validity_latch_key(kind,username),"1")
    if mode!="off" and R.set(RNS+"auto_%s:validity_warn:"%kind+username,"1",nx=True,ex=300):
        label="进单" if kind=="entry" else "平仓"
        _push_alert("warn","账户已停用或到期，自动%s已关闭；恢复有效后需重新武装"%label,username)

def _auto_validity_disarm_user(username: str) -> None:
    """Persistently disarm both automation directions for one invalid account."""
    for kind in ("entry","exit"):
        mode=R.get(RNS+"auto_%s:"%kind+username) or "off"
        _auto_validity_disarm(kind,username,mode)

def _reconcile_invalid_auto_users() -> int:
    """Disarm every invalid account, including users without parameter templates."""
    c=None
    try:
        c=db(); cur=c.cursor()
        cur.execute("""SELECT username FROM users
                       WHERE COALESCE(status,'active') IN ('banned','disabled')
                          OR (expire_at IS NOT NULL AND expire_at<now())""")
        users=[row[0] for row in cur.fetchall()]
    finally:
        try:
            if c is not None: c.close()
        except Exception: pass
    for username in users:
        _auto_validity_disarm_user(username)
    return len(users)

def require_subject(username: str, x_license: str = Header(default="")):
    require_license(x_license)
    _assert_subject(username,x_license)
    return True

def require_optional_subject(username: str = "", x_license: str = Header(default="")):
    require_license(x_license)
    if username: _assert_subject(username,x_license)
    return True

_WRITER_LEASE_TTL=max(5,int(os.environ.get("QH_WRITER_LEASE_TTL","12")))

def _writer_lease_key(username):
    return RNS+"writer_lease:"+(username or "").strip()

def _claim_writer_lease(username, writer_id, ttl=_WRITER_LEASE_TTL):
    """Claim or renew the account's short manual-trading lease atomically."""
    script="""
    local current = redis.call('get', KEYS[1])
    if not current or current == ARGV[1] then
        redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
        return 1
    end
    return 0
    """
    try:
        return bool(R.eval(script,1,_writer_lease_key(username),str(writer_id),str(max(1,int(ttl)))))
    except Exception:
        return False

def require_trade_writer(request: Request, x_license: str = Header(default=""),
                         x_qh_writer: str = Header(default="")):
    """Prevent two browser locations from writing the same trading account."""
    username=require_license(x_license)
    writer=(x_qh_writer or "").strip()
    if not writer:
        writer="legacy-ip:"+str(_client_ip(request) or "unknown")
    if len(writer)>128:
        import hashlib
        writer="sha256:"+hashlib.sha256(writer.encode("utf-8")).hexdigest()
    if not _claim_writer_lease(username,writer):
        try: remaining=max(1,int((R.pttl(_writer_lease_key(username)) or 0)/1000)+1)
        except Exception: remaining=_WRITER_LEASE_TTL
        raise HTTPException(409,
            "ACCOUNT_WRITER_LEASE_HELD: 该账号正在另一交易终端操作，请停止另一端后约%d秒再试"%remaining)
    return writer

@app.get("/api/health")
def health():
    info = {"service":"quant-hedge","build_id":QH_BUILD_ID,
            "ts":datetime.datetime.utcnow().isoformat()+"Z"}
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT count(*) FROM users"); info["users"]=cur.fetchone()[0]; c.close()
        info["db"]="ok"
    except Exception as e: info["db"]="error: %s"%e
    try: R.ping(); info["redis"]="ok (db3 ns=%s)"%RNS
    except Exception as e: info["redis"]="error: %s"%e
    info["connector"]="mt5-bridge (api2trade reserved)"
    task=_TRADE_QUEUE_LOOP_TASK
    queue_error=""
    if task is None:
        queue_error="not_started"
    elif task.done():
        if task.cancelled():
            queue_error="cancelled"
        else:
            try: error=task.exception()
            except BaseException as ex: error=ex
            queue_error=("%s: %s"%(error.__class__.__name__,str(error)[:160])) if error else "exited"
    info["trade_queue"]="error" if queue_error else "ok"
    if queue_error:
        info["trade_queue_error"]=queue_error
        return JSONResponse(info,status_code=503)
    return info

# ---- 薄授权：密钥校验（仅密钥与到期，无 MT 凭证）----
class LoginReq(BaseModel):
    license_key: str
@app.post("/api/auth/verify")
def verify(req: LoginReq, request: Request):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,nickname,plan,expire_at,feishu_id,status FROM users WHERE license_key=%s",(req.license_key,))
    row=cur.fetchone()
    if not row: c.close(); raise HTTPException(401,"invalid license key")
    if row.get("status") in ("banned","disabled"):
        c.close(); raise HTTPException(403,"账户已停用,请联系客服" if row["status"]=="disabled" else "账户已封禁")
    # 维护态禁登录: 全站维护时非操作员一律挡门外(操作员走 qhadmin, 不经此端点)
    _m=_maint_get()
    if _m.get("on") and _m.get("block_login"):
        c.close()
        raise HTTPException(503, json.dumps({"maintenance":True,"title":_m.get("title") or "系统维护中",
              "msg":_m.get("msg") or "系统正在维护，暂停登录，请稍后再试","until":_m.get("until") or ""}, ensure_ascii=False))
    # 记录来源 IP + 地区(离线解析, 失败不阻断登录)
    try:
        ip=_client_ip(request); iso,zh=_geoip(ip)
        cur.execute("UPDATE users SET last_ip=%s,last_login=now(),geo_country=COALESCE(%s,geo_country),geo_name=COALESCE(%s,geo_name) WHERE id=%s",
                    (ip,iso,zh,row["id"]))
    except Exception as ge: print("geo record err",ge)
    c.close()
    expired = row["expire_at"] < datetime.datetime.now(datetime.timezone.utc)
    R.setex(RNS+"session:"+req.license_key, 86400, "1")
    R.setex(RNS+"ws:primary_user", 86400, row["username"])   # HUB 路径无本地连接时的 user_data 归属(单用户场景)
    return {"ok":not expired,"username":row["username"],"nickname":row.get("nickname"),"plan":row["plan"],
            "expire_at":row["expire_at"].isoformat(),"expired":expired,"feishu_id":row["feishu_id"]}

# ---- 用户自助注册 / 体验试用 / 内购下单(用户端公开, 防滥用限 IP) ----
INVITE_REWARD_TRIAL = 100    # 邀请好友激活试用 → 邀请人 +100 积分
INVITE_REWARD_PAID_RATE = 0.10  # 邀请好友首次付费 → 邀请人返实付 10% 积分(×POINTS_PER_USDT)
def _self_register(username, contact, feishu_id, request, trial_days=0, agent_code="", staff_code="", inviter=""):
    """建号(生成 license), trial_days>0 则写试用期+强制DEMO。返回 license/username。防滥用: 同 IP 24h 限 3 次。
       staff_code: 员工首归因(终身); inviter: 好友邀请人(终身)。三者并行, 数据隔离。
       试用激活额外发 +20 积分; 若有 inviter 且本次是试用 → 邀请人 +100(每被邀人一次)。"""
    import secrets
    ip=_client_ip(request)
    cnt_key=RNS+"reg_ip:"+ip
    try:
        n=R.incr(cnt_key)
        if n==1: R.expire(cnt_key, 86400)
        if n>3: raise HTTPException(429,"注册过于频繁, 请稍后再试或联系客服")
    except HTTPException: raise
    except Exception: pass
    if _uid(username): raise HTTPException(400,"用户名已被占用")
    newk="QH-"+secrets.token_hex(8).upper()
    iso,zh=_geoip(ip)
    now=datetime.datetime.now(datetime.timezone.utc)
    exp = now+datetime.timedelta(days=trial_days) if trial_days>0 else now+datetime.timedelta(days=3650)
    status = "trial" if trial_days>0 else "active"
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # 绑定代理(分佣归因)
    aid=None
    if agent_code:
        cur.execute("SELECT id FROM agents WHERE code=%s",(agent_code,)); a=cur.fetchone(); aid=(a["id"] if a else None)
    # 员工首归因: 校验 staff_code 存在且启用
    sc=None
    if staff_code:
        cur.execute("SELECT code FROM staff WHERE code=%s AND enabled=true",(staff_code,)); s=cur.fetchone(); sc=(s["code"] if s else None)
    # 邀请人首归因: 必须是存在的用户, 且不能自邀
    inv=None
    if inviter and inviter!=username:
        cur.execute("SELECT id FROM users WHERE username=%s",(inviter,)); iv=cur.fetchone(); inv=(inviter if iv else None)
    cur.execute("""INSERT INTO users(username,license_key,plan,expire_at,feishu_id,status,created_at,last_ip,last_login,geo_country,geo_name,agent_id,staff_code,inviter,source,
                   trial_until,trial_started)
                   VALUES(%s,%s,%s,%s,%s,%s,now(),%s,now(),%s,%s,%s,%s,%s,'self',%s,%s) RETURNING id""",
                (username,newk,None,exp,feishu_id or None,status,ip,iso,zh,aid,sc,inv,
                 (exp if trial_days>0 else None),(now if trial_days>0 else None)))
    uid=cur.fetchone()["id"]
    # 试用激活 +20 积分(与建号同事务)
    if trial_days>0:
        try: _points_add(cur, uid, 20, "试用激活", "trial", username, "self")
        except Exception as pe: print("trial points err",pe)
    # 邀请关系 + 邀请人试用奖励(每被邀人一次, reward_trial_done 防重)
    if inv:
        cur.execute("""INSERT INTO invites(inviter,invitee,stage,reward_trial_done)
                       VALUES(%s,%s,%s,%s) ON CONFLICT (invitee) DO NOTHING""",
                    (inv,username,("trial" if trial_days>0 else "registered"), False))
        if trial_days>0:
            cur.execute("SELECT reward_trial_done FROM invites WHERE invitee=%s",(username,)); iv2=cur.fetchone()
            if iv2 and not iv2["reward_trial_done"]:
                inv_uid=_uid(inv)
                if inv_uid:
                    try:
                        _points_add(cur, inv_uid, INVITE_REWARD_TRIAL, "邀请好友激活试用(%s)"%username, "invite_trial", username, "self")
                        cur.execute("UPDATE invites SET reward_trial_done=true,stage='trial' WHERE invitee=%s",(username,))
                    except Exception as pe: print("invite trial reward err",pe)
    # 活动引擎: register / trial_activate 事件 + 员工绩效自动发放(试用达标)
    try:
        _fire_campaigns(cur, "register", uid, username, {})
        if trial_days>0:
            _fire_campaigns(cur, "trial_activate", uid, username, {})
            if sc: _staff_perf_auto(cur, sc, "trial_activate")
    except Exception as ce: print("camp register err",ce)
    c.close()
    if trial_days>0: R.set(RNS+"force_demo:"+username,"1")
    _audit(username,"self","register",{"trial_days":trial_days,"ip":ip,"agent":agent_code,"staff":sc,"inviter":inv},DEMO_MODE,status)
    return {"ok":True,"username":username,"license_key":newk,"status":status,"expire_at":exp.isoformat(),"trial":trial_days>0,"staff":sc,"inviter":inv}

class RegisterReq(BaseModel):
    username:str; contact:str=""; feishu_id:str=""; agent_code:str=""; staff_code:str=""; inviter:str=""
@app.post("/api/auth/register")
def auth_register(r:RegisterReq, request:Request):
    if not r.username or len(r.username)<3: raise HTTPException(400,"用户名至少3位")
    return _self_register(r.username, r.contact, r.feishu_id, request, trial_days=0, agent_code=r.agent_code, staff_code=r.staff_code, inviter=r.inviter)

class TrialReq2(BaseModel):
    username:str; contact:str=""; feishu_id:str=""; agent_code:str=""; staff_code:str=""; inviter:str=""; days:int=7
@app.post("/api/auth/trial")
def auth_trial(r:TrialReq2, request:Request):
    if not r.username or len(r.username)<3: raise HTTPException(400,"用户名至少3位")
    return _self_register(r.username, r.contact, r.feishu_id, request, trial_days=max(1,min(30,r.days)), agent_code=r.agent_code, staff_code=r.staff_code, inviter=r.inviter)

class PurchaseReq(BaseModel):
    license_key:str; product_key:str
# ================= 会员积分 + 会员等级(第一阶段; 全在业务层, 绝不进交易引擎) =================
# 积分: 消费返10/USDT、签到、试用激活/转正; 兑换权益写 entitlements。会员等级由订阅+成长值纯推导(就高)。
POINTS_PER_USDT = 10          # 消费/成长: 每 1 USDT = 10 积分 + 10 成长值
# 会员等级阈值(成长值; 与订阅档就高): L0<L1<L2<L3<L4
_GROWTH_TIERS = [(30000,4),(9600,3),(2700,2),(1000,1)]   # 累计消费 3000/960/270/100 USDT ×10
_LEVEL_NAME = {0:"体验交易者",1:"基础对冲者",2:"进阶交易者",3:"专业套利者",4:"旗舰合伙人"}
def _member_level(u):
    """u: dict 含 paid_until/plan/growth_value/total_recharge/trial_until。返回 {level,name,source}。
       订阅档等级与成长值等级就高生效; 无付费但在试用=L0。"""
    now=datetime.datetime.now(datetime.timezone.utc)
    gv=int(u.get("growth_value") or 0)
    # 订阅有效期内, 按累计充值折算的订阅档给一个下限(月100→L1, 季270→L2, 年960→L3)
    lvl_sub=0
    pu=u.get("paid_until")
    if pu and pu>now:
        tr=float(u.get("total_recharge") or 0)
        lvl_sub = 3 if tr>=960 else 2 if tr>=270 else 1 if tr>=100 else 1
    lvl_gv=0
    for thr,lv in _GROWTH_TIERS:
        if gv>=thr: lvl_gv=lv; break
    lvl=max(lvl_sub,lvl_gv)
    return {"level":lvl,"name":_LEVEL_NAME.get(lvl,"体验交易者"),
            "source":("subscription" if lvl_sub>=lvl_gv and lvl_sub>0 else ("growth" if lvl_gv>0 else "trial"))}
def _points_add(cur, uid, delta, reason, ref_type="", ref_id="", operator=""):
    """积分入账(与调用方同事务): 更新 users.points 缓存 + 写 points_ledger。delta 可负; 余额不可为负。
       返回新余额。cur 必须是 RealDictCursor(读 balance_after)。"""
    delta=int(delta)
    cur.execute("SELECT points FROM users WHERE id=%s FOR UPDATE",(uid,))
    row=cur.fetchone()
    if not row: raise HTTPException(404,"user not found")
    cur_bal=int(row["points"] if isinstance(row,dict) else row[0])
    new_bal=cur_bal+delta
    if new_bal<0: raise HTTPException(400,"积分不足(当前 %d, 需扣 %d)"%(cur_bal,-delta))
    cur.execute("UPDATE users SET points=%s WHERE id=%s",(new_bal,uid))
    cur.execute("""INSERT INTO points_ledger(user_id,delta,balance_after,reason,ref_type,ref_id,operator)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",(uid,delta,new_bal,reason,ref_type,str(ref_id),operator))
    return new_bal
def _grow_add(cur, uid, usdt):
    """成长值累加(永久, 仅升不降): 每 USDT ×10。与调用方同事务。"""
    inc=int(round(float(usdt)*POINTS_PER_USDT))
    if inc>0: cur.execute("UPDATE users SET growth_value=COALESCE(growth_value,0)+%s WHERE id=%s",(inc,uid))
    return inc

# ================= 活动引擎(声明式: 事件+条件+动作; 运营在 qhadmin 建活动即生效) =================
# 复用三期所有钩子点, 每个动作走已验证链路。全在业务层, 绝不进交易引擎。
# event: register/trial_activate/first_paid/paid/recharge/checkin/recall_trial/recall_sub
# cond(JSON, 全部满足才触发): min_amount / months_in([..]) / kind_in([..]) / first_paid(bool)
# actions(JSON 数组, 每项 {type,...}):
#   points   {value}            发固定积分
#   points_pct {rate}           按 ctx.amount 实付比例发积分(×POINTS_PER_USDT)
#   growth   {value}            加成长值
#   extend_days {days}          延长 paid_until/expire_at N 天
#   trial_days {days}           延长 trial_until N 天(演示)
#   coupon   {code_prefix,kind,value,applies_to,max_discount,per_user_limit,valid_days}  发专属券给该用户
def _camp_cond_ok(cond, ctx):
    """条件全满足才触发。ctx: {amount,months,kind,first_paid}。"""
    try:
        if not cond: return True
        if "min_amount" in cond and float(ctx.get("amount") or 0) < float(cond["min_amount"]): return False
        if "kind_in" in cond and ctx.get("kind") not in (cond.get("kind_in") or []): return False
        if "months_in" in cond and int(ctx.get("months") or 0) not in [int(x) for x in (cond.get("months_in") or [])]: return False
        if cond.get("first_paid") is True and not ctx.get("first_paid"): return False
        if "streak_min" in cond and int(ctx.get("streak") or 0) < int(cond["streak_min"]): return False
        return True
    except Exception: return True
def _camp_do_action(cur, act, uid, username, ctx, campaign_id):
    """执行单个动作(与调用方同事务)。返回简短结果串(供审计)。"""
    t=act.get("type"); import secrets as _sx
    if t=="points":
        v=int(act.get("value") or 0)
        if v>0: _points_add(cur, uid, v, "活动:%s"%act.get("_cname",""), "campaign", campaign_id, "campaign"); return "points+%d"%v
    elif t=="points_pct":
        v=int(round(float(ctx.get("amount") or 0)*float(act.get("rate") or 0)*POINTS_PER_USDT))
        if v>0: _points_add(cur, uid, v, "活动:%s"%act.get("_cname",""), "campaign", campaign_id, "campaign"); return "points_pct+%d"%v
    elif t=="growth":
        v=int(act.get("value") or 0)
        if v>0: cur.execute("UPDATE users SET growth_value=COALESCE(growth_value,0)+%s WHERE id=%s",(v,uid)); return "growth+%d"%v
    elif t=="extend_days":
        d=int(act.get("days") or 0)
        if d>0: cur.execute("""UPDATE users SET paid_until=GREATEST(COALESCE(paid_until,now()),now())+(%s||' days')::interval,
                 expire_at=GREATEST(COALESCE(paid_until,now()),now())+(%s||' days')::interval, status='active' WHERE id=%s""",(d,d,uid)); return "extend+%dd"%d
    elif t=="trial_days":
        d=int(act.get("days") or 0)
        if d>0:
            cur.execute("UPDATE users SET trial_until=GREATEST(COALESCE(trial_until,now()),now())+(%s||' days')::interval WHERE id=%s",(d,uid))
            R.set(RNS+"force_demo:"+username,"1"); return "trial+%dd"%d
    elif t=="coupon":
        # 发一张该用户专属券(code=前缀+随机, target_username=用户)
        code=(act.get("code_prefix") or "CAMP")+"-"+_sx.token_hex(3).upper()
        vd=int(act.get("valid_days") or 30)
        cur.execute("""INSERT INTO coupons(code,name,kind,value,applies_to,max_discount,total_qty,per_user_limit,target_username,valid_until,enabled)
                       VALUES(%s,%s,%s,%s,%s,%s,1,%s,%s,now()+(%s||' days')::interval,true)""",
                    (code, act.get("name") or "活动专属券", act.get("kind") or "percent", float(act.get("value") or 0),
                     act.get("applies_to") or "any", float(act.get("max_discount") or 0), int(act.get("per_user_limit") or 1), username, vd))
        return "coupon:"+code
    return ""
def _fire_campaigns(cur, event, uid, username, ctx=None):
    """触发某事件的所有匹配活动(与调用方同事务)。cur 必须 RealDictCursor。
       逐活动: 校验开关/有效期/总量/逐用户限次/条件 → 执行动作 → 记 campaign_grants + fired_count+1。
       失败单个活动不阻断其他(try 包裹), 但动作内 _points_add 等异常会被吞以保主流程。"""
    ctx=ctx or {}
    try:
        cur.execute("""SELECT id,name,category,cond,actions,per_user_limit,total_limit,fired_count
                       FROM campaigns WHERE enabled=true AND event=%s
                       AND (valid_from IS NULL OR valid_from<=now()) AND (valid_until IS NULL OR valid_until>now())
                       ORDER BY priority DESC, id""",(event,))
        camps=cur.fetchall()
    except Exception as e:
        print("fire_campaigns load err",e); return []
    fired=[]
    for cp in camps:
        try:
            if int(cp["total_limit"] or 0)>0 and int(cp["fired_count"] or 0)>=int(cp["total_limit"]): continue
            if int(cp["per_user_limit"] or 0)>0:
                cur.execute("SELECT count(*) n FROM campaign_grants WHERE campaign_id=%s AND username=%s",(cp["id"],username))
                if cur.fetchone()["n"]>=int(cp["per_user_limit"]): continue
            if not _camp_cond_ok(cp["cond"] or {}, ctx): continue
            results=[]
            for act in (cp["actions"] or []):
                act=dict(act); act["_cname"]=cp["name"]
                r=_camp_do_action(cur, act, uid, username, ctx, cp["id"])
                if r: results.append(r)
            if results:
                cur.execute("INSERT INTO campaign_grants(campaign_id,username,event,detail) VALUES(%s,%s,%s,%s)",
                            (cp["id"],username,event,json.dumps({"results":results,"ctx":{k:ctx.get(k) for k in ('amount','months','kind')}})))
                cur.execute("UPDATE campaigns SET fired_count=COALESCE(fired_count,0)+1 WHERE id=%s",(cp["id"],))
                fired.append({"campaign":cp["name"],"results":results})
        except Exception as e:
            print("campaign fire err (%s):"%cp.get("name"),e)
    return fired

# 员工"达标"自动发绩效积分(与用户对冲积分隔离; 挂在归因事件, 配置存 channels.json staff_perf 段)
# 默认: 每有效试用 +10 / 每首单付费 +50 / 每 100USDT 订单额 +20(即 per_usdt=0.2)
def _staff_perf_auto(cur, staff_code, event, amount=0):
    if not staff_code: return
    try:
        cfg=_chcfg_load().get("staff_perf",{})
        if cfg.get("enabled") is False: return   # 缺省启用(未配也发默认); 显式 false 才关
        trial_pt=int(cfg.get("trial", 10)); first_pt=int(cfg.get("first_paid", 50)); per_usdt=float(cfg.get("per_usdt", 0.2))
    except Exception:
        trial_pt,first_pt,per_usdt=10,50,0.2
    delta=0; reason=""
    if event=="trial_activate": delta=trial_pt; reason="员工达标:有效试用"
    elif event=="first_paid": delta=first_pt; reason="员工达标:首单付费"
    elif event=="paid": delta=int(round(float(amount or 0)*per_usdt)); reason="员工达标:订单额提成分"
    if delta>0:
        try: _perf_add(cur, staff_code, delta, reason, "auto", event, "system")
        except Exception as pe: print("staff_perf_auto err",pe)

@app.post("/api/iap/purchase")
def iap_purchase(r:PurchaseReq):
    """用户自助内购: 校验密钥→建订单(pending 待财务核对)→授商品权益→计佣。支付走演示(与现充值一致)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,status FROM users WHERE license_key=%s",(r.license_key,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    if u["status"] in ("banned","disabled"): c.close(); raise HTTPException(403,"账户不可用")
    cur.execute("SELECT * FROM iap_products WHERE key=%s AND enabled=true",(r.product_key,)); p=cur.fetchone()
    if not p: c.close(); raise HTTPException(404,"商品不存在/已下架")
    p=_sellable_iap_product(p)
    if not p: c.close(); raise HTTPException(404,"商品不存在/已下架")
    uid=u["id"]; grants=p["grants"]; amount=float(p["price"] or 0); dur=p["duration_days"]
    exp = datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=dur) if dur and dur>0 else None
    for fk,val in grants.items():
        cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,expire_at,updated_at)
                       VALUES(%s,%s,%s,'iap',%s,now()) ON CONFLICT (user_id,feature_key) DO UPDATE SET
                       value=EXCLUDED.value,source='iap',expire_at=EXCLUDED.expire_at,updated_at=now()""",(uid,fk,str(val),exp))
    cur.execute("INSERT INTO iap_orders(user_id,product_key,amount,unit,status,operator,reconcile_status,paid_at) VALUES(%s,%s,%s,%s,'paid','self','pending',now()) RETURNING id",
                (uid,r.product_key,amount,p["unit"]))
    oid=cur.fetchone()["id"]
    try: _calc_commissions(cur, oid, "iap", uid, amount)
    except Exception as ce: print("commission err",ce)
    c.close()
    _audit(u["username"],"self","iap_purchase",{"product":r.product_key,"amount":amount},DEMO_MODE,"paid")
    return {"ok":True,"product":p["name"],"granted":list(grants.keys()),"order_id":oid,"amount":amount,"demo":DEMO_MODE}

# ---- 统一下单端点(内购/包月/充值 × 链上TRC20/余额) ----
SUB_PRICES={1:100.0, 3:270.0, 12:960.0}   # 月卡/季卡/年卡(与前端 plans 对齐)
class OrderSubmitReq(BaseModel):
    license_key:str; kind:str                     # iap / subscription / recharge
    product_key:str=""; months:int=0; amount:float=0
    pay_method:str="onchain"                        # onchain(TRC20 到账后财务核对) / balance(扣余额即时)
    tx_hash:str=""; coupon_code:str=""              # 折扣券(仅 iap/subscription; 服务端权威计算)
    points_use:int=0                                # 积分抵现(100分=1USDT, 单单≤30%; 抵现部分不计佣不返积分)
@app.post("/api/order/submit")
def order_submit(r:OrderSubmitReq):
    """用户自助下单统一入口。三类:
       - iap: 按 product_key 授商品权益
       - subscription: 按 months 延长 paid_until/expire_at(价用服务端 SUB_PRICES, 防篡改)
       - recharge: 充值到 users.balance(仅 onchain)
       支付方式: onchain=建 pending 订单待财务核对(演示环境即时生效); balance=扣余额即时确认。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,status,balance,points FROM users WHERE license_key=%s",(r.license_key,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    if u["status"] in ("banned","disabled"): c.close(); raise HTTPException(403,"账户不可用")
    uid=u["id"]; bal=float(u["balance"] or 0); user_pts=int(u["points"] or 0); prod=None; grants={}; amount=0.0; months=0; unit="USDT"
    # 1) 计价 + 校验
    if r.kind=="iap":
        cur.execute("SELECT * FROM iap_products WHERE key=%s AND enabled=true",(r.product_key,)); prod=cur.fetchone()
        if not prod: c.close(); raise HTTPException(404,"商品不存在/已下架")
        prod=_sellable_iap_product(prod)
        if not prod: c.close(); raise HTTPException(404,"商品不存在/已下架")
        grants=prod["grants"]; amount=float(prod["price"] or 0); unit=prod["unit"] or "USDT"
    elif r.kind=="subscription":
        months=int(r.months or 0)
        if months not in SUB_PRICES: c.close(); raise HTTPException(400,"套餐月数非法(仅 1/3/12)")
        amount=SUB_PRICES[months]
    elif r.kind=="recharge":
        amount=round(float(r.amount or 0),2)
        if amount<=0: c.close(); raise HTTPException(400,"充值金额需>0")
        if r.pay_method=="balance": c.close(); raise HTTPException(400,"充值不支持用余额支付")
    else:
        c.close(); raise HTTPException(400,"未知订单类型: %s"%r.kind)
    # 1b) 折扣券(仅 iap/subscription; 服务端权威, 减免后为实付 amount, 佣金/积分按实付算)
    gross=amount; discount=0.0; cp_used=None
    if r.coupon_code and r.kind in ("iap","subscription"):
        try:
            discount, cp_used = _coupon_eval(cur, r.coupon_code, uid, u["username"], r.kind, amount)
            amount=round(amount-discount, 2)
        except HTTPException: c.close(); raise
    # 1c) 积分抵现(仅 iap/subscription; 100分=1USDT, 单单≤券后金额30%; 抵现部分不计佣不返积分, 防刷)
    POINTS_PER_USDT_CASH=100    # 抵现比: 100 积分抵 1 USDT
    pts_use=0; pts_discount=0.0
    if int(r.points_use or 0)>0 and r.kind in ("iap","subscription"):
        want=int(r.points_use)
        if want>user_pts: c.close(); raise HTTPException(400,"积分不足(当前 %d)"%user_pts)
        cap_usdt=round(amount*0.30, 2)                       # 30% 上限(基于券后金额)
        max_pts_by_cap=int(cap_usdt*POINTS_PER_USDT_CASH)
        max_pts_by_amt=int(amount*POINTS_PER_USDT_CASH)      # 不超过订单额本身
        pts_use=min(want, max_pts_by_cap, max_pts_by_amt)
        pts_use=(pts_use//POINTS_PER_USDT_CASH)*POINTS_PER_USDT_CASH   # 取整到 100 的倍数(整 USDT)
        if pts_use>0:
            pts_discount=round(pts_use/POINTS_PER_USDT_CASH, 2)
            amount=round(amount-pts_discount, 2)
    # 2) 支付方式
    if r.pay_method=="balance":
        if bal < amount: c.close(); raise HTTPException(400,"余额不足(当前 %.2f, 需 %.2f)"%(bal,amount))
        cur.execute("UPDATE users SET balance=balance-%s WHERE id=%s",(amount,uid))
        recon="confirmed"; ostatus="paid"   # 余额已是平台内资金, 直接确认
    else:
        recon="pending"; ostatus="paid"      # 链上到账后财务核对
    # 3) 履约(授权益 / 延期 / 加余额)
    exp=None
    if r.kind=="iap":
        dur=prod["duration_days"]; exp=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=dur) if dur and dur>0 else None
        for fk,val in grants.items():
            cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,expire_at,updated_at)
                           VALUES(%s,%s,%s,'iap',%s,now()) ON CONFLICT (user_id,feature_key) DO UPDATE SET
                           value=EXCLUDED.value,source='iap',expire_at=EXCLUDED.expire_at,updated_at=now()""",(uid,fk,str(val),exp))
    elif r.kind=="subscription":
        cur.execute("""UPDATE users SET paid_until=GREATEST(COALESCE(paid_until,now()),now())+(%s||' months')::interval,
                       expire_at=GREATEST(COALESCE(paid_until,now()),now())+(%s||' months')::interval, status='active' WHERE id=%s""",(months,months,uid))
    elif r.kind=="recharge":
        cur.execute("UPDATE users SET balance=balance+%s,total_recharge=COALESCE(total_recharge,0)+%s WHERE id=%s",(amount,amount,uid))
    # 4) 落订单(统一入 iap_orders, 供 admin/orders 财务核对); 带员工归因 staff_code
    cur.execute("SELECT staff_code FROM users WHERE id=%s",(uid,)); _sc=(cur.fetchone() or {}).get("staff_code")
    pkey = r.product_key if r.kind=="iap" else ("_sub_%dm"%months if r.kind=="subscription" else "_recharge")
    cur.execute("""INSERT INTO iap_orders(user_id,product_key,amount,unit,status,operator,reconcile_status,kind,pay_method,tx_hash,months,staff_code,points_used,points_discount,paid_at)
                   VALUES(%s,%s,%s,%s,%s,'self',%s,%s,%s,%s,%s,%s,%s,%s,now()) RETURNING id""",
                (uid,pkey,amount,unit,ostatus,recon,r.kind,r.pay_method,r.tx_hash or None,months,_sc,pts_use,pts_discount))
    oid=cur.fetchone()["id"]
    # 4a) 积分抵现扣分(同事务; _points_add 再锁行校验余额不可为负, 双保险)
    if pts_use>0:
        try: _points_add(cur, uid, -pts_use, "积分抵现(%s)"%r.kind, "order_pay", oid, "self")
        except HTTPException: c.close(); raise
    # 4b) 券核销(下单成功后记 redemption + 全局用量+1; 与订单同事务)
    if cp_used and discount>0:
        cur.execute("INSERT INTO coupon_redemptions(code,user_id,order_id,discount) VALUES(%s,%s,%s,%s)",
                    (cp_used["code"],uid,oid,discount))
        cur.execute("UPDATE coupons SET used_qty=COALESCE(used_qty,0)+1 WHERE code=%s",(cp_used["code"],))
    # 计佣(充值不计佣, 内购/订阅计; 按券后+抵现后实付 amount 计 → 抵现部分自动不计佣)
    if r.kind in ("iap","subscription"):
        try: _calc_commissions(cur, oid, r.kind, uid, amount)
        except Exception as ce: print("commission err",ce)
    # 积分返 + 成长值(内购/订阅按实付 ×10; 充值不返积分不计成长, 与不计佣一致)
    pts_gained=0
    if r.kind in ("iap","subscription") and amount>0:
        try:
            pts_gained=_points_add(cur, uid, int(round(amount*POINTS_PER_USDT)),
                                   "消费返积分(%s)"%r.kind, "order", oid, "self")
            _grow_add(cur, uid, amount)
        except Exception as pe: print("points err",pe)
    # 邀请人首付返积分(被邀人首次付费, 返实付10%积分给邀请人; reward_paid_done 防重)
    if r.kind in ("iap","subscription") and amount>0:
        try:
            cur.execute("SELECT inviter,reward_paid_done FROM invites WHERE invitee=%s",(u["username"],)); iv=cur.fetchone()
            if iv and iv["inviter"] and not iv["reward_paid_done"]:
                inv_uid=_uid(iv["inviter"])
                if inv_uid:
                    _points_add(cur, inv_uid, int(round(amount*INVITE_REWARD_PAID_RATE*POINTS_PER_USDT)),
                                "邀请好友首付返积分(%s)"%u["username"], "invite_paid", oid, "self")
                    cur.execute("UPDATE invites SET reward_paid_done=true,stage='paid' WHERE invitee=%s",(u["username"],))
        except Exception as pe: print("invite paid reward err",pe)
    # 活动引擎: paid/first_paid(内购/订阅) 或 recharge。first_paid=该用户此前无 paid 的内购/订阅单
    # + 连续续费: renewal_streak 事件(近90天订阅单数, ctx.streak); 员工绩效自动发放(达标)
    try:
        ectx={"amount":amount,"months":months,"kind":r.kind}
        if r.kind in ("iap","subscription"):
            cur.execute("SELECT count(*) n FROM iap_orders WHERE user_id=%s AND status='paid' AND kind IN ('iap','subscription') AND id<>%s",(uid,oid))
            is_first=(cur.fetchone()["n"]==0); ectx["first_paid"]=is_first
            _fire_campaigns(cur, "paid", uid, u["username"], ectx)
            if is_first: _fire_campaigns(cur, "first_paid", uid, u["username"], ectx)
            # 连续续费: 近90天该用户订阅单数(含本单), 触发 renewal_streak(cond streak_min 判达标)
            if r.kind=="subscription":
                cur.execute("SELECT count(*) n FROM iap_orders WHERE user_id=%s AND status='paid' AND kind='subscription' AND paid_at>=now()-interval '90 days'",(uid,))
                _fire_campaigns(cur, "renewal_streak", uid, u["username"], {**ectx,"streak":cur.fetchone()["n"]})
            # 员工绩效自动发放(订单额提成分 + 首单)
            if _sc:
                _staff_perf_auto(cur, _sc, "paid", amount)
                if is_first: _staff_perf_auto(cur, _sc, "first_paid")
        elif r.kind=="recharge":
            _fire_campaigns(cur, "recharge", uid, u["username"], ectx)
    except Exception as ce: print("camp order err",ce)
    cur.execute("SELECT balance,points FROM users WHERE id=%s",(uid,)); _row=cur.fetchone()
    newbal=float(_row["balance"] or 0); newpts=int(_row["points"] or 0)
    c.close()
    _audit(u["username"],"self","order_submit",{"kind":r.kind,"gross":gross,"coupon_disc":discount,"pts_use":pts_use,"pts_disc":pts_discount,"amount":amount,"coupon":(cp_used["code"] if cp_used else None),"pay":r.pay_method,"tx":bool(r.tx_hash),"pts":pts_gained},DEMO_MODE,recon)
    return {"ok":True,"order_id":oid,"kind":r.kind,"gross":round(gross,2),"discount":round(discount,2),
            "points_used":pts_use,"points_discount":round(pts_discount,2),"amount":amount,"pay_method":r.pay_method,
            "reconcile_status":recon,"granted":list(grants.keys()),"balance":newbal,"points":newpts,"demo":DEMO_MODE,
            "expire_at":str(exp) if exp else None}

# ================= 折扣券(第二阶段; 服务端权威计算, 与积分/佣金链路解耦) =================
def _coupon_eval(cur, code, uid, username, kind, amount):
    """校验券并算折扣(不落用量, 供预览与下单复用)。返回 (discount, coupon_row) 或 raise HTTPException。
       cur 必须 RealDictCursor。规则: 启用/有效期/适用类型/最低额/专属用户/全局余量/逐用户次数。"""
    cur.execute("SELECT * FROM coupons WHERE code=%s",(code,)); cp=cur.fetchone()
    if not cp or not cp["enabled"]: raise HTTPException(400,"券不存在或已停用")
    now=datetime.datetime.now(datetime.timezone.utc)
    if cp["valid_from"] and now<cp["valid_from"]: raise HTTPException(400,"券未到生效时间")
    if cp["valid_until"] and now>cp["valid_until"]: raise HTTPException(400,"券已过期")
    at=cp["applies_to"] or "any"
    if at!="any" and at!=kind: raise HTTPException(400,"该券仅适用于 %s 订单"%at)
    if cp["target_username"] and cp["target_username"]!=username: raise HTTPException(400,"该券为专属券, 不可用")
    if float(cp["min_amount"] or 0)>0 and amount<float(cp["min_amount"]): raise HTTPException(400,"未达最低金额 %.2f"%float(cp["min_amount"]))
    if int(cp["total_qty"] or 0)>0 and int(cp["used_qty"] or 0)>=int(cp["total_qty"]): raise HTTPException(400,"券已被领完")
    cur.execute("SELECT count(*) n FROM coupon_redemptions WHERE code=%s AND user_id=%s",(code,uid))
    used_by_user=cur.fetchone()["n"]
    if int(cp["per_user_limit"] or 1)>0 and used_by_user>=int(cp["per_user_limit"]): raise HTTPException(400,"该券你已用过")
    # 折扣计算
    if cp["kind"]=="percent":
        disc=round(amount*float(cp["value"])/100.0, 2)
    else:
        disc=round(float(cp["value"]), 2)
    md=float(cp["max_discount"] or 0)
    if md>0: disc=min(disc, md)
    disc=min(disc, round(amount,2))   # 折扣不超过订单额
    if disc<=0: raise HTTPException(400,"券折扣为 0")
    return disc, cp
class CouponPreviewReq(BaseModel):
    license_key:str=""; code:str; kind:str; amount:float=0; months:int=0; product_key:str=""
@app.post("/api/coupon/preview")
def coupon_preview(r:CouponPreviewReq, x_license: str = Header(default="")):
    """下单前预览券折扣(不核销)。amount 缺省时按 kind 服务端算(防前端传假价)。"""
    lk=x_license or r.license_key
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username FROM users WHERE license_key=%s",(lk,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    amt=float(r.amount or 0)
    if r.kind=="subscription": amt=SUB_PRICES.get(int(r.months or 0),0)
    elif r.kind=="iap":
        cur.execute("SELECT key,price,grants FROM iap_products WHERE key=%s AND enabled=true",(r.product_key,)); p=cur.fetchone()
        p=_sellable_iap_product(p)
        if not p: c.close(); raise HTTPException(404,"商品不存在/已下架")
        amt=float(p["price"] or 0)
    try:
        disc,cp=_coupon_eval(cur, r.code, u["id"], u["username"], r.kind, amt)
    except HTTPException: c.close(); raise
    c.close()
    return {"ok":True,"code":r.code,"name":cp["name"],"amount":round(amt,2),"discount":disc,"payable":round(amt-disc,2)}
@app.get("/api/coupon/mine/{username}", dependencies=[Depends(require_subject)])
def coupon_mine(username:str):
    """用户可用券(通用启用券 + 该用户专属券; 排除已达用量的; 简单列出, 前端下单选)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM users WHERE username=%s",(username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    uid=u["id"]; now=datetime.datetime.now(datetime.timezone.utc)
    cur.execute("""SELECT code,name,kind,value,applies_to,min_amount,max_discount,valid_until,target_username,total_qty,used_qty,per_user_limit
                   FROM coupons WHERE enabled=true AND (target_username IS NULL OR target_username=%s)
                   AND (valid_until IS NULL OR valid_until>now()) ORDER BY created_at DESC""",(username,))
    out=[]
    for cp in cur.fetchall():
        if int(cp["total_qty"] or 0)>0 and int(cp["used_qty"] or 0)>=int(cp["total_qty"]): continue
        cur.execute("SELECT count(*) n FROM coupon_redemptions WHERE code=%s AND user_id=%s",(cp["code"],uid))
        if int(cp["per_user_limit"] or 1)>0 and cur.fetchone()["n"]>=int(cp["per_user_limit"]): continue
        d=dict(cp); d.pop("total_qty",None); d.pop("used_qty",None); out.append(d)
    c.close()
    return {"coupons":out}

# ================= 好友邀请(第三阶段; 用户侧) =================
@app.get("/api/invite/mine/{username}", dependencies=[Depends(require_subject)])
def invite_mine(username:str):
    """我的邀请: 邀请链接 + 已邀好友列表(阶段/奖励状态) + 累计邀请奖励积分。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM users WHERE username=%s",(username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    cur.execute("SELECT invitee,stage,reward_trial_done,reward_paid_done,created_at FROM invites WHERE inviter=%s ORDER BY id DESC LIMIT 100",(username,))
    rows=[dict(x) for x in cur.fetchall()]
    cur.execute("SELECT COALESCE(SUM(delta),0) s FROM points_ledger WHERE user_id=%s AND ref_type IN ('invite_trial','invite_paid')",(u["id"],))
    earned=int(cur.fetchone()["s"] or 0)
    c.close()
    n_trial=sum(1 for x in rows if x["reward_trial_done"]); n_paid=sum(1 for x in rows if x["reward_paid_done"])
    return {"username":username,"invite_link":"https://qh.hustle2026.xyz/?inviter="+username,
            "invites":rows,"total":len(rows),"trial_converted":n_trial,"paid_converted":n_paid,"points_earned":earned}

@app.get("/api/user/wallet/{username}", dependencies=[Depends(require_subject)])
def user_wallet(username:str):
    """用户余额 + 近期订单(用户端支付页/账户页用)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT balance,total_recharge FROM users WHERE username=%s",(username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    c.close()
    return {"balance":round(float(u["balance"] or 0),2),"total_recharge":round(float(u["total_recharge"] or 0),2)}

# ================= 会员积分: 用户侧端点(余额/签到/兑换; 走 license 鉴权) =================
# 兑换目录(第一阶段, 全对现有 iap_features 权益; 花积分→写 entitlements 带 expire_at)
# key -> {name, cost(积分), feature_key, value, days(权益有效天), max_per_day(可选防刷)}
_REDEEM_CATALOG = {
    "ai_1":        {"name":"AI套利分析 1 次",  "cost":10,  "feature_key":"ai_arb",       "value":"true", "days":1},
    "pairs3_1d":   {"name":"3对账户日权",       "cost":80,  "feature_key":"max_pairs",     "value":"3",    "days":1},
    "mobile_7d":   {"name":"移动端权限周卡",    "cost":200, "feature_key":"mobile_access", "value":"true", "days":7},
    "trial_7d":    {"name":"试用延长 7 天(演示)","cost":100, "feature_key":"_trial_ext",    "value":"7",    "days":0},
}
@app.get("/api/points/catalog")
def points_catalog():
    """兑换目录(公开只读, 用户端渲染)。"""
    return {"catalog":[{"key":k,**{x:v[x] for x in ("name","cost")}} for k,v in _REDEEM_CATALOG.items()],
            "points_per_usdt":POINTS_PER_USDT}
@app.get("/api/points/{username}", dependencies=[Depends(require_subject)])
def points_get(username:str):
    """用户积分余额 + 会员等级 + 成长值 + 近期流水(用户端积分页)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,points,growth_value,paid_until,plan,total_recharge,trial_until FROM users WHERE username=%s",(username,))
    u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    cur.execute("SELECT delta,balance_after,reason,ref_type,created_at FROM points_ledger WHERE user_id=%s ORDER BY id DESC LIMIT 30",(u["id"],))
    led=[dict(x) for x in cur.fetchall()]; c.close()
    ml=_member_level(u)
    return {"username":username,"points":int(u["points"] or 0),"growth_value":int(u["growth_value"] or 0),
            "level":ml["level"],"level_name":ml["name"],"level_source":ml["source"],
            "paid_until":(str(u["paid_until"])[:10] if u.get("paid_until") else None),
            "trial_until":(str(u["trial_until"])[:10] if u.get("trial_until") else None),"ledger":led}
class CheckinReq(BaseModel):
    license_key:str=""
@app.post("/api/points/checkin")
def points_checkin(r:CheckinReq, x_license: str = Header(default="")):
    """每日签到 +5; 连续 7 天当天额外 +30。连签计数走 Redis(当日键 + 连签计数键)。"""
    lk=x_license or r.license_key
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,status FROM users WHERE license_key=%s",(lk,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    if u["status"] in ("banned","disabled"): c.close(); raise HTTPException(403,"账户不可用")
    uid=u["id"]; today=datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    dk=RNS+"checkin:%s:%s"%(uid,today)
    if R.get(dk): c.close(); raise HTTPException(400,"今日已签到")
    # 连签: streak 键(2天过期, 隔天断签归1)
    sk=RNS+"checkin_streak:%s"%uid
    try:
        prev=int(R.get(sk) or 0)
    except Exception: prev=0
    streak=prev+1
    R.setex(dk, 172800, "1")           # 当日已签(48h TTL 足够跨日)
    R.setex(sk, 172800, str(streak))   # 连签计数(隔天不续则失效归零)
    gained=5
    bonus = 30 if (streak%7==0) else 0
    try:
        new_bal=_points_add(cur, uid, gained+bonus, "每日签到" + ("(连签7天+30)" if bonus else ""), "checkin", today, "self")
        # 活动引擎: checkin 事件(如连签额外奖/活动加码; ctx 带连签天数)
        try: _fire_campaigns(cur, "checkin", uid, u["username"], {"streak":streak})
        except Exception as ce: print("camp checkin err",ce)
    except Exception as pe:
        c.close(); raise HTTPException(500,"签到失败: %s"%pe)
    c.close()
    return {"ok":True,"gained":gained+bonus,"streak":streak,"bonus":bonus,"points":new_bal}
class RedeemReq(BaseModel):
    license_key:str=""; item:str
@app.post("/api/points/redeem")
def points_redeem(r:RedeemReq, x_license: str = Header(default="")):
    """积分兑换权益: 扣积分 + 写 entitlements(带 expire_at), 全程同事务、余额不可为负。
       _trial_ext 特例: 不写权益, 延长 trial_until N 天。"""
    lk=x_license or r.license_key
    item=_REDEEM_CATALOG.get(r.item)
    if not item: raise HTTPException(400,"未知兑换项: %s"%r.item)
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,status FROM users WHERE license_key=%s",(lk,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    if u["status"] in ("banned","disabled"): c.close(); raise HTTPException(403,"账户不可用")
    uid=u["id"]
    try:
        new_bal=_points_add(cur, uid, -int(item["cost"]), "兑换:"+item["name"], "redeem", r.item, "self")  # 余额不足会抛400
        fk=item["feature_key"]
        if fk=="_trial_ext":
            days=int(item["value"])
            cur.execute("""UPDATE users SET trial_until=GREATEST(COALESCE(trial_until,now()),now())+(%s||' days')::interval WHERE id=%s""",(days,uid))
            R.set(RNS+"force_demo:"+u["username"],"1")   # 延长的是演示试用
        else:
            days=int(item.get("days") or 0)
            exp=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)) if days>0 else None
            cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,expire_at,updated_at)
                           VALUES(%s,%s,%s,'points',%s,now()) ON CONFLICT (user_id,feature_key) DO UPDATE SET
                           value=EXCLUDED.value,source='points',expire_at=EXCLUDED.expire_at,updated_at=now()""",
                        (uid,fk,item["value"],exp))
    except HTTPException:
        c.close(); raise
    except Exception as e:
        c.close(); raise HTTPException(500,"兑换失败: %s"%e)
    c.close()
    _audit(u["username"],"self","points_redeem",{"item":r.item,"cost":item["cost"]},DEMO_MODE,"redeemed")
    return {"ok":True,"item":item["name"],"cost":item["cost"],"points":new_bal}

# ---- 用户自助: 修改昵称(显示名) + 消费记录 ----
# 设计: username 是全局唯一登录身份+Redis/DB 键(qh:slot_cfg:{user} 等), 不可改;
#       nickname 是可改的显示名, 面板/菜单展示优先用之, 空则回落 username。
class NickReq(BaseModel):
    license_key: str
    nickname: str
@app.post("/api/user/nickname")
def set_nickname(r:NickReq, x_license: str = Header(default="")):
    require_license(x_license or r.license_key)   # 运行时校验(require_license 定义在后, 不能用 import 期 Depends)
    nn=(r.nickname or "").strip()
    if not nn: raise HTTPException(400,"昵称不能为空")
    if len(nn)>32: raise HTTPException(400,"昵称过长(≤32)")
    c=db(); cur=c.cursor()
    cur.execute("UPDATE users SET nickname=%s WHERE license_key=%s RETURNING username",(nn,r.license_key))
    row=cur.fetchone(); c.close()
    if not row: raise HTTPException(404,"用户不存在")
    return {"ok":True,"username":row[0],"nickname":nn}

@app.get("/api/user/orders/{username}", dependencies=[Depends(require_subject)])
def user_orders(username:str, limit:int=100):
    """用户消费记录: iap_orders 联商品名, 按 paid_at 最近→最早, 同日按金额高→低。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id FROM users WHERE username=%s",(username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    cur.execute("""SELECT o.id, o.product_key, COALESCE(p.name,o.product_key,o.kind) AS name,
                          o.amount, o.unit, o.status, o.kind, o.pay_method, o.months,
                          o.reconcile_status, o.paid_at
                   FROM iap_orders o LEFT JOIN iap_products p ON p.key=o.product_key
                   WHERE o.user_id=%s
                   ORDER BY o.paid_at DESC NULLS LAST, o.amount DESC
                   LIMIT %s""",(u["id"],max(1,min(limit,500))))
    rows=cur.fetchall(); c.close()
    out=[]
    for r in rows:
        out.append({"id":r["id"],"name":r["name"],"product_key":r["product_key"],
                    "amount":round(float(r["amount"] or 0),2),"unit":r["unit"] or "USDT",
                    "status":r["status"],"kind":r["kind"],"pay_method":r["pay_method"],
                    "months":r["months"],"reconcile_status":r["reconcile_status"],
                    "paid_at":r["paid_at"].isoformat() if r["paid_at"] else None})
    return {"username":username,"orders":out}

@app.get("/api/params/{username}", dependencies=[Depends(require_subject)])
def params(username:str):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT pt.* FROM param_templates pt JOIN users u ON u.id=pt.user_id
                   WHERE u.username=%s""",(username,))
    rows=cur.fetchall(); c.close()
    return {"username":username,"params":[dict(r) for r in rows]}

# ---- 交易记录入库（凭证不入，仅成交）----
class Deal(BaseModel):
    username:str; ticket:str; symbol:str; side:str
    lots:float; price:float; profit:float=0.0; platform:str="MT5"
@app.post("/api/deals/ingest")
def ingest(d:Deal):
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s",(d.username,))
    u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    cur.execute("""INSERT INTO deals(user_id,ticket,symbol,side,lots,price,profit,platform)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (u[0],d.ticket,d.symbol,d.side,d.lots,d.price,d.profit,d.platform))
    c.close()
    R.incr(RNS+"deals:count")
    return {"ok":True,"ingested":d.ticket}

@app.get("/api/deals/{username}", dependencies=[Depends(require_subject)])
def deals(username:str, limit:int=50):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT d.ticket,d.symbol,d.side,d.lots,d.price,d.profit,d.platform,d.dealt_at
                   FROM deals d JOIN users u ON u.id=d.user_id
                   WHERE u.username=%s ORDER BY d.dealt_at DESC LIMIT %s""",(username,limit))
    rows=cur.fetchall(); c.close()
    return {"username":username,"deals":[dict(r) for r in rows]}

# ================= 连接方式路由 (P0: Bridge / Api2Trade) =================
from connector import get_connector, build_connector
import time as _t_conn
# active_mode 持久在 Redis(qh:conn:active_mode; 默认 bridge, 重启不丢); 连接器按方式懒建+缓存
_CONN_CACHE={}                       # {mode: connector}
_CONN_MODE_CACHE={"mode":None,"ts":0.0}
def _active_mode():
    """当前生效连接方式。api/云端连接已彻底移除, 执行链路恒 bridge(缓存里若残留 api 也不再采信)。"""
    return "bridge"
    now=_t_conn.time()
    if _CONN_MODE_CACHE["mode"] and (now-_CONN_MODE_CACHE["ts"])<15:
        return _CONN_MODE_CACHE["mode"]
    try: m=R.get(RNS+"conn:active_mode") or "bridge"
    except Exception: m="bridge"
    if m not in ("bridge","api"): m="bridge"
    _CONN_MODE_CACHE["mode"]=m; _CONN_MODE_CACHE["ts"]=now
    return m
def _active_connector():
    m=_active_mode()
    c=_CONN_CACHE.get(m)
    if c is None:
        c=build_connector(m); _CONN_CACHE[m]=c
    return c
def _conn_cache_bust():
    _CONN_MODE_CACHE["mode"]=None; _CONN_MODE_CACHE["ts"]=0.0
_READ_SRC_CACHE={"v":None,"ts":0.0}
def _read_source():
    """读取数据源: 'a2t'=纯云端(默认, 内网桥退出读取链路; 登记即有数据, 清除即停) / 'bridge'=回滚杆(桥优先+熔断回退云端)。
       Redis qh:conn:read_source 热切换, 15s 缓存, 无需重启。"""
    now=_t_conn.time()
    if _READ_SRC_CACHE["v"] and (now-_READ_SRC_CACHE["ts"])<15: return _READ_SRC_CACHE["v"]
    try: v=R.get(RNS+"conn:read_source") or "a2t"
    except Exception: v="a2t"
    if v not in ("a2t","bridge"): v="a2t"
    _READ_SRC_CACHE["v"]=v; _READ_SRC_CACHE["ts"]=now
    return v
def _raw_bridge():
    c=_CONN_CACHE.get("bridge")
    if c is None: c=build_connector("bridge"); _CONN_CACHE["bridge"]=c
    return c

# ---- A2T 动态读取腿: 按 mt_accounts 登记行(conn_mode=api 且有 UUID)实时构建云端读取腿 ----
# 用途: 行情 tick/账户/持仓/历史成交(过夜费/手续费)读取回退 —— 桥无该账户或桥挂时不断流。
# 与 FRA 静态代理不同: UUID 直接取自 DB 当前登记, 重注册换 UUID 后零配置自动跟随。
_A2T_LEG_CACHE={"ts":0.0,"legs":None,"rows":None}
def _a2t_read_legs():
    now=_t_conn.time()
    if _A2T_LEG_CACHE["legs"] is not None and (now-_A2T_LEG_CACHE["ts"])<30:
        return _A2T_LEG_CACHE["legs"]
    legs={"main":None,"hedge":None}; rowsmap={}
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT role,login,server,platform,user_id,api2trade_uuid,api2trade_config_id FROM mt_accounts WHERE role IN ('main','hedge') AND enabled AND conn_mode='api' AND api2trade_uuid<>'' ORDER BY id")
        rows=cur.fetchall(); c.close()
        from connector import Api2TradeLeg
        for r in rows:
            if legs.get(r["role"]) is not None: continue
            try:
                cfg=_a2t_cfg(r["api2trade_config_id"], need_active=False)
                is_pro=(cfg.get("plan") or "single")=="pro" and (cfg.get("basic_user") or "").strip()
                legs[r["role"]]=Api2TradeLeg(r["api2trade_uuid"], (cfg.get("api_key") or "").strip(),
                                             (cfg.get("base_url") or "").strip() or "https://api.api2trade.com",
                                             cfg["basic_user"].strip() if is_pro else "",
                                             (cfg.get("basic_pass") or "") if is_pro else "")
                rowsmap[r["role"]]=dict(r)
            except Exception: pass
    except Exception:
        return legs
    _A2T_LEG_CACHE["legs"]=legs; _A2T_LEG_CACHE["rows"]=rowsmap; _A2T_LEG_CACHE["ts"]=now
    return legs
def _a2t_leg_bust():
    _A2T_LEG_CACHE["legs"]=None; _A2T_LEG_CACHE["rows"]=None; _A2T_LEG_CACHE["ts"]=0.0
    try: _A2T_RC.clear()   # 读取微缓存一并清(防重注册后 ≤30s 读到旧 UUID 数据)
    except Exception: pass
    try: _USER_LEG_CACHE.clear()   # 多租户: 逐用户腿缓存一并清
    except Exception: pass

# ===== 多租户: 逐用户 A2T 读取腿(按该用户 mt_accounts 构建, 与全局 _a2t_read_legs 同构) =====
# 铁律: 单用户(hedge_pro)解析结果与全局 CONN 完全一致→零回归; 第二用户接入即获独立腿。
_USER_LEG_CACHE={}
def _a2t_read_legs_for(username):
    now=_t_conn.time(); e=_USER_LEG_CACHE.get(username)
    if e and (now-e["ts"])<30: return e["legs"]
    legs={"main":None,"hedge":None}; rowsmap={}
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT a.role,a.login,a.server,a.platform,a.user_id,a.api2trade_uuid,a.api2trade_config_id
                       FROM mt_accounts a JOIN users u ON u.id=a.user_id
                       WHERE u.username=%s AND a.role IN ('main','hedge') AND a.enabled AND a.conn_mode='api' AND a.api2trade_uuid<>'' ORDER BY a.id""",(username,))
        rows=cur.fetchall(); c.close()
        from connector import Api2TradeLeg
        for r in rows:
            if legs.get(r["role"]) is not None: continue
            try:
                cfg=_a2t_cfg(r["api2trade_config_id"], need_active=False)
                is_pro=(cfg.get("plan") or "single")=="pro" and (cfg.get("basic_user") or "").strip()
                legs[r["role"]]=Api2TradeLeg(r["api2trade_uuid"], (cfg.get("api_key") or "").strip(),
                                             (cfg.get("base_url") or "").strip() or "https://api.api2trade.com",
                                             cfg["basic_user"].strip() if is_pro else "",
                                             (cfg.get("basic_pass") or "") if is_pro else "")
                rowsmap[r["role"]]=dict(r)
            except Exception: pass
    except Exception:
        return legs
    _USER_LEG_CACHE[username]={"legs":legs,"rows":rowsmap,"ts":now}
    return legs
def _pair_uuids_for(username):
    """逐用户执行 UUID(FRA /pair 用)。缺 username→回落全局(仪表盘单用户路径向后兼容)。"""
    if not username: return _pair_uuids()
    _a2t_read_legs_for(username)
    rows=(_USER_LEG_CACHE.get(username) or {}).get("rows") or {}
    return ((rows.get("main") or {}).get("api2trade_uuid") or "", (rows.get("hedge") or {}).get("api2trade_uuid") or "")
def _user_conn(username):
    """逐用户读取连接器(Mt5BridgeConnector 形状: .main/.hedge + both_*)。
       a2t 两腿=该用户 FallbackLeg(role,username); 缺 username→仅供 admin/internal 使用全局 CONN。"""
    if not username: return CONN
    # A user connector is always scoped.  A configured bridge is preferred;
    # otherwise strict fallback legs can only read that user's A2T rows.
    bridge=_user_bridge_conn(username)
    if bridge is not None: return bridge
    import connector as _cn
    c=_cn.Mt5BridgeConnector.__new__(_cn.Mt5BridgeConnector)
    c.main=_FallbackLeg("main", username, strict=True); c.hedge=_FallbackLeg("hedge", username, strict=True)
    return c

def _strict_user_read_conn(username):
    """Return a connector that can only read *username*'s registered legs.

    User-facing read routes must never fall back to the process-global bridge:
    a missing bridge registration is an unavailable/empty account, not an
    invitation to display another account's state.  A configured per-user
    bridge remains the preferred source; otherwise the strict fallback legs
    may use that user's own A2T registration only.
    """
    username=str(username or "").strip()
    if not username:
        return None
    bridge=_user_bridge_conn(username)
    if bridge is not None:
        return bridge
    import connector as _cn
    c=_cn.Mt5BridgeConnector.__new__(_cn.Mt5BridgeConnector)
    c.main=_FallbackLeg("main", username, strict=True)
    c.hedge=_FallbackLeg("hedge", username, strict=True)
    return c

# Read-only history/statistics use the same strict routing contract.  Keep a
# separate name so execution call sites cannot accidentally opt into it.
def _strict_user_exec_conn(username):
    return _strict_user_read_conn(username)

# ---- P4a: per-user 桥读取连接器(消费已登记的 mt_accounts.bridge_url; 引擎原从不读此字段=串账根源) ----
# 桥基础设施已就位: 各用户账户的 MT 客户端各跑一桥端口(no123 8041/8042·hedge_pro 8061/8063·jj456 8065/8066),
# 但引擎 EXEC/CONN 从 env 读死全局桥→所有用户落 no123 账户。此处让读取按 bridge_url 路由到用户自己的桥。
_USER_BRIDGE_CACHE={}
_USER_POSITION_CACHE={}
_USER_POSITION_VERSIONS={}
_USER_REG_ROWS_CACHE={}

def _position_snapshot_stale(raw):
    if not isinstance(raw,dict): return False
    value=raw.get("snapshot_stale",False)
    if isinstance(value,str):
        return value.strip().lower() in ("1","true","yes","stale")
    return bool(value)

def _position_snapshot_version(raw):
    if not isinstance(raw,dict): return None
    try:
        boot=raw.get("snapshot_boot"); seq=raw.get("snapshot_seq")
        if boot is None or seq is None: return None
        if isinstance(boot,bool) or isinstance(seq,bool) or int(boot)<=0 or int(seq)<=0:
            return None
        ts=int(raw.get("snapshot_ts") or 0)
        ts_ms=raw.get("snapshot_ts_ms")
        ts_ms=int(ts_ms) if ts_ms is not None else ts*1000
        source=str(raw.get("snapshot_source") or "")
        return {"boot":int(boot),"seq":int(seq),
                "ts":ts,"ts_ms":ts_ms,
                "age_ms":float(raw.get("snapshot_age_ms") or 0),
                "stale":_position_snapshot_stale(raw),
                "source":source}
    except (TypeError,ValueError):
        return None

def _accept_position_snapshot_version(cache_key, raw):
    """Reject a snapshot that goes backwards within an EA boot or to an older boot."""
    version=_position_snapshot_version(raw)
    if version is None:
        return True,None
    previous=_USER_POSITION_VERSIONS.get(cache_key)
    if previous:
        if version["boot"]<previous["boot"]:
            return False,version
        if version["boot"]==previous["boot"] and version["seq"]<previous["seq"]:
            return False,version
    if (not previous or version["boot"]>previous["boot"] or
            version["seq"]>previous["seq"]):
        _USER_POSITION_VERSIONS[cache_key]=version
    return True,version
def _user_bridge_urls(username):
    """该用户 main/hedge 的 bridge_url(conn_mode=bridge 且 enabled)。返回 {role:url}, 空则 {}。"""
    rows=_reg_rows_for(username)
    return {
        role:str(row.get("bridge_url") or "").strip()
        for role,row in rows.items()
        if str(row.get("conn_mode") or "bridge")=="bridge" and
           str(row.get("bridge_url") or "").strip()
    }
def _user_bridge_conn(username):
    """Return the cached per-user bridge; account writes explicitly invalidate it."""
    ent=_USER_BRIDGE_CACHE.get(username)
    if ent:
        return ent[0]
    urls=_user_bridge_urls(username)
    if not urls.get("main") and not urls.get("hedge"): return None
    key=os.environ.get("QH_BRIDGE_KEY","")
    sig=(urls.get("main"),urls.get("hedge"))
    import connector as _cn
    conn=_cn._bridge_from_urls(urls.get("main") or "http://127.0.0.1:0", key, urls.get("hedge") or "", key)
    _USER_BRIDGE_CACHE[username]=(conn,sig,_t_conn.time()); return conn
def _exec_per_user_on():
    """执行层 per-user 路由开关(qh:exec:per_user, 默认 on; off=回滚全局 EXEC)。"""
    try: return (R.get(RNS+"exec:per_user") or "on")=="on"
    except Exception: return True
def _user_exec_conn(username):
    """执行连接器(P4b): per_user 开 + 用户有 bridge_url -> 用户自己的桥; 否则全局 EXEC。
       无 bridge_url 回落 EXEC, 但 owner gate(per_user) 会先拦, 不会误落别人桥。"""
    if not _exec_per_user_on() or not username: return EXEC
    c=_user_bridge_conn(username)
    return c if c is not None else EXEC
async def _leg_status_safe(leg):
    try: return await leg.status()
    except Exception as e: return {"connected":False,"error":e.__class__.__name__}
async def _leg_pos_safe(leg):
    try:
        p=await leg.positions(); return p.get("positions",p) if isinstance(p,dict) else (p or [])
    except Exception: return []

# A2T 响应归一化为桥形状(上层解析零改动)。MT4/MT5 两组字段差异大坑:
#   方向: MT5组=orderType("Buy"/"Balance") / MT4组=type("Sell"), Balance/出入金→-1 自动排除
#   时间: MT5组=closeTimestampUTC(毫秒) / MT4组该字段为 null, 真 UTC 纪元在 ex.close_time/ex.open_time,
#         ISO 字符串(closeTime)是经纪商本地墙钟(仅最后兜底, 精度够天数窗过滤)
def _a2t_norm_order(o, off=0):
    ot=str(o.get("orderType") or o.get("type") or "").lower()
    t=0 if "buy" in ot else (1 if "sell" in ot else -1)
    ex=o.get("ex") or {}
    def _iso_ep(v):
        try:
            if v and not str(v).startswith("1970"):
                return int(_dt.datetime.fromisoformat(str(v)).replace(tzinfo=_dt.timezone.utc).timestamp())
        except Exception: pass
        return 0
    if o.get("closeTimestampUTC"): close_ep=int(o["closeTimestampUTC"]/1000)
    elif ex.get("close_time"):     close_ep=int(ex["close_time"] or 0)
    else:                          close_ep=_iso_ep(o.get("closeTime"))
    if o.get("openTimestampUTC"): open_ep=int(o["openTimestampUTC"]/1000)
    elif ex.get("open_time"):     open_ep=int(ex["open_time"] or 0)
    else:                         open_ep=_iso_ep(o.get("openTime"))
    # 统一折回 UTC(off=该腿经纪商墙钟偏移, _a2t_leg_off 标定; A2T 所有时间字段均为墙钟纪元)
    if close_ep: close_ep-=off
    if open_ep:  open_ep-=off
    closed=bool(close_ep)
    px=float(o.get("closePrice") or 0) if closed else 0.0
    if not px: px=float(o.get("openPrice") or 0)
    return {"ticket":o.get("ticket"),"order":o.get("ticket"),"symbol":o.get("symbol"),"type":t,
            "entry":1 if closed else 0,   # 整单模型: 已平=出场行(paired_history 按平仓行配对)
            "volume":float(o.get("lots") or o.get("volume") or 0),
            "price":px,"price_open":o.get("openPrice"),"price_current":o.get("closePrice"),
            "profit":float(o.get("profit") or 0),"swap":float(o.get("swap") or 0),
            "commission":float(o.get("commission") or 0)+float(o.get("fee") or 0),
            "time":(close_ep or open_ep),"time_open":open_ep,"comment":o.get("comment") or ""}
async def _a2t_tick(leg, sym):
    """行情: 用 /GetQuoteMany(MT4/MT5 两组通用)。坑: /GetQuote 仅 MT5 组存在, MT4 账户 403 "path not valid";
       无效符号返回 201 INVALID_SYMBOL(非4xx, httpx 不抛)——须显式判列表。"""
    j=await leg._get("/GetQuoteMany", symbols=sym)
    lst=j if isinstance(j,list) else []
    if not lst:
        raise RuntimeError("a2t no quote for %s: %s"%(sym,str((j or {}).get("message") or "")[:60]))
    q=lst[0]
    t=0
    try:
        _ts=q.get("time")
        if isinstance(_ts,str): t=int(_dt.datetime.fromisoformat(_ts).replace(tzinfo=_dt.timezone.utc).timestamp())
    except Exception: pass
    return {"symbol":q.get("symbol") or sym,"bid":q.get("bid"),"ask":q.get("ask"),
            "last":q.get("last") or 0.0,"volume":q.get("volume") or 0,"time":t,"time_msc":t*1000,"src":"a2t"}
# 每腿经纪商墙钟偏移标定: A2T 的 ex.close_time/ISO 时间全是**各经纪商本地墙钟纪元非 UTC**
# (IC=+3h / Exness=0, 两腿相差 3h 曾致配对历史错配出假单腿)。用该腿行情时间与服务器 UTC 差值
# 推偏移(取整到 30min 吸收链路噪声), 10min 缓存, 换券商自动适应。
_A2T_OFF_CACHE={}
def _role_sym(role):
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT symbol,hedge_symbol FROM param_templates LIMIT 1")
        r=cur.fetchone(); c.close()
        if r:
            base=(r[0] or "XAUUSD")
            return base if role=="main" else (ENG.map_hedge_symbol(base, r[1]) or base)
    except Exception: pass
    return "XAUUSD"
async def _a2t_leg_off(role, leg):
    ent=_A2T_OFF_CACHE.get(role); now=_t_conn.time()
    if ent and (now-ent[1])<600: return ent[0]
    off=ent[0] if ent else 0
    try:
        tk=await _a2t_cached(("tick",role,"_off"),5.0,lambda: _a2t_tick(leg,_role_sym(role)))
        if tk.get("time"):
            off=int(round((float(tk["time"])-now)/1800.0)*1800)
    except Exception: pass
    _A2T_OFF_CACHE[role]=(off,now)
    return off
async def _a2t_positions(leg, role=None):
    off=await _a2t_leg_off(role,leg) if role else 0
    j=await leg._get("/OpenedOrders")
    items=j if isinstance(j,list) else ((j or {}).get("orders") or [])
    return {"positions":[_a2t_norm_order(o,off) for o in items],"src":"a2t"}
async def _a2t_history(leg, days=1, role=None):
    """历史成交 = 云端会话增量 ∪ 本地持久层(leg_deals)。
       命门: A2T ClosedOrders 是**会话级近期缓存**(断线重连即清零, ~100笔上限), 绝不能单独当历史真相源
       (Exness-Trial 会话重启曾把对冲腿账本整段抹掉→配对历史全变假单腿)。ticket 去重, 云端优先。"""
    off=await _a2t_leg_off(role,leg) if role else 0
    j=await leg._get("/ClosedOrders")
    items=j if isinstance(j,list) else ((j or {}).get("orders") or [])
    cutoff=(_t_conn.time()-float(days or 1)*86400)
    deals=[_a2t_norm_order(o,off) for o in items]
    cloud=[d for d in deals if (d.get("time") or 0)>=cutoff]
    if role:
        try:
            seen={str(d.get("ticket")) for d in cloud}
            c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT ticket,symbol,type,volume,price,price_open,profit,swap,commission,comment,entry,time_utc,time_open FROM leg_deals WHERE leg=%s AND time_utc>=%s",(role,int(cutoff)))
            for r_ in cur.fetchall():
                if str(r_["ticket"]) in seen: continue
                cloud.append({"ticket":r_["ticket"],"order":r_["ticket"],"symbol":r_["symbol"],"type":r_["type"],
                              "entry":int(r_["entry"] or 1),"volume":float(r_["volume"] or 0),"price":float(r_["price"] or 0),
                              "price_open":r_["price_open"],"price_current":r_["price"],
                              "profit":float(r_["profit"] or 0),"swap":float(r_["swap"] or 0),
                              "commission":float(r_["commission"] or 0),"time":int(r_["time_utc"] or 0),
                              "time_open":int(r_["time_open"] or 0),"comment":r_["comment"] or ""})
            c.close()
        except Exception: pass
    cloud.sort(key=lambda d:(d.get("time") or 0))
    return {"deals":cloud,"src":"a2t+db"}

def _persist_leg_rows(role, rows, user_id=None):
    """平仓行落库(ticket 幂等去重)。仅真实成交(type 0/1)且已平(entry=1)。返回新增行数。"""
    if not rows: return 0
    try:
        c=db(); cur=c.cursor(); n=0
        for d in rows:
            if d.get("type") not in (0,1) or not d.get("entry"): continue
            tk=str(d.get("ticket") or "")
            if not tk: continue
            cur.execute("""INSERT INTO leg_deals(user_id,leg,ticket,symbol,type,volume,price,price_open,profit,swap,commission,comment,entry,time_utc,time_open)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (leg,ticket) DO NOTHING""",
                        (user_id,role,tk,d.get("symbol"),d.get("type"),d.get("volume"),d.get("price"),d.get("price_open"),
                         d.get("profit"),d.get("swap"),d.get("commission"),d.get("comment"),1,
                         int(d.get("time") or 0),int(d.get("time_open") or 0)))
            n+=cur.rowcount
        c.close(); return n
    except Exception:
        return 0

async def _persist_sweep_once():
    """把两腿云端会话内的已平记录增量落库一次。供 120s 周期对账 + 平仓后即时补账共用。"""
    total=0
    try:
        legs=_a2t_read_legs(); rowsmap=(_A2T_LEG_CACHE.get("rows") or {})
        for role,leg in (legs or {}).items():
            if leg is None: continue
            try:
                off=await _a2t_leg_off(role,leg)
                j=await leg._get("/ClosedOrders")
                items=j if isinstance(j,list) else ((j or {}).get("orders") or [])
                rows=[_a2t_norm_order(o,off) for o in items]
                uid=(rowsmap.get(role) or {}).get("user_id")
                total+=_persist_leg_rows(role,[d for d in rows if d.get("entry")],uid)
            except Exception: pass
        if total: R.set(RNS+"deals:persist:last", json.dumps({"n":total,"ts":_dt.datetime.utcnow().isoformat()}))
    except Exception: pass
    return total

def _persist_after_close():
    """平仓成功后即时补账(3s 延迟等云端记录就绪, fire-and-forget): 会话在下一轮对账前重启也不丢单。"""
    async def once():
        await _aio.sleep(3)
        await _persist_sweep_once()
    try: _aio.create_task(once())
    except Exception: pass

async def _deal_persist_sweeper():
    await _aio.sleep(30)
    while True:
        await _persist_sweep_once()
        await _aio.sleep(120)

@app.on_event("startup")
async def _deal_persist_boot():
    try:
        c=db(); cur=c.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS leg_deals(
            id BIGSERIAL PRIMARY KEY, user_id INT, leg TEXT NOT NULL, ticket TEXT NOT NULL,
            symbol TEXT, type INT, volume DOUBLE PRECISION, price DOUBLE PRECISION, price_open DOUBLE PRECISION,
            profit DOUBLE PRECISION, swap DOUBLE PRECISION, commission DOUBLE PRECISION,
            comment TEXT, entry INT DEFAULT 1, time_utc BIGINT, time_open BIGINT,
            created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(leg,ticket))""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_leg_deals_time ON leg_deals(leg,time_utc)")
        c.close()
    except Exception: pass
    _aio.create_task(_deal_persist_sweeper())
async def _a2t_leg_status(role, leg):
    st=await leg.status()
    if st.get("connected"):
        try:
            ai=await leg.account_info()
            st.update({"balance":ai.get("balance"),"equity":ai.get("equity")})
        except Exception: pass
        row=(_A2T_LEG_CACHE.get("rows") or {}).get(role) or {}
        st.update({"account":row.get("login") or "--","server":row.get("server") or "--",
                   "platform":row.get("platform") or "--","via":"a2t"})
    return st

# A2T 读取微缓存: A2T 是计费 SaaS(402 配额), 1s 快照热路径直打会烧配额/触限。
# tick 1s / 持仓 2s / 状态·账户 5s / 历史成交 30s。仅缓存成功结果, 异常直接透传。
_A2T_RC={}
def _a2t_meter(kind):
    """A2T 调用计数(日滚动, 供配额/402 监控)。kind: call|402|err|hit。"""
    try:
        now=_dt.datetime.utcnow()
        day=now.strftime("%Y%m%d")
        k=RNS+"a2t:cnt:%s:%s"%(kind,day)
        n=R.incr(k)
        if n==1: R.expire(k, 172800)
        if kind in ("call","402"):   # 逐时桶(供大屏趋势图, 保留26h)
            hk=RNS+"a2t:h:%s:%s"%(kind,now.strftime("%Y%m%d%H"))
            if R.incr(hk)==1: R.expire(hk, 93600)
        if kind=="402": R.set(RNS+"a2t:last402", now.isoformat())
    except Exception: pass
def _a2t_meter_get():
    day=_dt.datetime.utcnow().strftime("%Y%m%d")
    def g(kind):
        try: return int(R.get(RNS+"a2t:cnt:%s:%s"%(kind,day)) or 0)
        except Exception: return 0
    return {"calls":g("call"),"hits":g("hit"),"errors":g("err"),"quota_402":g("402"),
            "last_402":R.get(RNS+"a2t:last402")}
async def _a2t_cached(key, ttl, fn):
    now=_t_conn.time(); e=_A2T_RC.get(key)
    if e and (now-e[0])<ttl: _a2t_meter("hit"); return e[1]   # 缓存命中=省一次云端配额
    try:
        v=await fn(); _a2t_meter("call")
    except _httpx.HTTPStatusError as ex:
        code=getattr(getattr(ex,"response",None),"status_code",0)
        _a2t_meter("402" if code==402 else "err"); raise
    except Exception:
        _a2t_meter("err"); raise
    _A2T_RC[key]=(now,v)
    if len(_A2T_RC)>512: _A2T_RC.clear()
    return v

# ---- sg-bridge 读取层: 会话制经纪商直连视图, 比旧云API新鲜(治"云端读滞后=单腿告警噪音"根因) ----
# 仅当该(用户,role)登记账号 == sg 会话账号(QH_SG_*_LOGIN)才启用(防错账户); 3败熔断60s回落云端; history 仍走云端。
_SG_READ_LEGS={}
_SG_READ_STATE={"main":{"fail":0,"skip":0.0},"hedge":{"fail":0,"skip":0.0}}
def _sg_read_env(role):
    base=os.environ.get("QH_SG_AGENT_URL","").rstrip("/")
    if not base: return None,None
    login=(os.environ.get("QH_SG_MAIN_LOGIN" if role=="main" else "QH_SG_HEDGE_LOGIN") or "").strip()
    if not login: return None,None
    port=os.environ.get("QH_SG_MAIN_PORT","8021") if role=="main" else os.environ.get("QH_SG_HEDGE_PORT","8001")
    return "%s:%s"%(base,port), login
def _sg_read_leg(role):
    url,_l=_sg_read_env(role)
    if not url: return None
    leg=_SG_READ_LEGS.get(role)
    if leg is None or leg.base!=url:
        import connector as _cn
        leg=_cn._BridgeLeg(url, os.environ.get("QH_SG_KEY",""))
        _SG_READ_LEGS[role]=leg
    return leg
async def _sg_leg_status(role, username, sg):
    """sg 读取腿状态(形状对齐 _a2t_leg_status, via='sg' 供 UI/验证辨识)。"""
    st=await sg.status()
    if st.get("connected"):
        try:
            ai=await sg.account_info()
            st.update({"balance":ai.get("balance"),"equity":ai.get("equity")})
        except Exception: pass
        rows=((_USER_LEG_CACHE.get(username) or {}).get("rows") if username else (_A2T_LEG_CACHE.get("rows") or {})) or {}
        row=rows.get(role) or {}
        st.update({"account":row.get("login") or "--","server":row.get("server") or "--",
                   "platform":row.get("platform") or "--","via":"sg"})
    return st

class _FallbackLeg:
    """读取腿(数据源由 _read_source() 决定):
       - 'a2t'(默认): **sg-bridge 优先(账号匹配时) → 云端** —— 内网桥退出读取链路; 该腿以 mt_accounts
         登记(conn_mode=api+UUID)为准, 未登记→返回良性空形状(both_* 聚合不塌), 登记→行情/账户/持仓走
         sg 会话直连视图(新鲜), 历史成交仍走云端(每腿时区折算+leg_deals持久并集在云端路径)。
       - 'bridge'(回滚杆): 桥优先+连续3败熔断60s回退云端(保留旧行为, redis 热切换)。
       执行(_post/open/close)与桥专属路径(symbol_info/symbols等)不参与切换, 原样走桥。"""
    _EMPTY_POS={"positions":[],"registered":False}
    _EMPTY_HIST={"deals":[],"registered":False}
    _EMPTY_ST={"connected":False,"registered":False}
    def __init__(self, role, username=None, strict=False):
        self.role=role; self.username=username; self.strict=bool(strict)
        self._fail=0; self._skip_until=0.0
    def _b(self):
        # Strict per-user readers must never cross the account boundary through
        # the process-global bridge.  Returning None makes _read use only the
        # user's own A2T leg (or its explicit empty shape).
        if self.strict and self.username:
            return None
        bc=_raw_bridge(); return bc.main if self.role=="main" else getattr(bc,"hedge",None)
    def _fb(self):
        # 多租户: 绑用户则取该用户腿; 否则全局(仪表盘单用户)
        return (_a2t_read_legs_for(self.username) if self.username else _a2t_read_legs()).get(self.role)
    def _sg(self):
        """sg-bridge 读取腿: 该(用户,role)登记账号=sg 会话账号才用(防错账户); 熔断窗内返回 None。
           前置: _fb() 已加载 rows 缓存(调用点保证)。"""
        url,want=_sg_read_env(self.role)
        if not url: return None
        rows=((_USER_LEG_CACHE.get(self.username) or {}).get("rows") if self.username else (_A2T_LEG_CACHE.get("rows") or {})) or {}
        if str((rows.get(self.role) or {}).get("login") or "").strip()!=want: return None
        if _t_conn.time()<_SG_READ_STATE[self.role]["skip"]: return None
        return _sg_read_leg(self.role)
    async def _read(self, bridge_call, a2t_call, empty=None, sg_call=None):
        fb=self._fb()
        if _read_source()=="a2t":
            if sg_call is not None:
                sg=self._sg()
                if sg is not None:
                    st=_SG_READ_STATE[self.role]
                    try:
                        r=await sg_call(sg); st["fail"]=0; return r
                    except Exception:
                        st["fail"]+=1
                        if st["fail"]>=3: st["skip"]=_t_conn.time()+60   # 熔断60s→云端兜底
            if fb is None:
                if empty is not None: return dict(empty)
                raise RuntimeError("%s 腿未登记(纯云端读取模式)"%self.role)
            return await a2t_call(fb)
        # bridge 回滚模式: 桥优先 + 熔断回退云端
        if fb is not None and _t_conn.time()<self._skip_until:
            try: return await a2t_call(fb)
            except Exception: pass          # 云端也挂→半开重试桥
        b=self._b(); err=None
        if b is not None:
            try:
                r=await bridge_call(b); self._fail=0; self._skip_until=0.0; return r
            except Exception as e:
                err=e; self._fail+=1
                if self._fail>=3: self._skip_until=_t_conn.time()+60
        if fb is not None:
            return await a2t_call(fb)
        if err: raise err
        raise RuntimeError("no %s leg (bridge/a2t both missing)"%self.role)
    async def _get(self, path, **params):
        if path.startswith("/mt5/tick/"):
            sym=path.rsplit("/",1)[-1]
            _tk = await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("tick",self.role,sym),1.0,lambda: _a2t_tick(fb,sym)),
                                    sg_call=lambda sg: sg._get(path,**params))
            return _norm_tick(_tk, self.role, self.username)
        if path=="/mt5/history/deals":
            d=params.get("days",1)
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("hist",self.role,d),30.0,lambda: _a2t_history(fb,d,self.role)), empty=self._EMPTY_HIST)
        if path=="/mt5/account/info":
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("acct",self.role),5.0,lambda: fb.account_info()),
                                    sg_call=lambda sg: sg._get(path,**params))
        if path=="/mt5/positions":
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("pos",self.role),2.0,lambda: _a2t_positions(fb,self.role)), empty=self._EMPTY_POS,
                                    sg_call=lambda sg: sg._get(path,**params))
        b=self._b()
        if b is None: raise RuntimeError("bridge leg missing: "+path)
        return await b._get(path, **params)                     # 桥专属路径(symbol_info/symbols等)
    async def account_info(self):
        return await self._read(lambda b: b.account_info(),
                                lambda fb: _a2t_cached(("acct",self.role),5.0,lambda: fb.account_info()),
                                sg_call=lambda sg: sg.account_info())
    async def positions(self):
        return await self._read(lambda b: b.positions(),
                                lambda fb: _a2t_cached(("pos",self.role),2.0,lambda: _a2t_positions(fb,self.role)), empty=self._EMPTY_POS,
                                sg_call=lambda sg: sg.positions())
    async def history_deals(self, days=1):
        return await self._read(lambda b: b.history_deals(days),
                                lambda fb: _a2t_cached(("hist",self.role,days),30.0,lambda: _a2t_history(fb,days,self.role)), empty=self._EMPTY_HIST)
    async def status(self):
        return await self._read(lambda b: b.status(),
                                lambda fb: _a2t_cached(("st",self.role),5.0,lambda: _a2t_leg_status(self.role,fb)), empty=self._EMPTY_ST,
                                sg_call=lambda sg: _sg_leg_status(self.role,self.username,sg))
    def __getattr__(self, name):                                 # 执行/其它方法透传桥(不参与读取源切换)
        b=self._b()
        if b is None: raise AttributeError("bridge leg missing: "+name)
        return getattr(b, name)

def _bridge_connector():
    """读取连接器: 桥优先 + A2T 云端回退的双腿(both_* 组合逻辑复用 Mt5BridgeConnector)。"""
    c=_CONN_CACHE.get("bridge_read")
    if c is None:
        import connector as _cn
        c=_cn.Mt5BridgeConnector.__new__(_cn.Mt5BridgeConnector)
        c.main=_FallbackLeg("main"); c.hedge=_FallbackLeg("hedge")
        _CONN_CACHE["bridge_read"]=c
    return c
class _BridgeProxy:
    """读取代理: 优先内网桥(完整实时真相; 与执行连接方式解耦); 桥无该账户/不可达时按登记 UUID 回退 A2T 云端,
       行情/点差/账户/持仓/过夜费/手续费在纯云端托管场景不断流。"""
    def __getattr__(self, name): return getattr(_bridge_connector(), name)
class _ExecProxy:
    """执行代理: 开/平仓委托到当前生效连接方式(active_mode: bridge 或 api/FRA)。"""
    def __getattr__(self, name): return getattr(_active_connector(), name)
CONN = _BridgeProxy()   # 读取 = 桥真相(48 处调用点零改动, 现全部读桥)
EXEC = _ExecProxy()     # 执行 = active_mode(仅 6 处开/平仓)

_REG_ROLES_CACHE={"roles":None,"ts":0.0}
def _reg_roles():
    """当前有启用登记行的角色集合(10s 缓存; 供操作台账户卡门控)。DB 异常 fail-open 不遮真相。"""
    now=_t_conn.time()
    if _REG_ROLES_CACHE["roles"] is not None and (now-_REG_ROLES_CACHE["ts"])<10:
        return _REG_ROLES_CACHE["roles"]
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT DISTINCT role FROM mt_accounts WHERE role IN ('main','hedge') AND enabled")
        roles=set(r[0] for r in cur.fetchall()); c.close()
    except Exception:
        return _REG_ROLES_CACHE["roles"] if _REG_ROLES_CACHE["roles"] is not None else {"main","hedge"}
    _REG_ROLES_CACHE["roles"]=roles; _REG_ROLES_CACHE["ts"]=now
    return roles
def _reg_roles_bust():
    _REG_ROLES_CACHE["roles"]=None; _REG_ROLES_CACHE["ts"]=0.0
    try: _USER_REG_ROWS_CACHE.clear()
    except Exception: pass
    try:
        bust=globals().get("_bridge_pool_cache_bust")
        if bust is not None: bust()
    except Exception: pass
    try: _a2t_leg_bust()   # A2T 动态读取腿一并失效(重注册换 UUID 立即跟随)
    except Exception: pass
    try: _USER_BRIDGE_CACHE.clear()
    except Exception: pass
    try: _BRIDGE_CLIENTS_USER_CACHE.clear()
    except Exception: pass
    try:
        hcache=globals().get("_CONN_HEALTH_USER_CACHE")
        if hcache is not None: hcache.clear()
    except Exception: pass
    try:
        bcache=globals().get("_BRIDGE_CLIENTS_CACHE")
        if bcache is not None: bcache.update({"ts":0.0,"data":None})
    except Exception: pass

def _auto_loop_running(username=None):
    """Return an armed automatic loop for one user or for the whole system."""
    try:
        if username:
            for pfx in ("auto_entry:","auto_exit:"):
                value=R.get(RNS+pfx+username) or "off"
                if value in ("armed","full"):
                    return "%s=%s (用户 %s)"%(pfx[:-1],value,username)
            return None
        for pfx in ("auto_entry:","auto_exit:"):
            for k in R.scan_iter(RNS+pfx+"*"):
                v=R.get(k) or "off"
                if v in ("armed","full"):
                    return "%s=%s (用户 %s)"%(pfx[:-1], v, str(k).split(":")[-1])
    except Exception: pass
    return None
async def _acct_clear_guard(role, username=None):
    """清除账户保护闸: 自动策略运行中 或 该腿有未平持仓 → 返回禁止原因(str); 放行返回 None。
       持仓查询失败时 fail-closed，避免删除仍有真实仓位的账户登记。"""
    username=str(username or "").strip()
    if not username:
        return "target username missing, cannot verify positions; account clear rejected"
    r=_auto_loop_running(username)
    if r: return "系统自动策略运行中(%s), 禁止清除账户; 请先在操作台停止自动进单/平仓"%r
    try:
        conn=_strict_user_read_conn(username)
        if conn is None:
            return "用户连接器不可用, 无法核对持仓, 已拒绝清除账户"
        pos=await conn.both_positions()
        if not isinstance(pos,dict):
            return "持仓快照不可用, 无法确认账户已空仓, 已拒绝清除账户"
        if role not in pos or pos.get(role) is None:
            return "目标腿持仓快照缺失, 无法确认账户已空仓, 已拒绝清除账户"
        pl=pos.get(role) or {}
        if isinstance(pl,dict) and pl.get("registered") is False:
            return "持仓快照不可用, 无法确认账户已空仓, 已拒绝清除账户"
        items=pl.get("positions",pl) if isinstance(pl,dict) else (pl or [])
        n=len([p for p in (items or []) if float(p.get("volume",0) or 0)>0])
        if n>0: return "该账户尚有 %d 笔未平持仓, 请先平仓再清除(防止监控盲区)"%n
    except Exception as ex:
        return "持仓核对失败(%s), 已fail-closed拒绝清除账户"%ex.__class__.__name__
    return None

def _conn_consistency(username=None):
    """Return connector-mode consistency globally or for one user."""
    try:
        c=db(); cur=c.cursor()
        if username:
            cur.execute("""SELECT m.role,m.conn_mode FROM mt_accounts m
                           JOIN users u ON u.id=m.user_id
                           WHERE u.username=%s AND m.role IN ('main','hedge') AND m.enabled""",
                        (username,))
        else:
            cur.execute("SELECT role, conn_mode FROM mt_accounts WHERE role IN ('main','hedge') AND enabled")
        rows=cur.fetchall(); c.close()
    except Exception as e:
        return {"consistent":False,"eff_mode":None,"main_modes":[],"hedge_modes":[],"err":str(e)[:100]}
    mains=set(r[1] for r in rows if r[0]=="main"); hedges=set(r[1] for r in rows if r[0]=="hedge")
    modes=mains|hedges
    consistent=(len(modes)==1) and bool(mains) and bool(hedges)
    return {"consistent":consistent,"eff_mode":(list(modes)[0] if len(modes)==1 else None),
            "main_modes":sorted(mains),"hedge_modes":sorted(hedges)}

async def _conn_health_once(mode=None):
    """某连接方式(默认当前 active)双腿可达? 返回 (ok, status)。"""
    try:
        c=_active_connector() if (mode is None or mode==_active_mode()) else build_connector(mode)
        st=await c.both_status() if hasattr(c,"both_status") else {"main":await c.status(),"hedge":None}
        def _ok(x):
            if x is None: return None
            return bool(x.get("connected", True)) and "error" not in x
        m=_ok(st.get("main")); h=_ok(st.get("hedge"))
        return (bool(m) and (h is None or h)), st
    except Exception as e:
        return False, {"err":str(e)[:120]}

_CONN_HEALTH_CACHE={"ts":0.0,"ok":None,"st":None}
async def _conn_health(mode=None):
    """健康检查加固: ①4s 结果缓存(开/平仓闸不再每次都付跨洲双腿探测) ②失败自动重试一次(网络抖动不再直接拒单)。
       仅缓存当前 active_mode 的结果; 显式查询其它 mode 不缓存。"""
    now=_t_conn.time()
    is_active=(mode is None or mode==_active_mode())
    if is_active and _CONN_HEALTH_CACHE["ok"] is not None and (now-_CONN_HEALTH_CACHE["ts"])<4:
        return _CONN_HEALTH_CACHE["ok"], _CONN_HEALTH_CACHE["st"]
    ok,st=await _conn_health_once(mode)
    if not ok:
        ok,st=await _conn_health_once(mode)   # 抖动重试
    if is_active:
        _CONN_HEALTH_CACHE["ts"]=now; _CONN_HEALTH_CACHE["ok"]=ok; _CONN_HEALTH_CACHE["st"]=st
    return ok,st

# ---- P0: per-user 健康探测(执行链路按用户桥, 而非全局单桥) ----
# 根因: 全局 _conn_health() 探 env 死写的 8041/8042(no123 桥); hedge_pro 执行落自己的
# 8061/8063, 却被 no123 的桥健康判死(误伤)。此处让健康前置闸也按 username 探用户自己的桥。
_CONN_HEALTH_USER_CACHE={}   # username -> {"ts","ok","st"}
_CONN_HEALTH_USER_INFLIGHT={}

async def _probe_conn_health_user(username, uconn):
    async def _once():
        try:
            if hasattr(uconn, "both_status"):
                st=await uconn.both_status()
            else:
                st={"main":await uconn.status(),"hedge":None}
            def _ok(value):
                if value is None:
                    return None
                return bool(value.get("connected", True)) and "error" not in value
            main_ok=_ok(st.get("main")); hedge_ok=_ok(st.get("hedge"))
            return bool(main_ok) and (hedge_ok is None or hedge_ok), st
        except Exception as ex:
            return False, {"err":str(ex)[:120]}
    ok, status=await _once()
    if not ok:
        ok, status=await _once()
    _CONN_HEALTH_USER_CACHE[username]={"ts":_t_conn.time(),"ok":ok,"st":status}
    return ok, status

async def _conn_health_user(username):
    """该用户自己桥(_user_bridge_conn)双腿可达? 返回 (ok, status)。4s 缓存 + 抖动重试一次。
       无 per-user 桥(bridge_url 缺失)→ 回落全局 _conn_health(向后兼容)。"""
    uconn=_user_bridge_conn(username)
    if uconn is None:
        return await _conn_health()
    now=_t_conn.time()
    e=_CONN_HEALTH_USER_CACHE.get(username)
    # P0修复2: ok→4s缓存, failed→1s缓存(防 concurrent UNKNOWN→recovered 过程中的
    # 临时失败污染后续请求, 导致 main_first/hedge_first 被缓存误拦)
    _ttl = 4 if (e and e.get("ok")) else 1
    if e and e["ok"] is not None and (now-e["ts"])<_ttl:
        return e["ok"], e["st"]
    inflight=_CONN_HEALTH_USER_INFLIGHT.get(username)
    if inflight is None or inflight.done():
        inflight=_aio.create_task(_probe_conn_health_user(username,uconn))
        _CONN_HEALTH_USER_INFLIGHT[username]=inflight
    try:
        return await _aio.shield(inflight)
    finally:
        if _CONN_HEALTH_USER_INFLIGHT.get(username) is inflight:
            _CONN_HEALTH_USER_INFLIGHT.pop(username,None)

async def _conn_block_reason(username=None):
    """执行连接方式(active_mode)是否可执行? 不一致/不可达→返回原因串, 否则 None。读取不受此限(读桥真相)。
       username 给定且 per-user 开启且该用户有 bridge_url → 探用户自己的桥(修 hedge_pro 被 no123 桥误伤)。"""
    cons=_conn_consistency(username)
    if not cons["consistent"]:
        return "主/对冲连接方式不一致(主%s/对冲%s)"%(cons["main_modes"] or "未设",cons["hedge_modes"] or "未设")
    if username and _exec_per_user_on() and _user_bridge_conn(username) is not None:
        ok,_st=await _conn_health_user(username)   # per-user: 探该用户自己的桥
    else:
        ok,_st=await _conn_health()   # active_mode(执行链路)健康(全局, 向后兼容)
    if not ok:
        return "当前连接方式(%s)双腿不可达"%_active_mode()
    return None

async def _conn_gate_exec(username=None):
    """执行前 fail-closed 闸: 连接方式不一致或执行链路不可达 → 409。返回执行连接器 EXEC。
       username 透传给 block_reason: per-user 时按该用户桥判健康(不再被别人的桥误伤)。"""
    r=await _conn_block_reason(username)
    if r: raise HTTPException(409, r+", 已fail-closed拒绝执行, 请统一/切换连接方式后再操作")
    return EXEC

# ---- 多用户串账墙(架构债止血): 引擎单一全局 EXEC 桥, 若下单用户登记账户≠执行桥实际账户 → 会落到别人账户 ----
# 现实: 引擎单 CONN/EXEC 从 env, per-user 连接器池是大重构(未做); 在此之前, 用执行前身份核对硬拦跨账户下单。
_EXEC_ACCT_CACHE={"main":None,"hedge":None,"ts":0.0}
async def _exec_bridge_accounts():
    """执行桥双腿实际登录号(缓存60s)。失败返回上次值(fail-open 由上层再判)。"""
    now=_t_conn.time()
    if _EXEC_ACCT_CACHE["ts"] and (now-_EXEC_ACCT_CACHE["ts"])<60:
        return _EXEC_ACCT_CACHE["main"],_EXEC_ACCT_CACHE["hedge"]
    try:
        # 桥身份取自 CONN(读取真相源, 与 EXEC 落同一 MT 账户); EXEC 代理可能因 key/路由取不到账户号
        st=await CONN.both_status() if hasattr(CONN,"both_status") else {"main":await CONN.status(),"hedge":None}
        def _acc(x):
            a=(x or {}).get("account") if isinstance(x,dict) else None
            return str(a) if a not in (None,"","--") else None
        m=_acc(st.get("main")); h=_acc(st.get("hedge"))
        if m: _EXEC_ACCT_CACHE.update({"main":m,"hedge":h,"ts":now})
        return m,h
    except Exception:
        return _EXEC_ACCT_CACHE["main"],_EXEC_ACCT_CACHE["hedge"]
async def _exec_owner_reason(username):
    """该用户登记的 main/hedge 登录号是否 == 执行桥实际账户? 不符→返回原因串(禁止下单), 相符/无法核对→None。
       目的: 引擎单桥架构下, 防用户A的下单落到桥账户(别人的钱)。登记缺失也拦(未接入执行桥)。"""
    rows=_reg_rows_for(username)
    if not rows: return "账户未登记, 无法交易"
    if _exec_per_user_on():
        # P4b per-user: 验证用户自己的桥(bridge_url 存在 + 桥账户==登记 + 在线); 不符 fail-closed
        uconn=_user_bridge_conn(username)
        if uconn is None: return "账户未配置执行桥(bridge_url 缺失), 请重新保存账户或联系管理员"
        # _conn_gate_exec immediately precedes this check. Reuse only a very fresh
        # successful status snapshot so ownership validation does not issue the same
        # two bridge requests twice for every click.
        _now=_t_conn.time(); _health=_CONN_HEALTH_USER_CACHE.get(username)
        _status_all=(_health.get("st") if (_health and _health.get("ok") and (_now-_health.get("ts",0))<1.0) else None)
        if not isinstance(_status_all,dict):
            async def _owner_status(_r):
                leg=getattr(uconn,_r,None)
                if leg is None: return {"connected":False,"error":"bridge_url_missing"}
                try: return await leg.status()
                except Exception as ex: return {"connected":False,"error":ex.__class__.__name__}
            _main_st,_hedge_st=await _aio.gather(_owner_status("main"),_owner_status("hedge"))
            _status_all={"main":_main_st,"hedge":_hedge_st}
            _status_ok=all(bool((_status_all.get(r) or {}).get("connected")) and "error" not in (_status_all.get(r) or {})
                           for r in ("main","hedge") if rows.get(r))
            _CONN_HEALTH_USER_CACHE[username]={"ts":_now,"ok":_status_ok,"st":_status_all}
        def _check_owner_leg(_r):
            reg=rows.get(_r); regl=str((reg or {}).get("login") or "").strip()
            if not regl: return None
            cn="主" if _r=="main" else "对冲"
            leg=getattr(uconn,_r,None)
            if leg is None: return "%s腿执行桥未配置(bridge_url 缺失)"%cn
            st=(_status_all.get(_r) or {})
            if "error" in st: return "%s腿执行桥不可达(客户端离线/未启动), 无法交易"%cn
            bacc=str(st.get("account") or "").strip()
            if bacc and regl!=bacc: return "%s腿桥账户(%s)与登记(%s)不符, 拒绝(防串账)"%(cn,bacc,regl)
            if not (st.get("connected") and "error" not in st): return "%s腿桥客户端离线, 无法交易"%cn
            return None
        _owner_reasons=(_check_owner_leg("main"),_check_owner_leg("hedge"))
        for _reason in _owner_reasons:
            if _reason: return _reason
        return None
    bm,bh=await _exec_bridge_accounts()
    if bm is None: return None
    um=str((rows.get("main") or {}).get("login") or "").strip()
    uh=str((rows.get("hedge") or {}).get("login") or "").strip()
    if um and um!=str(bm):
        return "主账户(%s)与当前执行桥账户(%s)不一致, 已拒绝(防串账); 请联系管理员将你的账户接入执行桥"%(um,bm)
    if uh and bh and uh!=str(bh):
        return "对冲账户(%s)与当前执行桥账户(%s)不一致, 已拒绝(防串账)"%(uh,bh)
    return None
_PLAT_CACHE={"m":{},"ts":0.0}
def _platform_of_login(login):
    """按 MT 登录号取登记平台(MT4/MT5)。缓存30s。供账户卡按桥实际账户显真平台(修硬编码 MT5)。"""
    now=_t_conn.time()
    if not _PLAT_CACHE["m"] or (now-_PLAT_CACHE["ts"])>=30:
        try:
            c=db(); cur=c.cursor()
            cur.execute("SELECT login,platform FROM mt_accounts WHERE login IS NOT NULL")
            _PLAT_CACHE["m"]={str(r[0]).strip():r[1] for r in cur.fetchall() if r[1]}; _PLAT_CACHE["ts"]=now; c.close()
        except Exception: pass
    return _PLAT_CACHE["m"].get(str(login).strip())

def _reg_rows_for(username):
    """Return immutable routing facts from a write-invalidated hot cache."""
    username=str(username or "").strip()
    if not username:
        return {}
    cached=_USER_REG_ROWS_CACHE.get(username)
    if cached is not None:
        return {role:dict(row) for role,row in cached.items()}
    out={}
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT m.role,m.platform,m.login,m.server,m.bridge_url,m.conn_mode FROM mt_accounts m JOIN users u ON u.id=m.user_id "
                    "WHERE u.username=%s AND m.role IN ('main','hedge') AND m.enabled",(username,))
        for r in cur.fetchall():
            out[r[0]]={"platform":r[1],"login":r[2],"server":r[3],
                       "bridge_url":r[4],"conn_mode":r[5]}
        c.close()
    except Exception:
        return {}
    _USER_REG_ROWS_CACHE[username]={role:dict(row) for role,row in out.items()}
    return {role:dict(row) for role,row in out.items()}
async def _exec_owner_gate(username):
    """手动交易端点前置: 串账→409 fail-closed。"""
    r=await _exec_owner_reason(username)
    if r: raise HTTPException(409, r)

async def _exec_leg_gate(username, leg):
    """Validate only the target leg for an exact-ticket emergency close."""
    rows=_reg_rows_for(username)
    reg=rows.get(leg) or {}
    expected=str(reg.get("login") or "").strip()
    if not expected:
        raise HTTPException(409,("主" if leg=="main" else "对冲")+"腿账户未登记, 拒绝平仓")
    conn=_user_exec_conn(username)
    legobj=getattr(conn,leg,None)
    if legobj is None:
        raise HTTPException(409,("主" if leg=="main" else "对冲")+"腿执行桥未配置")
    status=None
    for _attempt in range(2):
        try:
            status=await legobj.status()
            if status.get("connected") and "error" not in status: break
        except Exception:
            status=None
        if _attempt==0: await _aio.sleep(0.1)
    if not status or not status.get("connected") or "error" in status:
        raise HTTPException(409,("主" if leg=="main" else "对冲")+"腿执行桥不可达, 已 fail-closed 拒绝执行")
    actual=str(status.get("account") or "").strip()
    if not actual:
        raise HTTPException(409,"执行桥未返回账户号, 无法验证归属")
    if actual!=expected:
        raise HTTPException(409,"桥账户(%s)与登记(%s)不符, 拒绝执行"%(actual,expected))
    return conn

# ---- 经纪商服务器时区偏移活标定(MT5 成交/行情 time=经纪商墙钟epoch, 非UTC) ----
# **逐腿标定**(命门): 主/对冲可为不同经纪商不同时区 —— IC=GMT+3(10800) / Exness=GMT+0(0)。
# 单一全局偏移会把一条腿校对、另一条腿凭空多出整段偏移 → 源龄恒≈offset → 新鲜度闸拦死开仓
# (testgo「skew恒10800s拦死开仓」的 QH 翻版, 2026-07-21 实锤: Exness对冲腿被IC偏移误判源龄10801s)。
_BROKER_OFF={"main":{"sec":None,"ts":0.0},"hedge":{"sec":None,"ts":0.0}}
async def _broker_utc_offset(leg="main", conn=None, cache_key="", observed_tick=None):
    """某腿经纪商 epoch 与 UTC 偏移(秒)。桥 tick time 活标定→自动兼容夏令时/逐腿时区差异。
       缓存5min; 失败回落上次值或0。成交转UTC = broker_epoch - 此偏移。默认 main(向后兼容成交/持仓转UTC调用点)。
       纯云端读取(a2t)时恒 0: _a2t_norm_order 已按逐腿标定折回 UTC。"""
    if _read_source()=="a2t": return 0
    leg=leg if leg in ("main","hedge") else "main"
    slot_key=(str(cache_key)+":"+leg) if cache_key else leg
    slot=_BROKER_OFF.setdefault(slot_key,{"sec":None,"ts":0.0}); now=_t_conn.time()
    if slot["sec"] is not None and (now-slot["ts"])<300:
        return slot["sec"]
    try:
        if observed_tick is None:
            active_conn=conn or _bridge_connector()
            legobj=active_conn.main if leg=="main" else (getattr(active_conn,"hedge",None) or active_conn.main)
            tk=await legobj._get("/mt5/tick/XAUUSD")
        else:
            tk=observed_tick
        bt=tk.get("time")
        if isinstance(bt,(int,float)) and bt>0:
            off=int(round((float(bt)-_t_conn.time())/900.0))*900   # 取整到15min(时区粒度)
            if -43200<=off<=50400:                                 # 合理性 -12h..+14h
                slot["sec"]=off; slot["ts"]=now
                return off
    except Exception: pass
    return slot["sec"] or 0
def _to_utc(broker_epoch, off):
    try: return int(broker_epoch)-int(off) if broker_epoch else broker_epoch
    except Exception: return broker_epoch

# ---- V1.1 移植: 行情新鲜度闸(开仓前 tick 源龄校验; 纯逻辑在 engine.quote_stale_reason) ----
# 阈值 Redis qh:quote_gate:max_age(秒, 默认15, 0=关闭) — 热调无需重启。
def _quote_max_age():
    try:
        v=R.get(RNS+"quote_gate:max_age")
        return float(v) if v is not None else 15.0
    except Exception: return 15.0
async def _quote_stale(mt, ht, conn=None, cache_key=""):
    """双腿 tick 新鲜度: 陈旧→原因串, 否则 None。**逐腿偏移**(main/hedge 各自标定, 修不同经纪商时区差)。
       任一腿源龄>阈值即拦; 阈值≤0=关闭; 取不到 time 的腿放行(冻结报价仍带旧time一定逮得住)。"""
    try: lim=float(_quote_max_age() or 0)
    except Exception: lim=0.0
    if lim<=0: return None
    async def _offset(leg, tick):
        # The exact ticks being gated already contain broker time.  Reusing them
        # avoids two extra bridge reads on a cold offset cache and keeps the
        # freshness decision tied to the same quote that will be traded.
        try:
            broker_time=(tick or {}).get("time") if isinstance(tick,dict) else None
            if not isinstance(broker_time,(int,float)) or broker_time<=0:
                return 0
            return await _broker_utc_offset(leg,conn,cache_key,observed_tick=tick)
        except Exception:
            return 0
    try:
        moff,hoff=await _aio.gather(_offset("main",mt),_offset("hedge",ht))
    except Exception: moff=hoff=0
    try:
        for name,tk,off in (("主",mt,moff),("对冲",ht,hoff)):
            age=ENG.quote_age(tk,off)
            if age is not None and age>lim:
                return "%s腿行情陈旧(源龄%.1fs>阈值%.0fs, 报价可能冻结)"%(name,age,lim)
    except Exception: return None
    return None

# ---- 成交容差(deviation)按经纪商小数位自适应折算: 让实际 USD 容差对齐(修 3 位小数经纪商 REQUOTE 风暴) ----
def _dev_target():
    """目标成交容差(USD, Redis qh:exec:dev_target_usd 热调, 默认 0.50)。"""
    try: return float(R.get(RNS+"exec:dev_target_usd") or 0.50)
    except Exception: return 0.50
def _dev_for_price(price, target_usd=None):
    """从报价小数位反算 deviation(point), 使实际容差≈target。IC(2位)→50 / Exness(3位)→500;
       桥默认10对3位小数仅0.01USD易REQUOTE→活跃时段慢+单腿。price无效→None(回落桥默认)。"""
    if target_usd is None: target_usd=_dev_target()
    try:
        s=repr(float(price)); dig=len(s.split(".")[1]) if "." in s else 0
        if dig<=0 or dig>8: return None
        return max(10, int(round(float(target_usd)*(10**dig))))
    except Exception: return None

# ---- 执行滑点决策快照(带符号): 决策时刻按"将成交买卖侧"取价的方向化捕获点差; 读取时 滑点=实际成交捕获-决策快照 ----
def _cap_at(mt, ht, direction, action):
    """决策时刻方向化捕获点差(hedge/main 用各自将成交的买卖侧报价)。
       reverse=主卖/对冲买(开)→捕获=对冲价-主价; forward 相反; 平仓两腿反向成交。"""
    try:
        mb=float(mt.get("bid")); ma=float(mt.get("ask")); hb=float(ht.get("bid")); ha=float(ht.get("ask"))
    except Exception: return None
    if action=="open":
        return round(ha-mb,4) if direction=="reverse" else round(ma-hb,4)   # 开: 主卖@bid/对冲买@ask | 主买@ask/对冲卖@bid
    return round(hb-ma,4) if direction=="reverse" else round(mb-ha,4)        # 平: 主买@ask/对冲卖@bid | 主卖@bid/对冲买@ask
def _realized_cap(direction, m_price, h_price):
    """实际成交的方向化捕获点差(与 _cap_at 同向): reverse=对冲价-主价, forward=主价-对冲价。"""
    try: return round((h_price-m_price) if direction=="reverse" else (m_price-h_price),4)
    except Exception: return None
def _leg_tickets(legres):
    """从执行返回体抽 MT 票据候选(桥开=deal/order, 桥平=order, api=ticket/closed), 归一为字符串列表。
       供 paired_history 按 ticket 精确键匹配快照(deal票↔history.ticket, order票↔history.order)。"""
    out=[]
    if isinstance(legres, dict):
        for k in ("deal","order","ticket"):
            v=legres.get(k)
            if v: out.append(str(v))
        cl=legres.get("closed")
        if isinstance(cl,list): out+=[str(x) for x in cl if x]
    return out
def _slip_snap(direction, action, cap, slot=None, tickets=None, thr=None):
    """落一条决策快照(全局环形): 优先 ticket 精确键, 时间为兜底。tickets=主腿MT票候选; thr=该单生效的买入点位(逐单阈值, 供历史阈值列/达标差)。"""
    if cap is None: return
    try:
        R.lpush(RNS+"slipsnap", json.dumps({"d":direction,"a":action,"ts":int(_dt.datetime.utcnow().timestamp()),
                                            "c":cap,"slot":slot,"tk":tickets or [],"th":thr}))
        R.ltrim(RNS+"slipsnap",0,1999)
    except Exception: pass

from fastapi import Header
ADMIN_TOKEN = os.environ.get("QH_ADMIN_TOKEN","")   # 管理写操作令牌(systemd 注入, 默认真源)
def _admin_token():
    """当前有效超管令牌: channels.json 的 admin.token 轮换值优先, 否则回落 systemd env。
       支持从后台重置令牌而无需重启服务(_chcfg_load 定义在后, 仅运行时调用不影响导入)。"""
    try:
        ov=_chcfg_load().get("admin",{}).get("token")
        if ov: return ov
    except Exception: pass
    return ADMIN_TOKEN
def require_admin(x_admin_token: str = Header(default=""), x_license: str = Header(default="")):
    # 双因子：admin token 必须匹配，且 license 对应用户 role=admin
    _tok=_admin_token()
    if not _tok or x_admin_token != _tok:
        raise HTTPException(403, "admin token 校验失败")
    if x_license:
        c=db(); cur=c.cursor()
        cur.execute("SELECT role FROM users WHERE license_key=%s",(x_license,))
        row=cur.fetchone(); c.close()
        if not row or row[0]!="admin":
            raise HTTPException(403, "需要管理员角色")
    return True

# User-license and subject binding helpers are defined above route registration.

# ================= P5 操作员体系 (角色/权限/操作日志/IP 限制) =================
import secrets as _secrets
def _pwd_hash(salt, pwd): return hashlib.sha256((salt+pwd).encode()).hexdigest()
def _client_ip(request):
    xff=request.headers.get("x-forwarded-for","")
    return (xff.split(",")[0].strip() if xff else (request.client.host if request.client else ""))
def _op_perms(role):
    c=db(); cur=c.cursor(); cur.execute("SELECT perms FROM operator_roles WHERE role=%s",(role,)); r=cur.fetchone(); c.close()
    return (r[0] or "") if r else ""
def _op_session(token):
    """session token → operator dict(含 role/ip 校验信息); 无效返回 None。Redis 存 12h。"""
    if not token: return None
    raw=R.get(RNS+"opsess:"+token)
    return json.loads(raw) if raw else None
from fastapi import Request
def require_op(perm, danger=False):
    """操作员权限依赖工厂(权限三档): ①只读/常规写=有模块权限即可 ②危险操作 danger=True=须模块权限
       且角色含 'danger' 能力(或超管)。校验 session + 角色权限 + IP 白名单。
       向后兼容: 合法 admin token / role=super 恒放行(超管兜底)。"""
    def _dep(request: Request, x_op_token: str = Header(default=""), x_admin_token: str = Header(default="")):
        _tok=_admin_token()
        if _tok and x_admin_token==_tok:
            return {"operator":"admintoken","role":"super"}
        sess=_op_session(x_op_token)
        if not sess: raise HTTPException(401,"操作员未登录")
        if not sess.get("enabled",True): raise HTTPException(403,"操作员已禁用")
        allow=sess.get("allowed_ips") or ""
        if allow.strip():
            ip=_client_ip(request)
            if ip not in [x.strip() for x in allow.split(",") if x.strip()]:
                raise HTTPException(403,"IP 不在白名单: %s"%ip)
        role=sess.get("role"); perms=_op_perms(role); is_super=(role=="super" or perms=="*")
        plist=[x.strip() for x in perms.split(",")]
        if not is_super and perm not in plist:
            raise HTTPException(403,"无权限: %s(角色 %s)"%(perm,role))
        # 危险操作三档闸: 非超管须角色显式含 'danger' 能力
        if danger and not is_super and "danger" not in plist:
            raise HTTPException(403,"危险操作需「danger」能力(角色 %s 未授权; 联系超管在角色权限加 danger)"%role)
        return sess
    return _dep
def require_super(request: Request, x_op_token: str = Header(default=""), x_admin_token: str = Header(default="")):
    """仅超级管理员: 持有效超管令牌, 或操作员会话 role=='super'。用于令牌重置等最高危操作。"""
    _tok=_admin_token()
    if _tok and x_admin_token==_tok:
        return {"operator":"admintoken","role":"super"}
    sess=_op_session(x_op_token)
    if sess and sess.get("role")=="super":
        return sess
    raise HTTPException(403,"仅超级管理员可操作")
def _sess_has_perm(sess, perm):
    """会话是否拥有某模块权限。super/admintoken(perms='*')恒真。"""
    if not sess: return False
    if sess.get("role")=="super" or sess.get("operator")=="admintoken": return True
    perms=_op_perms(sess.get("role"))
    if perms=="*": return True
    return perm in [x.strip() for x in (perms or "").split(",") if x.strip()]
def _require_adv(sess, what="该高级操作"):
    """用户高级管理闸: 需 users_adv 权限或超管。用于套餐增删/权益/付费·试用日期/模式/状态/删除/封禁/重置密钥/导出。"""
    if not _sess_has_perm(sess, "users_adv"):
        raise HTTPException(403,"%s需要「用户高级管理(users_adv)」权限或超级管理员"%what)
    return True
def _op_log(sess, request, action, detail):
    try:
        c=db(); cur=c.cursor()
        cur.execute("INSERT INTO operator_audit(operator,role,ip,action,detail) VALUES(%s,%s,%s,%s,%s)",
                    (sess.get("operator"),sess.get("role"),_client_ip(request),action,json.dumps(detail)))
        c.close()
    except Exception as e: print("op_log err",e)

# ================= 维护/系统全停 状态机 (Redis qh:maintenance 单键真相) =================
# on=总开关; stop_strategy=停自动策略(复用 global_estop); block_trading=禁下单; block_login=禁登录(全站)。
# until=可选 ISO, 到点自动失效(惰性判)。开关本身不碰实时交易循环, 仅在端点前置闸拦截。
def _maint_get():
    try:
        raw=R.get(RNS+"maintenance")
        if not raw: return {"on":False}
        m=json.loads(raw)
        if not m.get("on"): return {"on":False}
        u=m.get("until")
        if u:
            try:
                if _dt.datetime.fromisoformat(u) < _dt.datetime.now(_dt.timezone.utc):
                    R.delete(RNS+"maintenance"); return {"on":False}   # 到点自动失效
            except Exception: pass
        return m
    except Exception:
        return {"on":False}

def _maint_block_trading():
    """交易前置闸: 维护态且禁下单 → 503。接入 open/close/repair/close_all + 自动循环入口。"""
    m=_maint_get()
    if m.get("on") and m.get("block_trading"):
        raise HTTPException(503, "系统维护中，暂停交易: "+(m.get("msg") or m.get("title") or "请稍后再试"))

@app.get("/api/bridge/status", dependencies=[Depends(require_license)])
async def bridge_status(x_license: str = Header(default="")):
    try:
        conn=_strict_user_read_conn(_license_to_username(x_license))
        if conn is None:
            return {"ok":False,"connected":False,"error":"user connector unavailable"}
        return {"ok":True, **(await conn.status())}
    except AttributeError:
        return {"ok":False,"connected":False,"error":"user connector unavailable"}
    except Exception as e: raise HTTPException(502, "bridge error: %s"%e)

@app.get("/api/bridge/account", dependencies=[Depends(require_license)])
async def bridge_account(x_license: str = Header(default="")):
    try:
        conn=_strict_user_read_conn(_license_to_username(x_license))
        if conn is None: raise RuntimeError("user connector unavailable")
        return await conn.account_info()
    except Exception as e: raise HTTPException(502, "bridge error: %s"%e)

@app.get("/api/bridge/positions", dependencies=[Depends(require_license)])
async def bridge_positions(x_license: str = Header(default="")):
    try:
        conn=_strict_user_read_conn(_license_to_username(x_license))
        if conn is None: raise RuntimeError("user connector unavailable")
        return await conn.positions()
    except Exception as e: raise HTTPException(502, "bridge error: %s"%e)

# 从 bridge 拉历史成交 -> 入库 deals (凭证不碰, 仅成交记录)
TYPE_MAP={0:"buy",1:"sell",2:"balance"}
ENTRY_MAP={0:"in",1:"out"}
import datetime as _dt

def _persist_user_deals(username, deals):
    """Persist bridge history outside the asyncio event-loop thread."""
    c=None
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s",(username,))
        user=cur.fetchone()
        if not user:
            raise HTTPException(404,"user not found")
        synced=0; skipped=0
        for deal in (deals or []):
            ticket=str(deal.get("ticket") or "")
            if not ticket or ticket=="0":
                continue
            trade_type=int(deal.get("type",-1))
            dtype=TYPE_MAP.get(trade_type,str(trade_type))
            entry=ENTRY_MAP.get(int(deal.get("entry",-1)),"")
            symbol=deal.get("symbol","") or ""
            volume=float(deal.get("volume",0) or 0)
            price=float(deal.get("price",0) or 0)
            profit=float(deal.get("profit",0) or 0)
            swap=float(deal.get("swap",0) or 0)
            commission=float(deal.get("commission",0) or 0)
            comment=deal.get("comment","") or ""
            timestamp=deal.get("time")
            dealt_at=(_dt.datetime.fromtimestamp(timestamp,_dt.timezone.utc)
                      if timestamp else _dt.datetime.now(_dt.timezone.utc))
            cur.execute("""INSERT INTO deals(user_id,ticket,symbol,side,deal_type,entry,lots,price,profit,swap,commission,comment,is_trade,platform,dealt_at)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'MT5',%s)
                           ON CONFLICT (user_id,ticket) DO NOTHING""",
                        (user[0],ticket,symbol,dtype,dtype,entry,volume,price,
                         profit,swap,commission,comment,trade_type in (0,1),dealt_at))
            if cur.rowcount>0: synced+=1
            else: skipped+=1
        R.incr(RNS+"sync:count")
        return {"ok":True,"synced":synced,"skipped_dup":skipped,
                "source":"mt5-bridge"}
    finally:
        if c is not None:
            c.close()

async def _sync_user_deals(username:str, days:int=1, conn=None):
    """Synchronise one user's bridge history without relying on URL identity."""
    username=str(username or "").strip()
    if not username:
        raise HTTPException(400,"username required")
    try:
        conn=conn or _strict_user_read_conn(username)
        if conn is None:
            raise RuntimeError("user connector unavailable")
        data = await conn.history_deals(days=days)
    except Exception as e:
        raise HTTPException(502, "bridge error: %s"%e)
    deals = data.get("deals", data) if isinstance(data, dict) else data
    return await _aio.to_thread(_persist_user_deals,username,list(deals or []))

@app.post("/api/bridge/sync/{username}", dependencies=[Depends(require_subject)])
async def bridge_sync(username:str, days:int=1):
    return await _sync_user_deals(username, days=days)
# ================= 后台自动 sync (P0 加固) =================
import asyncio as _aio

def _auto_sync_usernames():
    c=None
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT username FROM users")
        return [row[0] for row in cur.fetchall()]
    finally:
        if c is not None:
            c.close()

async def _auto_sync_loop():
    await _aio.sleep(10)
    while True:
        try:
            users=await _aio.to_thread(_auto_sync_usernames)
            for un in users:
                try: await _sync_user_deals(un, days=1)
                except Exception as ex: print("auto-sync %s err: %s"%(un,ex))
            R.set(RNS+"autosync:last", _dt.datetime.utcnow().isoformat())
        except Exception as e:
            print("auto-sync loop err:", e)
        await _aio.sleep(60)

@app.on_event("startup")
async def _startup():
    _aio.create_task(_auto_sync_loop())

@app.get("/api/sync/last", dependencies=[Depends(require_license)])
def sync_last():
    return {"last_auto_sync": R.get(RNS+"autosync:last"), "sync_count": R.get(RNS+"sync:count")}
# ================= 引擎循环 (P1) — 单进程 asyncio 管全部用户对 =================
import engine as ENG
import policy as POL   # P1-b 统一Policy(shadow双跑阶段)

def _background_query(sql):
    """Run periodic PostgreSQL reads away from the trade event loop."""
    c=None
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(sql)
        return cur.fetchall()
    finally:
        if c is not None:
            c.close()

_ENGINE_TEMPLATE_QUERY="""SELECT u.username, pt.symbol, pt.entry_spread, pt.tp_points, pt.sl_points,
                                  pt.ladders, pt.hold_secs, pt.weekend_guard,
                                  pt.main_spread_cap, pt.hedge_spread_cap, pt.slippage_tol,
                                  pt.entry_interval_sec, pt.max_inflight, pt.auto_close,
                                  pt.main_lot_mult, pt.hedge_lot_mult, pt.hedge_symbol,
                                  pt.base_lot, pt.basis_offset, pt.data_mult, pt.digits,
                                  pt.single_leg_alert,
                                  pt.match_count, pt.fluctuation_band, pt.weekend_sat, pt.weekend_sun
                           FROM param_templates pt JOIN users u ON u.id=pt.user_id"""

_AUTOMATION_TEMPLATE_QUERY="""SELECT u.username, pt.*,
                                  (COALESCE(u.status,'active') NOT IN ('banned','disabled')
                                   AND (u.expire_at IS NULL OR u.expire_at>=now())) AS account_valid
                           FROM param_templates pt JOIN users u ON u.id=pt.user_id"""

_SAMPLER_TEMPLATE_QUERY="""SELECT DISTINCT ON (u.username) u.username,pt.symbol,pt.hedge_symbol,
                                   pt.sync_interval_sec,pt.records_per_sec
                            FROM param_templates pt JOIN users u ON u.id=pt.user_id
                            ORDER BY u.username,pt.id"""

async def _engine_loop():
    await _aio.sleep(12)
    while True:
        cycle={"ts":_dt.datetime.utcnow().isoformat(),"pairs":0,"gated":0,"single_leg":0}
        cycle_read_error=False
        try:
            # 遍历用户参数模板，评估点差闸（行情接第二腿后补全）
            tmpls=await _aio.to_thread(_background_query,_ENGINE_TEMPLATE_QUERY)
            def _legsum(pl):
                items = pl.get("positions",pl) if isinstance(pl,dict) else (pl or [])
                total=0.0
                for item in items or []:
                    if not isinstance(item,dict):
                        continue
                    try:
                        volume=float(item.get("volume") or 0)
                        if volume>0: total+=volume
                    except (TypeError,ValueError):
                        continue
                return total
            for t in tmpls:
                cycle["pairs"]+=1
                user=t["username"]
                closed,why=ENG.market_closed(
                    weekend_guard=t.get("weekend_guard",True),
                    weekend_sat=t.get("weekend_sat"),weekend_sun=t.get("weekend_sun"))
                market_state={"closed":closed,"why":why}
                R.hset(RNS+"engine:market:user",user,json.dumps(market_state))
                fluct_state={"paused":False,"amp":None,"reason":"off"}
                try:
                    _mc=int(t.get("match_count") or 0); _bd=float(t.get("fluctuation_band") or 0)
                    if _bd>0 and _mc>=2:
                        fl=ENG.fluctuation_guard(_pol_hist(t),_mc,_bd)
                        fluct_state={"paused":fl[0],"amp":fl[1],"reason":fl[2]}
                except Exception:
                    fluct_state={"paused":True,"amp":None,"reason":"read_error"}
                R.hset(RNS+"engine:fluctuation:user",user,json.dumps(fluct_state))
                if closed:
                    cycle["gated"]+=1
                # Monitoring truth is tenant-scoped. A missing registration is
                # an unavailable account, never a fallback to another user.
                conn=_strict_user_read_conn(user)
                acct=None; both_pos=None; mtick=None; htick=None; read_errors=[]
                if conn is None:
                    read_errors.append("connector unavailable")
                else:
                    main_sym=t.get("symbol") or "XAUUSD"
                    hedge_sym=ENG.map_hedge_symbol(main_sym,t.get("hedge_symbol")) or main_sym
                    hedge_leg=getattr(conn,"hedge",None)
                    reads=[conn.account_info(),conn.both_positions(),
                           conn.main._get("/mt5/tick/"+main_sym)]
                    reads.append(hedge_leg._get("/mt5/tick/"+hedge_sym) if hedge_leg is not None
                                 else _aio.sleep(0,result=None))
                    results=await _aio.gather(*reads,return_exceptions=True)
                    acct,both_pos,mtick,htick=results
                    labels=("account","positions","main_tick","hedge_tick")
                    for idx,value in enumerate(results):
                        if isinstance(value,BaseException):
                            read_errors.append("%s:%s"%(labels[idx],value.__class__.__name__))
                    if isinstance(acct,BaseException): acct=None
                    if isinstance(both_pos,BaseException): both_pos=None
                    if isinstance(mtick,BaseException): mtick=None
                    if isinstance(htick,BaseException): htick=None
                    if both_pos is not None and not isinstance(both_pos,dict):
                        read_errors.append("positions:invalid_payload"); both_pos=None
                if read_errors:
                    cycle_read_error=True
                    R.hset(RNS+"engine:err:user",user,";".join(read_errors)[:240])
                else:
                    R.hdel(RNS+"engine:err:user",user)
                R.hset(RNS+"engine:account:user",user,json.dumps(acct,default=str))
                main_lots=_legsum((both_pos or {}).get("main")) if both_pos else 0.0
                hedge_lots=_legsum((both_pos or {}).get("hedge")) if both_pos else 0.0
                basis_off=float(t.get("basis_offset") or 0.0)
                div_key=RNS+"engine:div_tripped:"+user
                div_prev=R.get(div_key)=="1"; div_state=None
                if mtick and htick:
                    dprev=ENG.divergence_guard(
                        mtick.get("bid"),mtick.get("ask"),htick.get("bid"),htick.get("ask"),
                        None,None,0.7,0.3,prev_tripped=div_prev,basis_offset=basis_off)
                    div_state={"paused":dprev[0],"main_spread":dprev[1],
                               "hedge_spread":dprev[2],"reason":dprev[3]}
                    if dprev[3].startswith("diverged") or dprev[3].startswith("still_diverged"):
                        R.set(div_key,"1")
                    elif dprev[3] in ("ok","recovered"):
                        R.set(div_key,"0")
                    if dprev[0] and dprev[3] not in ("ok","recovered"):
                        alert_key=RNS+"engine:div_alert:"+user
                        if R.set(alert_key,"1",nx=True,ex=30):
                            _push_alert("warn","背离/点差护栏: %s"%dprev[3],user)
                R.hset(RNS+"engine:divergence:user",user,json.dumps(div_state))
                # 第二批: 手数倍率参与平衡判定(比例校正单腿) + 下单量目标计算
                _mm=float(t.get("main_lot_mult") or 1.0); _hm=float(t.get("hedge_lot_mult") or 1.0)
                _ratio=(_hm/_mm) if _mm>0 else 1.0
                sl_flag, gap, miss = ENG.single_leg_check(
                    {"main_lots":main_lots,"hedge_lots":hedge_lots}, ratio=_ratio)
                if sl_flag: cycle["single_leg"]+=1
                sizing = ENG.order_lots(t.get("base_lot"), _mm, _hm, rungs=t.get("ladders") or 1)
                # 止盈止损软告警(净浮盈点数代理: 账户 profit)
                net_pts = (acct.get("profit") if acct else None)
                tp_act, tp_reason = ENG.tp_sl_check(net_pts, t.get("tp_points"), t.get("sl_points"))
                if tp_act in ("take_profit","stop_loss") and t.get("auto_close"):
                    _push_alert("err" if tp_act=="stop_loss" else "info",
                        "%s建议: %s (软告警, 平仓需人工确认)"%(tp_act,tp_reason),t["username"])
                R.hset(RNS+"engine:eval", t["username"], json.dumps({
                    "symbol":t["symbol"],"hedge_symbol":ENG.map_hedge_symbol(t["symbol"],t.get("hedge_symbol")),
                    "entry_spread":float(t["entry_spread"]),
                    "g_tp_points":float(t.get("tp_points") or 0),
                    "market":"closed" if closed else "open",
                    "main_lots":round(main_lots,3),"hedge_lots":round(hedge_lots,3),
                    "single_leg":sl_flag,"gap":gap,"missing":miss,
                    "main_lot_mult":_mm,"hedge_lot_mult":_hm,"hedge_ratio":round(_ratio,4),
                    "base_lot":float(t.get("base_lot") or 0),
                    "ladders":int(t.get("ladders") or 0),
                    "target_main_lots":sizing["main_lots"],"target_hedge_lots":sizing["hedge_lots"],
                    "main_spread_cap":float(t.get("main_spread_cap") or 0),"hedge_spread_cap":float(t.get("hedge_spread_cap") or 0),
                    "slippage_tol":float(t.get("slippage_tol") or 0),"entry_interval_sec":int(t.get("entry_interval_sec") or 0),
                    "divergence":div_state,"tp_sl":{"action":tp_act,"reason":tp_reason},
                    "status":"single_leg_alert" if sl_flag else ("divergence_pause" if (div_state and div_state["paused"]) else ("market_closed" if closed else "hedged_ok"))}))
                # 第三批: 单腿告警开关 — 默认开(NULL/旧行仍告警); 关则不推飞书/跑马灯, 但 eval 仍标记 single_leg(只读监控不蒙蔽)
                _sla = t.get("single_leg_alert")
                _sla = True if _sla is None else bool(_sla)
                if sl_flag and miss and _sla:
                    # 30s 节流+同轮多模板去重(原每模板行各推一条=×2重复+6s刷屏; RecoveryWorker 为权威对账方)
                    if R.set(RNS+"sla:cool:%s:%s"%(t["username"],miss),"1",nx=True,ex=30):
                        _push_alert("err","单腿告警 %s 缺口%.3f"%(miss,gap),t["username"])
            R.set(RNS+"engine:cycle", json.dumps(cycle))
            R.set(RNS+"engine:cycle_ts", _dt.datetime.utcnow().isoformat())   # 循环心跳戳(供运维监控算新鲜度)
            if not cycle_read_error:
                R.delete(RNS+"engine:err")
        except Exception as e:
            R.set(RNS+"engine:err", "loop:%s"%e)
        await _aio.sleep(5)

@app.on_event("startup")
async def _startup_engine():
    _aio.create_task(_engine_loop())

# ================= 点差采样循环 (数据同步: 按 sync_interval_sec/records_per_sec 节流写 spread:hist) =================
async def _spread_sampler():
    await _aio.sleep(14)
    due={}

    async def sample(row):
        user=row.get("username") or ""
        main_sym=row.get("symbol") or "XAUUSD"
        hedge_sym=ENG.map_hedge_symbol(main_sym,row.get("hedge_symbol")) or main_sym
        conn=_strict_user_read_conn(user)
        if conn is None or getattr(conn,"main",None) is None or getattr(conn,"hedge",None) is None:
            raise RuntimeError("user connector unavailable")
        mt,ht=await _aio.gather(
            conn.main._get("/mt5/tick/"+main_sym),
            conn.hedge._get("/mt5/tick/"+hedge_sym))
        if not mt or not ht or mt.get("ask") is None or ht.get("ask") is None:
            raise RuntimeError("tick unavailable")
        fs=round(float(mt["ask"])-float(ht["bid"]),5)
        rs=round(float(ht["ask"])-float(mt["bid"]),5)
        rps=max(1,int(row.get("records_per_sec") or 1))
        hist_key=RNS+"spread:hist:"+user
        payload=json.dumps({"t":_dt.datetime.utcnow().isoformat()+"Z","fs":fs,"rs":rs})
        pipe=R.pipeline()
        for _ in range(min(rps,20)):
            pipe.rpush(hist_key,payload)
        pipe.ltrim(hist_key,-60000,-1); pipe.execute()
        stamp=_dt.datetime.utcnow().isoformat()
        R.hset(RNS+"engine:sampler_ts:user",user,stamp)
        R.hdel(RNS+"engine:sampler_err:user",user)
        return True

    while True:
        try:
            rows=await _aio.to_thread(_background_query,_SAMPLER_TEMPLATE_QUERY)
        except Exception as e:
            R.set(RNS+"engine:sampler_err","templates:%s"%str(e)[:160])
            await _aio.sleep(1); continue
        now=_t_conn.time(); pending=[]; pending_users=[]
        for row in rows:
            user=row.get("username") or ""
            try: interval=max(0.25,float(row.get("sync_interval_sec") or 1.0))
            except (TypeError,ValueError): interval=1.0
            if now<due.get(user,0):
                continue
            due[user]=now+interval; pending.append(sample(row)); pending_users.append(user)
        if pending:
            results=await _aio.gather(*pending,return_exceptions=True)
            failures=[]
            for user,result in zip(pending_users,results):
                if isinstance(result,BaseException):
                    msg="%s:%s"%(result.__class__.__name__,str(result)[:100])
                    failures.append(user+":"+msg); R.hset(RNS+"engine:sampler_err:user",user,msg)
            if len(failures)<len(results):
                R.set(RNS+"engine:sampler_ts",_dt.datetime.utcnow().isoformat())
            R.set(RNS+"engine:sampler_err",";".join(failures)[:500])
        await _aio.sleep(0.25)

@app.on_event("startup")
async def _startup_sampler():
    _aio.create_task(_spread_sampler())

# ================= 流失召回定时任务(第二阶段; 业务层, 绝不进交易引擎) =================
# 每日扫一次: 试用到期(前3天/当天/后7天未转化) + 订阅到期(后7天未续) → 落跑马灯馈源 marquee_recent(个性化提示)。
# 单 worker 内存态; 用 Redis 当日键防重复推送。发券留给运营在 qhadmin 建"召回券"活动券, 此处只推提醒(不自动造券, 避免误发)。
def _recall_config():
    """召回开关/文案(存 channels.json 的 recall 段, 与飞书凭证同源; 缺省关闭)。"""
    try:
        cfg=_chcfg_load().get("recall",{})
        return {"enabled":bool(cfg.get("enabled")), "coupon_trial":cfg.get("coupon_trial",""), "coupon_sub":cfg.get("coupon_sub","")}
    except Exception:
        return {"enabled":False,"coupon_trial":"","coupon_sub":""}
def _recall_push(title, content, priority=1, color="#E6A23C"):
    """落一条召回跑马灯馈源(与 notify_broadcast 同一 marquee_recent 列表; 用户端轮询消费)。"""
    payload={"title":title,"content":content,"priority":priority,"color":color,"blink":False,"sound":"none",
             "src":"recall","ts":_dt.datetime.utcnow().isoformat()}
    try:
        R.lpush(RNS+"marquee_recent",json.dumps(payload)); R.ltrim(RNS+"marquee_recent",0,49)
    except Exception: pass
async def _recall_loop():
    await _aio.sleep(40)   # 启动后错峰
    while True:
        try:
            cfg=_recall_config()
            today=_dt.datetime.utcnow().strftime("%Y%m%d")
            dk=RNS+"recall:daily:"+today
            if cfg["enabled"] and not R.get(dk):
                c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                # 试用到期前3天内 或 到期后7天内、且未转化(paid_until 为空)的用户数
                cur.execute("""SELECT count(*) n FROM users
                               WHERE trial_until IS NOT NULL AND paid_until IS NULL
                               AND trial_until BETWEEN now()-interval '7 days' AND now()+interval '3 days'""")
                n_trial=cur.fetchone()["n"]
                # 订阅到期后7天内未续(paid_until 已过但在7天内)
                cur.execute("""SELECT count(*) n FROM users
                               WHERE paid_until IS NOT NULL AND paid_until BETWEEN now()-interval '7 days' AND now()""")
                n_sub=cur.fetchone()["n"]
                c.close()
                if n_trial>0:
                    ct=(" 专属券:"+cfg["coupon_trial"]) if cfg["coupon_trial"] else ""
                    _recall_push("试用即将到期", "有 %d 位试用用户临近/刚到期未转化, 记得跟进转化。%s"%(n_trial,ct), 1, "#E6A23C")
                if n_sub>0:
                    cs=(" 回归券:"+cfg["coupon_sub"]) if cfg["coupon_sub"] else ""
                    _recall_push("订阅到期召回", "有 %d 位订阅用户到期未续费, 建议推送回归优惠。%s"%(n_sub,cs), 1, "#E6A23C")
                # 活动引擎: 逐用户触发 recall_trial / recall_sub(如自动发回归专属券)。当日键防重复扫。
                try:
                    c2=db(); cur2=c2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                    cur2.execute("""SELECT id,username FROM users WHERE trial_until IS NOT NULL AND paid_until IS NULL
                                    AND trial_until BETWEEN now()-interval '7 days' AND now()+interval '3 days' LIMIT 500""")
                    for uu in cur2.fetchall(): _fire_campaigns(cur2, "recall_trial", uu["id"], uu["username"], {})
                    cur2.execute("""SELECT id,username FROM users WHERE paid_until IS NOT NULL
                                    AND paid_until BETWEEN now()-interval '7 days' AND now() LIMIT 500""")
                    for uu in cur2.fetchall(): _fire_campaigns(cur2, "recall_sub", uu["id"], uu["username"], {})
                    c2.close()
                except Exception as ce: print("camp recall err",ce)
                R.setex(dk, 172800, "1")   # 当日已扫(48h TTL)
        except Exception as e:
            print("recall_loop err",e)
        await _aio.sleep(3600)   # 每小时检查一次(当日键保证只推一次)
@app.on_event("startup")
async def _startup_recall():
    _aio.create_task(_recall_loop())

# ================= 周期冲榜赛结算(月度/季度; 业务层, 绝不进交易引擎) =================
def _period_bounds(period, ref=None):
    """返回"上一个已结束周期"的 (period_key, start, end)。period=month|quarter。
       ref=参考时刻(默认现在)。月: 上月; 季: 上一季。"""
    now=ref or _dt.datetime.utcnow()
    if period=="quarter":
        q=(now.month-1)//3           # 当前季 0-3
        # 上一季
        if q==0: y=now.year-1; pq=3
        else: y=now.year; pq=q-1
        sm=pq*3+1; start=_dt.datetime(y,sm,1)
        em=sm+3; ey=y+(1 if em>12 else 0); em=em-12 if em>12 else em
        end=_dt.datetime(ey,em,1)
        return ("%d-Q%d"%(y,pq+1), start, end)
    else:  # month
        y=now.year; m=now.month-1
        if m==0: y-=1; m=12
        start=_dt.datetime(y,m,1)
        em=m+1; ey=y+(1 if em>12 else 0); em=em-12 if em>12 else em
        end=_dt.datetime(ey,em,1)
        return ("%d-%02d"%(y,m), start, end)
def _contest_rank(cur, kind, metric, start, end):
    """返回 [(code,name,metric_value,owner_username)] 按 metric_value 降序。
       kind=staff: 按 users.staff_code 归因; kind=agent: 按 users.agent_id→agents。
       metric: paid_users(周期内首次付费用户数)/revenue(周期内订单额)/trials(周期内试用数)/new_users(周期内注册数)。"""
    rows=[]
    if kind=="staff":
        if metric=="revenue":
            cur.execute("""SELECT s.code,s.name, COALESCE(SUM(o.amount),0) v, ''::text owner
                           FROM staff s LEFT JOIN iap_orders o ON o.staff_code=s.code AND o.status='paid'
                             AND o.kind IN ('iap','subscription') AND o.paid_at>=%s AND o.paid_at<%s
                           GROUP BY s.code,s.name ORDER BY v DESC""",(start,end))
        else:
            col={"paid_users":"count(DISTINCT u.id) FILTER (WHERE u.paid_until IS NOT NULL AND u.created_at>=%s AND u.created_at<%s)",
                 "trials":"count(u.id) FILTER (WHERE u.trial_started>=%s AND u.trial_started<%s)",
                 "new_users":"count(u.id) FILTER (WHERE u.created_at>=%s AND u.created_at<%s)"}.get(metric)
            if not col: return []
            cur.execute("""SELECT s.code,s.name, %s v, ''::text owner
                           FROM staff s LEFT JOIN users u ON u.staff_code=s.code
                           GROUP BY s.code,s.name ORDER BY v DESC"""%col,(start,end))
        rows=[(r["code"],r["name"],float(r["v"] or 0),None) for r in cur.fetchall()]
    else:  # agent
        if metric=="revenue":
            cur.execute("""SELECT a.code,a.name,a.owner_username, COALESCE(SUM(o.amount),0) v
                           FROM agents a LEFT JOIN users u ON u.agent_id=a.id
                             LEFT JOIN iap_orders o ON o.user_id=u.id AND o.status='paid'
                             AND o.kind IN ('iap','subscription') AND o.paid_at>=%s AND o.paid_at<%s
                           GROUP BY a.code,a.name,a.owner_username ORDER BY v DESC""",(start,end))
        else:
            col={"paid_users":"count(DISTINCT u.id) FILTER (WHERE u.paid_until IS NOT NULL AND u.created_at>=%s AND u.created_at<%s)",
                 "new_users":"count(u.id) FILTER (WHERE u.created_at>=%s AND u.created_at<%s)"}.get(metric)
            if not col: return []
            cur.execute("""SELECT a.code,a.name,a.owner_username, %s v
                           FROM agents a LEFT JOIN users u ON u.agent_id=a.id
                           GROUP BY a.code,a.name,a.owner_username ORDER BY v DESC"""%col,(start,end))
        rows=[(r["code"],r["name"],float(r["v"] or 0),r["owner_username"]) for r in cur.fetchall()]
    return [r for r in rows if r[2]>0]   # 仅有成绩者上榜
def _contest_settle(cur, cp, period_key, start, end, actor="system"):
    """结算一个冲榜赛周期: 排名→分档发奖→落 contest_results→更 last_settled_period。返回发奖条数。"""
    ranked=_contest_rank(cur, cp["kind"], cp["metric"], start, end)
    ranked=ranked[:int(cp["top_n"] or 10)]
    rewards=cp["rewards"] or []
    def _reward_for(rank):   # rank 1-based
        for rw in rewards:
            if int(rw.get("rank_from",1))<=rank<=int(rw.get("rank_to",1)): return rw
        return None
    n=0
    for i,(code,name,mv,owner) in enumerate(ranked):
        rank=i+1; rw=_reward_for(rank)
        rtype=""; rval=0; rto=""
        if rw:
            rtype=rw.get("type","points"); rval=float(rw.get("value") or 0)
            try:
                if cp["kind"]=="staff" and rtype=="perf":
                    _perf_add(cur, code, int(rval), "冲榜赛[%s]第%d名"%(cp["name"],rank), "contest", period_key, actor); rto=code
                elif rtype=="points":
                    # 发积分: staff 无 owner 概念→跳过(改用 perf); agent 发 owner
                    tgt = owner if cp["kind"]=="agent" else None
                    if tgt:
                        tuid=_uid(tgt)
                        if tuid: _points_add(cur, tuid, int(rval), "冲榜赛[%s]第%d名"%(cp["name"],rank), "contest", period_key, actor); rto=tgt
            except Exception as e: print("contest reward err",e)
        cur.execute("""INSERT INTO contest_results(contest_id,period_key,rank,code,name,metric_value,reward_type,reward_value,reward_to)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(cp["id"],period_key,rank,code,name,mv,rtype,rval,rto))
        n+=1
    cur.execute("UPDATE contests SET last_settled_period=%s,updated_at=now() WHERE id=%s",(period_key,cp["id"]))
    return n
async def _contest_loop():
    await _aio.sleep(70)   # 启动错峰
    while True:
        try:
            c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT * FROM contests WHERE enabled=true")
            for cp in cur.fetchall():
                pk,start,end=_period_bounds(cp["period"])
                if (cp.get("last_settled_period") or "")==pk: continue   # 该周期已结算
                try:
                    n=_contest_settle(cur, cp, pk, start, end)
                    _recall_push("冲榜赛结算", "活动[%s] %s 周期已结算, %d 名上榜发奖。"%(cp["name"],pk,n), 1, "#2E8BD6")
                except Exception as e: print("contest settle err",e)
            c.close()
        except Exception as e:
            print("contest_loop err",e)
        await _aio.sleep(3600)   # 每小时检查(周期键防重, 只在跨周期后结算一次)
@app.on_event("startup")
async def _startup_contest():
    _aio.create_task(_contest_loop())

# ================= 买入点位=入场下限(点差须≥阈值才进) 统一判定(引擎+手动一致) =================
def _entry_gate(ov, gthr, cur_sp, fee_pts=0.0):
    """买入点位=入场下限: 当前点差 >= 下限 才进(点差要超过阈值才进; 与出场"点差≤卖出点位才卖"相反)。
       三态: 无覆盖(ov=None)→回落全局 entry_spread(gthr; 0则不限); 覆盖 buy_point=None→任意点差都开(无下限);
             数字(含0)→该值为下限(0=点差须≥0, 挡负点差)。费用 fee_pts 抬高下限(点差须更大以覆盖费用)。
       返回 (通过?, 有效下限或None)。cur_sp=None(无行情)时不拦(上层另有护栏)。"""
    if ov is not None and ("buy_point" in ov):
        bp = ov.get("buy_point")
        lb = None if bp is None else float(bp)
    else:
        lb = gthr if (gthr and gthr > 0) else None
    if lb is None:
        return True, None
    lb_eff = lb + (fee_pts or 0.0)
    if cur_sp is None:
        return True, lb_eff
    return (float(cur_sp) >= lb_eff), lb_eff

# ---- P1-b shadow双跑助手(阶段B): 内联闸放行到达执行点后, policy重裁; 分歧落红。全包try绝不影响交易 ----
def _pol_hist(t):
    """与内联波动闸同源取近 match_count 条 fs(shadow对拍输入)。"""
    try:
        _mc=int(t.get("match_count") or 0)
        if _mc<2: return []
        username=str(t.get("username") or "").strip()
        hist_key=RNS+"spread:hist:"+username if username else RNS+"spread:hist"
        return [json.loads(x).get("fs") for x in (R.lrange(hist_key,-_mc,-1) or [])]
    except Exception: return []

def _pol_shadow(path, thunk, ctx=""):
    """path: entry.auto|entry.manual|exit.auto。thunk()→(blocked,gate,why)。
       内联已放行, policy 若说 blocked=提取分歧 → mismatch+样本; 一致→ok计数。开关 qh:policy:mode。"""
    try:
        if (R.get(RNS+"policy:mode") or "shadow")=="off": return
        blocked,gate,why=thunk()
        if blocked:
            R.incr(RNS+"policy:shadow:%s:mismatch"%path)
            R.lpush(RNS+"policy:shadow:samples", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),
                "path":path,"gate":gate,"why":str(why)[:120],"ctx":str(ctx)[:120]}))
            R.ltrim(RNS+"policy:shadow:samples",0,49)
        else:
            R.incr(RNS+"policy:shadow:%s:ok"%path)
    except Exception:
        try: R.incr(RNS+"policy:shadow:err")
        except Exception: pass

# ================= 全自动平仓循环 (逐对盈亏判定 → 按模式平仓; 默认 OFF) =================
# 模式(Redis qh:auto_exit:{user}): off=不动 / armed=平武装坑(卖出点位启用→卖点/止盈/超时; 止损平仓→止损)。
# armed 由坑位规则保存自动派生(_recompute_auto_masters); 旧 shadow/full 遗留态分别归一为 off/armed。
async def _close_one_pair(username, symbol, hedge_sym, main_side, hedge_side, mode_seq, speed, slot_no, reason):
    """真实平一坑(带裸空守护+账本弹出); 复用 close_pair 内核。返回 (ok, detail)。"""
    res=await _exec_close_pair(symbol, hedge_sym, main_side, hedge_side, None, None, mode_seq, speed, username=username)
    account_token=(res or {}).pop("_account_op_token",None)
    if _pair_pending(res):
        try:
            res=await _user_exec_conn(username).resolve_pair_pending(res,timeout=60.0)
        finally:
            _release_account_op(username,account_token)
    mok=_resolved_leg_ok(res,"main"); hok=_resolved_leg_ok(res,"hedge")
    if mok != hok:
        _halt_auto_entry(username,"single_leg_exposed",{"slot":slot_no,"symbol":symbol,
            "res":res,"op":"auto_close"})
        _push_alert("err","自动平仓坑%s：仅一腿确认平仓，已停止进单并保留账本"%slot_no,username)
        _audit(username,"auto","auto_exit",{"slot":slot_no,"res":res},False,"NAKED_RISK_single_leg_close")
        return False,res
    if not mok and not hok:
        _audit(username,"auto","auto_exit",{"slot":slot_no,"res":res},False,"both_legs_failed")
        return False,res
    _dir="reverse" if main_side=="sell" else "forward"
    close_commit_id="auto-exit:%s:%s:%s:%s"%(
        username,symbol,slot_no,str((res or {}).get("request_id") or os.urandom(8).hex()))
    if not _close_ledger_commit_once(
            close_commit_id,RNS+"ledger:"+username+":"+_dir,slot_no):
        _push_alert("err","自动平仓坑%s已确认平仓，但精确账本提交失败"%slot_no,username)
        _audit(username,"auto","auto_exit",{"slot":slot_no,"res":res},False,"close_ledger_commit_failed")
        return False,res
    _persist_after_close()
    _audit(username,"auto","auto_exit",{"slot":slot_no,"reason":reason},DEMO_MODE,"auto_closed")
    return True,res

def _publish_auto_exit_decisions(username, mode, items=None, **extra):
    """Publish the current auto-exit snapshot, including an explicit empty set.

    The UI treats this key as a live status snapshot.  Leaving the previous
    Redis value in place after the last position closes makes the header keep
    reporting a stale pending slot indefinitely.
    """
    payload={"ts":_dt.datetime.utcnow().isoformat(),"mode":mode,
             "items":list(items or [])}
    payload.update(extra)
    R.set(RNS+"auto_exit:decisions:"+username,
          json.dumps(payload,ensure_ascii=False))
    return payload

async def _auto_exit_loop():
    await _aio.sleep(16)
    while True:
        try:
            await _aio.to_thread(_reconcile_invalid_auto_users)
            tmpls=await _aio.to_thread(
                _background_query,_AUTOMATION_TEMPLATE_QUERY)
        except Exception as e:
            R.set(RNS+"auto_exit:err","tmpl:%s"%e); await _aio.sleep(5); continue
        # 执行链路闸已下沉为按用户(见循环内 _conn_block_reason(user)): 别人桥挂不拦本用户平仓
        # 多租户: 持仓改逐用户读(下移进循环, 仅活跃用户才读, 省 A2T 配额)
        for t in tmpls:
            user=t["username"]; sym=t.get("symbol") or "XAUUSD"
            mode=R.get(RNS+"auto_exit:"+user) or "off"
            if not t.get("account_valid"):
                _auto_validity_disarm("exit",user,mode)
                continue
            _own=await _exec_owner_reason(user)   # 多用户串账墙: 平错桥=平别人仓, fail-closed跳过
            if _own:
                if R.set(RNS+"exec:ownerwarn:"+user,"1",nx=True,ex=300):
                    _push_alert("warn","自动平仓跳过: %s"%_own,user)
                continue
            if mode=="shadow": R.set(RNS+"auto_exit:"+user,"off"); mode="off"   # 影子已废除, 遗留态归一为关闭
            if mode=="full": R.set(RNS+"auto_exit:"+user,"armed"); mode="armed" # full 已废除(武装粒度下沉逐坑), 归一为 armed
            if mode=="off": continue
            _blk=await _conn_block_reason(user)   # P0同款按用户健康闸: 该用户自己桥离线才跳过
            if _blk:
                if R.set(RNS+"conn:autoexit_warn:"+user,"1",nx=True,ex=300):
                    _push_alert("warn","自动平仓暂停: %s"%_blk,user)
                continue
            # P1-b enforce: 循环级三闸(auto_close总闸→run_window休市可手平→market_closed避免休市单腿)统一走 policy
            if POL.exit_loop_verdict(t,_bj_hm())[0]: continue
            hedge_sym=ENG.map_hedge_symbol(sym,t.get("hedge_symbol")) or sym
            decision_conn=_user_exec_conn(user)
            try: both=await decision_conn.both_positions()
            except Exception: both=None
            try:
                close_index=_index_close_positions(both,sym,user)
            except HTTPException as ex:
                detail=str(ex.detail)[:200]
                _publish_auto_exit_decisions(user,mode,[],
                    blocked="position_ownership",detail=detail)
                if R.set(RNS+"auto_exit:positionwarn:"+user+":"+sym,"1",nx=True,ex=300):
                    _push_alert("err","AUTO_EXIT_BLOCKED: %s"%detail,user)
                continue
            if not close_index:
                # A successful empty snapshot is authoritative: clear the
                # previous pending decisions as soon as the last slot closes.
                _publish_auto_exit_decisions(user,mode,[],positions=0)
                continue
            # 双腿 tick 算当前点差
            mt=ht=None
            try: mt=await decision_conn.main._get("/mt5/tick/"+sym)
            except Exception: pass
            try: ht=await decision_conn.hedge._get("/mt5/tick/"+hedge_sym) if getattr(decision_conn,"hedge",None) else None
            except Exception: pass
            _csize_key=user+":"+sym
            if _csize_key not in _CSIZE:   # Contract metadata follows the user's execution bridge.
                _cs=float(_CSIZE.get(sym) or 100.0)
                try:
                    _si=await decision_conn.main._get("/mt5/symbol_info/"+sym)
                    fetched=float(_si.get("trade_contract_size") or 0)
                    if fetched>0: _cs=fetched
                except Exception: pass
                _CSIZE[_csize_key]=_cs
            slotcfg=R.hgetall(_slot_key(user,sym)) or {}
            xmode=(t.get("exit_mode") or "concurrent"); speed=(t.get("speed_mode") or "fast")
            if xmode not in ("concurrent","main_first","hedge_first"): xmode="concurrent"
            profit_first = (R.get(RNS+"sw:profitfirst:"+user)=="1")  # 盈利平台优先(前端落)
            now_ts=_dt.datetime.utcnow().timestamp()
            _bkoff=await _broker_utc_offset("main",decision_conn,user)   # 持仓 time=经纪商墙钟, 算 elapsed 前须转真UTC
            _hold_en=(R.get(RNS+"sw:entrymech:"+user)!="0")   # 进单机制开关: 关→持仓时长超时平仓不触发
            _bm={slot:pair.get("main") for slot,pair in close_index.items() if pair.get("main")}
            _bh={slot:pair.get("hedge") for slot,pair in close_index.items() if pair.get("hedge")}
            decisions=[]
            for slot_no in sorted(set(_bm)|set(_bh)):
                m=_bm.get(slot_no); h=_bh.get(slot_no)
                net,_mp,_hp=ENG.pair_pnl_live(m,h)
                # 该坑当前点差: 主腿 sell(reverse)=对冲ASK-主BID; buy(forward)=主ASK-对冲BID
                cur_sp=None
                if mt and ht:
                    mside=("sell" if (m and (str(m.get("type"))=="1" or m.get("side")=="sell")) else "buy")
                    if mside=="sell": cur_sp=round(float(ht.get("ask",0))-float(mt.get("bid",0)),4)
                    else:             cur_sp=round(float(mt.get("ask",0))-float(ht.get("bid",0)),4)
                # 持仓时长(opent=经纪商墙钟epoch → 转真UTC 再与 now_ts(UTC) 相减)
                opent=(m or h or {}).get("time") or 0
                elapsed=(now_ts-(float(opent)-_bkoff)) if opent else 0
                # 逐坑覆盖
                ov=None
                try: ov=json.loads(slotcfg.get(str(slot_no))) if slotcfg.get(str(slot_no)) else None
                except Exception: ov=None
                sell_point=float(ov.get("sell_point") or 0) if ov else 0
                exit_enabled=bool(ov.get("exit_enabled")) if ov else False   # 卖出点位启用=武装本坑自动平仓(卖点/止盈/超时)
                sl_en=bool(ov.get("sl_enabled")) if ov else False            # 止损平仓=武装本坑止损强制平仓(独立开关)
                if not exit_enabled and not sl_en: continue   # 本坑未武装任何自动平仓路径→跳过
                # 逐坑止盈/止损覆盖全局(0/缺省→回落全局)
                _tp = (float(ov.get("tp_points") or 0) if ov and ov.get("tp_points") else None) or t.get("tp_points")
                _sl = (float(ov.get("sl_points") or 0) if ov and ov.get("sl_points") else None) or t.get("sl_points")
                # 盈利/止损点位=点差净盈亏点数: 把$净盈亏折成点(/手数/面值)再比较
                _vol=float((m or h or {}).get("volume") or 0)
                net_pts=_pnl_to_points(net, _vol, sym, user)
                net_pts=_round_pts(net_pts, t.get("digits_main"), t.get("digits_hedge"))
                # 路径门控: 卖点/止盈/超时 仅在 卖出点位启用 时参与; 止损 仅在 止损平仓 时参与(且引擎内不受盈利闸限制)
                go,reason=ENG.auto_exit_decision(net_pts,cur_sp,elapsed,
                              (_tp if exit_enabled else None),(_sl if sl_en else None),
                              ((t.get("hold_secs") if _hold_en else None) if exit_enabled else None),
                              sell_point=sell_point,exit_enabled=exit_enabled,profit_first=profit_first)
                if not go: continue
                mside=("sell" if (m and (str(m.get("type"))=="1" or m.get("side")=="sell")) else "buy")
                hside=("sell" if (h and (str(h.get("type"))=="1" or h.get("side")=="sell")) else "buy")
                decisions.append({"slot":slot_no,"reason":reason,"net":net,"spread":cur_sp,"mside":mside,"hside":hside,
                                  "armed":exit_enabled,"main_ticket":(m or {}).get("ticket"),
                                  "hedge_ticket":(h or {}).get("ticket"),"main_vol":(m or {}).get("volume"),
                                  "hedge_vol":(h or {}).get("volume")})
            # 发布决策(影子/真平都先回显)
            _publish_auto_exit_decisions(user,mode,decisions,
                                         positions=len(close_index))
            close_items=[]
            for d in decisions:
                lockkey=RNS+"auto_exit:lock:"+user+":"+sym+":"+str(d["slot"])
                if mode=="shadow":
                    _push_alert("info","[影子]将平坑%d: %s 净%.2f"%(d["slot"],d["reason"],d["net"]),user)
                    continue
                # (武装过滤已在决策生成前逐坑完成: 未武装坑不进 decisions)
                # 在途锁 + 冷却(30s): 防 5s 循环重复发
                if R.get(lockkey): continue
                R.setex(lockkey, 30, "1")
                if d.get("main_ticket") and d.get("hedge_ticket"):
                    close_items.append({"op":"close_pair","slot":d["slot"],"main_side":d["mside"],
                        "hedge_side":d["hside"],"main_ticket":d["main_ticket"],"hedge_ticket":d["hedge_ticket"],
                        "main_vol":d.get("main_vol") or 0,"hedge_vol":d.get("hedge_vol") or 0,
                        "reason":d["reason"],"net":d["net"]})
                else:
                    leg="main" if d.get("main_ticket") else "hedge"
                    ticket=d.get("main_ticket") or d.get("hedge_ticket")
                    if ticket:
                        close_items.append({"op":"close_leg","slot":d["slot"],"leg":leg,
                            "side":d["mside"] if leg=="main" else d["hside"],"ticket":ticket,
                            "volume":d.get("main_vol") if leg=="main" else d.get("hedge_vol"),
                            "reason":d["reason"],"net":d["net"]})
            if close_items:
                try:
                    await _enqueue_close_items(user,sym,"auto",close_items,"auto_exit")
                    _push_alert("info","自动平仓已优先受理 %d 个坑"%len(close_items),user)
                except HTTPException as ex:
                    if ex.status_code!=409:
                        _push_alert("err","自动平仓批量受理失败: %s"%str(ex.detail)[:120],user)
        R.set(RNS+"auto_exit:last", _dt.datetime.utcnow().isoformat())
        await _aio.sleep(5)

@app.on_event("startup")
async def _startup_auto_exit():
    _aio.create_task(_auto_exit_loop())

# ================= 全自动进单循环 (与自动平仓对称; 逐坑按买入点位+全局阈值+各护栏自动开仓; 默认 OFF) =================
# 模式(Redis qh:auto_entry:{user}): off / armed(开 entry_state 设了方向的武装空坑)。armed 由坑位规则保存自动派生。
# 方向=逐坑 entry_state: forward(正向2空1涨)/reverse(反向1空2涨)/both(全开: 双向哪边点差到买入点位开哪边)。
# 旧全局方向键 qh:auto_entry_dir 已废除不再消费; 旧 shadow/full 遗留态分别归一为 off/armed。
def _auto_entry_paused():
    try:
        if R.get(RNS+"global_estop")=="1":
            return "global_estop"
        m=_maint_get()
        if m.get("on") and (m.get("stop_strategy") or m.get("block_trading")):
            return "maintenance"
        return ""
    except Exception:
        return "safety_state_unavailable"

async def _auto_entry_loop():
    await _aio.sleep(18)
    while True:
        pause_reason=_auto_entry_paused()
        if pause_reason:
            R.set(RNS+"auto_entry:paused",json.dumps({"ts":_dt.datetime.utcnow().isoformat(),
                  "reason":pause_reason},ensure_ascii=False))
            await _aio.sleep(5)
            continue
        R.delete(RNS+"auto_entry:paused")
        try:
            await _aio.to_thread(_reconcile_invalid_auto_users)
            tmpls=await _aio.to_thread(
                _background_query,_AUTOMATION_TEMPLATE_QUERY)
        except Exception as e:
            R.set(RNS+"auto_entry:err","tmpl:%s"%e); await _aio.sleep(5); continue
        # 执行链路闸已下沉为按用户(见循环内 _conn_block_reason(user)): 别人桥挂不拦本用户进单
        # 多租户: 持仓改逐用户读(下移进循环)
        for t in tmpls:
            user=t["username"]; sym=t.get("symbol") or "XAUUSD"
            mode=R.get(RNS+"auto_entry:"+user) or "off"
            if not t.get("account_valid"):
                _auto_validity_disarm("entry",user,mode)
                continue
            # 多用户串账墙: 登记账户≠执行桥账户→跳过该用户(防串账), 5min冷却告警
            _own=await _exec_owner_reason(user)
            if _own:
                if R.set(RNS+"exec:ownerwarn:"+user,"1",nx=True,ex=300):
                    _push_alert("warn","自动进单跳过: %s"%_own,user)
                continue
            if mode=="shadow": R.set(RNS+"auto_entry:"+user,"off"); mode="off"   # 影子已废除, 遗留态归一为关闭
            if mode=="full": R.set(RNS+"auto_entry:"+user,"armed"); mode="armed" # full 已废除(武装粒度下沉逐坑), 归一为 armed
            if mode=="off": continue
            _blk=await _conn_block_reason(user)   # P0同款按用户健康闸: 该用户自己桥离线才跳过
            if _blk:
                if R.set(RNS+"conn:autoentry_warn:"+user,"1",nx=True,ex=300):
                    _push_alert("warn","自动进单暂停: %s"%_blk,user)
                continue
            # 运行时段/进单时段闸(北京): 运行时段外→系统不进单; 进单时段外→不开仓(手动/自动一致)
            if POL.gate_window(t,"run",_bj_hm())[0]: continue
            if POL.gate_window(t,"entry",_bj_hm())[0]: continue
            # 休市/周末闸 — P1-b enforce: 统一走 policy
            closed,_why=POL.gate_market_closed(t)
            if closed: continue
            ladders=int(t.get("ladders") or 0) or 0
            if ladders<=0: continue
            decision_conn=_user_exec_conn(user)
            try: both=await decision_conn.both_positions()
            except Exception: both=None
            if both is None:
                if R.set(RNS+"position_read:warn:"+user,"1",nx=True,ex=300):
                    _push_alert("warn","自动进场暂停: 持仓读取失败(fail-closed)",user)
                continue
            _cap=_entry_capacity_guard_from_positions(user,both,requested=1)
            if _cap:
                _latch_entry_capacity(user,_cap,"auto_preflight")
                continue
            # gap-aware 空坑集合(支持坑号跳空: 定向开仓可能已占中间坑)
            _ann=_annotate_slots(both, sym, user)
            _occ=set()
            for _lg in ("main","hedge"):
                for _p in (_ann.get(_lg) or []):
                    _s=int(_p.get("slot") or 0)
                    if _s>0: _occ.add(_s)
            slotcfg=R.hgetall(_slot_key(user,sym)) or {}
            # 武装空坑候选(坑号升序=顺序填坑): entry_state 设了方向才武装; 旧 entry_enabled 不视为武装(兼容: 绝不静默武装旧数据)
            cands=[]
            for _s in range(1,ladders+1):
                if _s in _occ: continue
                _ov=None
                try: _ov=json.loads(slotcfg.get(str(_s))) if slotcfg.get(str(_s)) else None
                except Exception: _ov=None
                _st=((_ov or {}).get("entry_state") or "")
                if _st not in ("both","forward","reverse"): continue
                if _ov.get("entry_enabled") is False: continue   # 旧禁用黑名单仍尊重
                cands.append((_s,_ov,_st))
            if not cands: continue   # 无武装空坑
            hedge_sym=ENG.map_hedge_symbol(sym,t.get("hedge_symbol")) or sym
            # 双腿 tick → 两方向点差(reverse=对冲ASK-主BID / forward=主ASK-对冲BID)
            mt=ht=None
            try: mt=await decision_conn.main._get("/mt5/tick/"+sym)
            except Exception: pass
            try: ht=await decision_conn.hedge._get("/mt5/tick/"+hedge_sym) if getattr(decision_conn,"hedge",None) else None
            except Exception: pass
            if not mt or not ht: continue
            # 行情新鲜度闸(V1.1移植): 桥半开/报价冻结→陈旧价, fail-closed 跳过本轮(5min冷却告警)
            _stq=await _quote_stale(mt,ht,decision_conn,user)
            if _stq:
                if not R.get(RNS+"quote_gate:warn:"+user):
                    R.setex(RNS+"quote_gate:warn:"+user,300,"1")
                    _push_alert("warn","行情新鲜度闸: %s, 自动进单跳过"%_stq,user)
                continue
            sp_rev=round(float(ht.get("ask",0))-float(mt.get("bid",0)),4)
            sp_fwd=round(float(mt.get("ask",0))-float(ht.get("bid",0)),4)
            # 买入点位=入场下限(点差须≥阈值才进); 费用抬高下限(与手动一致)
            gthr=float(t.get("entry_spread") or 0)
            fee=float(t.get("fee_per_lot") or 0); _fp=0.0
            if fee>0:
                try: _,_fp=ENG.effective_spread_threshold(gthr,fee,100.0,legs=2)
                except Exception: _fp=0.0
            # 同一行情窗口收集全部达标武装空坑；批量规模受 ladders 约束。
            qualified=[]
            for _s,_ov,_st in cands:
                _dirs=("forward","reverse") if _st=="both" else (_st,)
                _best=None
                for _d in _dirs:
                    _sp=sp_rev if _d=="reverse" else sp_fwd
                    _ok,_l=POL.gate_entry_spread(_ov,gthr,_sp,_fp)
                    if _ok:
                        _mg=_sp-(_l if _l is not None else _sp)
                        if _best is None or _mg>_best[2]: _best=(_d,_sp,_mg,_l)
                if _best:
                    qualified.append({"slot":_s,"direction":_best[0],"spread":_best[1],
                        "threshold":_best[3],"reason":"点差%.4f>=买入点位%s"%(
                            _best[1],("%.2f"%_best[3] if _best[3] is not None else "任意"))})
            if not qualified: continue
            # 数据波动闸 — P1-b enforce: 统一走 policy(取数 _pol_hist 同源 spread:hist)
            if POL.gate_fluctuation(t,_pol_hist(t))[0]: continue
            # 保证金预留闸 + 智能预判预算闸(批33功能3) — P1-b enforce: 判定统一走 policy(D2 fail-open 原样)
            _rm=float(t.get("margin_reserve_main") or 0); _rh=float(t.get("margin_reserve_hedge") or 0)
            _pb=float(t.get("predict_budget") or 0)
            accs=None
            if _rm>0 or _rh>0 or _pb>0:
                try: accs=await decision_conn.both_accounts()
                except Exception: accs=None
            if POL.gate_margin_budget(t,accs,fail_closed=False)[0]: continue
            R.set(RNS+"auto_entry:decisions:"+user,json.dumps({"ts":_dt.datetime.utcnow().isoformat(),
                "mode":mode,"items":qualified},ensure_ascii=False))
            # 影子: 只回显
            if mode=="shadow":
                _push_alert("info","[影子]将批量开 %d 个达标坑"%len(qualified),user)
                R.set(RNS+"auto_entry:last", _dt.datetime.utcnow().isoformat()); continue
            # 在途锁 + 冷却: 进单等待开→按 entry_interval_sec(最低10s); 关→不按间隔(保留10s安全底线)
            lockkey=RNS+"auto_entry:lock:"+user+":"+sym
            if R.get(lockkey): continue
            if _auto_entry_paused(): continue
            _wait_en=(R.get(RNS+"sw:entrywait:"+user)!="0")
            cooldown=max(10,int(t.get("entry_interval_sec") or 5)) if _wait_en else 10
            R.setex(lockkey, cooldown, "1")
            queued=await _enqueue_open_items(user,sym,"auto",qualified,"auto_entry")
            if queued:
                _push_alert("info","自动进单已按进单量受理 %d 个达标坑"%len(queued[1]),user)
            R.set(RNS+"auto_entry:last", _dt.datetime.utcnow().isoformat())
        await _aio.sleep(5)

@app.on_event("startup")
async def _startup_auto_entry():
    _aio.create_task(_auto_entry_loop())

# ================= RecoveryWorker (V1.1 M2 移植·QH化): 周期净敞口对账 + 孤儿腿收敛 =================
# 病灶: 裸空处置只在事件时点(开/平仓失败当场告警), 残局靠人工 — 2026-07-17 Exness REQUOTE 裸空实锤=收敛缺位。
# 设计: 20s/轮; SETNX 单飞锁 TTL 10s **必须<轮距**(testgo 锁教训: TTL≥间隔会把自己后续轮锁死);
#   按 comment#rid 精确配对 → rid 孤儿 连续3轮可见+仓龄>60s 才行动(开仓过渡态绝不误伤);
#   行动=**只平不开**(风险收敛方向, 绝不自动反开); 每票冷却120s+每轮每用户至多2票;
#   无 rid 老仓 → 净手数差仅告警(无法精确定责哪张票); DEMO/急停 → 降级纯告警;
#   开关 qh:recovery:mode = converge(默认)|alert|off 热切换; 维护禁下单/执行链不可达 → 本轮跳过。
import re as _re_rw
_RID_RE=_re_rw.compile(r"#([0-9a-f]{8})\b")
def _pos_rid(p):
    m=_RID_RE.search(str(p.get("comment") or ""))
    return m.group(1) if m else None

async def _recovery_round(user):
    if await _exec_owner_reason(user): return 0,0   # 串账墙: 账户不属执行桥→不收敛(平错桥=平别人仓)
    conn=_user_conn(user)
    both=await conn.both_positions()
    def _plist(k):
        x=(both or {}).get(k) or {}
        return x.get("positions",x) if isinstance(x,dict) else (x or [])
    mains=_plist("main"); hedges=_plist("hedge")
    now=_t_conn.time()
    mrids={}; hrids={}; m_untag=[]; h_untag=[]
    for p in mains:
        r=_pos_rid(p)
        (mrids.setdefault(r,[]).append(p)) if r else m_untag.append(p)
    for p in hedges:
        r=_pos_rid(p)
        (hrids.setdefault(r,[]).append(p)) if r else h_untag.append(p)
    orphans=[("main",p) for r,ps in mrids.items() if r not in hrids for p in ps] \
           +[("hedge",p) for r,ps in hrids.items() if r not in mrids for p in ps]
    seen_key=RNS+"recovery:seen:"+user
    acted=0; converged=[]
    cur_tickets=set()
    mode=R.get(RNS+"recovery:mode") or "converge"
    estop=(R.get(RNS+"global_estop")=="1")
    for leg,p in orphans:
        tk=str(p.get("ticket") or ""); rid=_pos_rid(p)
        if not tk: continue
        cur_tickets.add(tk)
        n=R.hincrby(seen_key, tk, 1); R.expire(seen_key, 600)
        age=now-float(p.get("time_open") or p.get("time") or now)
        if n<3 or age<60: continue
        cn="主" if leg=="main" else "对冲"
        if mode!="converge" or DEMO_MODE or estop:
            if R.set(RNS+"recovery:alertcool:"+tk,"1",nx=True,ex=120):
                _push_alert("err","RecoveryWorker: %s腿孤儿持仓 %s(rid#%s, 仓龄%ds)无对腿, 请人工处理(收敛未启用)"%(cn,tk,rid,int(age)),user)
            continue
        if acted>=2: continue
        if not R.set(RNS+"recovery:actcool:"+tk,"1",nx=True,ex=120): continue
        side="buy" if int(p.get("type") or 0)==0 else "sell"   # close_position 语义: side=持仓方向(有ticket则精确平该票)
        _uec=_user_exec_conn(user)
        leg_obj=_uec.main if leg=="main" else getattr(_uec,"hedge",None)
        if leg_obj is None: continue
        from connector import _gen_rid, order_status_probe
        recovery_rid=_gen_rid()+leg[0]
        account_token="recovery:%s:%s"%(tk,recovery_rid)
        try:
            _begin_account_op(user,account_token)
        except HTTPException as ex:
            if ex.status_code==409:
                try: R.delete(RNS+"recovery:actcool:"+tk)
                except Exception: pass
                continue
            raise
        try:
            try:
                res=await leg_obj.close_position(
                    p.get("symbol"),side,ticket=p.get("ticket"),request_id=recovery_rid)
                if isinstance(res,dict) and res.get("pending"):
                    terminal=await order_status_probe(
                        leg_obj,recovery_rid,tries=800,delay=0.05)
                    if terminal is None:
                        res={"unknown":True,"error":"recovery close terminal timeout"}
                    else:
                        res=terminal
                ok=(bool((res or {}).get("ok",True)) and
                    not bool((res or {}).get("pending")) and
                    not bool((res or {}).get("unknown")) and
                    not bool((res or {}).get("failed")) and
                    "error" not in (res or {}))
            except Exception as e:
                res={"error":str(e)[:120]}; ok=False
        finally:
            _release_account_op(user,account_token)
        acted+=1
        _audit(user,"recovery","orphan_converge",{"leg":leg,"ticket":tk,"rid":rid,"age_s":int(age),"res":res},False,"closed" if ok else "close_fail")
        _push_alert("warn" if ok else "err",
            ("RecoveryWorker已收敛%s腿孤儿持仓 %s(rid#%s, 仓龄%ds): 已平仓归零"%(cn,tk,rid,int(age))) if ok
            else ("RecoveryWorker收敛失败 %s腿 %s: %s, 需人工"%(cn,tk,str((res or {}).get("error"))[:60])),user)
        if ok: converged.append(tk)
    # 已不再是孤儿的票 → 清计数(防陈旧计数误伤未来同号票)
    try:
        for f in (R.hkeys(seen_key) or []):
            if str(f) not in cur_tickets: R.hdel(seen_key, f)
    except Exception: pass
    # 无 rid 老仓净差: 只告警(5min 冷却)
    _ml=sum(float(p.get("volume") or 0) for p in m_untag); _hl=sum(float(p.get("volume") or 0) for p in h_untag)
    if abs(_ml-_hl)>0.001 and R.set(RNS+"recovery:untagcool:"+user,"1",nx=True,ex=300):
        _push_alert("warn","RecoveryWorker: 无rid旧仓净手数差 主%.3f/对冲%.3f, 无法定责单票, 请人工核对"%(_ml,_hl),user)
    if converged:
        R.set(RNS+"recovery:lastconv", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"user":user,"tickets":converged}))
    return len(orphans), len(converged)

async def _recovery_worker_loop():
    await _aio.sleep(25)
    while True:
        try:
            if (R.get(RNS+"recovery:mode") or "converge")=="off":
                await _aio.sleep(20); continue
            if not R.set(RNS+"recovery:lock","1",nx=True,ex=10):   # 单飞: TTL 10s < 轮距 20s
                await _aio.sleep(20); continue
            try: _maint_block_trading()
            except HTTPException:
                await _aio.sleep(20); continue
            try:
                c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
                cur.execute("SELECT DISTINCT u.username FROM param_templates pt JOIN users u ON u.id=pt.user_id")
                users=[r["username"] for r in cur.fetchall()]; c.close()
            except Exception:
                users=[]
            _sweep_clean=True
            for u in users:
                try:
                    # P0同款按用户健康闸: 只跳过自己桥离线的用户, 别人桥挂不拦本用户裸腿收敛
                    if await _conn_block_reason(u):
                        continue
                    await _recovery_round(u)
                except Exception as e:
                    _sweep_clean=False
                    R.set(RNS+"recovery:err","%s %s:%s"%(_dt.datetime.utcnow().isoformat(),u,str(e)[:80]))
            if _sweep_clean:
                try: R.delete(RNS+"recovery:err")
                except Exception: pass
            R.set(RNS+"recovery:last", _dt.datetime.utcnow().isoformat())
        except Exception as e:
            try: R.set(RNS+"recovery:err", str(e)[:120])
            except Exception: pass
        await _aio.sleep(20)

@app.on_event("startup")
async def _startup_recovery_worker():
    _aio.create_task(_recovery_worker_loop())


# ================= 产品对套利扫描采样器 (pairscan, 管理员分析用, 只读不碰交易) =================
# 宇宙: /opt/quanthedge/pairscan_universe.json (canonical -> ic/by/bn 各平台符号)
# 采样: 60s/轮; ic/by 经 FRA a2t-bridge /mt5/ticks 批量, bns/bnf 经 Binance 公共 bookTicker
# 落库: pairscan_samples(ts,instrument,platform,bid,ask), 保留14天
# 开关: Redis qh:pairscan:enabled ('0'=停, 缺省开); 心跳 qh:pairscan:last
_PAIRSCAN_UNI=[]
try: _PAIRSCAN_UNI=json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"pairscan_universe.json")))
except Exception: pass
_PSCAN_CX=None   # 复用 AsyncClient(命门: 每轮重建会反复触发SSL上下文重建阻塞事件循环, testgo老雷)
async def _pairscan_round():
    import httpx
    global _PSCAN_CX
    if _PSCAN_CX is None:
        _PSCAN_CX=httpx.AsyncClient(timeout=15,limits=httpx.Limits(max_keepalive_connections=8,keepalive_expiry=120))
    # 采样源: 内网 MT5 桥(QH_PSCAN_URL, ic:8021/by:8886)。旧桥无 /mt5/ticks 批量端点→回落逐 symbol 并发单 tick。
    fra=os.environ.get("QH_PSCAN_URL","http://172.31.5.62").rstrip("/")
    fk=os.environ.get("QH_PSCAN_KEY", os.environ.get("QH_BRIDGE_KEY",""))
    mp=os.environ.get("QH_PSCAN_IC_PORT","8021"); hp=os.environ.get("QH_PSCAN_BY_PORT","8886")
    ic_syms=[u["ic"] for u in _PAIRSCAN_UNI if u.get("ic")]
    by_syms=[u["by"] for u in _PAIRSCAN_UNI if u.get("by")]
    bn_syms=set(u["bn"] for u in _PAIRSCAN_UNI if u.get("bn"))
    ts=int(_t_conn.time()); rows=[]
    async def _one_tick(port,sym):
        try:
            r=await _PSCAN_CX.get("%s:%s/mt5/tick/%s"%(fra,port,sym),headers={"X-API-Key":fk})
            if r.status_code!=200: return sym,None
            q=r.json(); return sym,{"bid":q.get("bid"),"ask":q.get("ask")}
        except Exception: return sym,None
    async def fra_ticks(port,syms,plat):
        tk={}
        try:   # 优先批量端点(新桥有), 404/异常→回落逐 symbol 并发(旧内网桥无 /mt5/ticks)
            r=await _PSCAN_CX.get("%s:%s/mt5/ticks"%(fra,port),params={"symbols":",".join(syms)},headers={"X-API-Key":fk})
            if r.status_code==200: tk=(r.json() or {}).get("ticks",{}) or {}
        except Exception: pass
        if not tk:
            sem=_aio.Semaphore(16)   # 并发闸: 单 tick 逐个但限并发, 不打爆桥
            async def _g(sym):
                async with sem: return await _one_tick(port,sym)
            for sym,q in await _aio.gather(*[_g(s) for s in syms]):
                if q: tk[sym]=q
        rev={ (u["ic"] if plat=="ic" else u["by"]) : u["c"] for u in _PAIRSCAN_UNI if u.get("ic" if plat=="ic" else "by")}
        for s,q in tk.items():
            c=rev.get(s)
            try: b,a=float(q["bid"]),float(q["ask"])
            except (TypeError,KeyError,ValueError): continue
            if c and b>0 and a>0: rows.append((ts,c,plat,b,a))
    async def bn_ticks(url,plat):
        try:
            r=await _PSCAN_CX.get(url)
            js=r.json() if r.status_code==200 else []
        except Exception: js=[]
        rev={u["bn"]:u["c"] for u in _PAIRSCAN_UNI if u.get("bn")}
        for x in (js if isinstance(js,list) else []):
            c=rev.get(x.get("symbol"))
            if not c: continue
            try: b,a=float(x["bidPrice"]),float(x["askPrice"])
            except (TypeError,KeyError,ValueError): continue
            if b>0 and a>0: rows.append((ts,c,plat,b,a))
    await _aio.gather(fra_ticks(mp,ic_syms,"ic"), fra_ticks(hp,by_syms,"by"),
                      bn_ticks("https://api.binance.com/api/v3/ticker/bookTicker","bns"),
                      bn_ticks("https://fapi.binance.com/fapi/v1/ticker/bookTicker","bnf"))
    if rows:
        c=db(); cur=c.cursor()
        cur.executemany("INSERT INTO pairscan_samples(ts,instrument,platform,bid,ask) VALUES(%s,%s,%s,%s,%s)",rows)
        c.close()
    return len(rows)
async def _pairscan_carry():
    """费率缓存(小时级): 币安永续 funding(bps/日, 正=多付空) + MT5 双腿 swap 原始字段(内网桥 symbol_info)。"""
    fund={}; swap={}
    try:
        r=await _PSCAN_CX.get("https://fapi.binance.com/fapi/v1/premiumIndex")
        for x in (r.json() if r.status_code==200 else []):
            try: fund[x["symbol"]]=round(float(x.get("lastFundingRate") or 0)*3*1e4,3)   # 8h费率×3=日bps
            except (TypeError,ValueError): pass
    except Exception: pass
    for u in _PAIRSCAN_UNI:
        for plat in ("ic","by"):
            s=u.get(plat)
            if not s: continue
            try:
                leg=CONN.main if plat=="ic" else getattr(CONN,"hedge",None)
                if not leg: continue
                j=await leg._get("/mt5/symbol_info/"+s)
                swap["%s:%s"%(plat,u["c"])]={"mode":j.get("swap_mode"),"sl":j.get("swap_long"),
                                             "ss":j.get("swap_short"),"pt":j.get("point")}
            except Exception: pass
    R.set(RNS+"pairscan:fund", json.dumps(fund))
    R.set(RNS+"pairscan:swap", json.dumps(swap))
async def _pairscan_loop():
    await _aio.sleep(23)
    try:
        c=db(); cur=c.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS pairscan_samples(
            ts bigint NOT NULL, instrument text NOT NULL, platform text NOT NULL,
            bid double precision, ask double precision)""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pscan_inst_ts ON pairscan_samples(instrument,ts)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_pscan_ts ON pairscan_samples(ts)")
        # 时间窗列(进单时段/运行时段, 北京 "HH:MM"; 幂等)
        for _col in ("entry_win_start","entry_win_end","run_win_start","run_win_end"):
            cur.execute("ALTER TABLE param_templates ADD COLUMN IF NOT EXISTS %s text DEFAULT ''"%_col)
        # 官网/介绍站内容配置表(site_config + 草稿/发布/回滚; 幂等)
        cur.execute("CREATE TABLE IF NOT EXISTS site_config(site text PRIMARY KEY, cfg jsonb DEFAULT '{}'::jsonb, updated_at timestamptz DEFAULT now())")
        cur.execute("ALTER TABLE site_config ADD COLUMN IF NOT EXISTS draft jsonb")
        cur.execute("CREATE TABLE IF NOT EXISTS site_config_versions(id serial PRIMARY KEY, site text, cfg jsonb, published_at timestamptz DEFAULT now())")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_scv_site ON site_config_versions(site,id DESC)")
        c.close()
    except Exception as e:
        R.set(RNS+"pairscan:err","ddl:%s"%str(e)[:150])
    while True:
        try:
            if not _PAIRSCAN_UNI or R.get(RNS+"pairscan:enabled")=="0":
                await _aio.sleep(60); continue
            n=await _pairscan_round()
            R.set(RNS+"pairscan:last", _dt.datetime.utcnow().isoformat())
            R.set(RNS+"pairscan:lastn", str(n))
            if not R.get(RNS+"pairscan:carry_ok"):   # 费率缓存每小时刷一轮
                R.setex(RNS+"pairscan:carry_ok",3600,"1")
                try: await _pairscan_carry()
                except Exception: pass
            # 每小时清一次14天外旧样本
            if not R.get(RNS+"pairscan:purged"):
                R.setex(RNS+"pairscan:purged",3600,"1")
                try:
                    c=db(); cur=c.cursor()
                    cur.execute("DELETE FROM pairscan_samples WHERE ts<%s",(int(_t_conn.time())-14*86400,))
                    c.close()
                except Exception: pass
        except Exception as e:
            R.set(RNS+"pairscan:err",str(e)[:200])
        await _aio.sleep(60)
@app.on_event("startup")
async def _startup_pairscan():
    _aio.create_task(_pairscan_loop())

_PSCAN_PLAT_LBL={"ic":"ICMarkets","by":"BybitMT5","bns":"币安现货","bnf":"币安永续"}
# 主↔对冲取向: 主账户=币安(现货/永续), 对冲=IC/BybitMT5; ic-by 保留为参考对(主=IC)
_PSCAN_PAIRS=[("bnf","ic"),("bnf","by"),("bns","ic"),("bns","by"),("ic","by")]
def _pscan_swap_bps(sw, mid):
    """MT5 swap 原始字段→bps/日。mode1=点(×point/价), mode5=年化%(/365)。其它模式→None。"""
    if not sw or mid<=0: return (None,None)
    m=sw.get("mode"); sl=sw.get("sl"); ss=sw.get("ss"); pt=sw.get("pt")
    try:
        if m==1 and pt: return (round(float(sl)*float(pt)/mid*1e4,3), round(float(ss)*float(pt)/mid*1e4,3))
        if m==5: return (round(float(sl)*100.0/365.0,3), round(float(ss)*100.0/365.0,3))
    except (TypeError,ValueError): pass
    return (None,None)
@app.get("/api/admin/pairscan", dependencies=[Depends(require_admin)])
def admin_pairscan(hours:int=24):
    """产品对套利扫描排行(主=币安, 对冲=IC/BybitMT5): 基差摆幅/双边点差/捕获分 + 资金费/过夜费 carry → 纯利分。
       binance 腿按窗口内 USDC/USDT 中值折 USD。只读分析, 不构成交易信号。"""
    since=int(_t_conn.time())-max(1,min(hours,24*14))*3600
    c=db(); cur=c.cursor()
    cur.execute("SELECT ts,instrument,platform,bid,ask FROM pairscan_samples WHERE ts>=%s",(since,))
    data={}
    for ts,inst,plat,b,a in cur.fetchall():
        if b and a and b>0 and a>0: data.setdefault(inst,{}).setdefault(plat,{})[ts]=(b,a)
    c.close()
    pegs=[(b+a)/2 for b,a in (data.get("USDPEG",{}).get("bns",{}) or {}).values()]
    peg=sorted(pegs)[len(pegs)//2] if pegs else 1.0
    catmap={u["c"]:u["cat"] for u in _PAIRSCAN_UNI}
    bnmap={u["c"]:u.get("bn") for u in _PAIRSCAN_UNI}
    try: FUND=json.loads(R.get(RNS+"pairscan:fund") or "{}")
    except Exception: FUND={}
    try: SWAP=json.loads(R.get(RNS+"pairscan:swap") or "{}")
    except Exception: SWAP={}
    out=[]
    for inst,plats in data.items():
        if inst=="USDPEG": continue
        for pm,ph in _PSCAN_PAIRS:   # pm=主平台 ph=对冲平台
            if pm not in plats or ph not in plats: continue
            common=sorted(set(plats[pm])&set(plats[ph]))
            if len(common)<8: continue
            bas=[]; spm=[]; sph=[]; mms=[]; mhs=[]
            for t in common:
                bm,am=plats[pm][t]; bh,ah=plats[ph][t]
                if pm.startswith("bn"): bm,am=bm*peg,am*peg   # 主=币安 USDT→USD
                mm,mh=(bm+am)/2,(bh+ah)/2; mid=(mm+mh)/2
                bas.append((mh-mm)/mid*1e4)                    # 基差=对冲-主
                spm.append((am-bm)/mid*1e4); sph.append((ah-bh)/mid*1e4)
                mms.append(mm); mhs.append(mh)
            bs=sorted(bas); n=len(bs)
            med=bs[n//2]; p10=bs[int(n*0.1)]; p90=bs[min(n-1,int(n*0.9))]
            swing=p90-p10
            sm=sorted(spm)[n//2]; sh=sorted(sph)[n//2]
            freshm=len(set(round(x,10) for x in mms))/n; freshh=len(set(round(x,10) for x in mhs))/n
            score=swing-(sm+sh)
            # ---- carry: 资金费(主=币安永续)+过夜费(MT5腿) → 日bps ----
            midh=sorted(mhs)[n//2]; midm=sorted(mms)[n//2]
            fund_d=FUND.get(bnmap.get(inst) or "") if pm=="bnf" else None   # 正=多付空
            hsl,hss=_pscan_swap_bps(SWAP.get("%s:%s"%(ph,inst)), midh)      # 对冲腿 swap
            msl,mss=(None,None)
            if pm in ("ic","by"): msl,mss=_pscan_swap_bps(SWAP.get("%s:%s"%(pm,inst)), midm)
            def _main_carry(long_side):
                if pm=="bnf": return (-fund_d if long_side else fund_d) if fund_d is not None else None
                if pm=="bns": return 0.0 if long_side else None   # 现货多=0费; 现货空须借币, 成本未知→None
                return (msl if long_side else mss)
            def _add(a,b): return None if (a is None or b is None) else round(a+b,3)
            carry_a=_add(_main_carry(True),  hss)   # 主多+对冲空
            carry_b=_add(_main_carry(False), hsl)   # 主空+对冲多
            cands=[(v,l) for v,l in ((carry_a,"主多对冲空"),(carry_b,"主空对冲多")) if v is not None]
            carry_best,carry_dir=(max(cands) if cands else (None,None))
            net=round(score+carry_best,2) if carry_best is not None else None   # 纯利分=捕获分+最优方向1日carry
            flags=[]
            if freshm<0.3 or freshh<0.3: flags.append("stale")
            if abs(med)>50: flags.append("mismatch")
            elif abs(med)>3*max(swing,0.01) and abs(med)>2: flags.append("persistent")
            out.append({"instrument":inst,"cat":catmap.get(inst,"?"),"pair":"%s-%s"%(pm,ph),
                        "pair_lbl":"%s(主) ↔ %s(对冲)"%(_PSCAN_PLAT_LBL[pm],_PSCAN_PLAT_LBL[ph]),
                        "n":n,"basis_med":round(med,2),"swing":round(swing,2),
                        "sp1":round(sm,2),"sp2":round(sh,2),"score":round(score,2),
                        "fund_d":fund_d,"hswap_l":hsl,"hswap_s":hss,
                        "carry_a":carry_a,"carry_b":carry_b,"carry_best":carry_best,"carry_dir":carry_dir,
                        "net":net,
                        "fresh1":round(freshm,2),"fresh2":round(freshh,2),"flags":flags})
    # 排序: 失格沉底; 纯利分优先, 无carry数据的按捕获分
    out.sort(key=lambda x:(-((x["net"] if x["net"] is not None else x["score"]) if not x["flags"] else -1000+(x["net"] or x["score"]))))
    return {"rows":out[:300],"peg":round(peg,5),"hours":hours,
            "last":R.get(RNS+"pairscan:last"),"lastn":R.get(RNS+"pairscan:lastn"),
            "enabled":R.get(RNS+"pairscan:enabled")!="0","universe":len(_PAIRSCAN_UNI),
            "carry_syms":len(SWAP),"fund_syms":len(FUND),
            "err":R.get(RNS+"pairscan:err")}


def _json_hash_state(key):
    out={}
    for name,raw in (R.hgetall(key) or {}).items():
        try: out[name]=json.loads(raw)
        except Exception: out[name]=raw
    return out


@app.get("/api/engine/state", dependencies=[Depends(require_license)])
async def engine_state(x_license: str = Header(default="")):
    username=_license_to_username(x_license)
    eval_all=R.hgetall(RNS+"engine:eval") or {}
    own_eval={username:json.loads(eval_all[username])} if username and username in eval_all else {}
    account=None
    # The process-global engine:account key is admin-only.  Resolve the
    # authenticated user's account from that user's strict connector instead.
    try:
        conn=_strict_user_read_conn(username)
        if conn is not None:
            account=(await conn.both_accounts()) if hasattr(conn,"both_accounts") else (await conn.account_info())
    except Exception:
        account=None
    return {
        "cycle": json.loads(R.get(RNS+"engine:cycle") or "null"),
        "market": json.loads(R.hget(RNS+"engine:market:user",username) or "null") if username else None,
        "account": account,
        "eval": own_eval,
        "err": (R.hget(RNS+"engine:err:user",username) if username else None) or R.get(RNS+"engine:err"),
    }

@app.get("/api/engine/check")
def engine_check(main_ask:float, main_bid:float, hedge_ask:float, hedge_bid:float,
                 thr:float=0.30, direction:str="reverse"):
    """点差闸即时校验：有符号方向点差 >= 入场下限才通过。"""
    ok,sp,reason = ENG.spread_gate(main_ask,main_bid,hedge_ask,hedge_bid,thr,direction)
    closed,why = ENG.market_closed()
    return {"spread_gate":{"pass":ok,"spread":sp,"reason":reason,"direction":direction,
                           "threshold":thr,"semantics":"signed_spread_gte_entry_floor"},
            "market":{"closed":closed,"why":why}}
# ================= 双腿 / 告警 端点 =================
# ================= api 模式 in-flight 票据账本 =================
# A2T /OpenedOrders 对刚开的仓有读滞后(实测1-2min不可见) → api 模式开仓后本地记账,
# 供 坑位显示/已填坑计数 合并, 防"看不到新仓→阶梯误判空坑→重复开仓"。真实持仓出现或10min过期即清。
_INFLIGHT_TTL=600
def _inflight_key(leg,symbol): return RNS+"inflight:"+leg+":"+symbol
def _inflight_add(leg,symbol,pos):
    """记一笔 in-flight 伪持仓(dict 需含 ticket)。仅 api 模式调用方使用。"""
    try:
        tk=str((pos or {}).get("ticket") or "")
        if not tk: return
        pos=dict(pos); pos["pending"]=True; pos["_exp"]=_dt.datetime.utcnow().timestamp()+_INFLIGHT_TTL
        R.hset(_inflight_key(leg,symbol), tk, json.dumps(pos, default=str))
    except Exception: pass
def _inflight_remove(leg,symbol,ticket):
    try:
        if ticket: R.hdel(_inflight_key(leg,symbol), str(ticket))
    except Exception: pass
def _inflight_merge(leg,symbol,positions):
    """把未过期且真实持仓里还看不到的 in-flight 票并入 positions(list)。真实已含→顺手清账。"""
    try:
        h=R.hgetall(_inflight_key(leg,symbol)) or {}
        if not h: return positions
        now=_dt.datetime.utcnow().timestamp()
        seen=set(str(p.get("ticket")) for p in (positions or []) if isinstance(p,dict))
        out=list(positions or [])
        for tk,raw in h.items():
            try: p=json.loads(raw)
            except Exception: R.hdel(_inflight_key(leg,symbol),tk); continue
            if float(p.get("_exp") or 0)<now or tk in seen:
                R.hdel(_inflight_key(leg,symbol),tk); continue   # 过期 or 真实可见→清账
            out.append(p)
        return out
    except Exception:
        return positions

def _slotmap_key(leg, symbol, username=None):
    scope=(username or "").strip()
    if scope:
        return RNS+"slotmap:"+scope+":"+leg+":"+symbol
    return RNS+"slotmap:"+leg+":"+symbol

def _slotowner_key(leg, symbol, username=None):
    scope=(username or "").strip()
    if scope:
        return RNS+"slotowner:"+scope+":"+leg+":"+symbol
    return RNS+"slotowner:"+leg+":"+symbol

def _slotpending_key(leg, symbol, username=None):
    scope=(username or "").strip()
    if scope:
        return RNS+"slotpending:"+scope+":"+leg+":"+symbol
    return RNS+"slotpending:"+leg+":"+symbol

def _slotop_key(username, symbol, slot):
    return RNS+"slotop:%s:%s:%d"%((username or "").strip(),symbol,int(slot))

_SLOT_REVIEW_ACTIVE=frozenset((
    "UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED","RECONCILING","SUBMITTED"))
_ACCOUNT_REVIEW_LOCAL={}

def _slotreview_key(username, symbol, slot):
    return RNS+"slotreview:%s:%s:%d"%((username or "").strip(),symbol,int(slot))

def _slot_review_record(username, symbol, slot):
    """Return an unresolved durable review latch, clearing reconciled commands lazily."""
    try:
        raw=R.get(_slotreview_key(username,symbol,slot))
        if raw:
            if isinstance(raw,bytes): raw=raw.decode("utf-8","replace")
            record=json.loads(raw)
            if not isinstance(record,dict):
                return {"state":"MANUAL_REVIEW","reason":"invalid review latch"}
            command_id=str(record.get("command_id") or "")
            if command_id:
                try:
                    command=get_tracer().get_command(command_id)
                except Exception:
                    command=None
                status=str((command or {}).get("status") or "").upper()
                if status and status not in _SLOT_REVIEW_ACTIVE:
                    R.delete(_slotreview_key(username,symbol,slot))
                    _ACCOUNT_REVIEW_LOCAL.pop(
                        ((username or "").strip(),str(symbol),int(slot)),None)
                else:
                    # An unresolved broker outcome must never unlock merely because an old
                    # release wrote this key with a TTL.
                    R.persist(_slotreview_key(username,symbol,slot))
                    return record
            else:
                R.persist(_slotreview_key(username,symbol,slot))
                return record

        # The terminal queue record is a second durable latch.  It protects the
        # slot even when writing the dedicated review key failed after broker
        # dispatch.  Tests and maintenance tools sometimes replace only R; do
        # not consult a queue bound to a different Redis client.
        if getattr(TRADE_QUEUE,"redis",None) is R:
            for job in TRADE_QUEUE.slot_states(username,symbol,[slot]):
                state=str(job.get("state") or "").upper()
                if state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                    return {"username":username,"symbol":symbol,"slot":int(slot),
                            "state":state,"command_id":job.get("command_id") or "",
                            "job_id":job.get("job_id") or "",
                            "reason":"uncertain trade queue outcome"}
        return None
    except Exception:
        # A corrupt/unreadable safety latch must fail closed.
        return {"state":"MANUAL_REVIEW","reason":"review latch unavailable"}

def _set_slot_review(username, symbol, slot, state, command_id=None, job_id=None, reason=""):
    state=str(state or "").upper()
    slot=int(slot or 0)
    if slot<1 or state not in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
        return False
    record={"username":username,"symbol":symbol,"slot":slot,"state":state,
            "command_id":command_id or "","job_id":job_id or "",
            "reason":str(reason or state)[:300],"created_at":_dt.datetime.utcnow().isoformat()}
    _ACCOUNT_REVIEW_LOCAL[((username or "").strip(),str(symbol),slot)]=record
    try:
        return bool(R.set(_slotreview_key(username,symbol,slot),
            json.dumps(record,ensure_ascii=False,separators=(",",":"),default=str)))
    except Exception:
        return False

def _clear_slot_review(username, symbol, slot, command_id=None):
    try:
        key=_slotreview_key(username,symbol,slot)
        if command_id:
            record=_slot_review_record(username,symbol,slot)
            if record and str(record.get("command_id") or "") not in ("",str(command_id)):
                return False
        deleted=bool(R.delete(
            key,RNS+"auto_entry:slot_halt:%s:%s:%d"%(
                (username or "").strip(),symbol,int(slot))))
        local_key=((username or "").strip(),str(symbol),int(slot))
        existed=local_key in _ACCOUNT_REVIEW_LOCAL
        _ACCOUNT_REVIEW_LOCAL.pop(local_key,None)
        return bool(deleted or existed)
    except Exception:
        return False

def _account_review_record(username):
    """Return any unresolved account risk; unreadable review state fails closed."""
    scope=(username or "").strip()
    if not scope:
        return {"state":"MANUAL_REVIEW","reason":"missing account review scope"}
    try:
        for key,record in list(_ACCOUNT_REVIEW_LOCAL.items()):
            if key[0]!=scope:
                continue
            current=_slot_review_record(key[0],key[1],key[2])
            if current:
                _ACCOUNT_REVIEW_LOCAL[key]=current
                return current
            _ACCOUNT_REVIEW_LOCAL.pop(key,None)

        pattern=RNS+"slotreview:"+scope+":*"
        for raw_key in R.scan_iter(match=pattern,count=100):
            raw=R.get(raw_key)
            if isinstance(raw,bytes): raw=raw.decode("utf-8","replace")
            try: record=json.loads(raw) if raw else None
            except (TypeError,ValueError): record=None
            if not isinstance(record,dict):
                return {"username":scope,"state":"MANUAL_REVIEW",
                        "reason":"invalid account review latch"}
            symbol=str(record.get("symbol") or "XAUUSD")
            slot=int(record.get("slot") or 0)
            if slot<1:
                return {"username":scope,"state":"MANUAL_REVIEW",
                        "reason":"invalid account review slot"}
            current=_slot_review_record(scope,symbol,slot)
            if current:
                _ACCOUNT_REVIEW_LOCAL[(scope,symbol,slot)]=current
                return current

        # The queue slot is a second source when the dedicated review write
        # failed after dispatch. UNKNOWN review slots are persisted by finish().
        if getattr(TRADE_QUEUE,"redis",None) is R:
            namespace=str(getattr(TRADE_QUEUE,"namespace",RNS+"tradeq:"))
            for slot_key in R.scan_iter(match=namespace+"slot:"+scope+":*",count=100):
                job_id=R.get(slot_key)
                if not job_id:
                    continue
                job=TRADE_QUEUE.get_job(job_id) or {}
                state=str(job.get("state") or "").upper()
                if state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                    record={"username":scope,"symbol":job.get("symbol") or "XAUUSD",
                            "slot":int(job.get("slot") or 0),"state":state,
                            "command_id":job.get("command_id") or "",
                            "job_id":job.get("job_id") or str(job_id),
                            "reason":"uncertain account trade queue outcome"}
                    _ACCOUNT_REVIEW_LOCAL[(scope,record["symbol"],record["slot"])]=record
                    return record
        return None
    except Exception:
        return {"username":scope,"state":"MANUAL_REVIEW",
                "reason":"account review latch unavailable"}

def _assert_slot_review_clear(username, symbol, slot):
    record=_slot_review_record(username,symbol,slot)
    if record:
        raise HTTPException(409,"RECONCILIATION_REQUIRED: 坑 %d %s，禁止重复开仓/平仓"%(
            int(slot),record.get("state") or "MANUAL_REVIEW"))
    return True

def _authoritative_single_leg_review_close(username, symbol, item, review):
    """Allow only the exact known exposed ticket to reduce a SINGLE_LEG_EXPOSED risk."""
    if (str((review or {}).get("state") or "").upper()!="SINGLE_LEG_EXPOSED" or
            (item or {}).get("op")!="close_leg"):
        return False
    leg=(item or {}).get("leg"); ticket=_exact_positive_int((item or {}).get("ticket"))
    slot=_exact_positive_int((item or {}).get("slot"))
    if leg not in ("main","hedge") or ticket is None or slot is None:
        return False
    try:
        source_job=TRADE_QUEUE.get_job(str((review or {}).get("job_id") or ""))
        if (not isinstance(source_job,dict) or
                str(source_job.get("state") or "").upper()!="SINGLE_LEG_EXPOSED" or
                str(source_job.get("op") or "")!="open_pair" or
                str(source_job.get("username") or "")!=str(username) or
                str(source_job.get("symbol") or "XAUUSD")!=str(symbol) or
                _exact_positive_int(source_job.get("slot"))!=slot or
                str(source_job.get("command_id") or "")!=str((review or {}).get("command_id") or "") or
                _source_job_single_leg_exposure(source_job)!=(leg,ticket)):
            return False
        target_owner=R.hgetall(_slotowner_key(leg,symbol,username)) or {}
        target_map=R.hgetall(_slotmap_key(leg,symbol,username)) or {}
        other="hedge" if leg=="main" else "main"
        other_owner=R.hgetall(_slotowner_key(other,symbol,username)) or {}
        owned_here=[_exact_positive_int(raw_ticket) for raw_ticket,raw_slot in target_owner.items()
                    if _exact_positive_int(raw_slot)==slot]
        other_here=[raw_ticket for raw_ticket,raw_slot in other_owner.items()
                    if _exact_positive_int(raw_slot)==slot]
        return (owned_here==[ticket] and not other_here and
                _exact_positive_int(target_owner.get(str(ticket)))==slot and
                _exact_positive_int(target_map.get(str(ticket)))==slot)
    except Exception:
        return False


_SOURCE_REVIEW_FIELDS=(
    "source_review_state","source_review_command_id","source_review_job_id",
    "source_review_slot","source_review_leg","source_review_ticket",
)


def _single_leg_review_close_source(item, review):
    """Freeze the risk record that authorized an exact-ticket close."""
    return {
        "single_leg_review_authorized":True,
        "source_review_state":str((review or {}).get("state") or "").upper(),
        "source_review_command_id":str((review or {}).get("command_id") or ""),
        "source_review_job_id":str((review or {}).get("job_id") or ""),
        "source_review_slot":int((item or {}).get("slot") or 0),
        "source_review_leg":str((item or {}).get("leg") or ""),
        "source_review_ticket":int((item or {}).get("ticket") or 0),
    }


def _source_job_single_leg_exposure(source_job):
    """Return the one exact open ticket durably proven by a source review job."""
    result=(source_job or {}).get("result")
    if isinstance(result,bytes):
        result=result.decode("utf-8","replace")
    if isinstance(result,str):
        try: result=json.loads(result)
        except (TypeError,ValueError): return None
    if not isinstance(result,dict):
        return None
    if isinstance(result.get("prior_result"),dict):
        result=result["prior_result"]
    tickets=result.get("open_tickets")
    if not isinstance(tickets,dict):
        return None
    exposed=[]
    for leg in ("main","hedge"):
        ticket=_exact_positive_int(tickets.get(leg))
        if ticket is not None:
            exposed.append((leg,ticket))
    return exposed[0] if len(exposed)==1 else None


def _source_single_leg_review_identity(value):
    """Return a complete immutable source identity, or None for ordinary closes."""
    value=value or {}
    authorized=value.get("single_leg_review_authorized")
    if str(authorized).lower() not in ("1","true"):
        return None
    identity={name:value.get(name) for name in _SOURCE_REVIEW_FIELDS}
    identity["source_review_state"]=str(identity.get("source_review_state") or "").upper()
    identity["source_review_command_id"]=str(identity.get("source_review_command_id") or "")
    identity["source_review_job_id"]=str(identity.get("source_review_job_id") or "")
    identity["source_review_leg"]=str(identity.get("source_review_leg") or "")
    identity["source_review_slot"]=_exact_positive_int(identity.get("source_review_slot"))
    identity["source_review_ticket"]=_exact_positive_int(identity.get("source_review_ticket"))
    required=(
        identity["source_review_state"]=="SINGLE_LEG_EXPOSED",
        bool(identity["source_review_command_id"]),
        bool(identity["source_review_job_id"]),
        identity["source_review_leg"] in ("main","hedge"),
        identity["source_review_slot"] is not None,
        identity["source_review_ticket"] is not None,
    )
    return identity if all(required) else {}


def _source_resolution_matches(result, identity, resolved_by):
    result=result if isinstance(result,dict) else {}
    resolution=result.get("manual_resolution")
    if not isinstance(resolution,dict):
        return False
    return (
        resolution.get("reason")=="manual_exact_ticket_risk_closed" and
        str(resolution.get("resolved_by_command_id") or "")==str(resolved_by) and
        str(resolution.get("leg") or "")==identity["source_review_leg"] and
        _exact_positive_int(resolution.get("ticket"))==identity["source_review_ticket"] and
        _exact_positive_int(resolution.get("slot"))==identity["source_review_slot"]
    )


def _resolve_source_single_leg_review_after_close(username, symbol, command_id, value):
    """Retire the originating exposed job only after its exact ticket is closed."""
    identity=_source_single_leg_review_identity(value)
    if identity is None:
        return True,""
    if not identity:
        return False,"source_review_identity_incomplete"
    if (identity["source_review_leg"]!=str((value or {}).get("leg") or "") or
            identity["source_review_ticket"]!=_exact_positive_int((value or {}).get("ticket")) or
            identity["source_review_slot"]!=_exact_positive_int((value or {}).get("slot"))):
        return False,"source_review_close_identity_mismatch"

    leg=identity["source_review_leg"]; ticket=str(identity["source_review_ticket"])
    try:
        owner=R.hget(_slotowner_key(leg,symbol,username),ticket)
        mapped=R.hget(_slotmap_key(leg,symbol,username),ticket)
        tombstone=R.zscore(_closed_ticket_key(username,leg,symbol),ticket)
        if owner is not None or mapped is not None:
            return False,"source_review_ticket_still_owned"
        if tombstone is None or float(tombstone)<=_dt.datetime.utcnow().timestamp():
            return False,"source_review_closed_tombstone_missing"
    except Exception as ex:
        return False,"source_review_truth_unavailable:%s"%ex.__class__.__name__

    source_job_id=identity["source_review_job_id"]
    source_command_id=identity["source_review_command_id"]
    try:
        source_job=TRADE_QUEUE.get_job(source_job_id)
    except Exception as ex:
        return False,"source_review_job_read_failed:%s"%ex.__class__.__name__
    if not isinstance(source_job,dict):
        return False,"source_review_job_missing"
    if (str(source_job.get("username") or "")!=str(username) or
            str(source_job.get("symbol") or "XAUUSD")!=str(symbol) or
            _exact_positive_int(source_job.get("slot"))!=identity["source_review_slot"] or
            str(source_job.get("command_id") or "")!=source_command_id or
            str(source_job.get("op") or "")!="open_pair"):
        return False,"source_review_job_identity_mismatch"
    source_state=str(source_job.get("state") or "").upper()
    already_resolved=(source_state=="FAILED" and
                      _source_resolution_matches(source_job.get("result"),identity,command_id))
    if source_state!="SINGLE_LEG_EXPOSED" and not already_resolved:
        return False,"source_review_job_state_changed:%s"%(source_state or "missing")
    if _source_job_single_leg_exposure(source_job)!=(
            identity["source_review_leg"],identity["source_review_ticket"]):
        return False,"source_review_job_ticket_mismatch"

    resolution={
        "reason":"manual_exact_ticket_risk_closed",
        "resolved_by_command_id":str(command_id),
        "source_command_id":source_command_id,
        "source_job_id":source_job_id,
        "slot":identity["source_review_slot"],
        "leg":leg,"ticket":identity["source_review_ticket"],
        "resolved_at":_dt.datetime.utcnow().isoformat(),
    }
    if not already_resolved:
        try:
            reconciled=TRADE_QUEUE.reconcile_finish(source_job_id,"FAILED",result={
                "manual_resolution":resolution,"prior_result":source_job.get("result")})
        except Exception as ex:
            return False,"source_review_job_resolution_failed:%s"%ex.__class__.__name__
        if (not isinstance(reconciled,dict) or
                str(reconciled.get("state") or "").upper()!="FAILED" or
                not _source_resolution_matches(reconciled.get("result"),identity,command_id)):
            return False,"source_review_job_resolution_failed"

    try:
        _release_entry_capacity_reservation(username,source_job_id)
    except Exception as ex:
        return False,"source_review_capacity_release_failed:%s"%ex.__class__.__name__
    try:
        capacity_keys=_entry_capacity_reservation_keys(username)
        if (R.hget(capacity_keys[0],source_job_id) is not None or
                R.zscore(capacity_keys[1],source_job_id) is not None or
                R.hget(_entry_capacity_hold_failure_key(username),source_job_id) is not None):
            return False,"source_review_capacity_release_failed"
    except Exception as ex:
        return False,"source_review_capacity_verify_failed:%s"%ex.__class__.__name__

    try:
        tracer=get_tracer()
        source_command=tracer.get_command(source_command_id)
        if source_command:
            tracer.update_field(source_command_id,"manual_resolution",resolution)
            tracer.update_field(source_command_id,"failure_reason","manual_exact_ticket_risk_closed")
            tracer.update_status(source_command_id,CommandStatus.FAILED)
            updated=tracer.get_command(source_command_id) or {}
            if (str(updated.get("status") or "").upper()!="FAILED" or
                    str(updated.get("failure_reason") or "")!="manual_exact_ticket_risk_closed"):
                return False,"source_review_command_resolution_failed"
    except Exception as ex:
        return False,"source_review_command_resolution_failed:%s"%ex.__class__.__name__

    try:
        raw=R.get(_slotreview_key(username,symbol,identity["source_review_slot"]))
        if raw:
            if isinstance(raw,bytes): raw=raw.decode("utf-8","replace")
            current=json.loads(raw)
            if not isinstance(current,dict):
                return False,"source_review_latch_invalid"
            current_command=str(current.get("command_id") or "")
            if current_command not in ("",source_command_id,str(command_id)):
                return False,"source_review_latch_identity_changed"
            _clear_slot_review(username,symbol,identity["source_review_slot"],
                               current_command or None)
        if R.get(_slotreview_key(username,symbol,identity["source_review_slot"])) is not None:
            return False,"source_review_latch_clear_failed"
    except Exception as ex:
        return False,"source_review_latch_verify_failed:%s"%ex.__class__.__name__

    try:
        tracer.update_field(command_id,"source_review_resolution",resolution)
    except Exception as ex:
        return False,"source_review_close_command_update_failed:%s"%ex.__class__.__name__
    return True,""

_ACCOUNT_OP_TTL=max(30,int(os.environ.get("QH_ACCOUNT_OP_TTL","90")))

def _accountop_key(username):
    return RNS+"accountop:"+(username or "").strip()

def _acquire_account_op(username, token, ttl=_ACCOUNT_OP_TTL):
    """Allow one non-terminal broker operation across every slot of an account."""
    script="""
    local current = redis.call('get', KEYS[1])
    if not current or current == ARGV[1] then
        redis.call('set', KEYS[1], ARGV[1], 'EX', ARGV[2])
        return 1
    end
    return 0
    """
    try:
        return bool(R.eval(script,1,_accountop_key(username),str(token),str(max(1,int(ttl)))))
    except Exception:
        return False

def _release_account_op(username, token):
    if not token: return False
    script="""
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """
    try:
        return bool(R.eval(script,1,_accountop_key(username),str(token)))
    except Exception:
        return False

def _begin_account_op(username, token):
    if _acquire_account_op(username,token): return token
    try: remaining=max(1,int((R.pttl(_accountop_key(username)) or 0)/1000)+1)
    except Exception: remaining=_ACCOUNT_OP_TTL
    raise HTTPException(409,
        "ACCOUNT_EXECUTION_BUSY: 该账号上一笔交易尚未终态，请等待后再操作(锁剩余约%d秒)"%remaining)

_POSITION_OVERLAY_TTL=60
_CLOSED_TICKET_TTL=60

def _position_overlay_key(username, leg, symbol):
    return RNS+"position_overlay:%s:%s:%s"%((username or "").strip(),leg,symbol)

def _position_overlay_exp_key(username, leg, symbol):
    return RNS+"position_overlay_exp:%s:%s:%s"%((username or "").strip(),leg,symbol)

def _position_overlay_stable_key(username, symbol, pair_id):
    return RNS+"position_overlay_stable:%s:%s:%s"%((username or "").strip(),symbol,pair_id)

def _closed_ticket_key(username, leg, symbol):
    return RNS+"closed_ticket:%s:%s:%s"%((username or "").strip(),leg,symbol)

def _ticket_of(payload):
    payload=payload or {}
    return payload.get("order") or payload.get("deal") or payload.get("ticket")

def _record_trace_timestamp_once(tracer, command_id, timestamp_name):
    """Keep terminal latency anchors stable across reconciliation retries."""
    value=_dt.datetime.utcnow().isoformat()
    redis_client=getattr(tracer,"redis",None)
    key_prefix=getattr(tracer,"key_prefix",None)
    if redis_client is not None and key_prefix:
        key="%s%s"%(key_prefix,command_id)
        try:
            if redis_client.hsetnx(key,timestamp_name,value):
                return value
            stored=redis_client.hget(key,timestamp_name)
            if isinstance(stored,bytes):
                stored=stored.decode("utf-8","replace")
            if stored not in (None,""):
                return str(stored)
        except Exception:
            pass
    try:
        existing=(tracer.get_command(command_id) or {}).get(timestamp_name)
        if existing not in (None,""):
            return existing
    except Exception:
        pass
    tracer.record_timestamp(command_id,timestamp_name,value)
    return value

def _timestamp_from_epoch_ns(value):
    try:
        epoch_ns=int(value)
        if epoch_ns<=0:
            return None
        return _dt.datetime.utcfromtimestamp(epoch_ns/1_000_000_000).isoformat()
    except (TypeError,ValueError,OverflowError,OSError):
        return None

def _trace_timestamp_sort_key(value):
    try:
        return _dt.datetime.fromisoformat(str(value).replace("Z","+00:00")).timestamp()
    except (TypeError,ValueError,OverflowError,OSError):
        return None

def _record_trace_timestamp_value_once(tracer, command_id, timestamp_name, value):
    """Persist a source timestamp once so retries cannot move an anchor."""
    if value in (None,""):
        return None
    redis_client=getattr(tracer,"redis",None)
    key_prefix=getattr(tracer,"key_prefix",None)
    if redis_client is not None and key_prefix:
        key="%s%s"%(key_prefix,command_id)
        try:
            if redis_client.hsetnx(key,timestamp_name,str(value)):
                return str(value)
            stored=redis_client.hget(key,timestamp_name)
            if isinstance(stored,bytes):
                stored=stored.decode("utf-8","replace")
            if stored not in (None,""):
                return str(stored)
        except Exception:
            pass
    try:
        existing=(tracer.get_command(command_id) or {}).get(timestamp_name)
        if existing not in (None,""):
            return existing
    except Exception:
        pass
    tracer.record_timestamp(command_id,timestamp_name,str(value))
    return str(value)

def _trace_leg_bridge_ack(tracer, command_id, leg, result):
    """Record only an explicit durable Agent/Bridge admission response."""
    try:
        result=result if isinstance(result,dict) else {}
        if not (result.get("accepted") is True and result.get("pending") is True and
                result.get("unknown") is not True and
                str(result.get("state") or "").upper() in
                ("PENDING","SENDING","DISPATCHING")):
            return False
        field=(TraceTimestamp.BRIDGE_ACK_MAIN if leg=="main"
               else TraceTimestamp.BRIDGE_ACK_HEDGE)
        trace=result.get("trace") if isinstance(result.get("trace"),dict) else {}
        ack_value=_timestamp_from_epoch_ns(trace.get("agent_wal_durable_ns"))
        if ack_value:
            _record_trace_timestamp_value_once(tracer,command_id,field,ack_value)
        else:
            _record_trace_timestamp_once(tracer,command_id,field)
        return True
    except Exception:
        return False

def _trace_pair_bridge_ack(tracer, command_id, result):
    result=result if isinstance(result,dict) else {}
    for leg in ("main","hedge"):
        _trace_leg_bridge_ack(tracer,command_id,leg,result.get(leg))

def _trace_leg_broker_terminal(tracer, command_id, leg, result):
    """Record a successful terminal only when Bridge supplies native timing."""
    try:
        result=result if isinstance(result,dict) else {}
        if not (bool(result.get("success") or result.get("ok")) and
                not result.get("pending") and not result.get("unknown") and
                "error" not in result):
            return None
        timing=result.get("execution_timing")
        value=(_timestamp_from_epoch_ns(timing.get("execution_completed_at_ns"))
               if isinstance(timing,dict) else None)
        if not value:
            return None
        field=(TraceTimestamp.BROKER_TERMINAL_MAIN if leg=="main"
               else TraceTimestamp.BROKER_TERMINAL_HEDGE)
        _record_trace_timestamp_value_once(tracer,command_id,field,value)
        return value
    except Exception:
        return None

def _trace_pair_execution(tracer, command_id, result, mark_ack=False):
    try:
        result=result if isinstance(result,dict) else {}
        terminal=[]
        for leg in ("main","hedge"):
            leg_result=result.get(leg)
            if mark_ack:
                _trace_leg_bridge_ack(tracer,command_id,leg,leg_result)
            terminal.append(_trace_leg_broker_terminal(
                tracer,command_id,leg,leg_result))
        if not all(terminal):
            return False
        confirmed=max(terminal,key=lambda value: _trace_timestamp_sort_key(value) or 0)
        _record_trace_timestamp_value_once(
            tracer,command_id,TraceTimestamp.BROKER_TERMINAL_CONFIRMED,confirmed)
        return True
    except Exception:
        return False

def _update_trace_fields(tracer, command_id, fields):
    """Use the production tracer's batch write while preserving test adapters."""
    try:
        fields=dict(fields or {})
        if not fields:
            return
        update_many=getattr(tracer,"update_fields",None)
        if callable(update_many):
            update_many(command_id,fields)
            return
        for field,value in fields.items():
            tracer.update_field(command_id,field,value)
    except Exception:
        return

def _open_ledger_commit_once(command_id, ledger_key, entry, tracer=None):
    """Atomically append one recovered open ledger row per command.

    Releases before this guard recorded q12 only after appending.  When q12 is
    already present, seed the idempotency marker without appending so an older
    partially completed recovery cannot duplicate its FIFO ledger row.
    """
    command_id=str(command_id or "").strip()
    ledger_key=str(ledger_key or "").strip()
    if not command_id or not ledger_key or not isinstance(entry,dict):
        return False
    already_committed=False
    committed_at=None
    try:
        command=(tracer or get_tracer()).get_command(command_id) or {}
        raw_commit=command.get(TraceTimestamp.LEDGER_COMMITTED)
        already_committed=str(raw_commit or "").strip().lower() not in ("", "0", "false", "none", "null")
        if already_committed:
            try:
                committed_at=_dt.datetime.fromisoformat(
                    str(raw_commit).replace("Z","+00:00")).replace(tzinfo=None)
            except (TypeError,ValueError):
                return False
    except Exception:
        already_committed=False
    entry=dict(entry)
    supplied_command_id=str(entry.get("command_id") or "").strip()
    if supplied_command_id and supplied_command_id!=command_id:
        return False
    entry["command_id"]=command_id
    payload=json.dumps(entry,ensure_ascii=False,separators=(",",":"),default=str)
    legacy_match={key:entry.get(key) for key in ("q","m","s","ladder")}
    legacy_min_ts=(committed_at-_dt.timedelta(seconds=2)).isoformat() if committed_at else ""
    legacy_max_ts=(committed_at+_dt.timedelta(seconds=2)).isoformat() if committed_at else ""
    marker_key=RNS+"open_ledger:commits"
    script="""
    local marker_type=redis.call('type',KEYS[1])['ok']
    local ledger_type=redis.call('type',KEYS[2])['ok']
    if marker_type ~= 'none' and marker_type ~= 'hash' then return -2 end
    if ledger_type ~= 'none' and ledger_type ~= 'list' then return -3 end
    local existing=redis.call('hget',KEYS[1],ARGV[1])
    if existing then
        local existing_ok,existing_item=pcall(cjson.decode,existing)
        if not existing_ok or type(existing_item) ~= 'table' then return -6 end
        local existing_command=tostring(existing_item['command_id'] or '')
        if existing_command ~= '' and existing_command ~= ARGV[1] then return -7 end
        if existing_command == '' and ARGV[3] == '' then return -8 end
        return 0
    end
    if ARGV[3] ~= '' then
        local ok,wanted=pcall(cjson.decode,ARGV[3])
        if not ok or type(wanted) ~= 'table' then return -4 end
        local rows=redis.call('lrange',KEYS[2],0,-1)
        for _,row in ipairs(rows) do
            local row_ok,item=pcall(cjson.decode,row)
            if row_ok and type(item) == 'table'
                and (not item['command_id'] or tostring(item['command_id']) == ARGV[1])
                and tonumber(item['q']) == tonumber(wanted['q'])
                and tonumber(item['m']) == tonumber(wanted['m'])
                and tonumber(item['s']) == tonumber(wanted['s'])
                and tonumber(item['ladder']) == tonumber(wanted['ladder'])
                and tostring(item['ts'] or '') >= ARGV[4]
                and tostring(item['ts'] or '') <= ARGV[5] then
                redis.call('hset',KEYS[1],ARGV[1],row)
                return 2
            end
        end
        return -5
    end
    -- Recover a crash after RPUSH but before HSET.  A retry has a fresh ts,
    -- so use the command id plus immutable economic fields as its identity.
    local wanted_ok,wanted=pcall(cjson.decode,ARGV[2])
    if not wanted_ok or type(wanted) ~= 'table' then return -4 end
    local rows=redis.call('lrange',KEYS[2],0,-1)
    for _,row in ipairs(rows) do
        local row_ok,item=pcall(cjson.decode,row)
        if row_ok and type(item) == 'table'
            and tostring(item['command_id'] or '') == ARGV[1] then
            if tonumber(item['q']) == tonumber(wanted['q'])
                and tonumber(item['m']) == tonumber(wanted['m'])
                and tonumber(item['s']) == tonumber(wanted['s'])
                and tonumber(item['ladder']) == tonumber(wanted['ladder']) then
                redis.call('hset',KEYS[1],ARGV[1],row)
                return 2
            end
            return -9
        end
    end
    redis.call('rpush',KEYS[2],ARGV[2])
    redis.call('hset',KEYS[1],ARGV[1],ARGV[2])
    return 1
    """

    def _transactional_fallback():
        """Use WATCH/MULTI only when the Redis client has no EVAL command.

        Some development Redis shims (notably older fakeredis builds) expose
        normal list/hash commands but reject EVAL.  Keep the same identity and
        legacy-row rules in a bounded optimistic transaction; all other Redis
        errors still fail closed in the caller.
        """
        for _attempt in range(5):
            pipe=R.pipeline(transaction=True)
            try:
                pipe.watch(marker_key,ledger_key)
                marker_type=str(pipe.type(marker_key) or "none")
                ledger_type=str(pipe.type(ledger_key) or "none")
                if marker_type not in ("none","hash"):
                    pipe.unwatch(); return -2
                if ledger_type not in ("none","list"):
                    pipe.unwatch(); return -3
                existing=pipe.hget(marker_key,command_id)
                if existing is not None:
                    if isinstance(existing,bytes):
                        existing=existing.decode("utf-8","replace")
                    try:
                        item=json.loads(existing)
                    except Exception:
                        pipe.unwatch(); return -6
                    existing_command=str((item or {}).get("command_id") or "")
                    if existing_command and existing_command!=command_id:
                        pipe.unwatch(); return -7
                    if not existing_command and not already_committed:
                        pipe.unwatch(); return -8
                    pipe.unwatch(); return 0
                rows=pipe.lrange(ledger_key,0,-1) or []
                match=None
                if already_committed:
                    wanted=legacy_match
                    for raw in rows:
                        if isinstance(raw,bytes):
                            raw=raw.decode("utf-8","replace")
                        try: item=json.loads(raw)
                        except Exception: continue
                        if (str(item.get("command_id") or "") not in ("",command_id) or
                            any(_numeric(item.get(key)) != _numeric(wanted.get(key))
                                for key in ("q","m","s","ladder"))):
                            continue
                        item_ts=str(item.get("ts") or "")
                        if legacy_min_ts <= item_ts <= legacy_max_ts:
                            match=raw; break
                    if match is None:
                        pipe.unwatch(); return -5
                else:
                    for raw in rows:
                        if isinstance(raw,bytes):
                            raw=raw.decode("utf-8","replace")
                        try: item=json.loads(raw)
                        except Exception: continue
                        if str(item.get("command_id") or "") != command_id:
                            continue
                        if not all(_numeric(item.get(key)) == _numeric(entry.get(key))
                                   for key in ("q","m","s","ladder")):
                            pipe.unwatch(); return -9
                        match=raw; break
                pipe.multi()
                if match is not None:
                    pipe.hset(marker_key,command_id,match)
                    pipe.execute()
                    return 2
                pipe.rpush(ledger_key,payload)
                pipe.hset(marker_key,command_id,payload)
                pipe.execute()
                return 1
            except redis.exceptions.WatchError:
                continue
            finally:
                pipe.reset()
        return -10

    def _numeric(value):
        try: return float(value)
        except (TypeError,ValueError): return None

    try:
        try:
            result=int(R.eval(script,2,marker_key,ledger_key,
                              command_id,payload,
                              json.dumps(legacy_match,separators=(",",":")) if already_committed else "",
                              legacy_min_ts,legacy_max_ts) or 0)
        except redis.exceptions.ResponseError as ex:
            # Only an unavailable EVAL command may use the equivalent
            # transaction.  ACL/type/runtime errors remain fail-closed.
            detail=str(ex).lower()
            if "unknown command" not in detail or "eval" not in detail:
                return False
            result=int(_transactional_fallback())
        if result not in (0,1,2):
            return False
        stored=R.hget(marker_key,command_id)
        if isinstance(stored,bytes):
            stored=stored.decode("utf-8","replace")
        if not stored:
            return False
        try:
            stored_entry=json.loads(stored)
        except Exception:
            return False
        stored_command_id=str(stored_entry.get("command_id") or "").strip()
        if stored_command_id:
            if stored_command_id!=command_id:
                return False
        elif not already_committed:
            return False
        def _stable(value):
            if not isinstance(value,dict):
                return None
            return {key:value.get(key) for key in ("q","m","s","ladder")}
        if _stable(stored_entry)!=_stable(entry):
            return False
        try:
            rows=R.lrange(ledger_key,0,-1)
        except Exception:
            return False
        found=False
        for row in rows or ():
            if isinstance(row,bytes):
                row=row.decode("utf-8","replace")
            if row!=stored:
                continue
            try:
                decoded=json.loads(row)
                if already_committed and not stored_command_id and result==2:
                    try:
                        row_at=_dt.datetime.fromisoformat(
                            str(decoded.get("ts") or "").replace("Z","+00:00")).replace(tzinfo=None)
                        if abs((row_at-committed_at).total_seconds())>2.0:
                            continue
                    except (TypeError,ValueError):
                        continue
                found=True; break
            except Exception:
                continue
        # q12 from the legacy release is accepted only when the physical FIFO
        # row is present; the marker alone is not ledger proof.
        if not found:
            return False
        return True
    except Exception:
        return False


def _close_ledger_commit_once(command_id, ledger_key, slot):
    """Remove exactly one slot ledger row, once per close command.

    Close retries can run after a broker callback, a process restart, or a
    durable-review promotion.  The marker stores the original JSON row so a
    retry is a no-op.  Matching by ``ladder`` keeps independent slots from
    consuming each other's FIFO entries when several rows share a direction.
    """
    command_id=str(command_id or "").strip()
    ledger_key=str(ledger_key or "").strip()
    try:
        slot=int(slot)
    except (TypeError, ValueError):
        slot=0
    if not command_id or not ledger_key or slot < 1:
        return False
    marker_key=RNS+"close_ledger:commits"
    script="""
    local marker_type=redis.call('type',KEYS[1])['ok']
    local ledger_type=redis.call('type',KEYS[2])['ok']
    if marker_type ~= 'none' and marker_type ~= 'hash' then return -2 end
    if ledger_type ~= 'none' and ledger_type ~= 'list' then return -3 end
    local existing=redis.call('hget',KEYS[1],ARGV[1])
    if existing then
        local ok,item=pcall(cjson.decode,existing)
        if not ok or type(item) ~= 'table' then return -4 end
        if tonumber(item['ladder']) ~= tonumber(ARGV[2]) then return -5 end
        return 0
    end
    local rows=redis.call('lrange',KEYS[2],0,-1)
    local found=-1
    local found_row=''
    for i,row in ipairs(rows) do
        local ok,item=pcall(cjson.decode,row)
        if found == -1 and ok and type(item) == 'table'
            and tonumber(item['ladder']) == tonumber(ARGV[2]) then
            found=i-1
            found_row=row
        end
    end
    if found == -1 then return -6 end
    local tombstone='__qh_close_ledger__:'..ARGV[1]
    redis.call('lset',KEYS[2],found,tombstone)
    redis.call('lrem',KEYS[2],1,tombstone)
    redis.call('hset',KEYS[1],ARGV[1],found_row)
    return 1
    """

    def _fallback():
        for _attempt in range(5):
            pipe=R.pipeline(transaction=True)
            try:
                pipe.watch(marker_key,ledger_key)
                marker_type=str(pipe.type(marker_key) or "none")
                ledger_type=str(pipe.type(ledger_key) or "none")
                if marker_type not in ("none","hash"):
                    pipe.unwatch(); return -2
                if ledger_type not in ("none","list"):
                    pipe.unwatch(); return -3
                existing=pipe.hget(marker_key,command_id)
                if existing is not None:
                    try:
                        item=json.loads(existing)
                    except Exception:
                        pipe.unwatch(); return -4
                    if int(item.get("ladder"))!=slot:
                        pipe.unwatch(); return -5
                    pipe.unwatch(); return 0
                rows=pipe.lrange(ledger_key,0,-1) or []
                match=None
                for idx,raw in enumerate(rows):
                    try: item=json.loads(raw)
                    except Exception: continue
                    try: same=int(item.get("ladder"))==slot
                    except (TypeError,ValueError): same=False
                    if same:
                        match=(idx,raw)
                        break
                if match is None:
                    pipe.unwatch(); return -6
                idx,raw=match
                tombstone="__qh_close_ledger__:"+command_id
                pipe.multi()
                pipe.lset(ledger_key,idx,tombstone)
                pipe.lrem(ledger_key,1,tombstone)
                pipe.hset(marker_key,command_id,raw)
                pipe.execute()
                return 1
            except redis.exceptions.WatchError:
                continue
            finally:
                pipe.reset()
        return -10

    try:
        try:
            result=int(R.eval(script,2,marker_key,ledger_key,command_id,str(slot)) or 0)
        except redis.exceptions.ResponseError as ex:
            detail=str(ex).lower()
            if "unknown command" not in detail or "eval" not in detail:
                return False
            result=int(_fallback())
        if result not in (0,1):
            return False
        stored=R.hget(marker_key,command_id)
        if isinstance(stored,bytes):
            stored=stored.decode("utf-8","replace")
        item=json.loads(stored or "null")
        if not isinstance(item,dict) or int(item.get("ladder"))!=slot:
            return False
        return True
    except (TypeError,ValueError,KeyError,json.JSONDecodeError):
        return False
    except Exception:
        return False

def _remember_open_positions(symbol, hedge_symbol, direction, res, slot, username,
                             main_volume=None, hedge_volume=None, ttl=_POSITION_OVERLAY_TTL):
    """Expose confirmed fills until both legs are stable in versioned EA snapshots."""
    now=_dt.datetime.utcnow().timestamp()
    sides={"main":("sell" if direction=="reverse" else "buy"),
           "hedge":("buy" if direction=="reverse" else "sell")}
    volumes={"main":main_volume,"hedge":hedge_volume}
    symbols={"main":symbol,"hedge":hedge_symbol or symbol}
    tickets={leg:str(_ticket_of((res or {}).get(leg) or {}))
             for leg in ("main","hedge") if _ticket_of((res or {}).get(leg) or {})}
    pair_id=("pair-"+tickets["main"]+"-"+tickets["hedge"]
             if set(tickets)=={"main","hedge"}
             else "single-"+"-".join("%s-%s"%item for item in sorted(tickets.items())))
    for leg in ("main","hedge"):
        lr=(res or {}).get(leg) or {}
        tk=_ticket_of(lr)
        if not tk: continue
        side=sides[leg]
        price=lr.get("price") or lr.get("price_open")
        volume=lr.get("filled_volume") or lr.get("volume") or volumes[leg]
        row={"ticket":tk,"symbol":symbols[leg],"side":side,
             "type":1 if side=="sell" else 0,"volume":volume or 0,
             "price":price,"price_open":price,"price_current":price,
             "profit":0,"swap":0,"comment":lr.get("comment") or "",
             "slot":int(slot),"snapshot_pending":True,"_overlay_pair":pair_id}
        try:
            key=_position_overlay_key(username,leg,symbol)
            expkey=_position_overlay_exp_key(username,leg,symbol)
            R.hset(key,str(tk),json.dumps(row,default=str))
            R.zadd(expkey,{str(tk):now+max(1,int(ttl))})
        except Exception: pass

def _forget_open_position(symbol, leg, ticket, username):
    if not ticket: return
    try:
        R.hdel(_position_overlay_key(username,leg,symbol),str(ticket))
        R.zrem(_position_overlay_exp_key(username,leg,symbol),str(ticket))
    except Exception: pass

def _mark_ticket_closed(symbol, leg, ticket, username, ttl=_CLOSED_TICKET_TTL):
    """Hide a confirmed close while an older EA snapshot may still contain the ticket."""
    if not ticket: return
    try:
        R.zadd(_closed_ticket_key(username,leg,symbol),{
            str(ticket):_dt.datetime.utcnow().timestamp()+max(1,int(ttl))
        })
    except Exception: pass
    _forget_open_position(symbol,leg,ticket,username)

def _filter_closed_tickets(pos, symbol="XAUUSD", username=None):
    now=_dt.datetime.utcnow().timestamp(); out={}
    for leg in ("main","hedge"):
        rows=[dict(p) for p in _poslist((pos or {}).get(leg)) if isinstance(p,dict)]
        key=_closed_ticket_key(username,leg,symbol); kept=[]
        try: R.zremrangebyscore(key,0,now)
        except Exception: pass
        for row in rows:
            tk=str(row.get("ticket") or "")
            try: until=R.zscore(key,tk) if tk else None
            except Exception: until=None
            if until is not None and float(until)>now: continue
            kept.append(row)
        out[leg]=kept
    return out

def _snapshot_version_token(version):
    if not isinstance(version,dict): return None
    if version.get("boot") is None or version.get("seq") is None: return None
    return "%s:%s"%(version["boot"],version["seq"])

def _merge_open_position_overlays(pos, symbol="XAUUSD", username=None, snapshot_versions=None):
    """Keep pair overlays until two distinct fresh snapshots contain every required leg."""
    now=_dt.datetime.utcnow().timestamp(); out={}; groups={}; seen_by_leg={}
    for leg in ("main","hedge"):
        rows=[dict(p) for p in _poslist((pos or {}).get(leg)) if isinstance(p,dict)]
        seen={str(p.get("ticket")) for p in rows if p.get("ticket") is not None}
        seen_by_leg[leg]=seen
        key=_position_overlay_key(username,leg,symbol)
        expkey=_position_overlay_exp_key(username,leg,symbol)
        try: overlays=R.hgetall(key) or {}
        except Exception: overlays={}
        for tk,raw in overlays.items():
            try: until=R.zscore(expkey,tk)
            except Exception: until=None
            if until is None or float(until)<=now:
                try: R.hdel(key,tk); R.zrem(expkey,tk)
                except Exception: pass
                continue
            try: row=json.loads(raw)
            except Exception:
                try: R.hdel(key,tk); R.zrem(expkey,tk)
                except Exception: pass
                continue
            pair_id=str(row.get("_overlay_pair") or ("legacy-%s-%s"%(leg,tk)))
            groups.setdefault(pair_id,[]).append({"leg":leg,"ticket":tk,"row":row,
                                                   "key":key,"expkey":expkey,
                                                   "until":float(until)})
        out[leg]=rows
    versions=snapshot_versions or {}
    for pair_id,items in groups.items():
        required={item["leg"] for item in items}
        all_seen=all(item["ticket"] in seen_by_leg.get(item["leg"],set()) for item in items)
        tokens={leg:_snapshot_version_token(versions.get(leg)) for leg in required}
        state_key=_position_overlay_stable_key(username,symbol,pair_id)
        try: state=json.loads(R.get(state_key) or "{}")
        except Exception: state={}
        count=int(state.get("count") or 0); previous=state.get("versions") or {}
        if all_seen and tokens and all(tokens.values()):
            if not previous:
                count=1
            elif all(tokens[leg]!=previous.get(leg) for leg in required):
                count+=1
            state={"count":count,"versions":tokens}
            try: R.setex(state_key,max(1,int(max(x["until"] for x in items)-now)),json.dumps(state))
            except Exception: pass
        elif not all_seen:
            count=0
            try: R.delete(state_key)
            except Exception: pass
        if count>=2:
            for item in items:
                try: R.hdel(item["key"],item["ticket"]); R.zrem(item["expkey"],item["ticket"])
                except Exception: pass
            try: R.delete(state_key)
            except Exception: pass
            continue
        for item in items:
            leg=item["leg"]; tk=item["ticket"]
            if tk not in seen_by_leg.get(leg,set()):
                out[leg].append(item["row"])
                seen_by_leg[leg].add(tk)
    return out

def _acquire_slot_op(username, symbol, slot, token, ttl=90):
    """Atomically reserve a slot across requests; direction is deliberately not part of the key."""
    try:
        return bool(R.set(_slotop_key(username,symbol,slot),str(token),nx=True,ex=max(1,int(ttl))))
    except Exception:
        return False

def _release_slot_op(username, symbol, slot, token):
    """Release only the operation token owned by this command."""
    script="""
    if redis.call('get', KEYS[1]) == ARGV[1] then
        return redis.call('del', KEYS[1])
    end
    return 0
    """
    try:
        return bool(R.eval(script,1,_slotop_key(username,symbol,slot),str(token)))
    except Exception:
        # Do not perform a non-atomic get/delete fallback. The TTL will safely release it.
        return False

def _assign_display_slot(mapkey, ownerkey, ticket, candidate):
    """Assign a provisional display slot without racing an authoritative owner write."""
    script="""
    -- qh_atomic_display_slot_assignment
    local owner=redis.call('hget',KEYS[2],ARGV[1])
    if owner then
        redis.call('hset',KEYS[1],ARGV[1],owner)
        return owner
    end
    local existing=redis.call('hget',KEYS[1],ARGV[1])
    if existing then return existing end
    local owners=redis.call('hgetall',KEYS[2])
    for i=1,#owners,2 do
        if owners[i+1] == ARGV[2] then return 0 end
    end
    local displays=redis.call('hgetall',KEYS[1])
    for i=1,#displays,2 do
        if displays[i+1] == ARGV[2] then return 0 end
    end
    redis.call('hset',KEYS[1],ARGV[1],ARGV[2])
    return ARGV[2]
    """
    return int(R.eval(script,2,mapkey,ownerkey,str(ticket),str(int(candidate))) or 0)

def _assign_claimed_display_slot(mapkey, ownerkey, ticket, candidate):
    """Apply a durable-saga display hint without creating an owner claim."""
    script="""
    -- qh_atomic_claimed_display_slot_assignment
    local owner=redis.call('hget',KEYS[2],ARGV[1])
    if owner then
        redis.call('hset',KEYS[1],ARGV[1],owner)
        return owner
    end
    local owners=redis.call('hgetall',KEYS[2])
    for i=1,#owners,2 do
        if owners[i] ~= ARGV[1] and owners[i+1] == ARGV[2] then return 0 end
    end
    local displays=redis.call('hgetall',KEYS[1])
    for i=1,#displays,2 do
        if displays[i] ~= ARGV[1] and displays[i+1] == ARGV[2] then
            if redis.call('hexists',KEYS[2],displays[i]) == 1 then return 0 end
            redis.call('hdel',KEYS[1],displays[i])
        end
    end
    redis.call('hset',KEYS[1],ARGV[1],ARGV[2])
    return ARGV[2]
    """
    return int(R.eval(script,2,mapkey,ownerkey,str(ticket),str(int(candidate))) or 0)

def _annotate_slots(pos, symbol="XAUUSD", username=None, display_claims=None):
    """给双腿持仓分配稳定坑号(Redis 持久 ticket→slot 映射: 新仓分配最小空闲坑, 平仓释放该坑)。
       每笔持仓加 slot 字段, 返回 {"main":[...],"hedge":[...]}(归一为 list)。纯显示层, 不碰下单/平仓。
       目的: 平掉几号坑→几号坑空(坑号不再随持仓增减重排)。"""
    # Every user-scoped caller must honor confirmed-close tombstones.  Some
    # execution preflights pass a raw broker snapshot here; without this guard,
    # a lagging snapshot can recreate a display claim after _release_slot().
    if username:
        pos=_filter_closed_tickets(pos,symbol,username)
    if display_claims is None:
        display_claims={}
        claim_loader=globals().get("_open_saga_ticket_slots")
        if username and callable(claim_loader):
            try: display_claims=claim_loader(username,symbol,pos) or {}
            except Exception: display_claims={}
    out={}
    for leg in ("main","hedge"):
        lst=_poslist((pos or {}).get(leg))
        lst=[dict(p) for p in (lst or []) if isinstance(p,dict)]
        mapkey=_slotmap_key(leg,symbol,username)
        ownerkey=_slotowner_key(leg,symbol,username)
        pendingkey=_slotpending_key(leg,symbol,username)
        try: cur={k:int(v) for k,v in (R.hgetall(mapkey) or {}).items()}
        except Exception: cur={}
        try: owners={k:int(v) for k,v in (R.hgetall(ownerkey) or {}).items()}
        except Exception: owners={}
        live=set(str(p.get("ticket")) for p in lst if p.get("ticket") is not None)
        # Authoritative reservations always win over provisional display slots.
        for tk in live:
            if tk in owners and cur.get(tk)!=owners[tk]:
                cur[tk]=owners[tk]; R.hset(mapkey,tk,cur[tk])
        # 首次切换到用户隔离映射时，仅迁移该用户当前可见 ticket 的旧映射。
        if username:
            try:
                legacy=R.hgetall(_slotmap_key(leg,symbol)) or {}
                for tk in live:
                    if tk not in cur and tk in legacy:
                        cur[tk]=int(legacy[tk]); R.hset(mapkey,tk,cur[tk])
            except Exception: pass
        # A broker snapshot can expose one leg before the pair finalizer writes
        # authoritative ownership.  Rebind only an unambiguous durable-saga
        # hint so the row never borrows the smallest free slot in the interim.
        leg_claims={}
        claim_counts={}
        for p in lst:
            ticket=str(p.get("ticket"))
            try: claimed=int(display_claims.get((leg,ticket)) or 0)
            except (TypeError,ValueError): claimed=0
            if claimed>0:
                leg_claims[ticket]=claimed
                claim_counts[claimed]=claim_counts.get(claimed,0)+1
        for ticket,claimed in sorted(leg_claims.items(),key=lambda item:(item[1],item[0])):
            if claim_counts.get(claimed)!=1:
                continue
            try: _assign_claimed_display_slot(mapkey,ownerkey,ticket,claimed)
            except Exception: pass
        if leg_claims:
            try: cur={k:int(v) for k,v in (R.hgetall(mapkey) or {}).items()}
            except Exception: cur={}
            try: owners={k:int(v) for k,v in (R.hgetall(ownerkey) or {}).items()}
            except Exception: owners={}
        now=_dt.datetime.utcnow().timestamp()
        for tk in list(cur.keys()):        # 释放已平仓 ticket 占的坑
            if tk in live:
                try: R.zrem(pendingkey,tk)
                except Exception: pass
                continue
            try: pending_until=R.zscore(pendingkey,tk)
            except Exception: pending_until=None
            if pending_until is not None and float(pending_until)>now:
                continue  # Broker 已确认但 EA 持仓快照尚未刷新，保留原坑位。
            # A position snapshot is read evidence, not a close confirmation.
            # Transient empty snapshots may release the display slot, but the
            # authoritative owner survives until _release_slot() observes a
            # confirmed close.  If the ticket reappears, the owner restores the
            # original display mapping above instead of silently re-slotting it.
            R.hdel(mapkey,tk); cur.pop(tk,None)
            try: R.zrem(pendingkey,tk)
            except Exception: pass
        # A transient snapshot may have removed an authoritative ticket from
        # the display map.  Keep its slot unavailable until a confirmed close
        # releases the owner, otherwise a newly observed row can reuse it.
        used=set(cur.values()) | set(owners.values())
        new=[p for p in lst if str(p.get("ticket")) not in cur]
        new.sort(key=lambda p: float(p.get("time") or 0))   # 早开=小坑号
        for p in new:
            ticket=str(p.get("ticket")); s=1
            while True:
                while s in used: s+=1
                assigned=_assign_display_slot(mapkey,ownerkey,ticket,s)
                if assigned>0:
                    used.add(assigned); cur[ticket]=assigned
                    break
                s+=1
        for p in lst:
            ticket=str(p.get("ticket"))
            slot=cur.get(ticket,0)
            p["slot"]=slot
            # slotmap is only a stable display assignment. Pair-close controls
            # may trust a slot only when the durable execution owner agrees.
            p["ownership_verified"]=bool(slot and owners.get(ticket)==slot)
        out[leg]=lst
    return out

def _mark_slot_busy(symbol, slot, ttl=3, username=None):
    """标记某坑"正在操作中"(进/出), 供前端行进度渐变。zset member=坑号 score=过期时刻(秒)。"""
    try:
        now=_dt.datetime.utcnow().timestamp()
        scope=((username or "").strip()+":") if username else ""
        R.zadd(RNS+"slotbusy:"+scope+symbol, {str(int(slot)): now+ttl})
    except Exception: pass

def _clear_slot_busy(symbol, slot, username=None):
    try:
        scope=((username or "").strip()+":") if username else ""
        R.zrem(RNS+"slotbusy:"+scope+symbol,str(int(slot)))
    except Exception: pass

def _busy_slots(symbol, username=None):
    try:
        scope=((username or "").strip()+":") if username else ""
        now=_dt.datetime.utcnow().timestamp(); bk=RNS+"slotbusy:"+scope+symbol
        R.zremrangebyscore(bk,0,now)
        return [int(x) for x in (R.zrangebyscore(bk,now,"+inf") or [])]
    except Exception: return []

@app.get("/api/engine/legs", dependencies=[Depends(require_optional_subject)])
async def engine_legs(username:str="", x_license: str = Header(default="")):
    """双腿状态+持仓+忙坑。**P1 账户卡按用户隔离**(2026-07-21):
       带 username 时, 用户登记账户==全局执行桥账户→数据真属于他(正常显示); 不匹配→标未接入执行桥
       (显登记信息但余额/连接置空)+清空该腿持仓(绝不串显别人数据); 未登记→未登记态。
       不带 username=原全局逻辑(WS 全局快照/向后兼容)。"""
    try:
        # HTTP requests with an authenticated header are always scoped to that
        # principal when the legacy username query is omitted.  Admin/internal
        # callers deliberately omit both and retain the global view.
        if not username:
            username=_LICENSE_PRINCIPAL.get() or _license_to_username(x_license) or ""
        if username:
            rows=_reg_rows_for(username)
            # Route directly to the requested user's bridge before touching any global bridge.
            ucon=_user_bridge_conn(username)
            if ucon is None:
                # No per-user bridge: use only that user's registered A2T legs,
                # never the process-global CONN.
                ucon=_strict_user_read_conn(username)
            if ucon is not None:
                ust={}; upos={"main":[],"hedge":[]}; usnap={}
                async def _read_user_leg(_r):
                    reg=rows.get(_r); regl=str((reg or {}).get("login") or "").strip()
                    legobj=getattr(ucon,_r,None)
                    if not regl or legobj is None:
                        return _r,{"registered":bool(regl),"connected":False,"account":regl or "--",
                                   "server":(reg or {}).get("server") or "--",
                                   "platform":(reg or {}).get("platform") or "--","note":("桥未配置" if regl else None)},[],None
                    cache_key=(username,_r)
                    async def _positions_with_health():
                        try:
                            raw=await legobj.positions()
                            if _position_snapshot_stale(raw):
                                return False,[],_position_snapshot_version(raw),"snapshot_stale"
                            # MT4 and MT5 bridge legs share the same versioned
                            # snapshot contract.  A fresh-looking positions
                            # list without boot/sequence/source metadata is
                            # an old bridge response, not authoritative truth.
                            if isinstance(raw,dict) and "positions" in raw:
                                version = _position_snapshot_version(raw)
                                if (version is None or
                                        version.get("ts_ms", 0) <= 0 or
                                        version.get("source") not in ("broker", "ea_file")):
                                    return False,[],None,"snapshot_metadata_missing"
                            accepted,version=_accept_position_snapshot_version(cache_key,raw)
                            positions=(raw.get("positions",raw) if isinstance(raw,dict) else (raw or []))
                            return accepted,positions,version,(None if accepted else "snapshot_regression")
                        except Exception as ex:
                            return False,[],None,ex.__class__.__name__
                    s,pos_result=await _aio.gather(
                        _leg_status_safe(legobj),_positions_with_health()
                    )
                    pos_ok,positions,version,pos_error=pos_result
                    conn_ok=bool(s.get("connected")) and "error" not in s
                    status={"registered":True,"on_bridge":conn_ok,"connected":conn_ok,
                            "account":str(s.get("account") or regl),"server":s.get("server") or (reg or {}).get("server") or "--",
                            "platform":(reg or {}).get("platform") or _platform_of_login(regl) or "--",
                            "balance":s.get("balance"),"equity":s.get("equity"),
                            "note":(None if conn_ok else "桥客户端离线/未启动")}
                    if pos_ok:
                        _USER_POSITION_CACHE[cache_key]=(_t_conn.monotonic(),positions,version)
                    else:
                        cached=_USER_POSITION_CACHE.get(cache_key)
                        positions=(cached[1] if cached and _t_conn.monotonic()-cached[0]<5.0 else [])
                        version=(cached[2] if cached and len(cached)>2 else None)
                        status["positions_stale"]=bool(cached) or pos_error=="snapshot_stale"
                        status["positions_error"]=pos_error
                    if version:
                        status["position_snapshot"]={k:version.get(k) for k in
                            ("boot","seq","ts","ts_ms","age_ms","stale","source")}
                    return _r,status,positions,version
                for _r,_st,_pos,_ver in await _aio.gather(
                    _read_user_leg("main"), _read_user_leg("hedge")
                ):
                    ust[_r]=_st; upos[_r]=_pos; usnap[_r]=_ver
                try:
                    upos=_normalize_position_legs(upos)
                    upos=_filter_closed_tickets(upos,"XAUUSD",username)
                    upos=_merge_open_position_overlays(upos,"XAUUSD",username,usnap)
                    upos=_normalize_position_legs(upos)
                    upos=_annotate_slots(upos,"XAUUSD",username)
                except Exception: pass
                return {"status":ust,"positions":upos,"position_versions":usnap,
                        "busy_slots":_busy_slots("XAUUSD",username)}
        st = await CONN.both_status() if hasattr(CONN,"both_status") else {"main":await CONN.status(),"hedge":None}
        pos = await CONN.both_positions() if hasattr(CONN,"both_positions") else {"main":await CONN.positions(),"hedge":None}
        pos = _normalize_position_legs(pos)
        try: pos=_annotate_slots(pos, "XAUUSD")   # 注入稳定坑号
        except Exception as _e: R.set(RNS+"engine:slotmap_err", str(_e)[:120])
        if username:
            # ---- 无 per-user bridge_url: 回落 P1(登记 vs 全局桥账户对比, 不串显) ----
            bm,bh=await _exec_bridge_accounts(); bacc={"main":bm,"hedge":bh}
            posout={"main":[],"hedge":[]}
            for _r in ("main","hedge"):
                reg=rows.get(_r); regl=str((reg or {}).get("login") or "").strip()
                bridge_acc=str(bacc.get(_r) or "").strip()
                if not regl:
                    st[_r]={"registered":False,"connected":False,"account":"--","server":"--","platform":"--"}
                elif bridge_acc and regl!=bridge_acc:
                    st[_r]={"registered":True,"on_bridge":False,"connected":False,
                            "account":regl,"server":(reg or {}).get("server") or "--",
                            "platform":(reg or {}).get("platform") or _platform_of_login(regl) or "--",
                            "note":"未接入执行桥"}
                else:
                    if isinstance(st.get(_r),dict):
                        if not st[_r].get("platform"):
                            st[_r]["platform"]=_platform_of_login(regl) or (reg or {}).get("platform") or "--"
                        posout[_r]=(pos.get(_r) if isinstance(pos,dict) else None) or []
            pos=posout
            try:
                pos=_filter_closed_tickets(pos,"XAUUSD",username)
                pos=_merge_open_position_overlays(pos,"XAUUSD",username)
                pos=_normalize_position_legs(pos)
                pos=_annotate_slots(pos,"XAUUSD",username)
            except Exception: pass
            return {"status":st,"positions":pos,"busy_slots":_busy_slots("XAUUSD",username)}
        # ---- 无 username: 原全局逻辑 ----
        try:
            reg=_reg_roles()
            if isinstance(st,dict):
                for _r in ("main","hedge"):
                    if _r not in reg:
                        st[_r]={"registered":False,"connected":False,"account":"--","server":"--","platform":"--"}
                    elif isinstance(st.get(_r),dict) and not st[_r].get("platform"):
                        acc=str(st[_r].get("account") or "").strip()
                        if acc and acc not in ("","--"):
                            st[_r]["platform"]=_platform_of_login(acc) or "--"
        except Exception: pass
        return {"status":st,"positions":pos,"busy_slots":_busy_slots("XAUUSD")}
    except Exception as e:
        raise HTTPException(502,"bridge error: %s"%e)

@app.get("/api/engine/conn_mode")
async def engine_conn_mode(principal: str = Depends(require_license)):
    """连接方式(旧前端兼容): api/云端连接已彻底移除, 恒 bridge; 只查 bridge 健康, 绝不碰 api/FRA(已停机)。"""
    bok,_=await _conn_health_user(principal)
    return {"active_mode":"bridge","consistency":_conn_consistency(principal),
            "health":{"bridge":bok,"api":False},"api_armed":False}

class ConnSwitchReq(BaseModel):
    mode:str; license_key:str=""; confirm:bool=False
@app.post("/api/cmd/conn_switch")
async def cmd_conn_switch(r:ConnSwitchReq, principal: str = Depends(require_license)):
    """显式切换生效连接方式(bridge/api): 校验目标连接双腿可达→写两账户 conn_mode + 持久 active_mode。"""
    if r.mode!="bridge": raise HTTPException(400,"api/云端连接已停用, 仅支持 bridge")
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    if r.license_key:
        body_principal=_license_to_username(r.license_key)
        if body_principal != principal:
            raise HTTPException(403,"SUBJECT_CREDENTIAL_MISMATCH")
    ok,_st=await _conn_health_user(principal)
    if not ok: raise HTTPException(409,"目标连接方式(%s)双腿不可达, 拒绝切换"%r.mode)
    # Only the authenticated principal's connector rows may be changed.
    try:
        c=db(); cur=c.cursor()
        cur.execute("""UPDATE mt_accounts SET conn_mode=%s
                       WHERE user_id=(SELECT id FROM users WHERE username=%s)
                         AND role IN ('main','hedge')""",(r.mode,principal))
        updated=cur.rowcount; c.close()
        if updated<=0:
            raise HTTPException(409,"当前用户未登记可切换的主/对冲账户")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500,"写账户连接方式失败: %s"%e)
    R.set(RNS+"conn:active_mode", r.mode); _conn_cache_bust()
    _USER_REG_ROWS_CACHE.pop(principal,None)
    _USER_BRIDGE_CACHE.pop(principal,None); _CONN_HEALTH_USER_CACHE.pop(principal,None)
    R.delete(RNS+"conn:autoentry_warn:"+principal); R.delete(RNS+"conn:autoexit_warn:"+principal)
    _switch_user = principal
    _push_alert("warn", "连接方式已切换→%s(引擎执行/取数生效)" % r.mode,
                _switch_user)
    _audit(_switch_user,_switch_user,"conn_switch",{"mode":r.mode},DEMO_MODE,"switched")
    return {"ok":True,"active_mode":r.mode}

@app.get("/api/engine/alerts", dependencies=[Depends(require_license)])
def engine_alerts(limit:int=20, x_license:str=Header(default="")):
    username=_license_to_username(x_license)
    return {"alerts":_read_user_alerts(username,max(1,min(limit,200)))}

@app.get("/api/engine/spread_chart")
def engine_spread_chart(start_time:str="", end_time:str="", interval:int=5,
                        principal: str = Depends(require_license)):
    """点差走势(移植 testgo /spread/chart): 区间内按 interval 秒降采样, 返回 [{t,fs,rs}]。
       t=裸UTC ISO(前端按 UTC 解析再+8h转北京); fs=正向点差, rs=反向点差。"""
    if interval<1: interval=1
    import datetime as _d
    def _parse(s):
        if not s: return None
        try: return _d.datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception: return None
    st=_parse(start_time); et=_parse(end_time)
    rows=R.lrange(RNS+"spread:hist:"+principal,0,-1) or []
    out=[]; last_t=None
    for raw in rows:
        try: e=json.loads(raw)
        except Exception: continue
        ts=e.get("t");
        if not ts: continue
        try: t=_d.datetime.fromisoformat(ts.replace("Z","+00:00"))
        except Exception: continue
        if st and t<st: continue
        if et and t>et: continue
        t_sec=int(t.timestamp())
        if last_t is not None and (t_sec-last_t)<interval: continue
        last_t=t_sec
        out.append({"t":ts,"fs":e.get("fs",0),"rs":e.get("rs",0)})
    return out

# ================= 阶梯行(坑位)逐坑策略覆盖 (Redis hash, 引擎热读) =================
# 数据模型: qh:slot_cfg:{user}:{symbol}  field=坑号(1..N)  value=JSON{coin,lot_mode,qty,entry_enabled,buy_point}
def _slot_key(user,symbol): return RNS+"slot_cfg:"+user+":"+symbol

def _configured_ladders(username, symbol="XAUUSD"):
    """Return the authoritative configured slot count, failing closed."""
    tmpl=_load_tmpl(username,symbol)
    if not tmpl:
        raise HTTPException(404,"对冲参数模板未找到")
    raw=tmpl.get("ladders")
    try:
        ladders=int(raw)
    except (TypeError,ValueError):
        ladders=0
    if isinstance(raw,bool) or not 1<=ladders<=20:
        raise HTTPException(409,"对冲参数配置中的进单量无效，须为整数 1..20")
    return ladders

def _assert_slot_in_config(username, symbol, slot):
    try:
        slot=int(slot)
    except (TypeError,ValueError):
        raise HTTPException(400,"坑号必须为整数")
    ladders=_configured_ladders(username,symbol)
    if not 1<=slot<=ladders:
        raise HTTPException(400,"坑号 %d 超出进单量范围(1..%d)"%(slot,ladders))
    return ladders

def _active_slots_above_limit(username, symbol, proposed_ladders):
    """Collect authoritative/in-flight risk which a ladder reduction would hide."""
    limit=int(proposed_ladders)
    reasons={}
    def add(slot, reason):
        try: slot=int(slot)
        except (TypeError,ValueError): return
        if slot>limit:
            reasons.setdefault(slot,set()).add(reason)

    for leg in ("main","hedge"):
        for slot in (R.hgetall(_slotowner_key(leg,symbol,username)) or {}).values():
            add(slot,"position_owner")

    for key,record in list(_ACCOUNT_REVIEW_LOCAL.items()):
        if key[0]==(username or "").strip() and key[1]==str(symbol) and record:
            add(key[2],"review")

    for slot in range(limit+1,21):
        if _slot_review_record(username,symbol,slot):
            add(slot,"review")
        if R.get(_slotop_key(username,symbol,slot)):
            add(slot,"operation_lock")
    for slot in _busy_slots(symbol,username):
        add(slot,"busy")

    if getattr(TRADE_QUEUE,"redis",None) is R:
        for job in TRADE_QUEUE.slot_states(username,symbol,range(limit+1,21)):
            state=str(job.get("state") or "UNKNOWN").upper()
            if state not in ("COMPLETED","FAILED"):
                add(job.get("slot"),"trade_queue:"+state)
    return {slot:sorted(values) for slot,values in sorted(reasons.items())}

def _assert_ladder_reduction_safe(username, symbol, current_ladders, proposed_ladders):
    current=int(current_ladders or 0); proposed=int(proposed_ladders)
    if current<=proposed:
        return {}
    active=_active_slots_above_limit(username,symbol,proposed)
    if active:
        slots=",".join(str(slot) for slot in active)
        raise HTTPException(409,
            "进单量不能从 %d 缩减到 %d：坑位 %s 仍有持仓、排队或待核对状态，请先完成平仓/对账"%(
                current,proposed,slots))
    return active


def _trade_state_visible_slots(username, symbol, ladders=None):
    """Keep configured empty slots plus any out-of-range slot with live risk."""
    if ladders is None:
        ladders=_configured_ladders(username,symbol)
    visible=set(range(1,int(ladders)+1))
    visible.update(_active_slots_above_limit(username,symbol,int(ladders)))
    return sorted(visible)


def _trim_slot_overrides_above_limit(username, symbol, ladders):
    stale=[]
    key=_slot_key(username,symbol)
    for raw_slot in (R.hgetall(key) or {}):
        try: slot=int(raw_slot)
        except (TypeError,ValueError): continue
        if slot>int(ladders): stale.append(str(raw_slot))
    if stale:
        R.hdel(key,*stale)
    return sorted(int(slot) for slot in stale)

@app.get("/api/engine/slot_overrides", dependencies=[Depends(require_subject)])
def slot_overrides(username:str, symbol:str="XAUUSD"):
    """取该用户该品种全部坑位覆盖(field=坑号)。"""
    ladders=_configured_ladders(username,symbol)
    h=R.hgetall(_slot_key(username,symbol)) or {}
    out={}
    for k,v in h.items():
        try:
            slot=int(k)
            if not 1<=slot<=ladders: continue
            out[str(slot)]=json.loads(v)
        except Exception: pass
    return {"username":username,"symbol":symbol,"ladders":ladders,"slots":out}

class SlotOverride(BaseModel):
    username:str; license_key:str=""; symbol:str="XAUUSD"; slot:int
    coin:str=""; lot_mode:str="auto"        # auto=按每U手数自动算 / fixed=用 qty
    qty:float=0.0                            # 交易数量(该坑手数; lot_mode=fixed 时生效)
    entry_enabled:bool=True                  # 兼容旧字段(手动顺序填坑黑名单: False=跳过本坑)
    entry_state:str=""                       # 进单状态: off=不自动 / both=全开(双向哪边到点开哪边) / forward=正向 / reverse=反向; 设方向=武装本坑自动开仓。""=旧数据(不武装)
    entry_state_last:str=""                  # 上次武装方向(列表 chip 快捷开/关时还原用)
    buy_point:Optional[float]=None           # 买入点位(该坑入场点差阈值; null=回落全局 entry_spread, 0=字面0即任意点差都开)
    exit_enabled:bool=False                  # 卖出点位启用=武装本坑自动平仓(卖点/止盈/超时)
    sell_point:float=0.0                     # 卖出点位(该坑平仓点差目标)
    exit_calc:bool=False                     # 兼容旧字段(原"实时判到点", 从未消费; 已由 sl_enabled 取代)
    sl_enabled:bool=False                    # 止损平仓(开=按止损点位强制平仓; 独立于卖出点位启用, 不受盈利闸限制)
    tp_points:float=0.0                      # 盈利点位(该坑止盈; 0=回落全局)
    sl_points:float=0.0                      # 止损点位(该坑止损; 0=回落全局)

_ENTRY_STATES=("both","forward","reverse")
def _recompute_auto_masters(user):
    """按坑位武装态派生用户级自动开关(保存/删除坑规则后调用):
       任一坑 entry_state 设了方向→auto_entry=armed; 任一坑 卖出点位启用/止损平仓→auto_exit=armed; 否则 off。
       与右键"停止自动策略"共存: 停止置 off 后, 直到用户再次保存坑规则才会重新武装。"""
    e_on=x_on=False
    try:
        prefix=RNS+"slot_cfg:"+user+":"
        for key in R.scan_iter(prefix+"*"):
            key_text=key.decode("utf-8","replace") if isinstance(key,bytes) else str(key)
            symbol=key_text[len(prefix):] if key_text.startswith(prefix) else ""
            try: ladders=_configured_ladders(user,symbol)
            except HTTPException: continue
            for raw_slot,v in (R.hgetall(key) or {}).items():
                try: slot=int(raw_slot)
                except (TypeError,ValueError): continue
                if not 1<=slot<=ladders: continue
                try: ov=json.loads(v)
                except Exception: continue
                if (ov.get("entry_state") or "") in _ENTRY_STATES: e_on=True
                if ov.get("exit_enabled") or ov.get("sl_enabled"): x_on=True
    except Exception: pass
    pe=R.get(RNS+"auto_entry:"+user) or "off"; px=R.get(RNS+"auto_exit:"+user) or "off"
    if R.get(_auto_validity_latch_key("entry",user)): e_on=False
    if R.get(_auto_validity_latch_key("exit",user)): x_on=False
    ne="armed" if e_on else "off"; nx="armed" if x_on else "off"
    R.set(RNS+"auto_entry:"+user, ne); R.set(RNS+"auto_exit:"+user, nx)
    for nm,old,new in (("自动进单",pe,ne),("自动平仓",px,nx)):
        if old!=new:
            _push_alert("warn" if new=="armed" else "info",
                "%s→%s(按坑位武装态派生)%s"%(nm,"武装" if new=="armed" else "关闭"," (真金!)" if (new=="armed" and not DEMO_MODE) else ""),user)
    return ne,nx

@app.post("/api/engine/slot_override", dependencies=[Depends(require_license)])
def slot_override_save(r:SlotOverride):
    _assert_subject(r.username,r.license_key or "")
    _assert_slot_in_config(r.username,r.symbol,r.slot)
    st=(r.entry_state or "").strip().lower()
    if st not in ("","off")+_ENTRY_STATES: raise HTTPException(400,"entry_state 必须为 off/both/forward/reverse")
    # 武装安全门控: 自动进单/平仓是系统默认能力, 但全局急停时禁止武装。
    if (st in _ENTRY_STATES) or r.exit_enabled or r.sl_enabled:
        if R.get(RNS+"global_estop")=="1":
            raise HTTPException(409,"全局急停生效中, 无法武装自动进单/平仓; 请先解除急停")
        _assert_user_valid(r.username)
    if st in _ENTRY_STATES:
        R.delete(_auto_validity_latch_key("entry",r.username))
    if r.exit_enabled or r.sl_enabled:
        R.delete(_auto_validity_latch_key("exit",r.username))
    val={"coin":r.coin,"lot_mode":r.lot_mode,"qty":r.qty,"entry_enabled":r.entry_enabled,
         "entry_state":st,"entry_state_last":(r.entry_state_last or "").strip().lower(),"buy_point":r.buy_point,
         "exit_enabled":r.exit_enabled,"sell_point":r.sell_point,"exit_calc":r.exit_calc,"sl_enabled":r.sl_enabled,
         "tp_points":r.tp_points,"sl_points":r.sl_points}
    R.hset(_slot_key(r.username,r.symbol), str(r.slot), json.dumps(val))
    ae,ax=_recompute_auto_masters(r.username)
    _audit(r.username,_actor(r.license_key),"slot_override",{"symbol":r.symbol,"slot":r.slot,**val},DEMO_MODE,"saved")
    return {"ok":True,"slot":r.slot,"saved":val,"auto_entry":ae,"auto_exit":ax,"msg":"坑%d 策略已保存,引擎热读生效"%r.slot}

class SlotDel(BaseModel):
    username:str; license_key:str=""; symbol:str="XAUUSD"; slot:int
@app.post("/api/engine/slot_override_del", dependencies=[Depends(require_license)])
def slot_override_del(r:SlotDel):
    _assert_subject(r.username,r.license_key or "")
    _assert_slot_in_config(r.username,r.symbol,r.slot)
    R.hdel(_slot_key(r.username,r.symbol), str(r.slot))
    ae,ax=_recompute_auto_masters(r.username)
    return {"ok":True,"slot":r.slot,"auto_entry":ae,"auto_exit":ax,"msg":"坑%d 覆盖已清除(回落全局参数)"%r.slot}



# ================= 强平价估算 (绿框: 多/空强平价 + 强平距离%, 标注估算) =================
def _net_lots(poslist):
    """持仓列表 → 净手数(buy=+/sell=-, MT5 type 0=buy 1=sell)。"""
    items = poslist.get("positions",poslist) if isinstance(poslist,dict) else (poslist or [])
    net=0.0
    for p in (items or []):
        if not isinstance(p,dict):
            continue
        try:
            v=float(p.get("volume",0) or 0)
        except (TypeError,ValueError):
            continue
        if not math.isfinite(v) or v<=0:
            continue
        t=p.get("type"); side=str(p.get("side") or "").strip().lower()
        if str(t)=="1" or side=="sell":
            net -= v
        elif str(t)=="0" or side=="buy":
            net += v
    return round(net,4)

def _valid_liq_estimate(value, mid, net_lots, side, max_distance_pct=100.0):
    """Reject non-market liquidation extrapolations before they reach the UI."""
    import math
    try:
        value=float(value); mid=float(mid); net_lots=float(net_lots)
        max_distance_pct=float(max_distance_pct)
    except (TypeError,ValueError):
        return None
    if not math.isfinite(value) or not math.isfinite(mid) or value<=0 or mid<=0:
        return None
    if side=="long" and (net_lots<=0 or value>=mid): return None
    if side=="short" and (net_lots>=0 or value<=mid): return None
    if abs(value-mid)/mid*100.0>max(0.0,max_distance_pct): return None
    return round(value,2)

async def _engine_liq_for_user(symbol, username):
    """双腿账户级强平价【估算】+ 强平距离%。MT5 无原生强平价, 按 margin_level<=so_so 反推。"""
    out={"main":None,"hedge":None,"est":True}
    # conn=_user_exec_conn(username) was the legacy read path; strict routing
    # below intentionally prevents its global EXEC fallback.
    conn=_strict_user_read_conn(username)
    if conn is None:
        return {"symbol":symbol,"main":None,"hedge":None,"error":"user connector unavailable"}
    try:
        accts = await conn.both_accounts() if hasattr(conn,"both_accounts") else {"main":await conn.account_info(),"hedge":None}
        pos = await conn.both_positions() if hasattr(conn,"both_positions") else {"main":await conn.positions(),"hedge":None}
        pos = _normalize_position_legs(pos)
    except Exception as e:
        raise HTTPException(502,"bridge error: %s"%e)
    # 对冲品种映射(取首个模板)
    hsym=symbol
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT pt.hedge_symbol FROM param_templates pt JOIN users u ON u.id=pt.user_id "
                    "WHERE u.username=%s AND pt.symbol=%s LIMIT 1",(username,symbol))
        row=cur.fetchone(); c.close()
        if row: hsym=ENG.map_hedge_symbol(symbol, row.get("hedge_symbol")) or symbol
    except Exception: pass
    legs={"main":(accts.get("main"),pos.get("main"),symbol,"main"),
          "hedge":(accts.get("hedge"),pos.get("hedge"),hsym,"hedge")}
    def _empty_leg(sym, reason, net_lots=0.0):
        return {"symbol":sym,"net_lots":round(float(net_lots or 0),4),"price":None,
                "long":None,"short":None,"long_dist_pct":None,"short_dist_pct":None,
                "so_so":None,"reason":reason,"est":True}

    for key,(ac,pl,sym,leg) in legs.items():
        if not isinstance(ac,dict):
            out[key]=_empty_leg(sym,"account_unavailable")
            continue
        rows=[row for row in _poslist(pl) if isinstance(row,dict)]
        if not rows:
            out[key]=_empty_leg(sym,"positions_unavailable_or_flat")
            continue
        if any(bool(row.get("pair_ticket_conflict")) for row in rows):
            out[key]=_empty_leg(sym,"ambiguous_ticket_pair")
            continue
        try:
            leg_conn=conn.main if leg=="main" else getattr(conn,"hedge",None)
            tick=await leg_conn._get("/mt5/tick/"+sym) if leg_conn is not None else None
        except Exception:
            tick=None
        mid=None
        if tick and tick.get("bid") is not None and tick.get("ask") is not None:
            try:
                bid=float(tick["bid"]); ask=float(tick["ask"])
                if math.isfinite(bid) and math.isfinite(ask) and bid>0 and ask>0 and ask>=bid:
                    mid=(bid+ask)/2.0
            except (TypeError,ValueError):
                mid=None
        netl=_net_lots(pl)
        try:
            equity=float(ac.get("equity")); margin=float(ac.get("margin"))
        except (TypeError,ValueError):
            out[key]=_empty_leg(sym,"account_metrics_unavailable",netl)
            continue
        if (not math.isfinite(equity) or not math.isfinite(margin) or
                margin<=0 or mid is None or abs(netl)<1e-9):
            reason=("quote_unavailable" if mid is None else
                    ("positions_unavailable_or_flat" if abs(netl)<1e-9 else "account_metrics_unavailable"))
            out[key]=_empty_leg(sym,reason,netl)
            continue
        est=ENG.liq_estimate(ac.get("equity"), ac.get("margin"), ac.get("margin_so_so"),
                             netl, mid, contract_size=100.0, so_mode=ac.get("margin_so_mode") or 0)
        max_dist=os.environ.get("QH_LIQ_MAX_DISTANCE_PCT","100")
        raw_long=est.get("long"); raw_short=est.get("short")
        long_liq=_valid_liq_estimate(raw_long,mid,netl,"long",max_dist)
        short_liq=_valid_liq_estimate(raw_short,mid,netl,"short",max_dist)
        filtered=((raw_long is not None and long_liq is None) or
                  (raw_short is not None and short_liq is None))
        def _dist(liq):
            if liq is None or not mid or mid<=0: return None
            return round(abs(liq-mid)/mid*100.0, 2)
        out[key]={"symbol":sym,"net_lots":netl,"price":round(mid,2) if mid else None,
                  "long":long_liq,"short":short_liq,
                  "long_dist_pct":_dist(long_liq),"short_dist_pct":_dist(short_liq),
                  "so_so":ac.get("margin_so_so"),
                  "reason":"invalid_estimate_filtered" if filtered else est["reason"],"est":True}
    return out

@app.get("/api/engine/liq", dependencies=[Depends(require_license)])
async def engine_liq(symbol:str="XAUUSD", x_license:str=Header(default="")):
    return await _engine_liq_for_user(symbol,_license_to_username(x_license))
# ================= 多账户 / 指令 / 行情 (P2) =================
import hashlib
def _actor(key): return "lk:"+hashlib.sha256((key or "").encode()).hexdigest()[:8]

@app.get("/api/accounts/{username}", dependencies=[Depends(require_subject)])
def list_accounts(username:str):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT a.id,a.label,a.login,a.platform,a.broker,a.role,a.conn_mode,a.enabled,a.server,a.api2trade_uuid FROM mt_accounts a JOIN users u ON u.id=a.user_id WHERE u.username=%s ORDER BY a.role,a.id",(username,))
    rows=cur.fetchall(); c.close()
    return {"username":username,"accounts":[dict(r) for r in rows]}

class AcctReg(BaseModel):
    username:str; label:str; login:str; platform:str="MT5"; broker:str=""
    role:str="main"; conn_mode:str="bridge"; bridge_url:str=""; bridge_key_ref:str=""
    # conn_mode='api'(Api2Trade 云端)注册用: server=MT 服务器名; password 仅在途转交 Api2Trade, 绝不落库/落日志
    server:str=""; password:str=""
@app.post("/api/accounts/register", dependencies=[Depends(require_license)])
def reg_account(a:AcctReg, x_license: str = Header(default="")):
    # 改为用户密钥验证(PC+移动端): 账户绑定到密钥对应用户本人, 忽略 body.username 防越权
    a.conn_mode="bridge"   # api/云端连接已彻底移除, 强制 bridge(凭证留桥机, 服务端不接收密码)
    if not str(a.login or "").strip():   # bridge/api 均须有效登录号(防静默脏行=lei789 空白根因之一)
        raise HTTPException(400,"登录账号不能为空: 请选择桥客户端或手动填写 MT 登录号")
    if a.role not in ("main","hedge"):
        raise HTTPException(400,"role 须为 main|hedge")
    c=db(); cur=c.cursor()
    cur.execute("SELECT id,username FROM users WHERE license_key=%s",(x_license,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(403,"密钥无效")
    # P1 权益闸: max_pairs 限制对冲账户对数(按 role 计已有对; 新增不得超权益)
    try: maxp=int(float(_ent_get(u[0],"max_pairs") or 1))
    except (TypeError,ValueError): maxp=1
    cur.execute("SELECT login FROM mt_accounts WHERE user_id=%s AND role=%s",(u[0],a.role))
    existing=[x[0] for x in cur.fetchall()]
    if a.login not in existing and len(existing)>=maxp:
        c.close(); raise HTTPException(403,"账户对数已达上限(%d), 升级'多客户端'内购解锁更多(role=%s)"%(maxp,a.role))
    # 变更前旧云端绑定: 重注册(保存并登录)拿到新 UUID 后, 旧 UUID 须尽力联动注销, 防云端配额泄漏。
    # 注意 conn_mode 切 api→bridge 绝不释放 —— /engine/conn_mode 双向热切依赖 api2trade_uuid 留存。
    cur.execute("SELECT api2trade_uuid,api2trade_config_id FROM mt_accounts WHERE user_id=%s AND login=%s",(u[0],a.login))
    _prev=cur.fetchone(); prev_uuid=((_prev[0] or "").strip() if _prev else ""); prev_cfg_id=(_prev[1] if _prev else None)
    # ── conn_mode='api': 服务端代注册到 Api2Trade(密码仅在途), 成功后只存返回的账户 UUID ──
    a2t_uuid=""; a2t_cfg_id=None
    if a.conn_mode=="api":
        if not (a.server or "").strip() or not a.password:
            c.close(); raise HTTPException(400,"API 连接需提供 MT 服务器名与密码(密码仅注册时在途, 服务端不存储)")
        try:
            cfg=_a2t_cfg()  # 激活且未过期的订阅配置, 否则 503(fail-closed)
            typ="Metatrader 5" if a.platform=="MT5" else "Metatrader 4"
            j,_ms=_a2t_call(cfg,"/RegisterAccount",{"type":typ,"server":a.server.strip(),
                            "user":a.login,"password":a.password,"name":(a.label or a.login)},timeout=30)
            a2t_uuid=str((j or {}).get("id") or "")
            if not a2t_uuid:
                raise HTTPException(502,"Api2Trade 注册未返回账户 UUID: %s"%str((j or {}).get("message") or "")[:120])
            a2t_cfg_id=cfg["id"]
        except HTTPException:
            c.close(); raise
        except Exception as e:
            c.close(); raise HTTPException(502,"Api2Trade 注册失败: %s"%e.__class__.__name__)
    cur.execute(
        "INSERT INTO mt_accounts(user_id,label,login,platform,broker,role,conn_mode,bridge_url,bridge_key_ref,server,api2trade_uuid,api2trade_config_id) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (user_id,login) DO UPDATE SET "
        "label=EXCLUDED.label,role=EXCLUDED.role,conn_mode=EXCLUDED.conn_mode,"
        # The account API deliberately does not return bridge_url. Preserve the
        # provisioned route when an ordinary account save sends its blank default.
        "bridge_url=COALESCE(NULLIF(BTRIM(EXCLUDED.bridge_url),''),mt_accounts.bridge_url),"
        "server=EXCLUDED.server,"
        "api2trade_uuid=CASE WHEN EXCLUDED.api2trade_uuid<>'' THEN EXCLUDED.api2trade_uuid ELSE mt_accounts.api2trade_uuid END,"
        "api2trade_config_id=COALESCE(EXCLUDED.api2trade_config_id,mt_accounts.api2trade_config_id)",
        (u[0],a.label,a.login,a.platform,a.broker,a.role,a.conn_mode,a.bridge_url,
         a.bridge_key_ref,(a.server or "").strip(),a2t_uuid,a2t_cfg_id),
    )
    c.close()
    _reg_roles_bust()   # 账户卡登记门控缓存立即失效(注册后卡片即恢复)
    # 本地绑定已落库后再尽力释放旧云端注册(best-effort, 失败仅提示不回滚; 同 UUID=幂等更新则跳过)
    a2t_prev_released=False; a2t_prev_msg=""
    if a.conn_mode=="api" and prev_uuid and a2t_uuid and prev_uuid!=a2t_uuid:
        a2t_prev_released,a2t_prev_msg=_a2t_release(prev_cfg_id or a2t_cfg_id, prev_uuid)
    # FRA a2t-bridge 对应腿 UUID 热同步(api 执行模式的腿配置随注册自动跟随, 零人工)
    fra_ok=None; fra_msg=""
    if a.conn_mode=="api" and a.role in ("main","hedge") and a2t_uuid:
        fra_ok,fra_msg=_fra_sync_uuid(a.role, a2t_uuid)
    return {"ok":True,"login":a.login,"conn_mode":a.conn_mode,"a2t_uuid":a2t_uuid,
            "a2t_prev_released":a2t_prev_released,"a2t_prev_msg":a2t_prev_msg,
            "fra_synced":fra_ok,"fra_msg":fra_msg}

class AcctTestReq(BaseModel):
    role:str="main"; login:str=""; conn_mode:str="bridge"
@app.post("/api/accounts/test_conn", dependencies=[Depends(require_license)])
async def acct_test_conn(a:AcctTestReq, x_license: str = Header(default="")):
    """P3 真桥测试连接(替代原前端假 setTimeout): bridge=查执行桥该 login 客户端是否在线(在线=密码有效可交易);
       api=提示走保存时云端验证。绝不接收/回显密码。"""
    login=str(a.login or "").strip()
    if not login: raise HTTPException(400,"请先选择桥客户端或填写登录账号再测试")
    if a.conn_mode=="bridge":
        username=_license_to_username(x_license)
        uconn=_user_bridge_conn(username) if username else None
        # Never probe the process-global bridge for a user's login.  The
        # legacy expression (target_conn=uconn if uconn is not None else CONN)
        # leaked another tenant's account in the diagnostic message.
        target_conn=uconn if uconn is not None else _strict_user_read_conn(username)
        try:
            if target_conn is None:
                raise RuntimeError("user connector unavailable")
            st=await target_conn.both_status() if hasattr(target_conn,"both_status") else {"main":await target_conn.status(),"hedge":None}
        except Exception as e:
            return {"ok":False,"level":"err","msg":"执行桥不可达(%s)，请稍后重试或联系管理员"%e.__class__.__name__}
        for r in ("main","hedge"):
            s=st.get(r) or {}
            if str(s.get("account") or "").strip()==login:
                if s.get("connected"):
                    return {"ok":True,"level":"ok","balance":s.get("balance"),"equity":s.get("equity"),
                            "msg":"桥客户端在线 · 账户 %s @ %s 连接正常，密码有效可交易(余额 %s)"%(login,s.get("server") or "--",s.get("balance") if s.get("balance") is not None else "--")}
                return {"ok":False,"level":"warn","msg":"账户 %s 已在桥但当前离线(MT 客户端掉线或密码已变更)，请检查客户端登录状态"%login}
        # Do not disclose the connector's actual login IDs when the requested
        # account is not registered on this user's bridge.
        return {"ok":False,"level":"warn","msg":"账户 %s 未接入你的执行桥，无法通过桥验证；请联系管理员接入你的账户"%login}
    return {"ok":None,"level":"info","msg":"API 连接: 用「保存并登录」即完成云端密码验证(注册失败=密码错)；已接入后可再测试实时状态"}

# ---- P2: 桥上实际运行的 MT 客户端聚合(平台名称读真实客户端, 服务器按平台联动) ----
def _plat_from_instance(inst, server):
    """从桥实例名/服务器名推平台(桥 status 的 platform 字段为空)。qhmt4-*/ICMarketsSC-Demo→MT4; *mt5*/MT5-6→MT5。"""
    i=(inst or "").lower(); s=(i+" "+(server or "")).lower()
    if i.startswith("qhcell-s"): return "MT5"
    if i.startswith("qhcell-m"): return "MT4"
    if "mt5" in s: return "MT5"
    if "mt4" in s: return "MT4"
    return None
def _bridge_client_ports():
    """QH 桥客户端端口清单(Redis 可覆盖)。只发现 QH 专属端口，不混入共享节点上的 Go 桥。"""
    v=R.get(RNS+"bridge:client_ports")
    if v:
        try:
            ports=[]
            for raw in str(v).split(","):
                port=int(raw.strip())
                if 1<=port<=65535 and port not in ports: ports.append(port)
            if ports: return ports
        except Exception: pass
    return [8041,8042,8061,8063,8065,8066,8067,8068]
_BRIDGE_CLIENTS_CACHE={"ts":0.0,"data":None}
_BRIDGE_CLIENTS_USER_CACHE={}
@app.get("/api/bridge/clients", dependencies=[Depends(require_license)])
async def bridge_clients(x_license: str = Header(default="")):
    """桥上真实 MT 客户端(平台/服务器/账户/在线态), 供账户设置'从桥接客户端选择'+平台/服务器联动。5s缓存。"""
    principal=_license_to_username(x_license)
    if not principal:
        raise HTTPException(403,"缺少有效用户主体")
    now=_t_conn.time()
    cached=_BRIDGE_CLIENTS_USER_CACHE.get(principal)
    if cached and (now-cached[0])<5:
        return cached[1]
    rows=_reg_rows_for(principal)
    conn=_user_bridge_conn(principal)
    clients=[]
    async def _user_client(role, row):
        login=str((row or {}).get("login") or "").strip()
        if not login:
            return None
        leg=getattr(conn,role,None) if conn is not None else None
        status={}
        if leg is not None:
            try: status=await leg.status()
            except Exception: status={}
        actual=str(status.get("account") or login).strip()
        if status.get("account") and actual!=login:
            return None
        return {"role":role,"login":login,
                "server":status.get("server") or (row or {}).get("server") or "",
                "platform":(row or {}).get("platform") or status.get("platform") or "",
                "connected":bool(status.get("connected")),"port":None}
    if conn is not None:
        found=await _aio.gather(*[_user_client(role,rows.get(role)) for role in ("main","hedge")])
        clients=[item for item in found if item]
    else:
        for role,row in rows.items():
            login=str((row or {}).get("login") or "").strip()
            if login:
                clients.append({"role":role,"login":login,"server":row.get("server") or "",
                                "platform":row.get("platform") or "","connected":False,"port":None})
    servers={}
    for item in clients:
        platform=item.get("platform") or "其他"
        servers.setdefault(platform,[])
        if item.get("server") and item["server"] not in servers[platform]:
            servers[platform].append(item["server"])
    data={"clients":clients,
          "platforms":sorted(set(x.get("platform") for x in clients if x.get("platform"))),
          "servers":servers}
    _BRIDGE_CLIENTS_USER_CACHE[principal]=(now,data)
    return data
    # Legacy global scanner retained below for reference; user requests never
    # reach it because the strict response above returns first.
    if _BRIDGE_CLIENTS_CACHE["data"] is not None and (now-_BRIDGE_CLIENTS_CACHE["ts"])<5:
        return _BRIDGE_CLIENTS_CACHE["data"]
    import re as _re2
    from connector import _pooled
    base=os.environ.get("QH_BRIDGE_URL","http://172.31.5.62:8041")
    m=_re2.match(r"(https?://[^:/]+)", base); host=(m.group(1) if m else "http://172.31.5.62")
    key=os.environ.get("QH_BRIDGE_KEY","")
    async def _q(port):
        try:
            r=await _pooled("bridge",4).get("%s:%d/mt5/connection/status"%(host,port),headers={"X-API-Key":key},timeout=4)
            if r.status_code!=200: return None
            d=r.json(); login=str(d.get("account") or "").strip()
            if not login: return None
            return {"port":port,"login":login,"server":d.get("server") or "",
                    "platform":_plat_from_instance(d.get("instance"),d.get("server")),
                    "connected":bool(d.get("connected"))}
        except Exception: return None
    res=await _aio.gather(*[_q(p) for p in _bridge_client_ports()])
    clients=[x for x in res if x]
    servers={}
    for x in clients:
        p=x["platform"] or "其他"; servers.setdefault(p,[])
        if x["server"] and x["server"] not in servers[p]: servers[p].append(x["server"])
    data={"clients":clients,"platforms":sorted(set(x["platform"] for x in clients if x["platform"])),"servers":servers}
    _BRIDGE_CLIENTS_CACHE["data"]=data; _BRIDGE_CLIENTS_CACHE["ts"]=now
    return data

class AcctDelMine(BaseModel):
    role:str=""; login:str=""; confirm:bool=False
@app.post("/api/accounts/delete_mine", dependencies=[Depends(require_license)])
async def del_account_mine(b:AcctDelMine, x_license: str = Header(default="")):
    """用户自删本人 MT 账户登记行(按 role 或 login), 并**联动注销云端托管**(官方 /DeleteAccount, 幂等,
       失败不阻塞本地删除、结果透明回传)。**绝不动交易记录/历史成交**
       (配对历史读桥/券商实时, DB deals 表按 user 非按 account, 无级联)。
       保护闸: 自动策略运行中 或 该腿有未平持仓 → 409 禁止清除。"""
    if not b.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    c=db(); cur=c.cursor()
    cur.execute("SELECT id,username FROM users WHERE license_key=%s",(x_license,)); u=cur.fetchone(); c.close()
    if not u: raise HTTPException(403,"密钥无效")
    # 保护闸(角色: login 传入时反查; 都无则 400 在下方分支抛)
    _grole=b.role if b.role in ("main","hedge") else ""
    if not _grole and b.login:
        try:
            c=db(); cur=c.cursor()
            cur.execute("SELECT role FROM mt_accounts WHERE user_id=%s AND login=%s LIMIT 1",(u[0],b.login))
            _r=cur.fetchone(); c.close()
            if _r: _grole=_r[0]
        except Exception: pass
    if _grole:
        _deny=await _acct_clear_guard(_grole,u[1])
        if _deny: raise HTTPException(409,_deny)
    c=db(); cur=c.cursor()
    if b.login:
        cur.execute("DELETE FROM mt_accounts WHERE user_id=%s AND login=%s RETURNING login,role,api2trade_uuid,api2trade_config_id",(u[0],b.login))
    elif b.role in ("main","hedge"):
        cur.execute("DELETE FROM mt_accounts WHERE user_id=%s AND role=%s RETURNING login,role,api2trade_uuid,api2trade_config_id",(u[0],b.role))
    else:
        c.close(); raise HTTPException(400,"须提供 role(main|hedge) 或 login")
    rows=cur.fetchall(); c.close()
    if not rows: raise HTTPException(404,"未找到可删除的账户")
    _reg_roles_bust()   # 账户卡登记门控缓存立即失效(清除后卡片即清空)
    # 联动注销云端托管账户(UUID): best-effort, 云端已不存在视为已释放; 失败明确回传
    released=[]; _synced_roles=set()
    for r in rows:
        uuid=(r[2] or "").strip()
        if uuid:
            ok,msg=_a2t_release(r[3], uuid)
            released.append({"login":r[0],"role":r[1],"uuid8":uuid[:8],"a2t_ok":ok,"a2t_msg":msg})
        # FRA 对应腿清空(异步线程防阻塞事件循环; 每角色一次)
        if r[1] in ("main","hedge") and r[1] not in _synced_roles:
            _synced_roles.add(r[1])
            try: await _aio.to_thread(_fra_sync_uuid, r[1], "")
            except Exception: pass
    _audit(u[1],"user","account_delete_mine",{"deleted":[{"login":r[0],"role":r[1]} for r in rows],"a2t_released":released},DEMO_MODE,"deleted:%d"%len(rows))
    return {"ok":True,"deleted":[{"login":r[0],"role":r[1],"a2t_uuid":r[2]} for r in rows],"a2t_released":released}

DEMO_MODE = os.environ.get("QH_DEMO_MODE","1")=="1"
def _audit(user,actor,action,payload,demo,result):
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s",(user,)); u=cur.fetchone()
        cur.execute("INSERT INTO audit_log(user_id,actor,action,payload,demo_mode,result) VALUES(%s,%s,%s,%s,%s,%s)",(u[0] if u else None,actor,action,json.dumps(payload),demo,result))
        c.close()
    except Exception as e: print("audit err",e)

# ================= P0 权益门控中枢 (entitlements 唯一真相源 + 内购商品可自定义) =================
# 自动进单/平仓已转为有效用户的系统内置能力。保留兼容 entitlement 值供旧客户端读取，
# 但它不再出现在可售权益、商品 grants、积分兑换或手工授权入口中。
_BUILTIN_ENTITLEMENTS={"auto_loop":"true"}
_RETIRED_IAP_PRODUCT_KEYS=frozenset({"auto_loop_pro"})

def _norm_iap_key(value):
    return str(value or "").strip().lower()

def _is_builtin_entitlement_key(key):
    return _norm_iap_key(key) in _BUILTIN_ENTITLEMENTS

def _is_retired_iap_product_key(key):
    return _norm_iap_key(key) in _RETIRED_IAP_PRODUCT_KEYS

def _iap_grants_dict(grants):
    if isinstance(grants,dict):
        return dict(grants)
    if isinstance(grants,str):
        try:
            parsed=json.loads(grants)
            return dict(parsed) if isinstance(parsed,dict) else {}
        except Exception:
            return {}
    return {}

def _has_builtin_iap_grants(grants):
    return any(_is_builtin_entitlement_key(key) for key in _iap_grants_dict(grants))

def _sellable_iap_grants(grants):
    return {key:value for key,value in _iap_grants_dict(grants).items()
            if not _is_builtin_entitlement_key(key)}

def _sellable_iap_product(product):
    """Return a catalog/fulfilment-safe product or None for a retired auto-only item."""
    if not product:
        return None
    row=dict(product)
    if _is_retired_iap_product_key(row.get("key")):
        return None
    original=_iap_grants_dict(row.get("grants"))
    row["grants"]=_sellable_iap_grants(original)
    if original and not row["grants"]:
        return None
    return row

# 免费档默认(无权益行时回落): 保命护栏永不门控, 仅规模/个性化能力才门控
_ENT_DEFAULTS_FALLBACK={"max_pairs":"1","symbols":'["XAUUSD"]',"speed_turbo":"false",
               "max_clients":"1","theme_custom":"false"}
_feat_cache={"ts":0,"features":None,"defaults":None}
def _load_features(force=False):
    """权益目录单一真相源: 读 iap_features 表(30s 缓存), 缺表/空则回落硬编码。返回 (features_list, defaults_dict)。"""
    import time
    now=time.time()
    if not force and _feat_cache["features"] is not None and now-_feat_cache["ts"]<30:
        return _feat_cache["features"], _feat_cache["defaults"]
    feats=None; defaults=dict(_ENT_DEFAULTS_FALLBACK)
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT key,name,ftype,hint,default_value,sort FROM iap_features WHERE enabled=true ORDER BY sort,key")
        rows=[dict(x) for x in cur.fetchall()
              if not _is_builtin_entitlement_key(x.get("key"))]; c.close()
        if rows:
            feats=rows; defaults={r["key"]:r["default_value"] for r in rows}
    except Exception as e: print("load_features err",e)
    if feats is None:  # 回落
        feats=[{"key":k,"name":k,"ftype":("num" if v not in ("true","false") else "bool"),"hint":"","default_value":v,"sort":i}
               for i,(k,v) in enumerate(_ENT_DEFAULTS_FALLBACK.items())]
    _feat_cache.update({"ts":now,"features":feats,"defaults":defaults})
    return feats, defaults
def _ent_defaults():
    return _load_features()[1]
def _ent_all(user_id):
    """取该用户全部生效权益(未过期); 缺省回落免费档。返回 {feature_key:value}。"""
    out=dict(_ent_defaults())
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT feature_key,value,expire_at FROM entitlements WHERE user_id=%s""",(user_id,))
        for r in cur.fetchall():
            if _is_builtin_entitlement_key(r["feature_key"]):
                continue
            if r["expire_at"] is not None and r["expire_at"]<datetime.datetime.now(datetime.timezone.utc):
                continue   # 已过期→不生效(降级回落默认)
            out[r["feature_key"]]=r["value"]
        c.close()
    except Exception as e: print("ent_all err",e)
    if user_id:
        out.update(_BUILTIN_ENTITLEMENTS)
    return out
def _ent_get(user_id, key):
    if _is_builtin_entitlement_key(key):
        return _BUILTIN_ENTITLEMENTS[_norm_iap_key(key)] if user_id else None
    return _ent_all(user_id).get(key, _ent_defaults().get(key))

@app.on_event("startup")
def _retire_builtin_iap_commerce():
    """Make the catalog migration durable while preserving historical orders/entitlements."""
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT key,grants,enabled FROM iap_products")
        for product in cur.fetchall():
            key=product["key"]
            if _is_retired_iap_product_key(key):
                cur.execute("UPDATE iap_products SET enabled=false WHERE key=%s",(key,))
                continue
            if not _has_builtin_iap_grants(product.get("grants")):
                continue
            grants=_sellable_iap_grants(product.get("grants"))
            cur.execute("UPDATE iap_products SET grants=%s,enabled=%s WHERE key=%s",
                        (json.dumps(grants),bool(product.get("enabled")) and bool(grants),key))
        cur.execute("UPDATE iap_features SET enabled=false WHERE lower(trim(key))=%s",("auto_loop",))
        c.close()
        _load_features(force=True)
    except Exception as e:
        print("retire_builtin_iap_commerce err",e)
def _uid(username):
    c=db(); cur=c.cursor(); cur.execute("SELECT id FROM users WHERE username=%s",(username,)); r=cur.fetchone(); c.close()
    return r[0] if r else None
def require_entitlement(feature_key, truthy=True):
    """FastAPI 依赖工厂: 校验 X-License 用户是否拥有某权益(真值/非空)。无权益→403。
       铁律: 仅用于规模/自动化/个性化功能; 保命护栏(止损/单腿/裸空)绝不挂此闸。"""
    def _dep(x_license: str = Header(default="")):
        if not x_license: raise HTTPException(401,"缺少 X-License")
        c=db(); cur=c.cursor(); cur.execute("SELECT id FROM users WHERE license_key=%s",(x_license,)); r=cur.fetchone(); c.close()
        if not r: raise HTTPException(401,"license 无效")
        val=_ent_get(r[0], feature_key)
        ok=(str(val).lower() in ("true","1") ) if truthy else (val not in (None,"","false","0"))
        if not ok: raise HTTPException(403,"功能未解锁(需内购权益: %s)"%feature_key)
        return True
    return _dep

# ---- 用户端读权益(前端按此门控 UI 显隐/引导购买) ----
@app.get("/api/entitlements/{username}", dependencies=[Depends(require_subject)])
def get_entitlements(username:str):
    uid=_uid(username)
    if not uid: raise HTTPException(404,"user not found")
    return {"username":username,"entitlements":_ent_all(uid)}

# ---- 内购商品目录(用户端浏览, 公开只读) ----
@app.get("/api/iap/catalog")
def iap_catalog():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT key,name,sort,enabled FROM iap_categories WHERE enabled=true ORDER BY sort,key")
    cats=cur.fetchall()
    cur.execute("SELECT key,category,name,descr,price,unit,duration_days,grants,sort FROM iap_products WHERE enabled=true ORDER BY sort,key")
    prods=cur.fetchall(); c.close()
    sellable=[p for p in (_sellable_iap_product(x) for x in prods) if p]
    return {"categories":[dict(x) for x in cats],"products":sellable}

# ---- 权益项目录(前端商品编辑/授予区据此渲染, 公开只读) ----
@app.get("/api/iap/features")
def iap_features():
    feats,_=_load_features(force=True)
    return {"features":feats}

# ---- admin: 商品自定义增删改(三类可自定义) ----
class IapProduct(BaseModel):
    license_key:str=""; key:str; category:str; name:str; descr:str=""
    price:float=0; unit:str="USDT"; duration_days:int=0; grants:dict={}; sort:int=0; enabled:bool=True
@app.post("/api/admin/iap/product", dependencies=[Depends(require_op("iap"))])
def iap_product_save(r:IapProduct):
    if _is_retired_iap_product_key(r.key):
        raise HTTPException(400,"auto_loop_pro 已退役: 自动进单/平仓现为系统默认功能")
    if _has_builtin_iap_grants(r.grants):
        raise HTTPException(400,"auto_loop 是系统默认功能, 不可加入商品授权")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO iap_products(key,category,name,descr,price,unit,duration_days,grants,sort,enabled)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (key) DO UPDATE SET category=EXCLUDED.category,name=EXCLUDED.name,descr=EXCLUDED.descr,
                   price=EXCLUDED.price,unit=EXCLUDED.unit,duration_days=EXCLUDED.duration_days,grants=EXCLUDED.grants,
                   sort=EXCLUDED.sort,enabled=EXCLUDED.enabled""",
                (r.key,r.category,r.name,r.descr,r.price,r.unit,r.duration_days,json.dumps(r.grants),r.sort,r.enabled))
    c.close()
    _audit("",_actor(r.license_key),"iap_product_save",{"key":r.key},DEMO_MODE,"saved")
    return {"ok":True,"key":r.key}
class IapCatReq(BaseModel):
    license_key:str=""; key:str; name:str; sort:int=0; enabled:bool=True
@app.post("/api/admin/iap/category", dependencies=[Depends(require_op("iap"))])
def iap_cat_save(r:IapCatReq):
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO iap_categories(key,name,sort,enabled) VALUES(%s,%s,%s,%s)
                   ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name,sort=EXCLUDED.sort,enabled=EXCLUDED.enabled""",
                (r.key,r.name,r.sort,r.enabled))
    c.close()
    return {"ok":True,"key":r.key}

class IapFeatureReq(BaseModel):
    license_key:str=""; key:str; name:str; ftype:str="bool"; hint:str=""; default_value:str="false"; sort:int=0; enabled:bool=True
@app.post("/api/admin/iap/feature", dependencies=[Depends(require_op("iap"))])
def iap_feature_save(r:IapFeatureReq):
    if _is_builtin_entitlement_key(r.key):
        raise HTTPException(400,"auto_loop 是系统默认功能, 不可作为内购权益配置")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO iap_features(key,name,ftype,hint,default_value,sort,enabled)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name,ftype=EXCLUDED.ftype,hint=EXCLUDED.hint,
                   default_value=EXCLUDED.default_value,sort=EXCLUDED.sort,enabled=EXCLUDED.enabled""",
                (r.key,r.name,r.ftype,r.hint,r.default_value,r.sort,r.enabled))
    c.close(); _load_features(force=True)
    _audit("",_actor(r.license_key),"iap_feature_save",{"key":r.key},DEMO_MODE,"saved")
    return {"ok":True,"key":r.key}
class IapFeatureDel(BaseModel):
    license_key:str=""; key:str
@app.post("/api/admin/iap/feature_del", dependencies=[Depends(require_op("iap"))])
def iap_feature_del(r:IapFeatureDel):
    c=db(); cur=c.cursor(); cur.execute("UPDATE iap_features SET enabled=false WHERE key=%s",(r.key,)); c.close()
    _load_features(force=True)
    return {"ok":True}
class IapDel(BaseModel):
    license_key:str=""; key:str
@app.post("/api/admin/iap/product_del", dependencies=[Depends(require_op("iap"))])
def iap_product_del(r:IapDel):
    c=db(); cur=c.cursor(); cur.execute("UPDATE iap_products SET enabled=false WHERE key=%s",(r.key,)); c.close()
    return {"ok":True,"key":r.key,"msg":"商品已下架"}

# ---- admin: 给用户授予权益(内购成交/手工/赠送; 购买即写 entitlements + 记单) ----
class GrantReq(BaseModel):
    license_key:str=""; username:str; product_key:str=""
    feature_key:str=""; value:str=""; source:str="iap"; duration_days:int=0; amount:float=0
@app.post("/api/admin/entitlement/grant", dependencies=[Depends(require_op("iap"))])
def entitlement_grant(r:GrantReq):
    uid=_uid(r.username)
    if not uid: raise HTTPException(404,"user not found")
    grants={}; dur=r.duration_days; amount=r.amount; pkey=r.product_key
    if pkey:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM iap_products WHERE key=%s AND enabled=true",(pkey,)); p=cur.fetchone(); c.close()
        if not p: raise HTTPException(404,"商品不存在/已下架")
        p=_sellable_iap_product(p)
        if not p: raise HTTPException(404,"商品不存在/已下架")
        grants=p["grants"]; dur=p["duration_days"]; amount=amount or float(p["price"] or 0)
    elif r.feature_key:
        if _is_builtin_entitlement_key(r.feature_key):
            raise HTTPException(400,"auto_loop 是系统默认功能, 无需也不可手工授权")
        grants={r.feature_key:r.value}
    else:
        raise HTTPException(400,"需 product_key 或 feature_key")
    exp=None
    if dur and dur>0:
        exp=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=dur)
    c=db(); cur=c.cursor()
    for fk,val in (grants or {}).items():
        cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,expire_at,updated_at)
                       VALUES(%s,%s,%s,%s,%s,now())
                       ON CONFLICT (user_id,feature_key) DO UPDATE SET value=EXCLUDED.value,source=EXCLUDED.source,
                       expire_at=EXCLUDED.expire_at,updated_at=now()""",
                    (uid,fk,str(val),r.source,exp))
    if pkey:
        cur.execute("INSERT INTO iap_orders(user_id,product_key,amount,status,operator,agent_id) VALUES(%s,%s,%s,'paid',%s,%s) RETURNING id",
                    (uid,pkey,amount,_actor(r.license_key),None))
        oid=cur.fetchone()[0]
        try: _calc_commissions(cur, oid, "iap", uid, float(amount or 0))
        except Exception as ce: print("commission calc err",ce)
    c.close()
    _audit(r.username,_actor(r.license_key),"entitlement_grant",{"product":pkey,"grants":list((grants or {}).keys()),"exp":str(exp)},DEMO_MODE,"granted")
    return {"ok":True,"username":r.username,"granted":grants,"expire_at":str(exp) if exp else None}

# ================= P2 三级代理分销 =================
def _calc_commissions(cur, order_id, kind, user_id, base_amount):
    """按消费用户归属代理(users.agent_id=L1)向上回溯 3 级, 各级按上一级代理费率计佣, 写 commissions。
       同一 cursor 内执行(与订单同事务)。base_amount<=0 或无归属代理→不计。"""
    if base_amount<=0: return
    cur.execute("SELECT agent_id FROM users WHERE id=%s",(user_id,)); row=cur.fetchone()
    aid=row[0] if row else None
    tier=1
    while aid and tier<=3:
        cur.execute("SELECT id,parent_id,rate_l1,rate_l2,rate_l3,enabled FROM agents WHERE id=%s",(aid,))
        a=cur.fetchone()
        if not a: break
        a_id,parent,rl1,rl2,rl3,enabled=a
        rate=float([rl1,rl2,rl3][tier-1] or 0)
        if enabled and rate>0:
            amt=round(base_amount*rate,2)
            cur.execute("""INSERT INTO commissions(order_id,order_kind,user_id,agent_id,tier,base_amount,rate,amount)
                           VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",(order_id,kind,user_id,a_id,tier,base_amount,rate,amt))
        aid=parent; tier+=1

class AgentReq(BaseModel):
    license_key:str=""; code:str; name:str=""; parent_code:str=""
    rate_l1:float=0.10; rate_l2:float=0.05; rate_l3:float=0.02; contact:str=""; enabled:bool=True
    owner_username:str=""    # 代理运营用户(招募奖励/代理活动的积分接收方)
@app.post("/api/admin/agent/save", dependencies=[Depends(require_op("agents"))])
def agent_save(r:AgentReq):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    parent_id=None; level=1; parent_owner=None
    if r.parent_code:
        cur.execute("SELECT id,level,owner_username FROM agents WHERE code=%s",(r.parent_code,)); p=cur.fetchone()
        if not p: c.close(); raise HTTPException(404,"上级代理码不存在")
        parent_id=p["id"]; level=min(3,(p["level"] or 1)+1); parent_owner=p.get("owner_username")
    # 是否新代理(招募事件只在新建且有上级时触发一次)
    cur.execute("SELECT code FROM agents WHERE code=%s",(r.code,)); is_new=(cur.fetchone() is None)
    cur.execute("""INSERT INTO agents(code,name,parent_id,level,rate_l1,rate_l2,rate_l3,contact,enabled,owner_username)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name,parent_id=EXCLUDED.parent_id,level=EXCLUDED.level,
                   rate_l1=EXCLUDED.rate_l1,rate_l2=EXCLUDED.rate_l2,rate_l3=EXCLUDED.rate_l3,contact=EXCLUDED.contact,
                   enabled=EXCLUDED.enabled,owner_username=EXCLUDED.owner_username""",
                (r.code,r.name,parent_id,level,r.rate_l1,r.rate_l2,r.rate_l3,r.contact,r.enabled,(r.owner_username or None)))
    # 活动引擎: 代理招募成功(新建 + 有上级 + 上级有 owner_username)→ 奖励发给上级 owner
    fired=None
    if is_new and parent_owner:
        pu=_uid(parent_owner)
        if pu:
            try: fired=_fire_campaigns(cur, "agent_recruit", pu, parent_owner, {"new_agent":r.code,"level":level})
            except Exception as ce: print("camp agent_recruit err",ce)
    c.close()
    _audit("",_actor(r.license_key),"agent_save",{"code":r.code,"level":level,"recruit_reward":bool(fired)},DEMO_MODE,"saved")
    return {"ok":True,"code":r.code,"level":level}

@app.get("/api/admin/agents", dependencies=[Depends(require_op("agents"))])
def agents_list():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT a.id,a.code,a.name,a.parent_id,a.level,a.rate_l1,a.rate_l2,a.rate_l3,a.contact,a.enabled,
                          p.code AS parent_code,
                          (SELECT count(*) FROM users u WHERE u.agent_id=a.id) AS direct_users,
                          (SELECT COALESCE(SUM(amount),0) FROM commissions c WHERE c.agent_id=a.id) AS total_comm,
                          (SELECT COALESCE(SUM(amount),0) FROM commissions c WHERE c.agent_id=a.id AND c.settled=false) AS unsettled_comm
                   FROM agents a LEFT JOIN agents p ON p.id=a.parent_id ORDER BY a.level,a.id""")
    rows=cur.fetchall(); c.close()
    return {"agents":[dict(r) for r in rows]}

class BindReq(BaseModel):
    license_key:str=""; username:str; agent_code:str
@app.post("/api/admin/agent/bind", dependencies=[Depends(require_op("agents"))])
def agent_bind(r:BindReq):
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM agents WHERE code=%s",(r.agent_code,)); a=cur.fetchone()
    if not a: c.close(); raise HTTPException(404,"代理码不存在")
    cur.execute("UPDATE users SET agent_id=%s,source=%s WHERE username=%s",(a[0],r.agent_code,r.username))
    c.close()
    return {"ok":True,"username":r.username,"agent_code":r.agent_code}

@app.get("/api/admin/commissions", dependencies=[Depends(require_op("agents"))])
def commissions_list(agent_code:str="", settled:str=""):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q="""SELECT cm.id,cm.order_kind,cm.tier,cm.base_amount,cm.rate,cm.amount,cm.settled,cm.created_at,
                ag.code AS agent_code, u.username FROM commissions cm
         LEFT JOIN agents ag ON ag.id=cm.agent_id LEFT JOIN users u ON u.id=cm.user_id WHERE 1=1"""
    p=[]
    if agent_code: q+=" AND ag.code=%s"; p.append(agent_code)
    if settled in ("0","1"): q+=" AND cm.settled=%s"; p.append(settled=="1")
    q+=" ORDER BY cm.created_at DESC LIMIT 200"
    cur.execute(q,tuple(p)); rows=cur.fetchall(); c.close()
    return {"commissions":[dict(r) for r in rows]}

class SettleReq(BaseModel):
    license_key:str=""; agent_code:str
@app.post("/api/admin/commission/settle", dependencies=[Depends(require_op("agents"))])
def commission_settle(r:SettleReq):
    c=db(); cur=c.cursor()
    cur.execute("""UPDATE commissions SET settled=true WHERE settled=false AND agent_id=(SELECT id FROM agents WHERE code=%s)""",(r.agent_code,))
    n=cur.rowcount; c.close()
    _audit("",_actor(r.license_key),"commission_settle",{"agent":r.agent_code,"n":n},DEMO_MODE,"settled")
    return {"ok":True,"settled":n}

# ================= P3 试用体验 + 币产品交易分析 BI =================
class TrialReq(BaseModel):
    license_key:str=""; username:str; days:int=7; force_demo:bool=True
@app.post("/api/admin/trial/grant", dependencies=[Depends(require_op("trials"))])
def trial_grant(r:TrialReq):
    uid=_uid(r.username)
    if not uid: raise HTTPException(404,"user not found")
    now=datetime.datetime.now(datetime.timezone.utc)
    until=now+datetime.timedelta(days=max(1,r.days))
    c=db(); cur=c.cursor()
    cur.execute("UPDATE users SET trial_until=%s,trial_started=%s,status='trial' WHERE id=%s",(until,now,uid))
    c.close()
    # 试用强制 DEMO(限风险)+ 给基础权益体验(影子自动循环已免费, 这里不放真金权益)
    if r.force_demo:
        R.set(RNS+"force_demo:"+r.username,"1")
    _audit(r.username,_actor(r.license_key),"trial_grant",{"days":r.days,"until":str(until),"force_demo":r.force_demo},DEMO_MODE,"trial")
    return {"ok":True,"username":r.username,"trial_until":str(until),"force_demo":r.force_demo}

@app.get("/api/admin/trials", dependencies=[Depends(require_op("trials"))])
def trials_list():
    """试用用户漏斗: 试用中/已转化(付费)/已流失 + 试用期行为(成交数)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT u.username,u.status,u.trial_started,u.trial_until,u.paid_until,
                          (SELECT count(*) FROM deals d WHERE d.user_id=u.id AND d.is_trade=true) AS deal_cnt
                   FROM users u WHERE u.trial_started IS NOT NULL OR u.status='trial' ORDER BY u.trial_started DESC NULLS LAST""")
    rows=cur.fetchall(); c.close()
    now=datetime.datetime.now(datetime.timezone.utc)
    items=[]; n_trial=n_conv=n_lost=0
    for r in rows:
        d=dict(r)
        conv = d.get("paid_until") and d["paid_until"]>now
        in_trial = d.get("trial_until") and d["trial_until"]>now and not conv
        if conv: d["funnel"]="converted"; n_conv+=1
        elif in_trial: d["funnel"]="trialing"; n_trial+=1
        else: d["funnel"]="lost"; n_lost+=1
        items.append(d)
    total=len(items)
    return {"trials":items,"summary":{"total":total,"trialing":n_trial,"converted":n_conv,"lost":n_lost,
            "conv_rate":round(n_conv/total*100,1) if total else 0}}

@app.get("/api/admin/bi/symbols", dependencies=[Depends(require_op("bi"))])
def bi_symbols(days:int=30):
    """币产品交易分析(平台级跨用户): 每个 symbol 的活跃用户/成交量/净盈亏/手续费/过夜费/胜率。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT symbol,
                          count(DISTINCT user_id) AS users,
                          count(*) AS deals,
                          COALESCE(SUM(lots),0) AS volume,
                          COALESCE(SUM(profit),0) AS net_profit,
                          COALESCE(SUM(commission),0) AS fees,
                          COALESCE(SUM(swap),0) AS swap,
                          SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END) AS wins,
                          SUM(CASE WHEN profit<0 THEN 1 ELSE 0 END) AS losses
                   FROM deals
                   WHERE is_trade=true AND dealt_at >= now() - (%s||' days')::interval AND symbol<>''
                   GROUP BY symbol ORDER BY volume DESC""",(days,))
    rows=cur.fetchall(); c.close()
    out=[]
    for r in rows:
        d=dict(r); w=int(d["wins"] or 0); l=int(d["losses"] or 0); tot=w+l
        d["win_rate"]=round(w/tot*100,1) if tot else None
        for k in ("volume","net_profit","fees","swap"): d[k]=round(float(d[k] or 0),2)
        out.append(d)
    return {"days":days,"symbols":out}

@app.get("/api/admin/bi/symbol_users", dependencies=[Depends(require_op("bi"))])
def bi_symbol_users(symbol:str, days:int=30):
    """产品分析·单产品下钻: 某 symbol 下每个用户的成交量/净盈亏/手续费/过夜费/胜率(点活跃用户查单用户)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT u.username,
                          count(*) AS deals,
                          COALESCE(SUM(d.lots),0) AS volume,
                          COALESCE(SUM(d.profit),0) AS net_profit,
                          COALESCE(SUM(d.commission),0) AS fees,
                          COALESCE(SUM(d.swap),0) AS swap,
                          SUM(CASE WHEN d.profit>0 THEN 1 ELSE 0 END) AS wins,
                          SUM(CASE WHEN d.profit<0 THEN 1 ELSE 0 END) AS losses
                   FROM deals d JOIN users u ON u.id=d.user_id
                   WHERE d.is_trade=true AND d.symbol=%s AND d.dealt_at >= now() - (%s||' days')::interval
                   GROUP BY u.username ORDER BY volume DESC""",(symbol,days))
    rows=cur.fetchall(); c.close()
    out=[]
    for r in rows:
        d=dict(r); w=int(d["wins"] or 0); l=int(d["losses"] or 0); tot=w+l
        d["win_rate"]=round(w/tot*100,1) if tot else None
        for k in ("volume","net_profit","fees","swap"): d[k]=round(float(d[k] or 0),2)
        out.append(d)
    return {"symbol":symbol,"days":days,"users":out}

@app.get("/api/admin/bi/overview", dependencies=[Depends(require_op("bi"))])
def bi_overview(days:int=30):
    """平台总览 KPI: 用户/活跃/试用/付费 + 区间成交/净盈亏/费用 + Top 代理。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    now="now()"
    cur.execute("SELECT count(*) n FROM users"); total_u=cur.fetchone()["n"]
    cur.execute("SELECT count(*) n FROM users WHERE status='trial' AND trial_until>now()"); trialing=cur.fetchone()["n"]
    cur.execute("SELECT count(*) n FROM users WHERE paid_until>now()"); paid=cur.fetchone()["n"]
    cur.execute("""SELECT count(DISTINCT user_id) n FROM deals WHERE is_trade=true AND dealt_at>=now()-(%s||' days')::interval""",(days,)); active=cur.fetchone()["n"]
    cur.execute("""SELECT COALESCE(SUM(profit),0) p, count(*) c, COALESCE(SUM(commission),0) f FROM deals WHERE is_trade=true AND dealt_at>=now()-(%s||' days')::interval""",(days,))
    pr=cur.fetchone()
    cur.execute("""SELECT ag.code, COALESCE(SUM(cm.amount),0) comm FROM commissions cm JOIN agents ag ON ag.id=cm.agent_id GROUP BY ag.code ORDER BY comm DESC LIMIT 5""")
    topagents=[dict(x) for x in cur.fetchall()]
    cur.execute("""SELECT COALESCE(SUM(amount),0) s, count(*) c FROM iap_orders WHERE status='paid' AND paid_at>=now()-(%s||' days')::interval""",(days,))
    iap=cur.fetchone()
    cur.execute("SELECT username FROM users"); allu=[x["username"] for x in cur.fetchall()]
    c.close()
    # 在跑策略数: 扫 Redis auto_entry/auto_exit 标记(armed/full=真跑)
    running_entry=running_exit=0
    for u in allu:
        if (R.get(RNS+"auto_entry:"+u) or "off") in ("armed","full"): running_entry+=1
        if (R.get(RNS+"auto_exit:"+u) or "off") in ("armed","full"): running_exit+=1
    # 告警聚合: 最近告警按级别计数 + 取最新几条
    alerts=R.lrange(RNS+"alerts",0,49) or []
    lv={"err":0,"warn":0,"info":0}; recent=[]
    for a in alerts:
        try: o=json.loads(a)
        except Exception: continue
        lv[o.get("lv","info")]=lv.get(o.get("lv","info"),0)+1
        if len(recent)<8: recent.append({"lv":o.get("lv"),"msg":o.get("msg"),"ts":o.get("ts")})
    return {"days":days,"users":{"total":total_u,"active":active,"trialing":trialing,"paid":paid},
            "deals":{"count":pr["c"],"net_profit":round(float(pr["p"] or 0),2),"fees":round(float(pr["f"] or 0),2)},
            "iap":{"revenue":round(float(iap["s"] or 0),2),"orders":iap["c"]},
            "strategies":{"auto_entry":running_entry,"auto_exit":running_exit,"global_estop":R.get(RNS+"global_estop")=="1"},
            "alerts":{"levels":lv,"recent":recent},
            "top_agents":[{"code":a["code"],"comm":round(float(a["comm"] or 0),2)} for a in topagents]}

@app.get("/api/admin/orders", dependencies=[Depends(require_op("orders"))])
def orders_list(days:int=90, product:str="", username:str="", reconcile_status:str="", discrepancy_only:bool=False):
    """充值/内购订单明细(iap_orders 联商品/用户/代理)+ 核对字段。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q="""SELECT o.id,o.product_key,p.name AS product_name,p.category,o.amount,o.unit,o.status,o.operator,o.paid_at,
                u.username, ag.code AS agent_code,
                o.reconcile_status,o.received_amount,o.confirmed_by,o.confirmed_at,o.discrepancy_reason,o.reconcile_note,
                o.kind,o.pay_method,o.tx_hash,o.months
         FROM iap_orders o LEFT JOIN iap_products p ON p.key=o.product_key
         LEFT JOIN users u ON u.id=o.user_id LEFT JOIN agents ag ON ag.id=o.agent_id
         WHERE o.paid_at >= now()-(%s||' days')::interval"""
    pa=[days]
    if product: q+=" AND o.product_key=%s"; pa.append(product)
    if username: q+=" AND u.username=%s"; pa.append(username)
    if reconcile_status: q+=" AND COALESCE(o.reconcile_status,'pending')=%s"; pa.append(reconcile_status)
    if discrepancy_only: q+=" AND o.reconcile_status='discrepancy'"
    q+=" ORDER BY o.paid_at DESC LIMIT 300"
    cur.execute(q,tuple(pa)); rows=cur.fetchall(); c.close()
    return {"orders":[dict(r) for r in rows]}

class ReconcileReq(BaseModel):
    license_key:str=""; order_id:int; action:str        # confirm/mark_discrepancy/void/reopen
    received_amount:float=None; reason:str=""; note:str=""
@app.post("/api/admin/order/reconcile", dependencies=[Depends(require_op("orders"))])
def order_reconcile(r:ReconcileReq):
    """单笔核对: confirm(可填实收,与应收不等自动转差异)/mark_discrepancy/void/reopen。留操作员+时间。"""
    actor=_actor(r.license_key)
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT amount FROM iap_orders WHERE id=%s",(r.order_id,)); o=cur.fetchone()
    if not o: c.close(); raise HTTPException(404,"订单不存在")
    amount=float(o["amount"] or 0)
    if r.action=="confirm":
        recv = r.received_amount if r.received_amount is not None else amount
        st = "confirmed" if abs(float(recv)-amount)<0.01 else "discrepancy"
        reason = "" if st=="confirmed" else "实收 %.2f ≠ 应收 %.2f"%(float(recv),amount)
        cur.execute("UPDATE iap_orders SET reconcile_status=%s,received_amount=%s,confirmed_by=%s,confirmed_at=now(),discrepancy_reason=%s,reconcile_note=%s WHERE id=%s",
                    (st,recv,actor,reason,r.note,r.order_id))
    elif r.action=="mark_discrepancy":
        cur.execute("UPDATE iap_orders SET reconcile_status='discrepancy',confirmed_by=%s,confirmed_at=now(),discrepancy_reason=%s,reconcile_note=%s WHERE id=%s",
                    (actor,r.reason or "人工标记差异",r.note,r.order_id)); st="discrepancy"
    elif r.action=="void":
        # 退款/作废联动(幂等: 已 void 不重复回退)。回退: 作废该单佣金 + 扣回所返积分 + 退还抵现积分 + 退还所用券次 + 余额单退回余额
        cur.execute("SELECT reconcile_status,user_id,kind,amount,points_used,pay_method FROM iap_orders WHERE id=%s",(r.order_id,))
        od=cur.fetchone()
        if od and od["reconcile_status"]!="void":
            oid2=r.order_id; ouid=od["user_id"]
            rev={}
            # 1) 作废该单未结佣金
            cur.execute("UPDATE commissions SET settled=NULL WHERE order_id=%s AND settled=false",(oid2,))  # settled=NULL 视为作废(不参与结算)
            cur.execute("DELETE FROM commissions WHERE order_id=%s AND settled IS NULL",(oid2,)); rev["comm_removed"]=cur.rowcount
            # 2) 扣回该单曾返的积分(ref_type=order, 正数 delta)
            cur.execute("SELECT COALESCE(SUM(delta),0) s FROM points_ledger WHERE ref_type='order' AND ref_id=%s AND delta>0",(str(oid2),))
            gave=int(cur.fetchone()["s"] or 0)
            if gave>0:
                try: _points_add(cur, ouid, -gave, "订单作废扣回返积分", "order_void", oid2, actor); rev["pts_clawback"]=gave
                except HTTPException:
                    # 余额不足以扣回(已花掉)→ 记负差, 不阻断作废(资金安全优先, 差额人工跟进)
                    cur.execute("SELECT points FROM users WHERE id=%s",(ouid,)); _p=int(cur.fetchone()["points"] or 0)
                    if _p>0: _points_add(cur, ouid, -_p, "订单作废扣回返积分(部分)", "order_void", oid2, actor)
                    rev["pts_clawback"]="部分(积分已花,差额人工跟进)"
            # 3) 退还该单抵现所用积分(ref_type=order_pay, 负数 delta → 退正数)
            cur.execute("SELECT COALESCE(SUM(-delta),0) s FROM points_ledger WHERE ref_type='order_pay' AND ref_id=%s AND delta<0",(str(oid2),))
            used=int(cur.fetchone()["s"] or 0)
            if used>0:
                _points_add(cur, ouid, used, "订单作废退还抵现积分", "order_void", oid2, actor); rev["pts_refunded"]=used
            # 4) 退还券用量(该单核销过的券 used_qty-1; 保留 redemption 历史)
            cur.execute("SELECT code FROM coupon_redemptions WHERE order_id=%s",(oid2,))
            for cr in cur.fetchall():
                cur.execute("UPDATE coupons SET used_qty=GREATEST(0,COALESCE(used_qty,0)-1) WHERE code=%s",(cr["code"],)); rev["coupon_restored"]=cr["code"]
            # 5) 余额支付的单 → 退回余额(链上单不动, 由财务线下处理)
            if od["pay_method"]=="balance" and float(od["amount"] or 0)>0:
                cur.execute("UPDATE users SET balance=balance+%s WHERE id=%s",(float(od["amount"]),ouid)); rev["balance_refund"]=float(od["amount"])
            _audit("",actor,"order_void_reversal",{"order":oid2,**rev},DEMO_MODE,"reversed")
        cur.execute("UPDATE iap_orders SET reconcile_status='void',status='void',confirmed_by=%s,confirmed_at=now(),reconcile_note=%s WHERE id=%s",(actor,r.note,r.order_id)); st="void"
    elif r.action=="reopen":
        cur.execute("UPDATE iap_orders SET reconcile_status='pending',confirmed_by=NULL,confirmed_at=NULL,discrepancy_reason=NULL WHERE id=%s",(r.order_id,)); st="pending"
    else:
        c.close(); raise HTTPException(400,"未知动作: %s"%r.action)
    c.close()
    _audit("",actor,"order_reconcile",{"order":r.order_id,"action":r.action,"status":st},DEMO_MODE,st)
    return {"ok":True,"order_id":r.order_id,"reconcile_status":st}

class ReconcileBatch(BaseModel):
    license_key:str=""; order_ids:list=[]; action:str="confirm"
@app.post("/api/admin/order/reconcile_batch", dependencies=[Depends(require_op("orders"))])
def order_reconcile_batch(r:ReconcileBatch):
    """批量核销(仅 confirm/void, 按应收=实收确认), 供日终轧账。"""
    if r.action not in ("confirm","void"): raise HTTPException(400,"批量仅支持 confirm/void")
    actor=_actor(r.license_key); n=0
    c=db(); cur=c.cursor()
    for oid in (r.order_ids or []):
        if r.action=="confirm":
            cur.execute("UPDATE iap_orders SET reconcile_status='confirmed',received_amount=amount,confirmed_by=%s,confirmed_at=now() WHERE id=%s AND COALESCE(reconcile_status,'pending')='pending'",(actor,oid))
        else:
            cur.execute("UPDATE iap_orders SET reconcile_status='void',confirmed_by=%s,confirmed_at=now() WHERE id=%s",(actor,oid))
        n+=cur.rowcount
    c.close()
    _audit("",actor,"order_reconcile_batch",{"action":r.action,"n":n},DEMO_MODE,"done")
    return {"ok":True,"affected":n}

@app.get("/api/admin/reconcile/daily", dependencies=[Depends(require_op("orders"))])
def reconcile_daily(days:int=30):
    """对账日报: 每日 应收/已确认/差异/未核/已核/差异数量, 供日终轧账。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT to_char(paid_at,'YYYY-MM-DD') AS day,
                     COALESCE(SUM(amount),0) AS due,
                     COALESCE(SUM(received_amount) FILTER (WHERE reconcile_status='confirmed'),0) AS confirmed_amt,
                     count(*) AS orders,
                     count(*) FILTER (WHERE COALESCE(reconcile_status,'pending')='pending') AS pending_cnt,
                     count(*) FILTER (WHERE reconcile_status='confirmed') AS confirmed_cnt,
                     count(*) FILTER (WHERE reconcile_status='discrepancy') AS discrepancy_cnt
                   FROM iap_orders WHERE paid_at>=now()-(%s||' days')::interval
                   GROUP BY day ORDER BY day DESC""",(days,))
    rows=[dict(r) for r in cur.fetchall()]; c.close()
    for r in rows:
        r["due"]=round(float(r["due"] or 0),2); r["confirmed_amt"]=round(float(r["confirmed_amt"] or 0),2)
    return {"by_day":rows}

@app.get("/api/admin/revenue", dependencies=[Depends(require_op("orders"))])
def revenue_report(days:int=30):
    """收入报表: 按日 + 按商品 汇总(仅 paid)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT to_char(date_trunc('day',paid_at),'YYYY-MM-DD') AS day,
                          COALESCE(SUM(amount),0) AS revenue, count(*) AS orders
                   FROM iap_orders WHERE status='paid' AND paid_at>=now()-(%s||' days')::interval
                   GROUP BY day ORDER BY day DESC""",(days,))
    by_day=[dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT o.product_key, p.name AS product_name, p.category,
                          COALESCE(SUM(o.amount),0) AS revenue, count(*) AS orders
                   FROM iap_orders o LEFT JOIN iap_products p ON p.key=o.product_key
                   WHERE o.status='paid' AND o.paid_at>=now()-(%s||' days')::interval
                   GROUP BY o.product_key,p.name,p.category ORDER BY revenue DESC""",(days,))
    by_prod=[dict(r) for r in cur.fetchall()]
    cur.execute("""SELECT COALESCE(SUM(amount),0) total, count(*) cnt FROM iap_orders WHERE status='paid' AND paid_at>=now()-(%s||' days')::interval""",(days,))
    tot=cur.fetchone(); c.close()
    for x in by_day: x["revenue"]=round(float(x["revenue"] or 0),2)
    for x in by_prod: x["revenue"]=round(float(x["revenue"] or 0),2)
    return {"days":days,"total_revenue":round(float(tot["total"] or 0),2),"total_orders":tot["cnt"],
            "by_day":by_day,"by_product":by_prod}

# ================= P4a 用户管理经营中心 =================
@app.get("/api/admin/users", dependencies=[Depends(require_op("users"))])
def admin_users(q:str=""):
    """经营中心一屏: 每客户 授权状态/到期/累计充值/绑定代理/demo模式/引擎在跑/近7日盈亏。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql="""SELECT u.id,u.username,u.nickname,u.plan,u.status,u.expire_at,u.paid_until,u.trial_until,
                  u.total_recharge,u.risk_flags,u.created_at,u.last_ip,u.last_login,u.geo_country,u.geo_name, ag.code AS agent_code,
                  (SELECT COALESCE(SUM(profit),0) FROM deals d WHERE d.user_id=u.id AND d.is_trade=true AND d.dealt_at>=now()-interval '7 days') AS pnl_7d
           FROM users u LEFT JOIN agents ag ON ag.id=u.agent_id"""
    p=[]
    if q: sql+=" WHERE u.username ILIKE %s OR u.nickname ILIKE %s"; p.append("%"+q+"%"); p.append("%"+q+"%")
    sql+=" ORDER BY u.created_at DESC LIMIT 300"
    cur.execute(sql,tuple(p)); rows=cur.fetchall(); c.close()
    now=datetime.datetime.now(datetime.timezone.utc); out=[]
    for r in rows:
        d=dict(r)
        d["force_demo"]=(R.get(RNS+"force_demo:"+d["username"])=="1")
        d["auto_entry"]=R.get(RNS+"auto_entry:"+d["username"]) or "off"
        d["auto_exit"]=R.get(RNS+"auto_exit:"+d["username"]) or "off"
        exp=d.get("paid_until") or d.get("expire_at")
        d["days_left"]=round((exp-now).total_seconds()/86400,1) if exp else None
        d["pnl_7d"]=round(float(d["pnl_7d"] or 0),2)
        d["total_recharge"]=round(float(d["total_recharge"] or 0),2)
        out.append(d)
    return {"users":out}

@app.get("/api/admin/users/geo_stats", dependencies=[Depends(require_op("users"))])
def admin_users_geo_stats():
    """按地区(国家)聚合用户数 + 近30日活跃(有 last_login)。供 qhadmin/用户端地区统计。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT COALESCE(geo_name,'未知') AS name, geo_country AS code, count(*) AS users,
                          count(*) FILTER (WHERE last_login>=now()-interval '30 days') AS active_30d
                   FROM users GROUP BY geo_name,geo_country ORDER BY users DESC""")
    rows=[dict(r) for r in cur.fetchall()]
    cur.execute("SELECT count(*) n FROM users WHERE last_ip IS NOT NULL"); located=cur.fetchone()["n"]
    cur.execute("SELECT count(*) n FROM users"); total=cur.fetchone()["n"]
    c.close()
    return {"by_country":rows,"located":located,"total":total}

@app.get("/api/admin/users/export", dependencies=[Depends(require_op("users"))])
def admin_users_export(request: Request, q:str="", x_op_token: str = Header(default=""), x_admin_token: str = Header(default="")):
    """用户资料 Excel 导出(真 .xlsx)。仅超级管理员或持「用户高级管理(users_adv)」权限者可用。
       列: 用户名/别名/状态/主套餐/已购套餐/权益/付费到期/试用到期/累计充值/余额/代理/地区/最后登录/模式/自动进出/创建时间。"""
    # 权限闸(与用户高级管理一致)
    _tok=_admin_token()
    if _tok and x_admin_token==_tok: _sess={"operator":"admintoken","role":"super"}
    else: _sess=_op_session(x_op_token) or {}
    _require_adv(_sess, "导出用户资料")
    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except Exception:
        raise HTTPException(500,"服务端缺少 openpyxl 依赖, 请联系运维安装")
    from fastapi.responses import StreamingResponse
    import io as _io
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql="""SELECT u.id,u.username,u.nickname,u.plan,u.status,u.expire_at,u.paid_until,u.trial_until,
                  u.total_recharge,u.balance,u.feishu_id,u.created_at,u.last_login,u.geo_name, ag.code AS agent_code
           FROM users u LEFT JOIN agents ag ON ag.id=u.agent_id"""
    p=[]
    if q: sql+=" WHERE u.username ILIKE %s OR u.nickname ILIKE %s"; p=["%"+q+"%","%"+q+"%"]
    sql+=" ORDER BY u.created_at DESC LIMIT 5000"
    cur.execute(sql,tuple(p)); rows=cur.fetchall()
    # 商品 key→名 映射(已购套餐列可读)
    cur.execute("SELECT key,name FROM iap_products"); prodname={r["key"]:r["name"] for r in cur.fetchall()}
    def _owned(uid):
        cur.execute("SELECT DISTINCT product_key FROM iap_orders WHERE user_id=%s AND status='paid' AND product_key IS NOT NULL",(uid,))
        ks=[x["product_key"] for x in cur.fetchall() if x["product_key"] and not str(x["product_key"]).startswith("_")]
        return " / ".join(prodname.get(k,k) for k in ks)
    def _ents(uid):
        e=_ent_all(uid); return " · ".join("%s=%s"%(k,v) for k,v in e.items())
    def _fd(dt): return dt.strftime("%Y-%m-%d") if dt else ""
    wb=openpyxl.Workbook(); ws=wb.active; ws.title="用户资料"
    headers=["用户名","别名","状态","主套餐","已购套餐","权益","付费到期","试用到期","累计充值","余额","飞书ID","代理","地区","最后登录","模式","自动进","自动出","创建时间"]
    ws.append(headers)
    hf=Font(bold=True,color="FFFFFF"); fill=PatternFill("solid",fgColor="08113A")
    for cell in ws[1]: cell.font=hf; cell.fill=fill; cell.alignment=Alignment(horizontal="center")
    for r in rows:
        uname=r["username"]
        fdemo=(R.get(RNS+"force_demo:"+uname)=="1")
        ae=R.get(RNS+"auto_entry:"+uname) or "off"; ax=R.get(RNS+"auto_exit:"+uname) or "off"
        ws.append([uname, r.get("nickname") or "", r.get("status") or "", r.get("plan") or "",
                   _owned(r["id"]), _ents(r["id"]), _fd(r.get("paid_until")), _fd(r.get("trial_until")),
                   float(r.get("total_recharge") or 0), float(r.get("balance") or 0), r.get("feishu_id") or "",
                   r.get("agent_code") or "", r.get("geo_name") or "", _fd(r.get("last_login")),
                   "演示" if fdemo else "真金", ae, ax, _fd(r.get("created_at"))])
    c.close()
    widths=[16,12,9,14,22,30,12,12,10,10,16,10,10,12,7,7,7,12]
    for i,w in enumerate(widths,1): ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width=w
    ws.freeze_panes="A2"
    buf=_io.BytesIO(); wb.save(buf); buf.seek(0)
    _audit("",_actor(x_admin_token),"users_export",{"count":len(rows),"q":q},DEMO_MODE,"exported")
    fn="qh_users_%s.xlsx"%datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition":"attachment; filename=%s"%fn})

# ================= 会员积分 + 员工推广: 运营侧端点(qhadmin; require_op) =================
# 权限键: points(会员与积分) / staff(员工推广)。与 trials/iap/agents 数据隔离, 不改其行为。
@app.get("/api/admin/members", dependencies=[Depends(require_op("points"))])
def admin_members(q:str=""):
    """会员等级分布 + 逐用户等级/积分/成长值(会员与积分页)。等级由订阅+成长值纯推导。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql="SELECT id,username,nickname,plan,status,paid_until,total_recharge,points,growth_value,staff_code FROM users"
    p=[]
    if q: sql+=" WHERE username ILIKE %s OR nickname ILIKE %s"; p=["%"+q+"%","%"+q+"%"]
    sql+=" ORDER BY growth_value DESC, points DESC LIMIT 300"
    cur.execute(sql,tuple(p)); rows=cur.fetchall(); c.close()
    dist={0:0,1:0,2:0,3:0,4:0}; out=[]
    for r in rows:
        d=dict(r); ml=_member_level(d); d["member_level"]=ml["level"]; d["member_level_name"]=ml["name"]
        d["points"]=int(d.get("points") or 0); d["growth_value"]=int(d.get("growth_value") or 0)
        d["total_recharge"]=round(float(d.get("total_recharge") or 0),2)
        dist[ml["level"]]=dist.get(ml["level"],0)+1
        out.append(d)
    return {"users":out,"level_dist":[{"level":k,"name":_LEVEL_NAME[k],"count":v} for k,v in sorted(dist.items())]}
@app.get("/api/admin/points/ledger", dependencies=[Depends(require_op("points"))])
def admin_points_ledger(username:str="", limit:int=100):
    """积分流水(可按用户过滤)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if username:
        cur.execute("""SELECT l.id,u.username,l.delta,l.balance_after,l.reason,l.ref_type,l.ref_id,l.operator,l.created_at
                       FROM points_ledger l JOIN users u ON u.id=l.user_id WHERE u.username=%s ORDER BY l.id DESC LIMIT %s""",
                    (username,max(1,min(500,limit))))
    else:
        cur.execute("""SELECT l.id,u.username,l.delta,l.balance_after,l.reason,l.ref_type,l.ref_id,l.operator,l.created_at
                       FROM points_ledger l JOIN users u ON u.id=l.user_id ORDER BY l.id DESC LIMIT %s""",(max(1,min(500,limit)),))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"ledger":rows}
class PointsAdjustReq(BaseModel):
    license_key:str=""; username:str; delta:int; reason:str="手工调整"
@app.post("/api/admin/points/adjust", dependencies=[Depends(require_op("points"))])
def admin_points_adjust(r:PointsAdjustReq):
    """运营手工加减积分(审计留痕; 余额不可为负)。"""
    uid=_uid(r.username)
    if not uid: raise HTTPException(404,"user not found")
    if r.delta==0: raise HTTPException(400,"delta 不能为 0")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        nb=_points_add(cur, uid, r.delta, r.reason or "手工调整", "manual", "", _actor(r.license_key))
    except HTTPException: c.close(); raise
    except Exception as e: c.close(); raise HTTPException(500,str(e))
    c.close()
    _audit(r.username,_actor(r.license_key),"points_adjust",{"delta":r.delta,"reason":r.reason,"balance":nb},DEMO_MODE,"done")
    return {"ok":True,"username":r.username,"delta":r.delta,"points":nb}

@app.get("/api/admin/staff", dependencies=[Depends(require_op("staff"))])
def admin_staff_list():
    """员工推广码列表(与三级代理 agents 完全隔离)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT code,name,dept,username,default_trial_days,default_force_demo,comm_trial,comm_first_rate,comm_repeat_rate,enabled,created_at FROM staff ORDER BY created_at DESC")
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"staff":rows}
class StaffReq(BaseModel):
    license_key:str=""; code:str; name:str=""; dept:str=""; username:str=""
    default_trial_days:int=3; default_force_demo:bool=True; enabled:bool=True
    comm_trial:float=0; comm_first_rate:float=0; comm_repeat_rate:float=0   # 每有效试用固定额 / 首单比例 / 复购比例
@app.post("/api/admin/staff", dependencies=[Depends(require_op("staff"))])
def admin_staff_save(r:StaffReq):
    """新增/更新员工推广码(一人一码, 无层级)。含阶梯提成配置(走薪资, 此处仅配+算)。"""
    if not r.code: raise HTTPException(400,"推广码不能为空")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO staff(code,name,dept,username,default_trial_days,default_force_demo,enabled,comm_trial,comm_first_rate,comm_repeat_rate)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name,dept=EXCLUDED.dept,username=EXCLUDED.username,
                   default_trial_days=EXCLUDED.default_trial_days,default_force_demo=EXCLUDED.default_force_demo,enabled=EXCLUDED.enabled,
                   comm_trial=EXCLUDED.comm_trial,comm_first_rate=EXCLUDED.comm_first_rate,comm_repeat_rate=EXCLUDED.comm_repeat_rate""",
                (r.code,r.name,r.dept,r.username,r.default_trial_days,r.default_force_demo,r.enabled,r.comm_trial,r.comm_first_rate,r.comm_repeat_rate))
    c.close(); _audit("",_actor(r.license_key),"staff_save",{"code":r.code},DEMO_MODE,"saved")
    return {"ok":True,"code":r.code}
class StaffDel(BaseModel):
    license_key:str=""; code:str
@app.post("/api/admin/staff/del", dependencies=[Depends(require_op("staff"))])
def admin_staff_del(r:StaffDel):
    """删除员工码(不解除已归因用户的 staff_code, 保留历史归因)。"""
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM staff WHERE code=%s",(r.code,)); c.close()
    _audit("",_actor(r.license_key),"staff_del",{"code":r.code},DEMO_MODE,"deleted")
    return {"ok":True}
@app.get("/api/admin/staff/stats", dependencies=[Depends(require_op("staff"))])
def admin_staff_stats():
    """员工业绩(按 users.staff_code + iap_orders.staff_code 聚合, 不单独建业绩表):
       获客(注册/有效试用/试用转化) + 转化(付费用户) + 营收(订单额) + 应发提成(按阶梯配置算)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # 获客 + 提成配置
    cur.execute("""SELECT s.code, s.name, s.dept, s.comm_trial, s.comm_first_rate, s.comm_repeat_rate,
                     count(u.id) AS users,
                     count(u.id) FILTER (WHERE u.trial_started IS NOT NULL) AS trials,
                     count(u.id) FILTER (WHERE u.paid_until IS NOT NULL) AS paid_users
                   FROM staff s LEFT JOIN users u ON u.staff_code=s.code
                   GROUP BY s.code,s.name,s.dept,s.comm_trial,s.comm_first_rate,s.comm_repeat_rate ORDER BY users DESC""")
    base={r["code"]:dict(r) for r in cur.fetchall()}
    # 营收: 内购/订阅订单额(排除充值 _recharge, 提成不含充值)
    cur.execute("""SELECT staff_code, count(*) AS orders, COALESCE(SUM(amount),0) AS revenue
                   FROM iap_orders WHERE staff_code IS NOT NULL AND status='paid' AND kind IN ('iap','subscription') GROUP BY staff_code""")
    for r in cur.fetchall():
        if r["staff_code"] in base:
            base[r["staff_code"]]["orders"]=r["orders"]; base[r["staff_code"]]["revenue"]=round(float(r["revenue"] or 0),2)
    # 首单额(每用户最早一笔付费单) 与 复购额(其余), 用于阶梯提成
    cur.execute("""WITH o AS (
                     SELECT staff_code, user_id, amount, paid_at,
                            row_number() OVER (PARTITION BY user_id ORDER BY paid_at) AS rn
                     FROM iap_orders WHERE staff_code IS NOT NULL AND status='paid' AND kind IN ('iap','subscription'))
                   SELECT staff_code,
                          COALESCE(SUM(amount) FILTER (WHERE rn=1),0) AS first_amt,
                          COALESCE(SUM(amount) FILTER (WHERE rn>1),0) AS repeat_amt
                   FROM o GROUP BY staff_code""")
    firstrep={r["staff_code"]:(float(r["first_amt"] or 0),float(r["repeat_amt"] or 0)) for r in cur.fetchall()}
    c.close()
    out=[]
    for code,d in base.items():
        d.setdefault("orders",0); d.setdefault("revenue",0.0)
        u=d.get("users") or 0; d["conv_rate"]=round(100.0*(d.get("paid_users") or 0)/u,1) if u else 0.0
        fa,ra=firstrep.get(code,(0.0,0.0))
        comm = (d.get("trials") or 0)*float(d.get("comm_trial") or 0) \
             + fa*float(d.get("comm_first_rate") or 0) + ra*float(d.get("comm_repeat_rate") or 0)
        d["commission_due"]=round(comm,2); d["first_amt"]=round(fa,2); d["repeat_amt"]=round(ra,2)
        for k in ("comm_trial","comm_first_rate","comm_repeat_rate"): d[k]=float(d.get(k) or 0)
        out.append(d)
    out.sort(key=lambda x:x.get("revenue",0), reverse=True)
    return {"stats":out}
@app.get("/api/admin/staff/self/{code}", dependencies=[Depends(require_op("staff"))])
def admin_staff_self(code:str):
    """员工个人看板(单员工业绩明细; 普通员工角色配 staff 权限即可只读自己)。"""
    all_stats=admin_staff_stats().get("stats",[])
    mine=[s for s in all_stats if s["code"]==code]
    return {"code":code,"stat":(mine[0] if mine else None)}

# ---- 员工绩效积分(与用户对冲积分完全隔离; 内部激励) ----
def _perf_add(cur, staff_code, delta, reason, ref_type="", ref_id="", operator=""):
    """绩效积分入账(同事务): 更新 staff.perf_points + 写 staff_perf_ledger。cur 必须 RealDictCursor。"""
    delta=int(delta)
    cur.execute("SELECT perf_points FROM staff WHERE code=%s FOR UPDATE",(staff_code,)); row=cur.fetchone()
    if not row: raise HTTPException(404,"员工码不存在")
    nb=int(row["perf_points"] or 0)+delta
    if nb<0: raise HTTPException(400,"绩效积分不足")
    cur.execute("UPDATE staff SET perf_points=%s WHERE code=%s",(nb,staff_code))
    cur.execute("""INSERT INTO staff_perf_ledger(staff_code,delta,balance_after,reason,ref_type,ref_id,operator)
                   VALUES(%s,%s,%s,%s,%s,%s,%s)""",(staff_code,delta,nb,reason,ref_type,str(ref_id),operator))
    return nb
class PerfAdjustReq(BaseModel):
    license_key:str=""; staff_code:str; delta:int; reason:str="手工调整"
@app.post("/api/admin/staff/perf_adjust", dependencies=[Depends(require_op("staff"))])
def admin_staff_perf_adjust(r:PerfAdjustReq):
    """运营手工加减员工绩效积分(内部激励; 与用户积分隔离)。"""
    if r.delta==0: raise HTTPException(400,"delta 不能为 0")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try: nb=_perf_add(cur, r.staff_code, r.delta, r.reason or "手工调整", "manual", "", _actor(r.license_key))
    except HTTPException: c.close(); raise
    c.close(); _audit("",_actor(r.license_key),"perf_adjust",{"staff":r.staff_code,"delta":r.delta,"balance":nb},DEMO_MODE,"done")
    return {"ok":True,"staff_code":r.staff_code,"perf_points":nb}
@app.get("/api/admin/staff/perf_ledger", dependencies=[Depends(require_op("staff"))])
def admin_staff_perf_ledger(staff_code:str="", limit:int=100):
    """员工绩效积分流水。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if staff_code:
        cur.execute("SELECT * FROM staff_perf_ledger WHERE staff_code=%s ORDER BY id DESC LIMIT %s",(staff_code,max(1,min(500,limit))))
    else:
        cur.execute("SELECT * FROM staff_perf_ledger ORDER BY id DESC LIMIT %s",(max(1,min(500,limit)),))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"ledger":rows}

# ================= 全渠道总看板(第三阶段; 员工渠道 + 代理渠道 + 自然流量 对比) =================
@app.get("/api/admin/overview/channels", dependencies=[Depends(require_op("bi"))])
def overview_channels(days:int=30):
    """获客/转化/营收 按渠道汇总: 员工(staff_code) / 代理(agent_id) / 自然(都无)。统一漏斗口径。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    since="now()-interval '%d days'"%max(1,min(365,days))
    def _bucket(where):
        cur.execute("""SELECT count(*) users,
                         count(*) FILTER (WHERE trial_started IS NOT NULL) trials,
                         count(*) FILTER (WHERE paid_until IS NOT NULL) paid
                       FROM users WHERE %s"""%where)
        return dict(cur.fetchone())
    ch={}
    ch["staff"]=_bucket("staff_code IS NOT NULL")
    ch["agent"]=_bucket("staff_code IS NULL AND agent_id IS NOT NULL")
    ch["organic"]=_bucket("staff_code IS NULL AND agent_id IS NULL")
    # 营收(近 days 天, 内购/订阅 paid 单)按渠道
    cur.execute("""SELECT CASE WHEN o.staff_code IS NOT NULL THEN 'staff'
                          WHEN u.agent_id IS NOT NULL THEN 'agent' ELSE 'organic' END AS ch,
                     COALESCE(SUM(o.amount),0) revenue, count(*) orders
                   FROM iap_orders o JOIN users u ON u.id=o.user_id
                   WHERE o.status='paid' AND o.kind IN ('iap','subscription') AND o.paid_at>=%s
                   GROUP BY 1"""%since)
    rev={r["ch"]:{"revenue":round(float(r["revenue"] or 0),2),"orders":r["orders"]} for r in cur.fetchall()}
    c.close()
    for k in ch:
        u=ch[k]["users"] or 0
        ch[k]["conv_rate"]=round(100.0*(ch[k]["paid"] or 0)/u,1) if u else 0.0
        ch[k]["revenue"]=rev.get(k,{}).get("revenue",0.0); ch[k]["orders"]=rev.get(k,{}).get("orders",0)
    return {"days":days,"channels":ch}

# ================= 活动引擎: 运营侧 CRUD(qhadmin; require_op('campaigns')) =================
@app.get("/api/admin/campaigns", dependencies=[Depends(require_op("campaigns"))])
def admin_campaigns():
    """活动列表(含触发次数)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM campaigns ORDER BY priority DESC, id DESC"); rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"campaigns":rows}
class CampaignReq(BaseModel):
    license_key:str=""; id:int=0; name:str; category:str="retention"; event:str
    cond:dict={}; actions:list=[]; per_user_limit:int=1; total_limit:int=0; priority:int=1
    valid_from:str=""; valid_until:str=""; enabled:bool=True
_CAMP_EVENTS={"register","trial_activate","first_paid","paid","renewal_streak","recharge","checkin","agent_recruit","recall_trial","recall_sub"}
_CAMP_ACTION_TYPES={"points","points_pct","growth","extend_days","trial_days","coupon"}
@app.post("/api/admin/campaign", dependencies=[Depends(require_op("campaigns"))])
def admin_campaign_save(r:CampaignReq):
    """新增/更新活动。event 与 action.type 白名单校验, 防误配。"""
    if not r.name: raise HTTPException(400,"活动名不能为空")
    if r.event not in _CAMP_EVENTS: raise HTTPException(400,"未知触发事件: %s"%r.event)
    for a in (r.actions or []):
        if a.get("type") not in _CAMP_ACTION_TYPES: raise HTTPException(400,"未知动作类型: %s"%a.get("type"))
    c=db(); cur=c.cursor()
    if r.id:
        cur.execute("""UPDATE campaigns SET name=%s,category=%s,event=%s,cond=%s,actions=%s,per_user_limit=%s,total_limit=%s,
                       priority=%s,valid_from=%s,valid_until=%s,enabled=%s,updated_at=now() WHERE id=%s""",
                    (r.name,r.category,r.event,json.dumps(r.cond),json.dumps(r.actions),r.per_user_limit,r.total_limit,
                     r.priority,(r.valid_from or None),(r.valid_until or None),r.enabled,r.id))
    else:
        cur.execute("""INSERT INTO campaigns(name,category,event,cond,actions,per_user_limit,total_limit,priority,valid_from,valid_until,enabled)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r.name,r.category,r.event,json.dumps(r.cond),json.dumps(r.actions),r.per_user_limit,r.total_limit,
                     r.priority,(r.valid_from or None),(r.valid_until or None),r.enabled))
    c.close(); _audit("",_actor(r.license_key),"campaign_save",{"name":r.name,"event":r.event},DEMO_MODE,"saved")
    return {"ok":True}
class CampaignDel(BaseModel):
    license_key:str=""; id:int
@app.post("/api/admin/campaign/del", dependencies=[Depends(require_op("campaigns"))])
def admin_campaign_del(r:CampaignDel):
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM campaigns WHERE id=%s",(r.id,)); c.close()
    _audit("",_actor(r.license_key),"campaign_del",{"id":r.id},DEMO_MODE,"deleted")
    return {"ok":True}
@app.get("/api/admin/campaign/grants", dependencies=[Depends(require_op("campaigns"))])
def admin_campaign_grants(campaign_id:int=0, limit:int=100):
    """活动发放记录。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if campaign_id:
        cur.execute("SELECT * FROM campaign_grants WHERE campaign_id=%s ORDER BY id DESC LIMIT %s",(campaign_id,max(1,min(500,limit))))
    else:
        cur.execute("SELECT * FROM campaign_grants ORDER BY id DESC LIMIT %s",(max(1,min(500,limit)),))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"grants":rows}
@app.get("/api/admin/campaign/meta", dependencies=[Depends(require_op("campaigns"))])
def admin_campaign_meta():
    """前端渲染用: 事件/动作/条件 元数据 + 五大类模板。"""
    return {
      "events":[
        {"key":"register","name":"注册","cat":"trial_convert"},
        {"key":"trial_activate","name":"试用激活","cat":"trial_convert"},
        {"key":"first_paid","name":"首次付费","cat":"trial_convert"},
        {"key":"paid","name":"每次付费(内购/订阅)","cat":"retention"},
        {"key":"renewal_streak","name":"连续续费(近90天订阅数)","cat":"retention"},
        {"key":"recharge","name":"充值","cat":"retention"},
        {"key":"checkin","name":"每日签到","cat":"retention"},
        {"key":"agent_recruit","name":"代理招募成功(发上级)","cat":"agent"},
        {"key":"recall_trial","name":"试用流失召回(日扫)","cat":"recall"},
        {"key":"recall_sub","name":"订阅流失召回(日扫)","cat":"recall"},
      ],
      "action_types":[
        {"key":"points","name":"发固定积分","fields":["value"]},
        {"key":"points_pct","name":"按实付比例发积分","fields":["rate"]},
        {"key":"growth","name":"加成长值","fields":["value"]},
        {"key":"extend_days","name":"延长订阅天数","fields":["days"]},
        {"key":"trial_days","name":"延长试用天数","fields":["days"]},
        {"key":"coupon","name":"发专属券","fields":["kind","value","applies_to","max_discount","valid_days","code_prefix"]},
      ],
      "templates":[
        {"name":"试用转正首单9折","category":"trial_convert","event":"first_paid","cond":{},"actions":[{"type":"coupon","name":"首单9折","kind":"percent","value":10,"applies_to":"subscription","valid_days":7},{"type":"points","value":500}]},
        {"name":"年付赠2000积分","category":"retention","event":"paid","cond":{"months_in":[12]},"actions":[{"type":"points","value":2000}]},
        {"name":"连续签到7天加码","category":"retention","event":"checkin","cond":{},"actions":[{"type":"points","value":10}]},
        {"name":"试用流失召回券","category":"recall","event":"recall_trial","cond":{},"actions":[{"type":"coupon","name":"回归7折","kind":"percent","value":30,"applies_to":"subscription","valid_days":7}]},
        {"name":"充值满赠成长值","category":"retention","event":"recharge","cond":{"min_amount":200},"actions":[{"type":"growth","value":500}]},
        {"name":"连续续费3期赠1000分","category":"retention","event":"renewal_streak","cond":{"streak_min":3},"actions":[{"type":"points","value":1000}]},
        {"name":"代理招募成功奖300分","category":"agent","event":"agent_recruit","cond":{},"actions":[{"type":"points","value":300}]},
      ]
    }
class RecallCfgReq(BaseModel):
    license_key:str=""; enabled:bool=False; coupon_trial:str=""; coupon_sub:str=""
@app.get("/api/admin/recall/config", dependencies=[Depends(require_op("campaigns"))])
def recall_config_get():
    """召回日扫开关 + 提示券码(存 channels.json recall 段)。召回类活动依赖此开关开启才逐用户扫。"""
    return _recall_config()
@app.post("/api/admin/recall/config", dependencies=[Depends(require_op("campaigns"))])
def recall_config_set(r:RecallCfgReq):
    cfg=_chcfg_load(); cfg.setdefault("recall",{})
    cfg["recall"]["enabled"]=bool(r.enabled)
    cfg["recall"]["coupon_trial"]=r.coupon_trial or ""
    cfg["recall"]["coupon_sub"]=r.coupon_sub or ""
    if not _chcfg_save(cfg): raise HTTPException(500,"写入失败(检查文件权限)")
    _audit("",_actor(r.license_key),"recall_config",{"enabled":r.enabled},DEMO_MODE,"saved")
    return {"ok":True,**_recall_config()}
class StaffPerfCfgReq(BaseModel):
    license_key:str=""; enabled:bool=True; trial:int=10; first_paid:int=50; per_usdt:float=0.2
@app.get("/api/admin/staff_perf/config", dependencies=[Depends(require_op("staff"))])
def staff_perf_config_get():
    """员工绩效自动发放配置(存 channels.json staff_perf 段)。"""
    cfg=_chcfg_load().get("staff_perf",{})
    return {"enabled":cfg.get("enabled",True),"trial":int(cfg.get("trial",10)),"first_paid":int(cfg.get("first_paid",50)),"per_usdt":float(cfg.get("per_usdt",0.2))}
@app.post("/api/admin/staff_perf/config", dependencies=[Depends(require_op("staff"))])
def staff_perf_config_set(r:StaffPerfCfgReq):
    cfg=_chcfg_load(); cfg["staff_perf"]={"enabled":bool(r.enabled),"trial":int(r.trial),"first_paid":int(r.first_paid),"per_usdt":float(r.per_usdt)}
    if not _chcfg_save(cfg): raise HTTPException(500,"写入失败")
    _audit("",_actor(r.license_key),"staff_perf_config",{"enabled":r.enabled},DEMO_MODE,"saved")
    return {"ok":True}

# ================= 周期冲榜赛: 运营侧 CRUD + 手动结算(qhadmin; require_op('contests')) =================
@app.get("/api/admin/contests", dependencies=[Depends(require_op("contests"))])
def admin_contests():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM contests ORDER BY id DESC"); rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"contests":rows}
class ContestReq(BaseModel):
    license_key:str=""; id:int=0; name:str; kind:str="staff"; period:str="month"
    metric:str="paid_users"; top_n:int=10; rewards:list=[]; enabled:bool=True
_CONTEST_KINDS={"staff","agent"}; _CONTEST_PERIODS={"month","quarter"}
_CONTEST_METRICS={"paid_users","revenue","trials","new_users"}
@app.post("/api/admin/contest", dependencies=[Depends(require_op("contests"))])
def admin_contest_save(r:ContestReq):
    if not r.name: raise HTTPException(400,"活动名不能为空")
    if r.kind not in _CONTEST_KINDS: raise HTTPException(400,"kind 非法")
    if r.period not in _CONTEST_PERIODS: raise HTTPException(400,"period 非法")
    if r.metric not in _CONTEST_METRICS: raise HTTPException(400,"metric 非法")
    for rw in (r.rewards or []):
        if rw.get("type") not in ("perf","points"): raise HTTPException(400,"奖励类型只能 perf/points")
    c=db(); cur=c.cursor()
    if r.id:
        cur.execute("""UPDATE contests SET name=%s,kind=%s,period=%s,metric=%s,top_n=%s,rewards=%s,enabled=%s,updated_at=now() WHERE id=%s""",
                    (r.name,r.kind,r.period,r.metric,r.top_n,json.dumps(r.rewards),r.enabled,r.id))
    else:
        cur.execute("""INSERT INTO contests(name,kind,period,metric,top_n,rewards,enabled) VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (r.name,r.kind,r.period,r.metric,r.top_n,json.dumps(r.rewards),r.enabled))
    c.close(); _audit("",_actor(r.license_key),"contest_save",{"name":r.name},DEMO_MODE,"saved")
    return {"ok":True}
class ContestDel(BaseModel):
    license_key:str=""; id:int
@app.post("/api/admin/contest/del", dependencies=[Depends(require_op("contests"))])
def admin_contest_del(r:ContestDel):
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM contests WHERE id=%s",(r.id,)); c.close()
    _audit("",_actor(r.license_key),"contest_del",{"id":r.id},DEMO_MODE,"deleted")
    return {"ok":True}
class ContestSettleReq(BaseModel):
    license_key:str=""; id:int; force:bool=False
@app.post("/api/admin/contest/settle", dependencies=[Depends(require_op("contests"))])
def admin_contest_settle(r:ContestSettleReq):
    """手动结算上一周期(force=True 忽略 last_settled_period 重复保护, 供测试/补结算)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM contests WHERE id=%s",(r.id,)); cp=cur.fetchone()
    if not cp: c.close(); raise HTTPException(404,"活动不存在")
    pk,start,end=_period_bounds(cp["period"])
    if (cp.get("last_settled_period") or "")==pk and not r.force:
        c.close(); raise HTTPException(400,"该周期(%s)已结算, force=true 可重结"%pk)
    if r.force:
        cur.execute("DELETE FROM contest_results WHERE contest_id=%s AND period_key=%s",(r.id,pk))
    n=_contest_settle(cur, dict(cp), pk, start, end, _actor(r.license_key))
    c.close(); _audit("",_actor(r.license_key),"contest_settle",{"id":r.id,"period":pk,"n":n},DEMO_MODE,"settled")
    return {"ok":True,"period":pk,"ranked":n}
@app.get("/api/admin/contest/results", dependencies=[Depends(require_op("contests"))])
def admin_contest_results(contest_id:int, period_key:str=""):
    """榜单结果(默认最近周期)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if not period_key:
        cur.execute("SELECT period_key FROM contest_results WHERE contest_id=%s ORDER BY id DESC LIMIT 1",(contest_id,))
        row=cur.fetchone(); period_key=row["period_key"] if row else ""
    cur.execute("SELECT * FROM contest_results WHERE contest_id=%s AND period_key=%s ORDER BY rank",(contest_id,period_key))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"period_key":period_key,"results":rows}
@app.get("/api/admin/contest/preview", dependencies=[Depends(require_op("contests"))])
def admin_contest_preview(kind:str="staff", metric:str="paid_users", period:str="month"):
    """实时预览当前"上一周期"排名(不发奖, 供运营看效果)。"""
    if kind not in _CONTEST_KINDS or metric not in _CONTEST_METRICS or period not in _CONTEST_PERIODS:
        raise HTTPException(400,"参数非法")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    pk,start,end=_period_bounds(period)
    ranked=_contest_rank(cur, kind, metric, start, end); c.close()
    return {"period_key":pk,"ranking":[{"rank":i+1,"code":x[0],"name":x[1],"value":x[2]} for i,x in enumerate(ranked[:50])]}

# ================= 折扣券: 运营侧 CRUD + 发放(qhadmin; require_op('coupons')) =================
@app.get("/api/admin/coupons", dependencies=[Depends(require_op("coupons"))])
def admin_coupons():
    """券列表 + 用量。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM coupons ORDER BY created_at DESC"); rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"coupons":rows}
class CouponReq(BaseModel):
    license_key:str=""; code:str; name:str=""; kind:str="percent"; value:float=0
    applies_to:str="any"; min_amount:float=0; max_discount:float=0
    total_qty:int=0; per_user_limit:int=1; target_username:str=""
    valid_from:str=""; valid_until:str=""; enabled:bool=True
@app.post("/api/admin/coupon", dependencies=[Depends(require_op("coupons"))])
def admin_coupon_save(r:CouponReq):
    """新增/更新券。kind=percent(value=0-100) / fixed(value=立减USDT)。target_username 非空=专属券。"""
    if not r.code: raise HTTPException(400,"券码不能为空")
    if r.kind not in ("percent","fixed"): raise HTTPException(400,"kind 只能 percent/fixed")
    if r.applies_to not in ("any","iap","subscription"): raise HTTPException(400,"applies_to 非法")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO coupons(code,name,kind,value,applies_to,min_amount,max_discount,total_qty,per_user_limit,target_username,valid_from,valid_until,enabled)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name,kind=EXCLUDED.kind,value=EXCLUDED.value,applies_to=EXCLUDED.applies_to,
                   min_amount=EXCLUDED.min_amount,max_discount=EXCLUDED.max_discount,total_qty=EXCLUDED.total_qty,per_user_limit=EXCLUDED.per_user_limit,
                   target_username=EXCLUDED.target_username,valid_from=EXCLUDED.valid_from,valid_until=EXCLUDED.valid_until,enabled=EXCLUDED.enabled""",
                (r.code,r.name,r.kind,r.value,r.applies_to,r.min_amount,r.max_discount,r.total_qty,r.per_user_limit,
                 (r.target_username or None),(r.valid_from or None),(r.valid_until or None),r.enabled))
    c.close(); _audit("",_actor(r.license_key),"coupon_save",{"code":r.code},DEMO_MODE,"saved")
    return {"ok":True,"code":r.code}
class CouponDel(BaseModel):
    license_key:str=""; code:str
@app.post("/api/admin/coupon/del", dependencies=[Depends(require_op("coupons"))])
def admin_coupon_del(r:CouponDel):
    """删除券(核销历史 coupon_redemptions 保留)。"""
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM coupons WHERE code=%s",(r.code,)); c.close()
    _audit("",_actor(r.license_key),"coupon_del",{"code":r.code},DEMO_MODE,"deleted")
    return {"ok":True}
@app.get("/api/admin/coupon/redemptions", dependencies=[Depends(require_op("coupons"))])
def admin_coupon_redemptions(code:str="", limit:int=100):
    """券核销记录(可按券码过滤)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if code:
        cur.execute("""SELECT r.id,r.code,u.username,r.order_id,r.discount,r.created_at
                       FROM coupon_redemptions r JOIN users u ON u.id=r.user_id WHERE r.code=%s ORDER BY r.id DESC LIMIT %s""",(code,max(1,min(500,limit))))
    else:
        cur.execute("""SELECT r.id,r.code,u.username,r.order_id,r.discount,r.created_at
                       FROM coupon_redemptions r JOIN users u ON u.id=r.user_id ORDER BY r.id DESC LIMIT %s""",(max(1,min(500,limit)),))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"redemptions":rows}

@app.get("/api/admin/user/{username}", dependencies=[Depends(require_op("users"))])
def admin_user_detail(username:str):
    uid=_uid(username)
    if not uid: raise HTTPException(404,"user not found")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,plan,status,expire_at,paid_until,trial_until,trial_started,total_recharge,risk_flags,feishu_id,created_at,last_ip,last_login,geo_country,geo_name,points,growth_value,staff_code FROM users WHERE id=%s",(uid,))
    u=dict(cur.fetchone())
    cur.execute("SELECT login,broker,role,enabled FROM mt_accounts WHERE user_id=%s",(uid,)); u["accounts"]=[dict(x) for x in cur.fetchall()]
    cur.execute("SELECT product_key,amount,paid_at,status,kind FROM iap_orders WHERE user_id=%s ORDER BY paid_at DESC LIMIT 20",(uid,)); u["orders"]=[dict(x) for x in cur.fetchall()]
    cur.execute("SELECT count(*) n, COALESCE(SUM(profit),0) p FROM deals WHERE user_id=%s AND is_trade=true",(uid,)); dd=cur.fetchone(); u["deals_total"]=dd["n"]; u["pnl_total"]=round(float(dd["p"] or 0),2)
    c.close()
    u["entitlements"]=_ent_all(uid)
    u["force_demo"]=(R.get(RNS+"force_demo:"+username)=="1")
    u["auto_entry"]=R.get(RNS+"auto_entry:"+username) or "off"
    u["auto_exit"]=R.get(RNS+"auto_exit:"+username) or "off"
    # 会员积分(第一阶段): 积分/成长值/会员等级/员工归属
    _ml=_member_level(u)
    u["points"]=int(u.get("points") or 0); u["growth_value"]=int(u.get("growth_value") or 0)
    u["member_level"]=_ml["level"]; u["member_level_name"]=_ml["name"]; u["member_level_source"]=_ml["source"]
    return u

class UserOpReq(BaseModel):
    license_key:str=""; username:str; op:str         # extend/ban/unban/reset_key/force_demo/feature/create/edit/delete/disable/enable
    days:int=0; force:bool=False; feature_key:str=""; value:str=""; reason:str=""
    plan:str=""; feishu_id:str=""; expire_days:int=0; new_username:str=""; nickname:Optional[str]=None
    paid_until:str=""; trial_until:str=""; status:str=""; mode:str=""   # 付费到期/试用到期(ISO)/状态/模式(demo|real)
    product_key:str=""; revoke_grants:bool=True   # grant_package/revoke_package 用; revoke 是否连带撤权益
# 需「用户高级管理」权限的敏感操作(基础运营仅可 extend/disable/enable/feature)
_ADV_USER_OPS={"edit","delete","ban","unban","reset_key","force_demo","grant_package","revoke_package"}
@app.post("/api/admin/user/op", dependencies=[Depends(require_op("users"))])
def admin_user_op(r:UserOpReq, request: Request, x_op_token: str = Header(default=""), x_admin_token: str = Header(default="")):
    # 敏感操作二次鉴权: 需 users_adv 或超管(基础 users 权限只能做延期/停用/启用/功能开关)
    _tok=_admin_token()
    if _tok and x_admin_token==_tok:
        _sess={"operator":"admintoken","role":"super"}
    else:
        _sess=_op_session(x_op_token) or {}
    # edit 分支里若含高级字段(付费/试用/状态/模式)也要求 adv; 纯别名/飞书ID 归基础
    _edit_has_adv = r.op=="edit" and bool(r.paid_until or r.trial_until or r.status or r.mode or r.plan)
    if r.op in _ADV_USER_OPS or _edit_has_adv:
        _require_adv(_sess, "该操作")
    # create 是唯一不要求用户已存在的分支
    if r.op=="create":
        if _uid(r.username): raise HTTPException(400,"用户名已存在")
        import secrets
        newk="QH-"+secrets.token_hex(8).upper()
        exp=datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=max(1,r.expire_days or 30))
        c=db(); cur=c.cursor()
        cur.execute("""INSERT INTO users(username,nickname,license_key,plan,expire_at,feishu_id,status,created_at)
                       VALUES(%s,%s,%s,%s,%s,%s,'active',now()) RETURNING id""",
                    (r.username,(r.nickname or None),newk,(r.plan or None),exp,r.feishu_id or None))
        c.close()
        _audit(r.username,_actor(r.license_key),"user_op",{"op":"create","license":newk},DEMO_MODE,"done")
        return {"ok":True,"op":"create","new_license":newk,"expire_at":str(exp)}
    uid=_uid(r.username)
    if not uid: raise HTTPException(404,"user not found")
    was_valid=_user_is_valid(r.username)
    c=db(); cur=c.cursor(); res={}
    if r.op=="extend":                       # 延期(改 paid_until + expire_at)
        cur.execute("UPDATE users SET paid_until=GREATEST(COALESCE(paid_until,now()),now())+(%s||' days')::interval, expire_at=GREATEST(COALESCE(paid_until,now()),now())+(%s||' days')::interval, status='active' WHERE id=%s",(r.days,r.days,uid))
        res["extended_days"]=r.days
    elif r.op=="edit":                        # 编辑基础信息(套餐/飞书ID/到期天数/别名/付费到期/试用到期/状态/模式, 均可选)
        sets=[]; vals=[]
        if r.plan: sets.append("plan=%s"); vals.append(r.plan)
        if r.feishu_id: sets.append("feishu_id=%s"); vals.append(r.feishu_id)
        if r.nickname is not None: sets.append("nickname=%s"); vals.append(r.nickname or None)
        if r.expire_days and r.expire_days>0:
            sets.append("expire_at=now()+(%s||' days')::interval"); vals.append(r.expire_days)
        if r.paid_until: sets.append("paid_until=%s"); vals.append(r.paid_until)   # ISO 日期串, 空=不改
        if r.trial_until: sets.append("trial_until=%s"); vals.append(r.trial_until)
        if r.status and r.status in ("active","disabled","banned","trial"): sets.append("status=%s"); vals.append(r.status)
        if sets:
            vals.append(uid); cur.execute("UPDATE users SET "+",".join(sets)+" WHERE id=%s",tuple(vals))
        # 模式(force_demo)走 Redis, 与引擎一致: "demo"=强制演示 / "real"=真金
        if r.mode in ("demo","real"):
            if r.mode=="demo": R.set(RNS+"force_demo:"+r.username,"1")
            else: R.delete(RNS+"force_demo:"+r.username)
        if not sets and not r.mode: c.close(); raise HTTPException(400,"无可更新字段")
        res["edited"]={"plan":r.plan,"feishu_id":r.feishu_id,"nickname":r.nickname,"expire_days":r.expire_days,
                       "paid_until":r.paid_until,"trial_until":r.trial_until,"status":r.status,"mode":r.mode}
    elif r.op=="disable":                     # 轻量停用(阻止登录, 不动引擎/DEMO, 区别于 ban)
        cur.execute("UPDATE users SET status='disabled' WHERE id=%s",(uid,)); res["disabled"]=True
    elif r.op=="enable":                      # 解除停用
        cur.execute("UPDATE users SET status='active' WHERE id=%s AND status='disabled'",(uid,)); res["enabled"]=True
    elif r.op=="delete":                      # 守卫式删除: 有成交/订单的用户拒删(保审计), 干净用户级联删子行
        cur.execute("SELECT (SELECT count(*) FROM deals WHERE user_id=%s)+(SELECT count(*) FROM iap_orders WHERE user_id=%s)",(uid,uid))
        n=cur.fetchone()[0]
        if n>0: c.close(); raise HTTPException(400,"该用户有 %d 条成交/订单记录, 不能删除(请改用停用)"%n)
        for t in ("entitlements","hedge_positions","mt_accounts","param_templates"):
            cur.execute("DELETE FROM %s WHERE user_id=%%s"%t,(uid,))
        cur.execute("DELETE FROM users WHERE id=%s",(uid,))
        for k in ("auto_entry:","auto_exit:","force_demo:"):
            R.delete(RNS+k+r.username)
        res["deleted"]=True
    elif r.op=="ban":                        # 封禁(状态 + 风控原因) → 联动断引擎(铁律)
        cur.execute("UPDATE users SET status='banned', risk_flags=risk_flags||%s WHERE id=%s",(json.dumps({"banned_reason":r.reason}),uid))
        R.set(RNS+"auto_entry:"+r.username,"off"); R.set(RNS+"auto_exit:"+r.username,"off"); R.set(RNS+"force_demo:"+r.username,"1")
        _push_alert("err","账号已封禁(断自动+强制DEMO): %s"%r.reason,r.username)
        res["banned"]=True
    elif r.op=="unban":
        cur.execute("UPDATE users SET status='active' WHERE id=%s",(uid,)); R.delete(RNS+"force_demo:"+r.username); res["unbanned"]=True
    elif r.op=="reset_key":                  # 重置密钥(高危, 旧密钥立即失效)
        import secrets
        newk="QH-"+secrets.token_hex(8).upper()
        cur.execute("UPDATE users SET license_key=%s WHERE id=%s",(newk,uid)); res["new_license"]=newk
    elif r.op=="force_demo":                  # 强制 DEMO 开关
        if r.force: R.set(RNS+"force_demo:"+r.username,"1")
        else: R.delete(RNS+"force_demo:"+r.username)
        res["force_demo"]=r.force
    elif r.op=="grant_package":               # 授予套餐(权益包): 应用商品 grants → entitlements + 补录 comp 赠送单(0元, 不计佣)
        if not r.product_key: c.close(); raise HTTPException(400,"缺少 product_key")
        cur.close(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT key,name,grants,duration_days FROM iap_products WHERE key=%s",(r.product_key,))
        p=cur.fetchone()
        if not p: c.close(); raise HTTPException(404,"套餐不存在: %s"%r.product_key)
        p=_sellable_iap_product(p)
        if not p: c.close(); raise HTTPException(404,"套餐不存在/已退役: %s"%r.product_key)
        grants=p["grants"]; dur=p["duration_days"] or 0
        exp=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=dur)) if dur>0 else None
        for fk,val in grants.items():
            cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,expire_at,updated_at)
                           VALUES(%s,%s,%s,'comp',%s,now())
                           ON CONFLICT (user_id,feature_key) DO UPDATE SET value=EXCLUDED.value,source='comp',expire_at=EXCLUDED.expire_at,updated_at=now()""",
                        (uid,fk,str(val),exp))
        # 补录赠送单(kind=comp, 0元, status=paid, 不计佣)使"已购套餐"列体现
        cur.execute("""INSERT INTO iap_orders(user_id,product_key,amount,unit,status,operator,kind,pay_method,paid_at)
                       VALUES(%s,%s,0,'USDT','paid',%s,'comp','comp',now())""",
                    (uid,r.product_key,_actor(r.license_key)))
        res["granted_package"]={"product":r.product_key,"grants":list(grants.keys()),"expire_at":str(exp) if exp else None}
    elif r.op=="revoke_package":              # 撤销套餐: 作废该 comp 赠送单; revoke_grants=true 时连带删除对应权益(仅 source=comp)
        if not r.product_key: c.close(); raise HTTPException(400,"缺少 product_key")
        cur.execute("UPDATE iap_orders SET status='void' WHERE user_id=%s AND product_key=%s AND kind='comp' AND status='paid'",(uid,r.product_key))
        voided=cur.rowcount
        removed=[]
        if r.revoke_grants:
            cur2=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur2.execute("SELECT grants FROM iap_products WHERE key=%s",(r.product_key,)); pp=cur2.fetchone(); cur2.close()
            for fk in _sellable_iap_grants(pp["grants"] if pp else {}).keys():
                cur.execute("DELETE FROM entitlements WHERE user_id=%s AND feature_key=%s AND source='comp'",(uid,fk))
                if cur.rowcount>0: removed.append(fk)
        res["revoked_package"]={"product":r.product_key,"voided_orders":voided,"removed_grants":removed}
    elif r.op=="feature":                     # per-user 功能可见性 = 写一条 entitlement(复用)
        if _is_builtin_entitlement_key(r.feature_key):
            c.close(); raise HTTPException(400,"auto_loop 是系统默认功能, 无需也不可手工授权")
        cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,updated_at) VALUES(%s,%s,%s,'manual',now())
                       ON CONFLICT (user_id,feature_key) DO UPDATE SET value=EXCLUDED.value,source='manual',updated_at=now()""",(uid,r.feature_key,r.value))
        res["feature"]={r.feature_key:r.value}
    else:
        c.close(); raise HTTPException(400,"未知操作: %s"%r.op)
    c.close()
    if r.op in ("extend","edit","disable","enable","ban","unban"):
        # An invalid account must never carry an old armed state across an
        # admin status/expiry transition. A valid account extended in place
        # is left untouched; restoring an invalid account requires re-arming.
        if not was_valid or not _user_is_valid(r.username):
            _auto_validity_disarm_user(r.username)
    _audit(r.username,_actor(r.license_key),"user_op",{"op":r.op,**res},DEMO_MODE,"done")
    return {"ok":True,"op":r.op,**res}

# ---- QH 新桥池监控: 仅聚合 QH 已登记桥与当前执行连接器, 不做端口扫描 ----
_BRIDGE_POOL_DEFAULT_HOSTS=("43.206.15.17","172.31.5.62")
_BRIDGE_POOL_CACHE={"ts":0.0,"sig":None,"data":None,"task":None,"task_sig":None}

def _bridge_pool_cache_bust():
    task=_BRIDGE_POOL_CACHE.get("task")
    _BRIDGE_POOL_CACHE.update({"ts":0.0,"sig":None,"data":None})
    # Do not cancel an in-flight HTTP read. Its signature guard prevents it
    # from publishing stale data, while cancellation could disrupt a caller.
    if task is None or task.done():
        _BRIDGE_POOL_CACHE.update({"task":None,"task_sig":None})

def _bridge_pool_allowed_hosts():
    """Return the explicit bridge-pool host allowlist.

    43.206.15.17 and 172.31.5.62 are the public/private addresses of the
    same QH bridge node. Operators can replace or extend the list without
    allowing arbitrary URLs stored in mt_accounts to become probe targets.
    """
    raw=os.environ.get("QH_BRIDGE_POOL_HOSTS", ",".join(_BRIDGE_POOL_DEFAULT_HOSTS))
    hosts=[]
    for item in str(raw or "").split(","):
        value=item.strip().lower()
        if not value: continue
        try:
            if "://" in value:
                from urllib.parse import urlsplit
                value=(urlsplit(value).hostname or "").lower()
            else:
                value=value.strip("[]")
        except Exception:
            continue
        if value and value not in hosts: hosts.append(value)
    return tuple(hosts)

def _bridge_pool_normalize_url(raw_url, allowed_hosts=None, allowed_ports=None):
    """Validate a configured bridge URL and reduce it to one host/port endpoint."""
    from urllib.parse import urlsplit
    value=str(raw_url or "").strip().rstrip("/")
    if not value: return None
    try:
        parsed=urlsplit(value)
        host=(parsed.hostname or "").lower()
        if parsed.scheme not in ("http","https") or not host or parsed.username or parsed.password:
            return None
        if host not in set(allowed_hosts or _bridge_pool_allowed_hosts()):
            return None
        port=parsed.port or (443 if parsed.scheme=="https" else 80)
        trusted_ports=set(int(p) for p in (allowed_ports or _bridge_client_ports()))
        if not 1<=int(port)<=65535 or int(port) not in trusted_ports: return None
    except (TypeError,ValueError):
        return None
    endpoint="%s://%s:%d"%(parsed.scheme,host,int(port))
    return {"endpoint":endpoint,"host":host,"port":int(port),"scheme":parsed.scheme}

def _bridge_pool_targets(rows, execution_rows=()):
    """Build the deduplicated QH bridge target set from trusted associations."""
    allowed=_bridge_pool_allowed_hosts(); ports=_bridge_client_ports(); targets={}; skipped=0
    def _add(raw, source, association, key=""):
        nonlocal skipped
        norm=_bridge_pool_normalize_url(raw,allowed,ports)
        if norm is None:
            if str(raw or "").strip(): skipped+=1
            return
        ident=(norm["host"],norm["port"])
        target=targets.setdefault(ident,{**norm,"sources":[],"associations":[],"_keys":[]})
        if source and source not in target["sources"]: target["sources"].append(source)
        clean={k:v for k,v in (association or {}).items() if v not in (None,"")}
        if clean and clean not in target["associations"]: target["associations"].append(clean)
        if key and key not in target["_keys"]: target["_keys"].append(key)
    for raw in (rows or []):
        row=dict(raw)
        if not row.get("enabled",True) or str(row.get("conn_mode") or "bridge")!="bridge":
            continue
        assoc={"username":row.get("username"),"role":row.get("role"),
               "login":str(row.get("login") or ""),"platform":row.get("platform"),
               "server":row.get("server")}
        _add(row.get("bridge_url"),"mt_accounts",assoc,
             os.environ.get("QH_BRIDGE_KEY",""))
    for raw in (execution_rows or []):
        row=dict(raw)
        assoc={"username":row.get("username") or "QH system","role":row.get("role"),
               "login":str(row.get("login") or ""),"platform":row.get("platform"),
               "server":row.get("server"),"execution":True}
        _add(row.get("bridge_url"),"execution",assoc,row.get("bridge_key") or "")
    ordered=sorted(targets.values(),key=lambda x:(x["host"],x["port"]))
    try: limit=max(1,min(int(os.environ.get("QH_BRIDGE_POOL_MAX_TARGETS","16")),32))
    except (TypeError,ValueError): limit=16
    if len(ordered)>limit:
        skipped+=len(ordered)-limit; ordered=ordered[:limit]
    return ordered,skipped

def _bridge_pool_registered_rows():
    c=None
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT u.username,m.role,m.login,m.platform,m.server,m.conn_mode,
                              m.enabled,m.bridge_url
                       FROM mt_accounts m JOIN users u ON u.id=m.user_id
                       WHERE m.enabled AND m.conn_mode='bridge'
                         AND m.role IN ('main','hedge') AND BTRIM(COALESCE(m.bridge_url,''))<>''
                       ORDER BY u.username,m.role,m.id""")
        return [dict(r) for r in cur.fetchall()],None
    except Exception as e:
        return [],e.__class__.__name__
    finally:
        try:
            if c is not None: c.close()
        except Exception: pass

def _bridge_pool_execution_rows():
    """Read the actual active bridge connector endpoints without probing them."""
    if _active_mode()!="bridge": return []
    try: conn=_active_connector()
    except Exception: return []
    rows=[]
    for role in ("main","hedge"):
        leg=getattr(conn,role,None)
        if leg is None: continue
        headers=getattr(leg,"h",{}) or {}
        rows.append({"role":role,"bridge_url":getattr(leg,"base","") or "",
                     "bridge_key":headers.get("X-API-Key") or headers.get("x-api-key") or ""})
    return rows

async def _admin_bridge_pool_uncached(targets,skipped,discovery_error):
    from connector import _pooled
    import time as _t
    try: concurrency=max(1,min(int(os.environ.get("QH_BRIDGE_POOL_CONCURRENCY","8")),16))
    except (TypeError,ValueError): concurrency=8
    semaphore=_aio.Semaphore(concurrency)
    async def _probe(target):
        item={k:v for k,v in target.items() if k!="_keys"}
        expected=sorted(set(str(a.get("login") or "") for a in item["associations"] if a.get("login")))
        registered_platforms=sorted(set(str(a.get("platform") or "").upper()
                                        for a in item["associations"] if a.get("platform")))
        keys=target.get("_keys") or [""]
        response=None; last_error=None; latency=None
        for key in keys:
            response=None
            started=_t.perf_counter()
            try:
                response=await _pooled("bridge-pool-monitor",2.5).get(
                    item["endpoint"]+"/mt5/connection/status",
                    headers={"X-API-Key":key},timeout=2.5)
                latency=round((_t.perf_counter()-started)*1000)
                if response.status_code in (401,403) and key!=keys[-1]:
                    continue
                if response.status_code in (401,403):
                    # HTTP auth rejection still proves that the bridge
                    # service is reachable; keep it separate from terminal
                    # connectivity so the admin cards can show both facts.
                    item.update({"reachable":True,"service_online":True,
                                 "connected":False,"terminal_connected":False,
                                 "healthy":False,"reported_healthy":False,
                                 "account":None,"account_match":None,
                                 "server":"","instance":"",
                                 "platform":registered_platforms[0] if len(registered_platforms)==1 else None,
                                 "latency_ms":latency,"last_ok_at":None,
                                 "failures":None,"last_error":"桥服务鉴权失败"})
                    return item
                response.raise_for_status()
                status=response.json()
                if not isinstance(status,dict): raise ValueError("invalid_status_payload")
                actual=str(status.get("account") or "").strip()
                account_match=not expected or (len(expected)==1 and actual==expected[0])
                terminal_connected=bool(status.get("connected"))
                reported_healthy=bool(status.get("healthy",terminal_connected))
                # MT5 status computes its stale flag before the endpoint's
                # account_info ping. A returned balance/equity is newer proof
                # that the terminal is usable, so avoid a one-refresh false red.
                account_verified=(status.get("balance") is not None or status.get("equity") is not None)
                healthy=bool(terminal_connected and (reported_healthy or account_verified))
                platform=(status.get("platform") or
                          _plat_from_instance(status.get("instance"),status.get("server")) or
                          (registered_platforms[0] if len(registered_platforms)==1 else None))
                item.update({
                    "reachable":True,"service_online":True,
                    "connected":bool(terminal_connected and healthy and account_match),
                    "terminal_connected":terminal_connected,"healthy":healthy,
                    "reported_healthy":reported_healthy,
                    "account":actual or None,"account_match":account_match,
                    "server":status.get("server") or "","instance":status.get("instance") or "",
                    "platform":platform,
                    "latency_ms":latency,"last_ok_at":status.get("last_ok_at"),
                    "failures":status.get("failures"),"last_error":None,
                })
                if not account_match:
                    item["last_error"]="桥账户与 QH 登记不一致"
                elif not terminal_connected:
                    item["last_error"]="MT 客户端未连接"
                elif not healthy:
                    item["last_error"]="MT 客户端状态不健康"
                return item
            except Exception as e:
                latency=round((_t.perf_counter()-started)*1000)
                code=getattr(response,"status_code",None)
                last_error=("HTTP %s"%code) if code else e.__class__.__name__
        item.update({"reachable":False,"service_online":False,"connected":False,
                     "terminal_connected":False,"healthy":False,
                     "reported_healthy":False,
                     "account":None,"account_match":None,"server":"","instance":"",
                     "platform":registered_platforms[0] if len(registered_platforms)==1 else None,
                     "latency_ms":latency,"last_ok_at":None,"failures":None,
                     "last_error":last_error or "unreachable"})
        return item
    async def _bounded_probe(target):
        async with semaphore:
            return await _probe(target)
    clients=await _aio.gather(*[_bounded_probe(t) for t in targets]) if targets else []
    for item in clients:
        associations=item.get("associations") or []
        item["users"]=sorted(set(a.get("username") for a in associations if a.get("username") and a.get("username")!="QH system"))
        item["roles"]=sorted(set(a.get("role") for a in associations if a.get("role")))
        item["registered_accounts"]=sorted(set(str(a.get("login")) for a in associations if a.get("login")))
    platforms={}
    for name in ("MT4","MT5","OTHER"):
        subset=[x for x in clients if (str(x.get("platform") or "").upper() if x.get("platform") else "OTHER")==name]
        platforms[name]={"total":len(subset),"connected":sum(1 for x in subset if x.get("connected")),
                         "service_total":len(subset),
                         "service_online":sum(1 for x in subset if x.get("service_online",x.get("reachable"))),
                         "clients_total":len(subset),
                         "clients_connected":sum(1 for x in subset if x.get("connected"))}

    # QHCELL exposes the actual warm-cell pool independently of MT terminal
    # status.  This is the source of truth for the hot-standby count shown in
    # /system; no standby count is inferred from client rows.
    allowed=list(_bridge_pool_allowed_hosts())
    host_counts={}
    for target in targets:
        host=str(target.get("host") or "").strip()
        if host: host_counts[host]=host_counts.get(host,0)+1
    health_host=max(host_counts,key=host_counts.get) if host_counts else (allowed[0] if allowed else "")
    pool_service={"health_url":("http://%s:8600/cell/health"% health_host if health_host else None),
                  "host":health_host or None,"reachable":False,"healthy":False,
                  "cell":None,"warm":None,"allocated":None,"last_error":"未探测"}
    if health_host:
        try:
            started=_t.perf_counter()
            response=await _pooled("bridge-pool-monitor",2.5).get(
                "http://%s:8600/cell/health"%health_host,timeout=2.5)
            latency=round((_t.perf_counter()-started)*1000)
            code=int(getattr(response,"status_code",0) or 0)
            data=response.json() if code==200 else {}
            if not isinstance(data,dict): data={}
            pool_service.update({"reachable":code>0 and code<500,
                                 "healthy":bool(code==200 and data.get("ok")),
                                 "latency_ms":latency,"cell":data.get("cell"),
                                 "warm":data.get("warm"),"allocated":data.get("allocated"),
                                 "last_error":None if code==200 and data.get("ok") else ("HTTP %s"%code)})
        except Exception as e:
            pool_service["last_error"]=e.__class__.__name__
    warm=pool_service.get("warm")
    try: warm_count=max(0,int(warm)) if warm is not None else None
    except (TypeError,ValueError): warm_count=None
    pool_service["hot_standby"]={"ready":warm_count,
                                  "status":("ready" if warm_count and warm_count>0 else
                                            "empty" if warm_count==0 else "unknown")}
    service_total=len(clients)
    service_online=sum(1 for x in clients if x.get("service_online",x.get("reachable")))
    clients_connected=sum(1 for x in clients if x.get("connected"))
    return {"node":os.environ.get("QH_BRIDGE_POOL_NODE","43.206.15.17"),
            "scope":"qh_configured_only","allowed_hosts":list(_bridge_pool_allowed_hosts()),
            "total":len(clients),"connected":sum(1 for x in clients if x.get("connected")),
            "reachable":sum(1 for x in clients if x.get("reachable")),
            "service_total":service_total,"service_online":service_online,
            "clients_total":service_total,"clients_connected":clients_connected,
            "disconnected":sum(1 for x in clients if not x.get("connected")),
            "account_mismatch":sum(1 for x in clients if x.get("account_match") is False),
            "pool_service":pool_service,
            "platforms":platforms,"clients":clients,"skipped_unapproved":skipped,
            "discovery_error":discovery_error}

async def _admin_bridge_pool():
    """Return a fresh-enough pool snapshot with per-signature single-flight."""
    import hashlib as _hashlib
    rows,discovery_error=_bridge_pool_registered_rows()
    targets,skipped=_bridge_pool_targets(rows,_bridge_pool_execution_rows())
    signature_rows=[]
    for target in targets:
        public={k:v for k,v in target.items() if k!="_keys"}
        key_hashes=[_hashlib.sha256(str(k).encode("utf-8")).hexdigest()
                    for k in (target.get("_keys") or [])]
        signature_rows.append({"target":public,"key_hashes":key_hashes})
    sig=_hashlib.sha256(json.dumps(
        {"targets":signature_rows,"skipped":skipped,"error":discovery_error},
        sort_keys=True,separators=(",",":"),default=str).encode("utf-8")).hexdigest()
    try: ttl=max(1.0,min(float(os.environ.get("QH_BRIDGE_POOL_TTL_SEC","4")),10.0))
    except (TypeError,ValueError): ttl=4.0
    now=_t_conn.time(); cached=_BRIDGE_POOL_CACHE
    if cached.get("data") is not None and cached.get("sig")==sig and now-float(cached.get("ts") or 0)<ttl:
        return cached["data"]
    task=cached.get("task")
    if task is not None and not task.done() and cached.get("task_sig")==sig:
        return await _aio.shield(task)
    task=_aio.create_task(_admin_bridge_pool_uncached(targets,skipped,discovery_error))
    cached["task"]=task; cached["task_sig"]=sig
    try:
        result=await _aio.shield(task)
    except Exception:
        if cached.get("task") is task:
            cached["task"]=None; cached["task_sig"]=None
        raise
    if cached.get("task") is task and cached.get("task_sig")==sig:
        cached.update({"ts":_t_conn.time(),"sig":sig,"data":result,
                       "task":None,"task_sig":None})
    return result

# ================= P4b 系统管理 + 总控面板 =================
@app.get("/api/admin/system", dependencies=[Depends(require_op("system"))])
async def admin_system():
    """系统健康: QH 关联桥池 + 引擎/采样/护栏/WS/自动开关。"""
    import time as _t
    def _age(iso):
        """ISO 时间戳 → 距今秒数(无/解析失败返 None)。"""
        if not iso: return None
        try:
            s=iso.replace("Z","").split(".")[0]
            dt=_dt.datetime.fromisoformat(s)
            return max(0,int((_dt.datetime.utcnow()-dt).total_seconds()))
        except Exception: return None
    out={"bridge_pool":await _admin_bridge_pool(),"engine":{},"auto":{},"gates":{},"ws":{},"alerts":[]}
    # 引擎循环 + 采样器新鲜度
    cycle_ts=R.get(RNS+"engine:cycle_ts"); sampler_ts=R.get(RNS+"engine:sampler_ts")
    _samperr=R.get(RNS+"engine:sampler_err") or ""
    out["engine"]={
        "cycle":json.loads(R.get(RNS+"engine:cycle") or "null"),
        "cycle_age":_age(cycle_ts),                     # 引擎主循环距今秒(>15s 视为停滞)
        "market":_json_hash_state(RNS+"engine:market:user"),
        "sampler_age":_age(sampler_ts),                 # 点差采样器距今秒(>60s 视为停更)
        "sampler_err":_samperr or None,
        "auto_exit_last":R.get(RNS+"auto_exit:last"), "auto_exit_age":_age(R.get(RNS+"auto_exit:last")),
        "auto_entry_last":R.get(RNS+"auto_entry:last"), "auto_entry_age":_age(R.get(RNS+"auto_entry:last")),
        "err":R.get(RNS+"engine:err"),
    }
    # 点差新鲜度: 最后一条 spread:hist 距今秒
    try:
        sampler_users=R.hgetall(RNS+"engine:sampler_ts:user") or {}
        out["engine"]["spread_age"]={u:_age(ts) for u,ts in sampler_users.items()}
        out["engine"]["spread_count"]={u:R.llen(RNS+"spread:hist:"+u) for u in sampler_users}
    except Exception: out["engine"]["spread_age"]=None
    # 护栏闸: 波动闸 + 背离闸
    out["gates"]={
        "fluctuation":_json_hash_state(RNS+"engine:fluctuation:user"),
        "divergence":_json_hash_state(RNS+"engine:divergence:user"),
        "div_tripped":{u:(v=="1") for u,v in ((str(k).split(":")[-1],R.get(k))
            for k in (R.scan_iter(RNS+"engine:div_tripped:*") or []))},
    }
    # WS hub: 真实在线连接数取 Rust HUB 上报的 qh:ws:hub_clients(切 HUB 后本地 _WS_CLIENTS 恒空);
    # 无 HUB 键(未部署/回退本地 /ws/stream)则回落本地连接数。broadcaster 状态以快照新鲜度为准。
    try:
        now=int(_t.time()); fts=_WS_SNAP.get("fast_ts",0) or 0
        _hub_clients=R.get(RNS+"ws:hub_clients")
        _hub_alive=(R.get(RNS+"ws:hub_alive")=="1")
        if _hub_clients is not None:
            clients=int(_hub_clients); src="hub"
        else:
            clients=len(_WS_CLIENTS); src="local"
        # 新鲜度: 有连接且最近一帧 <15s = running; 无连接 = idle; 有连接但快照陈旧 = stale
        if clients>0 and fts and (now-fts)<15: bstate="running"
        elif clients==0: bstate="idle"
        else: bstate="stale"
        out["ws"]={"clients":clients,"src":src,"hub_alive":_hub_alive,
                   "fast_age":(now-fts) if fts else None,"broadcaster":bstate}
    except Exception as e: out["ws"]={"err":str(e)}
    # 最近告警流(实时滚动)
    try:
        out["alerts"]=[json.loads(x) for x in (R.lrange(RNS+"alerts",0,29) or [])]
    except Exception: out["alerts"]=[]
    # 全局自动开关聚合(扫所有用户)
    c=db(); cur=c.cursor(); cur.execute("SELECT username FROM users"); users=[x[0] for x in cur.fetchall()]; c.close()
    aentry=aexit=0
    for u in users:
        if (R.get(RNS+"auto_entry:"+u) or "off") in ("armed","full"): aentry+=1
        if (R.get(RNS+"auto_exit:"+u) or "off") in ("armed","full"): aexit+=1
    out["auto"]={"users":len(users),"auto_entry_armed":aentry,"auto_exit_armed":aexit,
                 "global_estop":R.get(RNS+"global_estop")=="1"}
    # 维护态保留旧 mode.maintenance 形状，避免运维横幅和外部只读大屏回归。
    _m=_maint_get()
    out["mode"]={
        "maintenance":{"on":bool(_m.get("on")),"block_login":bool(_m.get("block_login")),
                       "block_trading":bool(_m.get("block_trading")),"stop_strategy":bool(_m.get("stop_strategy")),
                       "title":_m.get("title") if _m.get("on") else None},
    }
    out["demo_mode"]=DEMO_MODE
    out["server_ts"]=_dt.datetime.utcnow().isoformat()
    return out


class EstopReq(BaseModel):
    license_key:str=""; confirm:bool=False
@app.post("/api/admin/system/estop", dependencies=[Depends(require_op("system",danger=True))])
def admin_estop(r:EstopReq):
    """全局急停: 所有用户 auto_entry/exit → off + 置全局 estop 标记。真金系统红色按钮。"""
    if not r.confirm: raise HTTPException(400,"急停需二次确认(confirm=true)")
    c=db(); cur=c.cursor(); cur.execute("SELECT username FROM users"); users=[x[0] for x in cur.fetchall()]; c.close()
    for u in users:
        R.set(RNS+"auto_entry:"+u,"off"); R.set(RNS+"auto_exit:"+u,"off")
    R.set(RNS+"global_estop","1")
    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err","msg":"⛔全局急停: 所有用户自动进单/平仓已停"})); R.ltrim(RNS+"alerts",0,49)
    _audit("",_actor(r.license_key),"global_estop",{"users":len(users)},DEMO_MODE,"ESTOP")
    return {"ok":True,"stopped_users":len(users)}
@app.post("/api/admin/system/estop_clear", dependencies=[Depends(require_op("system"))])
def admin_estop_clear(r:EstopReq):
    R.delete(RNS+"global_estop")
    _audit("",_actor(r.license_key),"global_estop_clear",{},DEMO_MODE,"cleared")
    return {"ok":True,"cleared":True}

# ---- 运行模式状态机: 组合态总览 + 受控切换(读取源) ----
# ================= 配置中心 (散在 Redis 的运行配置收进登记表 + 白名单编辑) =================
# 只登记"运行时可热改"的配置; env/DB 配置各有专页, 不进此中心。type: enum/json/text/int。
_CONFIG_REGISTRY=[
    {"key":"conn:read_source","label":"读取数据源","group":"连接","type":"enum","options":["a2t","bridge"],
     "default":"a2t","apply":"热生效(15s缓存)","note":"a2t=纯云端(登记即有/清除即停); bridge=桥优先+熔断回退"},
    {"key":"conn:active_mode","label":"执行连接方式","group":"连接","type":"enum","options":["bridge","api"],
     "default":"api","apply":"热生效","note":"开/平仓走哪条链路; 切换建议走运维页双腿可达校验"},
    {"key":"a2t:broker_seed","label":"经纪商种子清单","group":"A2T","type":"json",
     "default":"","apply":"下次目录刷新","note":"JSON 数组, A2T /Search 逐个查聚合; 缺平台加关键词"},
    {"key":"a2t:broker_finalize","label":"品牌改名/合并规则","group":"A2T","type":"json",
     "default":"","apply":"下次目录刷新","note":"JSON {rename,merge,bridge_map}; 法人→品牌名/合并服务器"},
    {"key":"a2t:broker_override","label":"本地客户端服务器覆盖","group":"A2T","type":"json",
     "default":"","apply":"下次目录刷新","note":"JSON {公司:[服务器]}, 本地真源置顶"},
]
_CONFIG_KEYS={c["key"] for c in _CONFIG_REGISTRY}
def _config_cache_bust(key):
    if key=="conn:read_source":
        try: _READ_SRC_CACHE["v"]=None; _READ_SRC_CACHE["ts"]=0.0; _A2T_RC.clear()
        except Exception: pass
    elif key=="conn:active_mode":
        try: _conn_cache_bust()
        except Exception: pass
    elif key.startswith("a2t:broker"):
        try: R.delete(RNS+"a2t:brokers")   # 目录聚合缓存
        except Exception: pass
@app.get("/api/admin/config", dependencies=[Depends(require_op("datamgr"))])
def config_list():
    """配置中心: 登记表 + 各键当前值(敏感不登记)。"""
    out=[]
    for c in _CONFIG_REGISTRY:
        try: v=R.get(RNS+c["key"])
        except Exception: v=None
        out.append({**c,"value":(v if v is not None else "")})
    return {"configs":out}
class ConfigSetReq(BaseModel):
    license_key:str=""; key:str; value:str=""
@app.post("/api/admin/config/set", dependencies=[Depends(require_op("datamgr",danger=True))])
def config_set(r:ConfigSetReq):
    """白名单编辑: 仅登记表内的键可改; JSON 类型先校验; 改后清相关缓存 + 审计。"""
    if r.key not in _CONFIG_KEYS: raise HTTPException(400,"非法配置键(不在登记表)")
    reg=next(c for c in _CONFIG_REGISTRY if c["key"]==r.key)
    val=(r.value or "").strip()
    if reg["type"]=="enum" and val and val not in reg.get("options",[]):
        raise HTTPException(400,"值须为: "+"/".join(reg["options"]))
    if reg["type"]=="json" and val:
        try: json.loads(val)
        except Exception as e: raise HTTPException(400,"JSON 格式非法: %s"%str(e)[:60])
    if reg["type"]=="int" and val:
        try: int(val)
        except Exception: raise HTTPException(400,"须为整数")
    if val=="": R.delete(RNS+r.key)
    else: R.set(RNS+r.key, val)
    _config_cache_bust(r.key)
    _audit("",_actor(r.license_key),"config_set",{"key":r.key,"value":val[:100]},DEMO_MODE,r.key)
    return {"ok":True,"key":r.key,"value":val}

@app.get("/api/admin/system/runmode", dependencies=[Depends(require_op("system"))])
def system_runmode():
    """系统运行模式组合态(总览卡数据源): 读取源/执行方式/维护/急停/DEMO + A2T 计量。"""
    _m=_maint_get()
    return {"read_source":_read_source(),"active_mode":_active_mode(),
            "maintenance":{"on":bool(_m.get("on")),"block_login":bool(_m.get("block_login")),
                           "block_trading":bool(_m.get("block_trading")),"stop_strategy":bool(_m.get("stop_strategy"))},
            "global_estop":R.get(RNS+"global_estop")=="1","demo_mode":DEMO_MODE,
            "a2t":_a2t_meter_get()}
_DV_CACHE={"ts":0.0,"data":None}
@app.get("/api/dv/public")
async def dv_public(token:str=""):
    """Go-View 大屏只读数据源(token 门控, 非操作员会话)。token=Redis qh:dv:token。
       只读聚合(健康/KPI/A2T/告警/总控面板dash), 无写能力, 泄漏也无风险。Go-View 数据源配 ?token=xxx。
       10s 缓存: 大屏每个组件独立轮询, 共享一份聚合防打爆 DB。"""
    want=R.get(RNS+"dv:token") or ""
    if not want or token!=want:
        raise HTTPException(403,"invalid dv token")
    now=_dt.datetime.utcnow().timestamp()
    if _DV_CACHE["data"] is not None and now-_DV_CACHE["ts"]<10:
        return _DV_CACHE["data"]
    d=await dv_summary()   # 路由级 Depends 不在函数签名, 直调=纯读无鉴权(正是 token 门控要的)
    _DV_CACHE["data"]=d; _DV_CACHE["ts"]=now
    return d

@app.get("/api/admin/dv/summary", dependencies=[Depends(require_op("system"))])
async def dv_summary():
    """只读大屏聚合(总控/运维两屏共用): 系统健康 + 当日交易 KPI + A2T 24h 桶 + 告警流。"""
    sysd=await admin_system()   # 复用全链路健康(mode/fra/a2t/engine/ws/auto/alerts/gates)
    # 当日交易 KPI(leg_deals 持久账本, UTC 今日)
    kpi={"trades":0,"lots":0.0,"net":0.0,"wins":0,"win_rate":None,"profit_main":0.0,"profit_hedge":0.0}
    try:
        day0=int(_dt.datetime.combine(_dt.datetime.utcnow().date(),_dt.time()).replace(tzinfo=_dt.timezone.utc).timestamp())
        c=db(); cur=c.cursor()
        cur.execute("""SELECT COUNT(*),COALESCE(SUM(profit+swap+commission),0),COALESCE(SUM(volume),0),
                       SUM(CASE WHEN profit>0 THEN 1 ELSE 0 END),
                       COALESCE(SUM(CASE WHEN leg='main' THEN profit ELSE 0 END),0),
                       COALESCE(SUM(CASE WHEN leg='hedge' THEN profit ELSE 0 END),0)
                       FROM leg_deals WHERE time_utc>=%s""",(day0,))
        r=cur.fetchone(); c.close()
        n=int(r[0] or 0); w=int(r[3] or 0)
        kpi={"trades":n,"net":round(float(r[1] or 0),2),"lots":round(float(r[2] or 0),2),"wins":w,
             "win_rate":(round(w*100.0/n,1) if n else None),
             "profit_main":round(float(r[4] or 0),2),"profit_hedge":round(float(r[5] or 0),2)}
    except Exception: pass
    # A2T 近24h 逐时桶(调用/402): 复用日计数不足以画趋势, 这里用小时键
    hourly=[]
    try:
        nowh=_dt.datetime.utcnow().replace(minute=0,second=0,microsecond=0)
        for i in range(23,-1,-1):
            h=(nowh-_dt.timedelta(hours=i)).strftime("%Y%m%d%H")
            def gh(kind):
                try: return int(R.get(RNS+"a2t:h:%s:%s"%(kind,h)) or 0)
                except Exception: return 0
            hourly.append({"h":(nowh-_dt.timedelta(hours=i)).strftime("%H:00"),"calls":gh("call"),"q402":gh("402")})
    except Exception: pass
    # 总控面板同款数据(qhadmin /dashboard 镜像; 直调 bi_overview/revenue/channels/members 纯读逻辑, 30天口径)
    dash=None
    try:
        ov=bi_overview(30)
        rv=revenue_report(30)
        ch=overview_channels(30)
        mem=admin_members("")
        ms={"total":len(mem["users"]),"paidLv":0,"pointsSum":0,"growthSum":0,"staffUsers":0,
            "byLevel":{str(k):0 for k in range(5)}}
        for u in mem["users"]:
            lv=int(u.get("member_level") or 0)
            ms["byLevel"][str(lv)]=ms["byLevel"].get(str(lv),0)+1
            if lv>=1: ms["paidLv"]+=1
            ms["pointsSum"]+=int(u.get("points") or 0); ms["growthSum"]+=int(u.get("growth_value") or 0)
            if u.get("staff_code"): ms["staffUsers"]+=1
        dash={"overview":ov,"rev_by_day":rv.get("by_day") or [],"channels":ch.get("channels") or {},"members":ms}
    except Exception as e:
        dash={"err":str(e)}
    return {"system":sysd,"kpi":kpi,"a2t_hourly":hourly,"dash":dash,"ts":_dt.datetime.utcnow().isoformat()}

class ReadSrcReq(BaseModel):
    license_key:str=""; read_source:str="a2t"
@app.post("/api/admin/system/read_source", dependencies=[Depends(require_op("system",danger=True))])
def system_set_read_source(r:ReadSrcReq):
    """切换读取数据源(a2t 纯云端 / bridge 桥优先回退)。状态机受控点: 记审计 + 清读取缓存。"""
    if r.read_source not in ("a2t","bridge"): raise HTTPException(400,"read_source 须为 a2t|bridge")
    R.set(RNS+"conn:read_source", r.read_source)
    try: _READ_SRC_CACHE["v"]=None; _READ_SRC_CACHE["ts"]=0.0; _A2T_RC.clear()
    except Exception: pass
    _audit("",_actor(r.license_key),"set_read_source",{"read_source":r.read_source},DEMO_MODE,r.read_source)
    return {"ok":True,"read_source":r.read_source}

# ---- 维护/系统全停 开关(与站内通知联动; require_op notify 同权限) ----
class MaintReq(BaseModel):
    license_key:str=""; on:bool=False; stop_strategy:bool=True; block_trading:bool=True; block_login:bool=False
    title:str="系统维护中"; msg:str=""; until:str=""
@app.get("/api/admin/notify/maintenance", dependencies=[Depends(require_op("notify"))])
def maint_get():
    return {"maintenance":_maint_get()}
@app.post("/api/admin/notify/maintenance", dependencies=[Depends(require_op("notify",danger=True))])
def maint_save(r:MaintReq):
    """保存维护态。开启+stop_strategy → 复用急停(全用户 auto off + global_estop);
       关闭维护**不自动解除 estop**(防误恢复真金策略, 需另点解除急停)。开启即自动落维护公告到跑马灯。"""
    now=_dt.datetime.now(_dt.timezone.utc)
    if r.on:
        m={"on":True,"stop_strategy":bool(r.stop_strategy),"block_trading":bool(r.block_trading),
           "block_login":bool(r.block_login),"title":(r.title or "系统维护中").strip(),
           "msg":(r.msg or "").strip(),"until":(r.until or "").strip(),
           "by":_actor(r.license_key),"ts":now.isoformat()}
        R.set(RNS+"maintenance", json.dumps(m))
        if r.stop_strategy:
            try:
                c=db(); cur=c.cursor(); cur.execute("SELECT username FROM users"); users=[x[0] for x in cur.fetchall()]; c.close()
                for u in users: R.set(RNS+"auto_entry:"+u,"off"); R.set(RNS+"auto_exit:"+u,"off")
                R.set(RNS+"global_estop","1")
            except Exception as e: print("maint estop err",e)
        # 维护公告落跑马灯(marquee_recent 兜底 + publish 实时)
        ann={"title":m["title"],"content":(m["msg"] or "系统维护中，部分功能暂停")+(("，预计恢复 "+m["until"]) if m["until"] else ""),
             "priority":3,"color":"#F56C6C","blink":True,"sound":"none","src":"maintenance","ts":now.isoformat()}
        try:
            R.publish(RNS+"notification:broadcast",json.dumps(ann))
            R.lpush(RNS+"marquee_recent",json.dumps(ann)); R.ltrim(RNS+"marquee_recent",0,49)
        except Exception: pass
        _audit("",_actor(r.license_key),"maintenance_on",m,DEMO_MODE,"on")
    else:
        R.delete(RNS+"maintenance")
        _audit("",_actor(r.license_key),"maintenance_off",{},DEMO_MODE,"off")
    return {"ok":True,"maintenance":_maint_get()}

@app.get("/api/admin/audit", dependencies=[Depends(require_op("system"))])
def admin_audit(limit:int=100, action:str=""):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q="""SELECT a.action,a.actor,a.demo_mode,a.result,a.ts, u.username
         FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE 1=1"""
    p=[]
    if action: q+=" AND a.action=%s"; p.append(action)
    q+=" ORDER BY a.ts DESC LIMIT %s"; p.append(limit)
    cur.execute(q,tuple(p)); rows=cur.fetchall(); c.close()
    return {"audit":[dict(r) for r in rows]}


class OpLogin(BaseModel):
    username:str; password:str
@app.post("/api/op/login")
def op_login(r:OpLogin, request: Request):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM operators WHERE username=%s",(r.username,)); o=cur.fetchone()
    if not o or not o["enabled"] or _pwd_hash(o["salt"],r.password)!=o["pwd_hash"]:
        c.close(); raise HTTPException(401,"用户名或密码错误")
    # IP 白名单(登录即校验)
    if (o["allowed_ips"] or "").strip():
        ip=_client_ip(request)
        if ip not in [x.strip() for x in o["allowed_ips"].split(",") if x.strip()]:
            c.close(); raise HTTPException(403,"IP 不在白名单: %s"%ip)
    cur.execute("UPDATE operators SET last_login=now() WHERE id=%s",(o["id"],)); c.close()
    tok=_secrets.token_hex(24)
    sess={"operator":o["username"],"role":o["role"],"allowed_ips":o["allowed_ips"],"enabled":True}
    R.setex(RNS+"opsess:"+tok, 43200, json.dumps(sess))   # 12h
    perms=_op_perms(o["role"])
    _op_log(sess,request,"op_login",{})
    return {"ok":True,"token":tok,"operator":o["username"],"role":o["role"],"perms":perms}

@app.post("/api/op/logout")
def op_logout(x_op_token: str = Header(default="")):
    if x_op_token: R.delete(RNS+"opsess:"+x_op_token)
    return {"ok":True}

@app.get("/api/op/me")
def op_me(x_op_token: str = Header(default=""), x_admin_token: str = Header(default="")):
    admin_token=_admin_token()
    if admin_token and x_admin_token==admin_token:
        return {"operator":"admintoken","role":"super","perms":"*"}
    s=_op_session(x_op_token)
    if not s: raise HTTPException(401,"未登录")
    return {"operator":s["operator"],"role":s["role"],"perms":_op_perms(s["role"])}

# Admin-only read adapters. User-facing routes keep strict license/subject binding;
# the operations console gets explicit permission-scoped cross-user views.
@app.get("/api/admin/engine/state", dependencies=[Depends(require_op("recon"))])
def admin_engine_state():
    eval_all=R.hgetall(RNS+"engine:eval") or {}
    eval_out={}
    for username, raw in eval_all.items():
        try: eval_out[username]=json.loads(raw)
        except Exception: eval_out[username]=raw
    return {
        "cycle": json.loads(R.get(RNS+"engine:cycle") or "null"),
        "market": _json_hash_state(RNS+"engine:market:user"),
        "account": _json_hash_state(RNS+"engine:account:user"),
        "divergence": _json_hash_state(RNS+"engine:divergence:user"),
        "errors": R.hgetall(RNS+"engine:err:user") or {},
        "eval": eval_out,
        "err": R.get(RNS+"engine:err"),
    }

@app.get("/api/admin/engine/legs", dependencies=[Depends(require_op("recon"))])
async def admin_engine_legs():
    return await engine_legs(username="")

@app.get("/api/admin/engine/alerts", dependencies=[Depends(require_op("system"))])
def admin_engine_alerts(limit:int=20):
    items=[]
    for raw in (R.lrange(RNS+"alerts",0,max(1,min(limit,200))-1) or []):
        try: items.append(json.loads(raw))
        except Exception: pass
    return {"alerts":items}

@app.get("/api/admin/deals/{username}", dependencies=[Depends(require_op("recon"))])
def admin_deals(username:str, limit:int=50):
    return deals(username,limit=max(1,min(limit,500)))

@app.get("/api/admin/params/{username}", dependencies=[Depends(require_op("params"))])
def admin_params(username:str):
    return params(username)

@app.get("/api/admin/sync/last", dependencies=[Depends(require_op("system"))])
def admin_sync_last():
    return sync_last()

@app.get("/api/admin/entitlements/{username}", dependencies=[Depends(require_op("iap"))])
def admin_entitlements(username:str):
    return get_entitlements(username)

# ---- 操作员管理(仅超管, 走 admin token 兜底或 super 角色) ----
class OperatorReq(BaseModel):
    license_key:str=""; username:str; password:str=""; role:str="viewer"; allowed_ips:str=""; enabled:bool=True
@app.post("/api/admin/operator/save", dependencies=[Depends(require_op("operators"))])
def operator_save(r:OperatorReq):
    c=db(); cur=c.cursor()
    cur.execute("SELECT id,salt,pwd_hash FROM operators WHERE username=%s",(r.username,)); ex=cur.fetchone()
    if ex:
        if r.password:
            salt=_secrets.token_hex(8); ph=_pwd_hash(salt,r.password)
            cur.execute("UPDATE operators SET role=%s,allowed_ips=%s,enabled=%s,salt=%s,pwd_hash=%s WHERE username=%s",(r.role,r.allowed_ips,r.enabled,salt,ph,r.username))
        else:
            cur.execute("UPDATE operators SET role=%s,allowed_ips=%s,enabled=%s WHERE username=%s",(r.role,r.allowed_ips,r.enabled,r.username))
    else:
        if not r.password: c.close(); raise HTTPException(400,"新建操作员需密码")
        salt=_secrets.token_hex(8); ph=_pwd_hash(salt,r.password)
        cur.execute("INSERT INTO operators(username,pwd_hash,salt,role,allowed_ips,enabled) VALUES(%s,%s,%s,%s,%s,%s)",(r.username,ph,salt,r.role,r.allowed_ips,r.enabled))
    c.close()
    _audit("",_actor(r.license_key),"operator_save",{"username":r.username,"role":r.role},DEMO_MODE,"saved")
    return {"ok":True,"username":r.username}

class OpResetPwd(BaseModel):
    license_key:str=""; username:str; password:str
@app.post("/api/admin/operator/reset_password", dependencies=[Depends(require_op("operators"))])
def operator_reset_password(r:OpResetPwd):
    """重置操作员登录密码(不改角色/IP/启用态)。"""
    if not r.password or len(r.password)<6: raise HTTPException(400,"新密码至少6位")
    c=db(); cur=c.cursor(); cur.execute("SELECT id FROM operators WHERE username=%s",(r.username,))
    if not cur.fetchone(): c.close(); raise HTTPException(404,"操作员不存在")
    salt=_secrets.token_hex(8); ph=_pwd_hash(salt,r.password)
    cur.execute("UPDATE operators SET salt=%s,pwd_hash=%s WHERE username=%s",(salt,ph,r.username)); c.close()
    _audit("",_actor(r.license_key),"operator_reset_pwd",{"username":r.username},DEMO_MODE,"done")
    return {"ok":True,"username":r.username}

class AdminTokenReset(BaseModel):
    license_key:str=""; new_token:str=""
@app.post("/api/admin/reset_admin_token", dependencies=[Depends(require_super)])
def reset_admin_token(r:AdminTokenReset):
    """重置超管令牌(仅超级管理员)。写 channels.json 的 admin.token 覆盖值, 运行时热生效, 无需重启。
       new_token 留空则随机生成。旧令牌立即失效, 当前会话请用新令牌重新登录。"""
    import secrets as _s
    newtok = r.new_token.strip() or ("QHADM-"+_s.token_hex(16))
    if len(newtok)<12: raise HTTPException(400,"令牌至少12位")
    cfg=_chcfg_load(); cfg.setdefault("admin",{})["token"]=newtok
    if not _chcfg_save(cfg): raise HTTPException(500,"写入失败(检查文件权限)")
    _audit("",_actor(r.license_key),"reset_admin_token",{"len":len(newtok)},DEMO_MODE,"done")
    return {"ok":True,"new_token":newtok,"note":"旧令牌已失效,请用新令牌重新登录"}

# ---- TRC20 收款配置(存 channels.json 的 pay 段) ----
@app.get("/api/admin/pay/config", dependencies=[Depends(require_op("orders"))])
def pay_config_get():
    p=_chcfg_load().get("pay",{})
    return {"trc20_address":p.get("trc20_address",""),"note":p.get("note","")}
class PayCfgReq(BaseModel):
    license_key:str=""; trc20_address:str=""; note:str=""
@app.post("/api/admin/pay/config", dependencies=[Depends(require_op("orders"))])
def pay_config_save(r:PayCfgReq):
    cfg=_chcfg_load(); pay=cfg.get("pay",{})
    if r.trc20_address!="": pay["trc20_address"]=r.trc20_address.strip()
    pay["note"]=r.note
    cfg["pay"]=pay
    if not _chcfg_save(cfg): raise HTTPException(500,"写入失败")
    _audit("",_actor(r.license_key),"pay_config",{"addr_set":bool(r.trc20_address)},DEMO_MODE,"saved")
    return {"ok":True}
@app.get("/api/pay/address")
def pay_address():
    """用户端公开读: 收款 TRC20 地址(前端生成二维码)。"""
    p=_chcfg_load().get("pay",{})
    return {"trc20_address":p.get("trc20_address",""),"note":p.get("note","")}

@app.get("/api/admin/operators", dependencies=[Depends(require_op("operators"))])
def operators_list():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT username,role,allowed_ips,enabled,last_login,created_at FROM operators ORDER BY created_at")
    ops=[dict(x) for x in cur.fetchall()]
    cur.execute("SELECT role,name,perms FROM operator_roles ORDER BY role"); roles=[dict(x) for x in cur.fetchall()]
    c.close()
    return {"operators":ops,"roles":roles}

class RoleReq(BaseModel):
    license_key:str=""; role:str; name:str=""; perms:str=""
@app.post("/api/admin/role/save", dependencies=[Depends(require_op("operators"))])
def role_save(r:RoleReq):
    if r.role=="super": raise HTTPException(400,"超级管理员角色不可改(始终全权限)")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO operator_roles(role,name,perms) VALUES(%s,%s,%s)
                   ON CONFLICT (role) DO UPDATE SET name=EXCLUDED.name,perms=EXCLUDED.perms""",(r.role,r.name,r.perms))
    c.close()
    _audit("",_actor(r.license_key),"role_save",{"role":r.role,"perms":r.perms},DEMO_MODE,"saved")
    return {"ok":True,"role":r.role}
class RoleDel(BaseModel):
    license_key:str=""; role:str
@app.post("/api/admin/role/del", dependencies=[Depends(require_op("operators"))])
def role_del(r:RoleDel):
    if r.role in ("super","viewer"): raise HTTPException(400,"内置角色不可删")
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM operator_roles WHERE role=%s",(r.role,)); c.close()
    return {"ok":True,"role":r.role}

@app.get("/api/admin/operator_audit", dependencies=[Depends(require_op("operators"))])
def operator_audit_list(limit:int=100):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT operator,role,ip,action,detail,ts FROM operator_audit ORDER BY ts DESC LIMIT %s",(limit,))
    rows=cur.fetchall(); c.close()
    return {"audit":[dict(r) for r in rows]}

# ================= P6 在线销售商机: 线索中台 + AI 客服 =================
def _kb_answer(site, text):
    """KB 简单匹配应答(关键词命中); 未命中回退引导留资。客服AI隔离, 绝不碰交易。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT kb,greeting FROM chat_config WHERE site=%s AND enabled=true",(site,)); cfg=cur.fetchone(); c.close()
    if not cfg: return "您好,请问有什么可以帮您?"
    kb=cfg["kb"] or []; t=(text or "").lower()
    for item in kb:
        q=(item.get("q") or "").lower()
        if q and q in t: return item.get("a") or ""
    return "已收到您的咨询,客服稍后联系您。如需快速对接,请留下联系方式(微信/手机)。"

# ---- 渠道适配: 各渠道 webhook 归一入 leads(此处统一入口, 各渠道验签在适配层各自实现) ----
class LeadIn(BaseModel):
    channel:str; ext_id:str=""; nickname:str=""; contact:str=""; content:str=""
    source_campaign:str=""; agent_code:str=""
@app.post("/api/lead/ingest")
def lead_ingest(r:LeadIn):
    """渠道消息归一入池 + AI 应答(独立站/双向渠道)。返回 AI 回复供渠道回传。"""
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM leads WHERE channel=%s AND ext_id=%s AND ext_id<>'' LIMIT 1",(r.channel,r.ext_id))
    row=cur.fetchone()
    if row: lead_id=row[0]; cur.execute("UPDATE leads SET updated_at=now() WHERE id=%s",(lead_id,))
    else:
        cur.execute("""INSERT INTO leads(channel,ext_id,nickname,contact,source_campaign,agent_code,status)
                       VALUES(%s,%s,%s,%s,%s,%s,'new') RETURNING id""",
                    (r.channel,r.ext_id,r.nickname,r.contact,r.source_campaign,r.agent_code or None))
        lead_id=cur.fetchone()[0]
    if r.content:
        cur.execute("INSERT INTO lead_messages(lead_id,direction,by_whom,content) VALUES(%s,'in','customer',%s)",(lead_id,r.content))
    c.close()
    ans=_kb_answer("qh", r.content) if r.content else ""
    if ans:
        c=db(); cur=c.cursor(); cur.execute("INSERT INTO lead_messages(lead_id,direction,by_whom,content) VALUES(%s,'out','ai',%s)",(lead_id,ans)); c.close()
    return {"ok":True,"lead_id":lead_id,"reply":ans}

@app.get("/api/admin/leads", dependencies=[Depends(require_op("leads"))])
def leads_list(status:str="", channel:str=""):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q="""SELECT l.id,l.channel,l.nickname,l.contact,l.status,l.owner_op,l.agent_code,l.source_campaign,l.converted_user,l.created_at,
                (SELECT count(*) FROM lead_messages m WHERE m.lead_id=l.id) AS msg_cnt FROM leads l WHERE 1=1"""
    p=[]
    if status: q+=" AND l.status=%s"; p.append(status)
    if channel: q+=" AND l.channel=%s"; p.append(channel)
    q+=" ORDER BY l.updated_at DESC LIMIT 300"
    cur.execute(q,tuple(p)); rows=cur.fetchall()
    cur.execute("""SELECT status,count(*) n FROM leads GROUP BY status"""); funnel={x["status"]:x["n"] for x in cur.fetchall()}
    c.close()
    return {"leads":[dict(r) for r in rows],"funnel":funnel}

@app.get("/api/admin/lead/{lead_id}", dependencies=[Depends(require_op("leads"))])
def lead_detail(lead_id:int):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE id=%s",(lead_id,)); l=cur.fetchone()
    if not l: c.close(); raise HTTPException(404,"lead not found")
    cur.execute("SELECT direction,by_whom,content,ts FROM lead_messages WHERE lead_id=%s ORDER BY ts",(lead_id,))
    msgs=[dict(x) for x in cur.fetchall()]; c.close()
    return {"lead":dict(l),"messages":msgs}

class LeadReply(BaseModel):
    license_key:str=""; lead_id:int; content:str; by_whom:str="operator"
@app.post("/api/admin/lead/reply", dependencies=[Depends(require_op("leads"))])
def lead_reply(r:LeadReply):
    c=db(); cur=c.cursor()
    cur.execute("INSERT INTO lead_messages(lead_id,direction,by_whom,content) VALUES(%s,'out',%s,%s)",(r.lead_id,r.by_whom,r.content))
    cur.execute("UPDATE leads SET status='contacted',updated_at=now() WHERE id=%s AND status='new'",(r.lead_id,))
    c.close()
    return {"ok":True}

class LeadConvert(BaseModel):
    license_key:str=""; lead_id:int; action:str        # trial/convert/lost
    username:str=""; days:int=7
@app.post("/api/admin/lead/convert", dependencies=[Depends(require_op("leads"))])
def lead_convert(r:LeadConvert):
    """线索→试用/转化/流失, 接死现有链路(试用走 trial, 绑代理/渠道 source)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM leads WHERE id=%s",(r.lead_id,)); lead=cur.fetchone()
    if not lead: c.close(); raise HTTPException(404,"lead not found")
    if r.action=="lost":
        cur.execute("UPDATE leads SET status='lost',updated_at=now() WHERE id=%s",(r.lead_id,)); c.close()
        return {"ok":True,"status":"lost"}
    # trial/convert 需绑定 user
    uname=r.username or lead.get("converted_user")
    if not uname: c.close(); raise HTTPException(400,"需指定 username(线索转化绑定用户)")
    uid=_uid(uname)
    if not uid: c.close(); raise HTTPException(404,"user not found(请先建用户)")
    # 绑渠道来源 + 代理(分佣归因)
    if lead.get("agent_code"):
        cur.execute("SELECT id FROM agents WHERE code=%s",(lead["agent_code"],)); ag=cur.fetchone()
        if ag: cur.execute("UPDATE users SET agent_id=%s,source=%s WHERE id=%s",(ag["id"],lead["channel"],uid))
    else:
        cur.execute("UPDATE users SET source=%s WHERE id=%s",(lead["channel"],uid))
    new_status = "trial" if r.action=="trial" else "converted"
    cur.execute("UPDATE leads SET status=%s,converted_user=%s,updated_at=now() WHERE id=%s",(new_status,uname,r.lead_id))
    c.close()
    # 试用走已建 trial 逻辑(强制 DEMO)
    if r.action=="trial":
        now=datetime.datetime.now(datetime.timezone.utc); until=now+datetime.timedelta(days=max(1,r.days))
        c=db(); cur=c.cursor(); cur.execute("UPDATE users SET trial_until=%s,trial_started=%s,status='trial' WHERE id=%s",(until,now,uid)); c.close()
        R.set(RNS+"force_demo:"+uname,"1")
    _audit(uname,_actor(r.license_key),"lead_convert",{"lead":r.lead_id,"action":r.action,"channel":lead["channel"]},DEMO_MODE,new_status)
    return {"ok":True,"status":new_status,"username":uname}

class LeadAssign(BaseModel):
    license_key:str=""; lead_id:int; owner_op:str="" ; agent_code:str=""
@app.post("/api/admin/lead/assign", dependencies=[Depends(require_op("leads"))])
def lead_assign(r:LeadAssign):
    """指派线索: owner_op(操作员归属)+/或 agent_code(代理归属, 用于分佣)。"""
    c=db(); cur=c.cursor()
    sets=[]; vals=[]
    if r.owner_op!="": sets.append("owner_op=%s"); vals.append(r.owner_op or None)
    if r.agent_code!="": sets.append("agent_code=%s"); vals.append(r.agent_code or None)
    if not sets: c.close(); raise HTTPException(400,"需 owner_op 或 agent_code")
    sets.append("updated_at=now()"); vals.append(r.lead_id)
    cur.execute("UPDATE leads SET "+",".join(sets)+" WHERE id=%s",tuple(vals)); c.close()
    _audit("",_actor(r.license_key),"lead_assign",{"lead":r.lead_id,"owner_op":r.owner_op,"agent":r.agent_code},DEMO_MODE,"done")
    return {"ok":True}

class LeadSetStatus(BaseModel):
    license_key:str=""; lead_id:int; status:str        # new/contacted/trial/converted/lost
@app.post("/api/admin/lead/set_status", dependencies=[Depends(require_op("leads"))])
def lead_set_status(r:LeadSetStatus):
    """通用状态流转(标记已联系 new→contacted / 重新激活 lost→new 等), 不做转化绑定。"""
    if r.status not in ("new","contacted","trial","converted","lost"):
        raise HTTPException(400,"非法状态: %s"%r.status)
    c=db(); cur=c.cursor()
    cur.execute("UPDATE leads SET status=%s,updated_at=now() WHERE id=%s",(r.status,r.lead_id)); c.close()
    _audit("",_actor(r.license_key),"lead_set_status",{"lead":r.lead_id,"status":r.status},DEMO_MODE,r.status)
    return {"ok":True,"status":r.status}

class LeadNote(BaseModel):
    license_key:str=""; lead_id:int; note:str
@app.post("/api/admin/lead/note", dependencies=[Depends(require_op("leads"))])
def lead_note(r:LeadNote):
    """内部跟进备注(与对话分离, 私有)。"""
    c=db(); cur=c.cursor()
    cur.execute("UPDATE leads SET note=%s,updated_at=now() WHERE id=%s",(r.note,r.lead_id)); c.close()
    return {"ok":True}

# ---- AI 客服知识库配置(admin) ----
class ChatCfg(BaseModel):
    license_key:str=""; site:str="qh"; greeting:str=""; kb:list=[]; enabled:bool=True
@app.post("/api/admin/chat/config", dependencies=[Depends(require_op("chat"))])
def chat_config_save(r:ChatCfg):
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO chat_config(site,greeting,kb,enabled,updated_at) VALUES(%s,%s,%s,%s,now())
                   ON CONFLICT (site) DO UPDATE SET greeting=EXCLUDED.greeting,kb=EXCLUDED.kb,enabled=EXCLUDED.enabled,updated_at=now()""",
                (r.site,r.greeting,json.dumps(r.kb),r.enabled))
    c.close()
    return {"ok":True,"site":r.site,"kb_count":len(r.kb)}
@app.get("/api/chat/config")
def chat_config_get(site:str="qh"):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT site,greeting,kb,enabled FROM chat_config WHERE site=%s",(site,)); r=cur.fetchone(); c.close()
    return dict(r) if r else {"site":site,"greeting":"您好","kb":[],"enabled":True}

# ---- 官网/介绍站 内容配置(site_config, admin可改; 与chat_config同层, 绝不碰引擎) ----
# 消费端: qh(顶栏LOGO/标题/官网按钮URL) + qhwww(介绍站全量, P2). 各站按 site 硬隔离。
_SITE_DEFAULT={
  "qh":{"brand":{"platformName":"Quant Hedge","title":"【Quant Hedge】对冲工具软件","logo":"QHEDGELOGO-s-single.ico"},
        "officialUrl":"https://app.hustle2026.xyz"},
  # qhadmin 运营后台侧栏品牌(消费端 qhadmin Layout.vue; logo 支持 URL 或 data:image base64)
  "qhadmin":{"brand":{"title":"Quant Hedge","logo":"/logo-white.png","loginTitle":"QUANT HEDGE","docTitle":"QH 运营后台"}},
  "qhwww":{"brand":{"platformName":"Quant Hedge","logo":""},
    "nav":[{"name":"核心功能","anchor":"#features"},{"name":"多端登录","anchor":"#devices"},
           {"name":"AI 套利分析","anchor":"#ai"},{"name":"会员权益","anchor":"#member"},
           {"name":"积分邀请","anchor":"#rewards"},{"name":"版本授权","anchor":"#plans"}],
    "hero":{"title":"把专业对冲量化","subtitle":"一套系统，覆盖对冲套利全流程","tagline":""},
    "sections":{"features":"核心功能","devices":"多端登录","ai":"AI 套利分析",
                "member":"会员权益","rewards":"积分邀请","plans":"版本授权"},
    "buttons":[{"key":"download","label":"⬇ 下载 Windows 客户端","url":"/QuantHedge-Setup-1.1.0.exe"},
               {"key":"login","label":"登录控制台","url":"https://qh.hustle2026.xyz"},
               {"key":"learn","label":"了解核心功能","url":"#features"}],
    "downloads":[{"os":"Windows","label":"QuantHedge-Setup-1.1.0.exe","url":"/QuantHedge-Setup-1.1.0.exe","ver":"1.1.0"}],
    "footer":{"email":"support@hustle2026.xyz","qq":"000000000","phone":"+86 000-0000-0000",
              "copyright":"© 2026 Quant Hedge　保留所有权利 All Rights Reserved",
              "icp":"浙ICP备 0000000000 号-0","icpUrl":"https://beian.miit.gov.cn","police":"浙公网安备 00000000000000 号",
              "qrs":{"wechatOA":"","wechatMini":"","douyin":"","kuaishou":""},
              "agreementTitle":"软件服务协议","agreementHtml":""}}
}
class SiteCfg(BaseModel):
    license_key:str=""; site:str="qh"; cfg:dict={}
@app.post("/api/admin/site/save", dependencies=[Depends(require_op("sitemgr"))])
def site_config_save(r:SiteCfg):
    if r.site not in ("qh","qhwww","qhadmin"): raise HTTPException(400,"site 须为 qh|qhwww|qhadmin")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO site_config(site,cfg,updated_at) VALUES(%s,%s,now())
                   ON CONFLICT (site) DO UPDATE SET cfg=EXCLUDED.cfg,updated_at=now()""",(r.site,json.dumps(r.cfg)))
    c.close()
    return {"ok":True,"site":r.site}
@app.get("/api/site/config")
def site_config_get(site:str="qh"):
    """公开只读: 官网/介绍站展示配置(已发布 live 版, 无敏感信息)。缺省回落内置默认。"""
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT cfg FROM site_config WHERE site=%s",(site,)); r=cur.fetchone(); c.close()
        if r and r.get("cfg"): return {"site":site,"cfg":r["cfg"]}
    except Exception: pass
    return {"site":site,"cfg":_SITE_DEFAULT.get(site,{})}

# ---- 草稿 / 发布 / 回滚(防手滑改崩官网; cfg=live·draft=草稿·versions=历史) ----
@app.post("/api/admin/site/draft", dependencies=[Depends(require_op("sitemgr"))])
def site_draft_save(r:SiteCfg):
    if r.site not in ("qh","qhwww","qhadmin"): raise HTTPException(400,"bad site")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO site_config(site,cfg,draft,updated_at) VALUES(%s,'{}'::jsonb,%s,now())
                   ON CONFLICT (site) DO UPDATE SET draft=EXCLUDED.draft,updated_at=now()""",(r.site,json.dumps(r.cfg)))
    c.close(); return {"ok":True,"site":r.site}
@app.get("/api/admin/site/draft", dependencies=[Depends(require_op("sitemgr"))])
def site_draft_get(site:str="qh"):
    """管理端编辑用: 优先取草稿, 无草稿回落 live(cfg), 再回落默认。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT cfg,draft FROM site_config WHERE site=%s",(site,)); r=cur.fetchone(); c.close()
    dflt=_SITE_DEFAULT.get(site,{})
    if not r: return {"site":site,"live":dflt,"draft":None,"has_draft":False}
    return {"site":site,"live":(r.get("cfg") or dflt),"draft":r.get("draft"),"has_draft":bool(r.get("draft"))}
@app.post("/api/admin/site/publish", dependencies=[Depends(require_op("sitemgr"))])
def site_publish(r:SiteCfg):
    """发布: 当前 live 存入历史 → (传入cfg 或 现有draft)成为 live, 清草稿。"""
    if r.site not in ("qh","qhwww","qhadmin"): raise HTTPException(400,"bad site")
    c=db(); cur=c.cursor()
    cur.execute("SELECT cfg,draft FROM site_config WHERE site=%s",(r.site,)); row=cur.fetchone()
    if row and row[0]: cur.execute("INSERT INTO site_config_versions(site,cfg) VALUES(%s,%s)",(r.site,json.dumps(row[0])))
    newcfg = r.cfg if r.cfg else ((row[1] if (row and row[1]) else {}) )
    cur.execute("""INSERT INTO site_config(site,cfg,draft,updated_at) VALUES(%s,%s,NULL,now())
                   ON CONFLICT (site) DO UPDATE SET cfg=EXCLUDED.cfg,draft=NULL,updated_at=now()""",(r.site,json.dumps(newcfg)))
    c.close(); return {"ok":True,"site":r.site}
@app.get("/api/admin/site/versions", dependencies=[Depends(require_op("sitemgr"))])
def site_versions(site:str="qh", limit:int=20):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,published_at FROM site_config_versions WHERE site=%s ORDER BY id DESC LIMIT %s",(site,min(limit,100)))
    rows=cur.fetchall(); c.close()
    return {"site":site,"versions":[{"id":x["id"],"ts":x["published_at"].isoformat()} for x in rows]}
class SiteRollback(BaseModel):
    license_key:str=""; site:str="qh"; version_id:int
@app.post("/api/admin/site/rollback", dependencies=[Depends(require_op("sitemgr"))])
def site_rollback(r:SiteRollback):
    c=db(); cur=c.cursor()
    cur.execute("SELECT cfg FROM site_config_versions WHERE id=%s AND site=%s",(r.version_id,r.site)); v=cur.fetchone()
    if not v: c.close(); raise HTTPException(404,"版本不存在")
    cur.execute("SELECT cfg FROM site_config WHERE site=%s",(r.site,)); old=cur.fetchone()
    if old and old[0]: cur.execute("INSERT INTO site_config_versions(site,cfg) VALUES(%s,%s)",(r.site,json.dumps(old[0])))
    cur.execute("UPDATE site_config SET cfg=%s,draft=NULL,updated_at=now() WHERE site=%s",(json.dumps(v[0]),r.site))
    c.close(); return {"ok":True,"site":r.site,"rolled_to":r.version_id}

# ================= AI 客服 LLM 服务(复刻 coinadmin ai-support; 完全隔离交易引擎) =================
# 安全边界: 独立表(ai_config/ai_conversations/ai_messages) + 独立 httpx 出站 + 独立端点;
#          绝不 import 引擎/不碰 CONN/交易 Redis 键。各站(qh/qhwww/qhadmin)按 site 硬隔离不串。
_AI_DEFAULT={"id":0,"provider":"claude","api_key":"","base_url":"","model_name":"claude-sonnet-4-6",
             "temperature":0.7,"max_tokens":2000,"system_prompt":"","is_enabled":False,"rate_limit_per_min":10}
def _ai_get_config(site):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM ai_config WHERE site=%s",(site,)); r=cur.fetchone(); c.close()
    if not r: return {**_AI_DEFAULT,"site":site}
    return dict(r)

class AiConfigReq(BaseModel):
    license_key:str=""; site:str="qh"
    provider:Optional[str]=None; api_key:Optional[str]=None; base_url:Optional[str]=None
    model_name:Optional[str]=None; temperature:Optional[float]=None; max_tokens:Optional[int]=None
    system_prompt:Optional[str]=None; is_enabled:Optional[bool]=None; rate_limit_per_min:Optional[int]=None

@app.get("/api/admin/ai/config", dependencies=[Depends(require_op("chat"))])
def ai_config_get(site:str="qh"):
    cfg=_ai_get_config(site)
    return {**cfg,"site":site}

@app.post("/api/admin/ai/config", dependencies=[Depends(require_op("chat"))])
def ai_config_save(r:AiConfigReq):
    cur_cfg=_ai_get_config(r.site)
    merged={k:(getattr(r,k) if getattr(r,k) is not None else cur_cfg.get(k)) for k in
            ("provider","api_key","base_url","model_name","temperature","max_tokens","system_prompt","is_enabled","rate_limit_per_min")}
    if merged.get("base_url"): merged["base_url"]=str(merged["base_url"]).rstrip("/")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO ai_config(site,provider,api_key,base_url,model_name,temperature,max_tokens,system_prompt,is_enabled,rate_limit_per_min,updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (site) DO UPDATE SET provider=EXCLUDED.provider,api_key=EXCLUDED.api_key,base_url=EXCLUDED.base_url,
                     model_name=EXCLUDED.model_name,temperature=EXCLUDED.temperature,max_tokens=EXCLUDED.max_tokens,
                     system_prompt=EXCLUDED.system_prompt,is_enabled=EXCLUDED.is_enabled,rate_limit_per_min=EXCLUDED.rate_limit_per_min,updated_at=now()""",
                (r.site,merged["provider"],merged["api_key"],merged["base_url"],merged["model_name"],
                 merged["temperature"],merged["max_tokens"],merged["system_prompt"],merged["is_enabled"],merged["rate_limit_per_min"]))
    c.close()
    return {"ok":True,"site":r.site,"msg":"AI 服务配置已保存"}

def _ai_call_llm(cfg, history):
    """调用大模型(claude/openai 兼容). history=[{role,content}...]. 返回 (text, tokens). 失败抛异常。
       独立 httpx 出站, 8~40s 超时; 支持中转 base_url。"""
    provider=(cfg.get("provider") or "claude").lower()
    key=cfg.get("api_key") or ""; base=(cfg.get("base_url") or "").rstrip("/")
    model=cfg.get("model_name") or "claude-sonnet-4-6"
    temp=float(cfg.get("temperature") or 0.7); maxtok=int(cfg.get("max_tokens") or 2000)
    sysp=cfg.get("system_prompt") or ""
    if not key: raise HTTPException(400,"AI 服务未配置 API Key")
    if provider=="openai":
        url=(base or "https://api.openai.com")+"/v1/chat/completions"
        msgs=([{"role":"system","content":sysp}] if sysp else [])+history
        body={"model":model,"messages":msgs,"temperature":temp,"max_tokens":maxtok}
        headers={"Authorization":"Bearer "+key,"Content-Type":"application/json"}
        with _httpx.Client(timeout=40) as cl:
            resp=cl.post(url,json=body,headers=headers); resp.raise_for_status(); j=resp.json()
        text=j["choices"][0]["message"]["content"]; tok=(j.get("usage") or {}).get("total_tokens",0)
        return text,int(tok or 0)
    else:  # claude(anthropic)
        url=(base or "https://api.anthropic.com")+"/v1/messages"
        body={"model":model,"max_tokens":maxtok,"temperature":temp,"messages":history}
        if sysp: body["system"]=sysp
        headers={"x-api-key":key,"anthropic-version":"2023-06-01","Content-Type":"application/json"}
        with _httpx.Client(timeout=40) as cl:
            resp=cl.post(url,json=body,headers=headers); resp.raise_for_status(); j=resp.json()
        text="".join(b.get("text","") for b in (j.get("content") or []) if b.get("type")=="text")
        us=j.get("usage") or {}; tok=int(us.get("input_tokens",0))+int(us.get("output_tokens",0))
        return text,tok

class AiChatReq(BaseModel):
    site:str="qh"; conversation_id:Optional[int]=None; message:str; user_id:str=""

@app.post("/api/ai/chat")
def ai_chat(r:AiChatReq, request:Request):
    """公开: 用户发消息 → LLM 回复(带会话上下文+落库+限频)。未启用则回退 KB 关键词。site 隔离。"""
    cfg=_ai_get_config(r.site)
    uid=r.user_id or _client_ip(request) or "anon"
    if not cfg.get("is_enabled"):
        # 未接大模型 → 回退关键词知识库(与旧 chat 一致)
        return {"reply":_kb_answer(r.site if r.site in ("qh","app","site") else "qh", r.message),"llm":False}
    # 限频: 按 site+uid 每分钟
    rl=int(cfg.get("rate_limit_per_min") or 10)
    rk=RNS+"ai:rl:%s:%s"%(r.site,uid)
    used=R.incr(rk);
    if used==1: R.expire(rk,60)
    if used>rl: raise HTTPException(429,"提问太频繁, 请稍后再试")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    # 会话: 复用或新建
    conv_id=r.conversation_id
    if conv_id:
        cur.execute("SELECT id FROM ai_conversations WHERE id=%s AND site=%s",(conv_id,r.site))
        if not cur.fetchone(): conv_id=None
    if not conv_id:
        cur.execute("INSERT INTO ai_conversations(site,user_id,title) VALUES(%s,%s,%s) RETURNING id",
                    (r.site,uid,(r.message or "")[:40]))
        conv_id=cur.fetchone()["id"]
    # 取历史(最近 10 条)构造上下文
    cur.execute("SELECT role,content FROM ai_messages WHERE conversation_id=%s ORDER BY id DESC LIMIT 10",(conv_id,))
    hist=[{"role":x["role"],"content":x["content"]} for x in reversed(cur.fetchall())]
    hist.append({"role":"user","content":r.message})
    cur.execute("INSERT INTO ai_messages(conversation_id,role,content) VALUES(%s,'user',%s)",(conv_id,r.message))
    c.connection.commit() if hasattr(c,"connection") else None
    try:
        text,tok=_ai_call_llm(cfg,hist)
    except HTTPException:
        c.close(); raise
    except Exception as e:
        c.close(); raise HTTPException(502,"AI 服务调用失败: "+str(e)[:120])
    cur.execute("INSERT INTO ai_messages(conversation_id,role,content,tokens) VALUES(%s,'assistant',%s,%s)",(conv_id,text,tok))
    cur.execute("UPDATE ai_conversations SET token_used=token_used+%s,updated_at=now() WHERE id=%s",(tok,conv_id))
    c.close()
    return {"reply":text,"conversation_id":conv_id,"tokens":tok,"llm":True}

@app.get("/api/admin/ai/stats", dependencies=[Depends(require_op("chat"))])
def ai_stats(site:str=""):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    w=" WHERE site=%s" if site else ""; p=((site,) if site else ())
    cur.execute("SELECT count(*) n, COALESCE(SUM(token_used),0) tok FROM ai_conversations"+w,p); conv=cur.fetchone()
    mw=" WHERE c.site=%s" if site else ""
    cur.execute("SELECT count(*) n FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id"+mw,p); msg=cur.fetchone()
    cur.execute("SELECT count(*) n FROM ai_messages m JOIN ai_conversations c ON c.id=m.conversation_id"+
                (mw+" AND " if site else " WHERE ")+"m.created_at>=date_trunc('day',now())",p); today=cur.fetchone()
    c.close()
    return {"total_conversations":conv["n"],"total_messages":msg["n"],"today_messages":today["n"],"total_tokens":int(conv["tok"] or 0)}

@app.get("/api/admin/ai/conversations", dependencies=[Depends(require_op("chat"))])
def ai_conversations(site:str="", limit:int=50):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    w=" WHERE site=%s" if site else ""; p=((site,max(1,min(limit,200))) if site else (max(1,min(limit,200)),))
    cur.execute("""SELECT c.id,c.site,c.user_id,c.title,c.token_used,c.updated_at,
                          (SELECT count(*) FROM ai_messages m WHERE m.conversation_id=c.id) message_count
                   FROM ai_conversations c"""+w+" ORDER BY c.updated_at DESC LIMIT %s",p)
    rows=cur.fetchall(); c.close()
    return {"conversations":[dict(x) for x in rows]}

@app.get("/api/admin/ai/conversation/{cid}/messages", dependencies=[Depends(require_op("chat"))])
def ai_conv_messages(cid:int):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT role,content,tokens,created_at FROM ai_messages WHERE conversation_id=%s ORDER BY id",(cid,))
    rows=cur.fetchall(); c.close()
    return {"messages":[dict(x) for x in rows]}


@app.get("/api/admin/channels", dependencies=[Depends(require_op("chat"))])
def channels_list():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT key,name,kind,enabled,sort FROM channels ORDER BY sort"); rows=cur.fetchall(); c.close()
    return {"channels":[dict(r) for r in rows]}

# ================= 渠道 webhook 适配器 (验签 + token 刷新; 凭证走 systemd env) =================
# env 命名约定: QH_<CH>_TOKEN / QH_<CH>_AESKEY / QH_<CH>_APPID / QH_<CH>_SECRET (CH=FEISHU/WECOM/MPWX/MINIAPP)
# 配置优先级: app 自管文件 channels.json(600, 离库离git, 运行时热读, 改后无需重启) > systemd env(回退)
_CHCFG_PATH=os.environ.get("QH_CHCFG_PATH","/opt/quanthedge/channels.json")
def _chcfg_load():
    try:
        with open(_CHCFG_PATH,encoding="utf-8") as f: return json.load(f)
    except Exception: return {}
def _chcfg_save(d):
    try:
        with open(_CHCFG_PATH,"w",encoding="utf-8") as f: json.dump(d,f)
        try: os.chmod(_CHCFG_PATH,0o600)
        except Exception: pass
        return True
    except Exception as e: print("chcfg_save err",e); return False
def _chenv(ch, key, default=""):
    cfg=_chcfg_load().get(ch.lower(),{})
    v=cfg.get(key.lower())
    if v: return v
    return os.environ.get("QH_%s_%s"%(ch.upper(),key.upper()), default)
def _lead_from_channel(channel, ext_id, content, nickname=""):
    """渠道消息归一入 leads(复用 lead_ingest 逻辑, 内部直调)。"""
    try:
        return lead_ingest(LeadIn(channel=channel, ext_id=ext_id, content=content, nickname=nickname))
    except Exception as e:
        print("lead_from_channel err",e); return {"ok":False}

async def _wx_access_token(ch):
    """微信公众号/小程序 access_token(2h 时效, Redis 缓存)。ch=mp_wx/miniapp。"""
    ck=RNS+"wxtoken:"+ch; cached=R.get(ck)
    if cached: return cached
    appid=_chenv(ch,"APPID"); secret=_chenv(ch,"SECRET")
    if not appid or not secret: return ""
    try:
        async with __import__("httpx").AsyncClient(timeout=8) as cl:
            r=await cl.get("https://api.weixin.qq.com/cgi-bin/token",params={"grant_type":"client_credential","appid":appid,"secret":secret})
            j=r.json(); tok=j.get("access_token")
            if tok: R.setex(ck, max(60,int(j.get("expires_in",7200))-300), tok); return tok
    except Exception as e: R.set(RNS+"wxtoken_err:"+ch,str(e))
    return ""

# ---- 微信公众号/小程序: GET 校验(echostr) + POST 消息(签名 sha1(token,ts,nonce)) ----
@app.get("/api/webhook/{ch}")
def wh_verify(ch:str, signature:str="", timestamp:str="", nonce:str="", echostr:str=""):
    tok=_chenv(ch,"TOKEN")
    if not tok: raise HTTPException(503,"渠道 %s 未配置 TOKEN(systemd env)"%ch)
    s="".join(sorted([tok,timestamp,nonce]))
    if hashlib.sha1(s.encode()).hexdigest()==signature:
        return PlainResponse(echostr)
    raise HTTPException(403,"签名校验失败")

from fastapi.responses import PlainTextResponse as PlainResponse
@app.post("/api/webhook/{ch}")
async def wh_message(ch:str, request: Request, signature:str="", timestamp:str="", nonce:str=""):
    """统一 webhook 入口: 验签 → 解析 → 归一入 leads。各渠道报文不同, 此处覆盖常见(微信XML/飞书JSON)。"""
    tok=_chenv(ch,"TOKEN")
    if tok and signature:
        s="".join(sorted([tok,timestamp,nonce]))
        if hashlib.sha1(s.encode()).hexdigest()!=signature:
            raise HTTPException(403,"签名校验失败")
    body=await request.body()
    ext_id=""; content=""; nickname=""
    ctype=request.headers.get("content-type","")
    try:
        if "xml" in ctype or body.strip().startswith(b"<"):   # 微信公众号/小程序 XML
            import re as _re
            def _x(tag):
                m=_re.search((r"<%s><!\[CDATA\[(.*?)\]\]></%s>"%(tag,tag)).encode(),body,_re.S) or _re.search((r"<%s>(.*?)</%s>"%(tag,tag)).encode(),body,_re.S)
                return m.group(1).decode() if m else ""
            ext_id=_x("FromUserName"); content=_x("Content")
        else:                                                  # 飞书/企微 JSON
            j=json.loads(body or b"{}")
            if j.get("type")=="url_verification": return {"challenge":j.get("challenge")}  # 飞书回调验证
            ev=j.get("event",j)
            ext_id=str(ev.get("open_id") or ev.get("user_id") or ev.get("FromUserName") or ev.get("from",{}).get("open_id") or "")
            content=str(ev.get("text") or (ev.get("message",{}) or {}).get("content") or ev.get("Content") or "")
    except Exception as e:
        R.set(RNS+"wh_err:"+ch,str(e))
    if ext_id and content:
        res=_lead_from_channel(ch, ext_id, content, nickname)
        # 微信需 XML 回复; 这里简化为 success(被动回复可后续补), 飞书/企微返回 JSON
        if "xml" in ctype or body.strip().startswith(b"<"):
            return PlainResponse("success")
        return {"ok":True,"reply":res.get("reply") if isinstance(res,dict) else None}
    return PlainResponse("success") if ("xml" in ctype or body.strip().startswith(b"<")) else {"ok":True}

@app.get("/api/admin/channel/token_status", dependencies=[Depends(require_op("chat"))])
def channel_token_status():
    """各渠道凭证配置 + token 缓存状态 + 回调URL(不回显密钥, 只显是否已配)。"""
    base=os.environ.get("QH_PUBLIC_BASE","https://qh.hustle2026.xyz")
    meta={"feishu":{"name":"飞书","fields":["token","appid","secret"]},
          "wecom":{"name":"企业微信","fields":["token","aeskey","secret"]},
          "mp_wx":{"name":"微信公众号","fields":["token","appid","secret"]},
          "miniapp":{"name":"微信小程序","fields":["token","appid","secret"]}}
    out={}
    for ch,m in meta.items():
        out[ch]={"name":m["name"],"callback":base+"/api/webhook/"+ch,
                 "fields":{f:bool(_chenv(ch,f)) for f in m["fields"]},
                 "cached_token":bool(R.get(RNS+"wxtoken:"+ch))}
    return out

class ChannelCfgReq(BaseModel):
    license_key:str=""; channel:str; token:str=""; appid:str=""; secret:str=""; aeskey:str=""
@app.post("/api/admin/channel/config", dependencies=[Depends(require_op("chat"))])
def channel_config_save(r:ChannelCfgReq):
    """保存渠道凭证到 app 自管文件(600权限, 运行时热读, 无需重启; 留空字段=不改)。"""
    if r.channel not in ("feishu","wecom","mp_wx","miniapp"): raise HTTPException(400,"未知渠道")
    cfg=_chcfg_load(); ch=cfg.get(r.channel,{})
    for k in ("token","appid","secret","aeskey"):
        v=getattr(r,k,"")
        if v: ch[k]=v                      # 仅非空覆盖(留空=保留原值)
    cfg[r.channel]=ch
    if not _chcfg_save(cfg): raise HTTPException(500,"配置写入失败(检查文件权限)")
    R.delete(RNS+"wxtoken:"+r.channel)     # 改密钥→清 token 缓存, 下次重取
    _audit("",_actor(r.license_key),"channel_config",{"channel":r.channel,"fields":[k for k in ("token","appid","secret","aeskey") if getattr(r,k,"")]},DEMO_MODE,"saved")
    return {"ok":True,"channel":r.channel}

# ================= P2-5 系统通知(飞书出站 + 邮件 + 模板 + 跑马灯) =================
import httpx as _httpx
def _feishu_token():
    """飞书 tenant_access_token(复用 channels.json 的 feishu APPID/SECRET, Redis 缓存 100 分钟)。"""
    ck=RNS+"feishu_tok"; cached=R.get(ck)
    if cached: return {"ok":True,"token":cached}
    aid=_chenv("feishu","APPID"); sec=_chenv("feishu","SECRET")
    if not aid or not sec: return {"ok":False,"error":"飞书 APPID/SECRET 未配置(客服配置页填写)"}
    try:
        resp=_httpx.post("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                         json={"app_id":aid,"app_secret":sec},timeout=10)
        d=resp.json()
        if d.get("code")!=0: return {"ok":False,"error":d.get("msg","获取token失败")}
        tok=d["tenant_access_token"]; R.setex(ck,6000,tok)
        return {"ok":True,"token":tok}
    except Exception as e: return {"ok":False,"error":str(e)}
def _feishu_resolve_phone(token,phone):
    if not phone.startswith("+"): phone="+86"+phone
    try:
        r=_httpx.post("https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id",
                      params={"user_id_type":"open_id"},headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
                      json={"mobiles":[phone]},timeout=10); d=r.json()
        if d.get("code")!=0: return {"ok":False,"error":d.get("msg","解析失败")}
        ul=d.get("data",{}).get("user_list",[])
        if not ul or not ul[0].get("user_id"): return {"ok":False,"error":"未找到手机号 %s 对应飞书用户"%phone}
        return {"ok":True,"open_id":ul[0]["user_id"]}
    except Exception as e: return {"ok":False,"error":str(e)}
def _feishu_send_card(token, receive_id, title, content, color="blue"):
    rt = "open_id" if receive_id.startswith("ou_") else ("email" if "@" in receive_id else "open_id")
    if rt=="open_id" and receive_id.replace("+","").isdigit():
        lk=_feishu_resolve_phone(token,receive_id)
        if not lk["ok"]: return {"ok":False,"error":lk["error"]}
        receive_id=lk["open_id"]
    card={"config":{"wide_screen_mode":True},
          "header":{"title":{"tag":"plain_text","content":title},"template":color},
          "elements":[{"tag":"div","text":{"tag":"lark_md","content":content}},
                      {"tag":"hr"},{"tag":"note","elements":[{"tag":"plain_text","content":"🔔 Quant Hedge 量化系统"}]}]}
    try:
        r=_httpx.post("https://open.feishu.cn/open-apis/im/v1/messages",params={"receive_id_type":rt},
                      headers={"Authorization":"Bearer "+token,"Content-Type":"application/json"},
                      json={"receive_id":receive_id,"msg_type":"interactive","content":json.dumps(card)},timeout=10)
        b=r.json()
        if b.get("code")==0: return {"ok":True,"message_id":b.get("data",{}).get("message_id")}
        return {"ok":False,"error":b.get("msg","发送失败")}
    except Exception as e: return {"ok":False,"error":str(e)}
def _notif_log(name,channel,status,content="",recipient=""):
    try:
        c=db(); cur=c.cursor(); cur.execute("INSERT INTO notification_logs(template_name,channel,recipient,status,content) VALUES(%s,%s,%s,%s,%s)",(name,channel,recipient,status,content)); c.close()
    except Exception as e: print("notif_log err",e)
def _smtp_send(to, subject, body):
    """读 email_config 单行发信(SSL/非SSL)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM email_config WHERE id=1"); cfg=cur.fetchone(); c.close()
    if not cfg or not cfg["is_enabled"] or not cfg["smtp_host"]: return {"ok":False,"error":"邮件服务未配置/未启用"}
    import smtplib
    from email.mime.text import MIMEText
    frm=cfg["smtp_from"] or cfg["smtp_user"]
    msg=MIMEText(body,"plain","utf-8"); msg["Subject"]=subject; msg["From"]=frm; msg["To"]=to
    try:
        if cfg["use_ssl"]:
            s=smtplib.SMTP_SSL(cfg["smtp_host"],cfg["smtp_port"] or 465,timeout=15)
        else:
            s=smtplib.SMTP(cfg["smtp_host"],cfg["smtp_port"] or 587,timeout=15); s.starttls()
        if cfg["smtp_user"]: s.login(cfg["smtp_user"],cfg["smtp_password"] or "")
        s.sendmail(frm,[to],msg.as_string()); s.quit()
        return {"ok":True}
    except Exception as e: return {"ok":False,"error":str(e)}

@app.get("/api/admin/notify/feishu_status", dependencies=[Depends(require_op("notify"))])
def notify_feishu_status():
    aid=_chenv("feishu","APPID")
    if not aid: return {"connected":False,"error":"飞书 APPID 未配置"}
    t=_feishu_token()
    return {"connected":t["ok"],"error":t.get("error")}
class NotifyTestReq(BaseModel):
    license_key:str=""; recipient:str=""
@app.post("/api/admin/notify/feishu_test", dependencies=[Depends(require_op("notify"))])
def notify_feishu_test(r:NotifyTestReq):
    if not r.recipient: raise HTTPException(400,"请填测试接收人(open_id/邮箱/手机号)")
    t=_feishu_token()
    if not t["ok"]: return {"status":"error","detail":t["error"]}
    import datetime as _d
    res=_feishu_send_card(t["token"],r.recipient,"🧪 测试消息","**飞书通知配置成功!**\n\n测试时间:"+_d.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),"blue")
    _notif_log("测试消息","feishu","sent" if res["ok"] else "failed","→ "+r.recipient,r.recipient)
    return {"status":"sent" if res["ok"] else "error","detail":res.get("error"),"message_id":res.get("message_id")}

@app.get("/api/admin/notify/email_config", dependencies=[Depends(require_op("notify"))])
def notify_email_get():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT smtp_host,smtp_port,smtp_user,smtp_from,use_ssl,is_enabled FROM email_config WHERE id=1"); r=cur.fetchone(); c.close()
    return dict(r) if r else {"smtp_host":"","smtp_port":465,"use_ssl":True,"is_enabled":False}
class EmailCfgReq(BaseModel):
    license_key:str=""; smtp_host:str=""; smtp_port:int=465; smtp_user:str=""; smtp_password:str=""; smtp_from:str=""; use_ssl:bool=True; is_enabled:bool=False
@app.post("/api/admin/notify/email_config", dependencies=[Depends(require_op("notify"))])
def notify_email_save(r:EmailCfgReq):
    c=db(); cur=c.cursor()
    # 密码留空=保留原值
    if r.smtp_password:
        cur.execute("""INSERT INTO email_config(id,smtp_host,smtp_port,smtp_user,smtp_password,smtp_from,use_ssl,is_enabled,updated_at)
                       VALUES(1,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (id) DO UPDATE SET smtp_host=EXCLUDED.smtp_host,
                       smtp_port=EXCLUDED.smtp_port,smtp_user=EXCLUDED.smtp_user,smtp_password=EXCLUDED.smtp_password,
                       smtp_from=EXCLUDED.smtp_from,use_ssl=EXCLUDED.use_ssl,is_enabled=EXCLUDED.is_enabled,updated_at=now()""",
                    (r.smtp_host,r.smtp_port,r.smtp_user,r.smtp_password,r.smtp_from,r.use_ssl,r.is_enabled))
    else:
        cur.execute("""INSERT INTO email_config(id,smtp_host,smtp_port,smtp_user,smtp_from,use_ssl,is_enabled,updated_at)
                       VALUES(1,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT (id) DO UPDATE SET smtp_host=EXCLUDED.smtp_host,
                       smtp_port=EXCLUDED.smtp_port,smtp_user=EXCLUDED.smtp_user,smtp_from=EXCLUDED.smtp_from,
                       use_ssl=EXCLUDED.use_ssl,is_enabled=EXCLUDED.is_enabled,updated_at=now()""",
                    (r.smtp_host,r.smtp_port,r.smtp_user,r.smtp_from,r.use_ssl,r.is_enabled))
    c.close(); return {"ok":True}
@app.post("/api/admin/notify/email_test", dependencies=[Depends(require_op("notify"))])
def notify_email_test():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT smtp_from,smtp_user FROM email_config WHERE id=1"); cfg=cur.fetchone(); c.close()
    if not cfg: raise HTTPException(400,"邮件未配置")
    to=cfg["smtp_from"] or cfg["smtp_user"]
    res=_smtp_send(to,"[Quant Hedge] 测试邮件","邮件通知连接正常。")
    _notif_log("测试邮件","email","sent" if res["ok"] else "failed","连接测试",to)
    return {"status":"sent" if res["ok"] else "failed","detail":res.get("error")}

@app.get("/api/admin/notify/templates", dependencies=[Depends(require_op("notify"))])
def notify_templates():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM notification_templates ORDER BY id"); rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"templates":rows}
class TemplateReq(BaseModel):
    license_key:str=""; id:int=0; template_name:str; category:str="system"; title_template:str=""; content_template:str=""
    enable_feishu:bool=True; enable_email:bool=False; enable_marquee:bool=True; priority:int=1; cooldown_seconds:int=0
    marquee_color:str="#2E8BD6"; marquee_blink:bool=False; sound_key:str="none"; is_enabled:bool=True
@app.post("/api/admin/notify/template", dependencies=[Depends(require_op("notify"))])
def notify_template_save(r:TemplateReq):
    c=db(); cur=c.cursor()
    if r.id:
        cur.execute("""UPDATE notification_templates SET template_name=%s,category=%s,title_template=%s,content_template=%s,
                       enable_feishu=%s,enable_email=%s,enable_marquee=%s,priority=%s,cooldown_seconds=%s,
                       marquee_color=%s,marquee_blink=%s,sound_key=%s,is_enabled=%s,updated_at=now() WHERE id=%s""",
                    (r.template_name,r.category,r.title_template,r.content_template,r.enable_feishu,r.enable_email,r.enable_marquee,
                     r.priority,r.cooldown_seconds,r.marquee_color,r.marquee_blink,r.sound_key,r.is_enabled,r.id))
    else:
        cur.execute("""INSERT INTO notification_templates(template_name,category,title_template,content_template,
                       enable_feishu,enable_email,enable_marquee,priority,cooldown_seconds,marquee_color,marquee_blink,sound_key,is_enabled)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (r.template_name,r.category,r.title_template,r.content_template,r.enable_feishu,r.enable_email,r.enable_marquee,
                     r.priority,r.cooldown_seconds,r.marquee_color,r.marquee_blink,r.sound_key,r.is_enabled))
    c.close(); return {"ok":True}
class TemplateDel(BaseModel):
    license_key:str=""; id:int
@app.post("/api/admin/notify/template_del", dependencies=[Depends(require_op("notify"))])
def notify_template_del(r:TemplateDel):
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM notification_templates WHERE id=%s",(r.id,)); c.close()
    return {"ok":True}

class BroadcastReq(BaseModel):
    license_key:str=""; title:str; content:str; priority:int=1; color:str="#2E8BD6"; blink:bool=False; sound:str="none"
@app.post("/api/admin/notify/broadcast", dependencies=[Depends(require_op("notify"))])
def notify_broadcast(r:BroadcastReq):
    """网站跑马灯广播: 发 Redis(用户端订阅) + 写 marquee 日志(recent-marquee 兜底轮询源)。"""
    payload={"title":r.title,"content":r.content,"priority":r.priority,"color":r.color,"blink":r.blink,"sound":r.sound,
             "ts":datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        R.publish(RNS+"notification:broadcast",json.dumps(payload))
        R.lpush(RNS+"marquee_recent",json.dumps(payload)); R.ltrim(RNS+"marquee_recent",0,49)
    except Exception as e: raise HTTPException(500,"广播失败: %s"%e)
    _notif_log(r.title,"marquee","sent",r.content)
    return {"ok":True}
@app.get("/api/notify/marquee/recent")
def notify_marquee_recent(limit:int=10):
    """公开跑马灯只返回网站公告；账户交易告警走鉴权后的用户级流。"""
    lim=max(1,min(50,limit)); out=[]
    # 0) 维护公告置顶(维护态持续注入, 无需重复 publish)
    _m=_maint_get(); maint_top=None
    if _m.get("on"):
        maint_top={"title":_m.get("title") or "系统维护中",
                   "content":(_m.get("msg") or "系统维护中，部分功能暂停")+((" · 预计恢复 "+_m["until"]) if _m.get("until") else ""),
                   "priority":3,"color":"#F56C6C","blink":True,"sound":"none","src":"maintenance","ts":_m.get("ts","")}
    # 1) 运营网站广播
    try:
        for x in (R.lrange(RNS+"marquee_recent",0,49) or []):
            d=json.loads(x)
            if d.get("src")=="maintenance": continue   # 维护条统一走上面置顶注入, 避免重复
            d.setdefault("src","broadcast"); out.append(d)
    except Exception: pass
    # 2) 用户交易告警不得进入公开馈源，避免跨账户泄露。
    # 公告按时间倒序, 截断; 维护公告恒置顶
    out.sort(key=lambda d:d.get("ts",""), reverse=True)
    items=out[:lim]
    if maint_top: items=[maint_top]+[x for x in items if x.get("src")!="maintenance"]
    return {"items":items,"maintenance":bool(maint_top)}

@app.get("/api/admin/notify/logs", dependencies=[Depends(require_op("notify"))])
def notify_logs(channel:str="", status:str="", limit:int=100):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    q="SELECT id,template_name,channel,recipient,status,content,created_at FROM notification_logs WHERE 1=1"; p=[]
    if channel: q+=" AND channel=%s"; p.append(channel)
    if status: q+=" AND status=%s"; p.append(status)
    q+=" ORDER BY id DESC LIMIT %s"; p.append(max(1,min(500,limit)))
    cur.execute(q,tuple(p)); rows=[dict(x) for x in cur.fetchall()]; c.close()
    return {"logs":rows}
@app.get("/api/admin/notify/sounds", dependencies=[Depends(require_op("notify"))])
def notify_sounds():
    """声音人设管理列表(含 TTS 调参)。用于通知模板「声音人设」下拉与广播声音选择。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT key,name,persona,engine,lang,rate,pitch,voice_hint,edge_voice,edge_rate,edge_pitch,sample_text,enabled,sort FROM notification_sounds ORDER BY sort,key")
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    # 固定首项「无(静音)」不入库, 前端联合展示
    return {"sounds":rows}
class SoundReq(BaseModel):
    license_key:str=""; key:str; name:str; persona:str=""; engine:str="browser"; lang:str="zh-CN"
    rate:float=1.0; pitch:float=1.0; voice_hint:str=""
    edge_voice:str=""; edge_rate:str="+0%"; edge_pitch:str="+0Hz"
    sample_text:str=""; enabled:bool=True; sort:int=0
@app.post("/api/admin/notify/sound", dependencies=[Depends(require_op("notify"))])
def notify_sound_save(r:SoundReq):
    """新增/更新声音人设。key 唯一(sweet/mature 等)。engine=browser(浏览器TTS,voice_hint挑声/rate/pitch)
       或 edge(edge-tts 微软神经语音, edge_voice 如 zh-CN-XiaoxiaoNeural + edge_rate/edge_pitch 如 +8%/-10Hz)。"""
    if not r.key or r.key=="none": raise HTTPException(400,"key 不能为空或 none")
    if r.engine not in ("browser","edge"): raise HTTPException(400,"engine 只能 browser/edge")
    if r.engine=="edge" and not r.edge_voice: raise HTTPException(400,"edge 引擎需指定 edge_voice")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO notification_sounds(key,name,persona,engine,lang,rate,pitch,voice_hint,edge_voice,edge_rate,edge_pitch,sample_text,enabled,sort,updated_at)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now())
                   ON CONFLICT (key) DO UPDATE SET name=EXCLUDED.name,persona=EXCLUDED.persona,engine=EXCLUDED.engine,lang=EXCLUDED.lang,
                   rate=EXCLUDED.rate,pitch=EXCLUDED.pitch,voice_hint=EXCLUDED.voice_hint,edge_voice=EXCLUDED.edge_voice,
                   edge_rate=EXCLUDED.edge_rate,edge_pitch=EXCLUDED.edge_pitch,sample_text=EXCLUDED.sample_text,
                   enabled=EXCLUDED.enabled,sort=EXCLUDED.sort,updated_at=now()""",
                (r.key,r.name,r.persona,r.engine,r.lang,r.rate,r.pitch,r.voice_hint,r.edge_voice,r.edge_rate,r.edge_pitch,r.sample_text,r.enabled,r.sort))
    c.close(); _audit("",_actor(r.license_key),"notify_sound_save",{"key":r.key,"engine":r.engine},DEMO_MODE,"saved")
    return {"ok":True,"key":r.key}
class SoundDel(BaseModel):
    license_key:str=""; key:str
@app.post("/api/admin/notify/sound_del", dependencies=[Depends(require_op("notify"))])
def notify_sound_del(r:SoundDel):
    """删除声音人设。若仍被模板引用, 该模板的 sound_key 回落 none(静音)。"""
    c=db(); cur=c.cursor()
    cur.execute("UPDATE notification_templates SET sound_key='none' WHERE sound_key=%s",(r.key,))
    cur.execute("DELETE FROM notification_sounds WHERE key=%s",(r.key,))
    c.close(); _audit("",_actor(r.license_key),"notify_sound_del",{"key":r.key},DEMO_MODE,"deleted")
    return {"ok":True}
@app.get("/api/admin/notify/edge_voices", dependencies=[Depends(require_op("notify"))])
async def notify_edge_voices(locale:str="zh-CN"):
    """列出 edge-tts 可用神经语音(供人设选择)。默认中文; locale=all 列全部。"""
    try:
        import edge_tts
        vs=await edge_tts.list_voices()
    except Exception as e:
        raise HTTPException(500,"edge-tts 不可用: %s"%e)
    out=[]
    for v in vs:
        loc=v.get("Locale","")
        if locale!="all" and not loc.startswith(locale): continue
        out.append({"short_name":v.get("ShortName"),"gender":v.get("Gender"),"locale":loc,
                    "friendly":v.get("FriendlyName","")})
    out.sort(key=lambda x:(x["locale"],x["short_name"]))
    return {"voices":out,"count":len(out)}

# ---- edge-tts 合成(服务端调微软神经语音, 落盘缓存; 公开只读, 用户端/试听按 key 播放 MP3) ----
_TTS_CACHE_DIR="/opt/quanthedge/tts_cache"
def _tts_cache_path(key, text):
    import hashlib as _h
    os.makedirs(_TTS_CACHE_DIR, exist_ok=True)
    h=_h.sha256(((key or "")+"|"+(text or "")).encode("utf-8")).hexdigest()[:24]
    return os.path.join(_TTS_CACHE_DIR, "%s_%s.mp3"%(key or "x", h))
@app.get("/api/notify/tts")
async def notify_tts(key:str, text:str=""):
    """按声音人设 key 合成语音并返回 MP3(engine=edge 走 edge-tts; 落盘缓存同 key+text 复用)。
       公开只读: 用户端跑马灯播报 + qhadmin 试听共用。engine!=edge 或人设不存在 → 404 让前端回落浏览器 TTS。"""
    from fastapi.responses import FileResponse
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT key,engine,edge_voice,edge_rate,edge_pitch,sample_text FROM notification_sounds WHERE key=%s AND enabled=true",(key,))
    s=cur.fetchone(); c.close()
    if not s or s["engine"]!="edge" or not s["edge_voice"]:
        raise HTTPException(404,"该人设非 edge 引擎或不存在(前端回落浏览器 TTS)")
    say=(text or s.get("sample_text") or "语音播报测试")[:200]
    path=_tts_cache_path(key, say)
    if not os.path.exists(path):
        try:
            import edge_tts
            comm=edge_tts.Communicate(text=say, voice=s["edge_voice"],
                                      rate=(s.get("edge_rate") or "+0%"), pitch=(s.get("edge_pitch") or "+0Hz"))
            await comm.save(path)
        except Exception as e:
            raise HTTPException(502,"合成失败: %s"%str(e)[:120])
    return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control":"public, max-age=86400"})
@app.get("/api/notify/sounds")
def notify_sounds_public():
    """用户端 TTS 声音参数(公开只读): key→引擎/浏览器调参/edge标记。
       engine=edge 的项用户端改走 /api/notify/tts?key=... 取 MP3; browser 的项按 lang/rate/pitch/voice_hint 本地合成。"""
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT key,name,persona,engine,lang,rate,pitch,voice_hint,edge_voice FROM notification_sounds WHERE enabled=true ORDER BY sort,key")
        rows=[dict(x) for x in cur.fetchall()]; c.close()
        return {"sounds":rows}
    except Exception:
        return {"sounds":[]}

# ================= P3 数据管理(版本只读 / DB / SSL / WS 心跳) =================
import subprocess as _sp
_SSL_STAGE="/opt/quanthedge/ssl_stage"; _SSL_DEPLOY="/etc/ssl/quanthedge"
@app.get("/api/admin/datamgr/version", dependencies=[Depends(require_op("datamgr"))])
def dm_version():
    """版本信息(只读): 版本号取 VERSION 文件(每次 GitHub 推送 _qh_bump_ver 自增, 真随备份变化) +
       git 提交哈希/时间/是否有未提交改动/与 origin/qh 领先落后 + python + 提交历史。"""
    def _g(args,timeout=8):
        try:
            r=_sp.run(["git","-C","/opt/quanthedge"]+args,capture_output=True,text=True,timeout=timeout)
            return r.stdout.strip() if r.returncode==0 else ""
        except Exception: return ""
    out={"app_version":_qh_read_ver(),"python":os.sys.version.split()[0]}   # VERSION 文件=真版本
    out["git_hash"]=_g(["rev-parse","--short","HEAD"]) or "非git部署"
    out["git_branch"]=_g(["rev-parse","--abbrev-ref","HEAD"])
    out["git_time"]=_g(["log","-1","--format=%ci"])
    out["git_msg"]=_g(["log","-1","--format=%s"])
    st=_g(["status","--porcelain"])
    out["git_dirty"]=bool(st)   # 有未提交改动=部署了但未推送备份
    out["git_dirty_n"]=len([x for x in st.splitlines() if x.strip()]) if st else 0
    ab=_g(["rev-list","--left-right","--count","origin/%s...HEAD"%_QH_BRANCH])
    if ab and "\t" in ab:
        try: b,a=ab.split("\t"); out["behind"]=int(b); out["ahead"]=int(a)
        except Exception: out["behind"]=out["ahead"]=None
    out["git"]=("%s %s %s"%(out["git_hash"],out["git_time"],out["git_msg"])).strip() or "非 git 部署(patch 方式)"
    hist=_g(["log","-10","--format=%h|%ci|%s"])
    out["history"]=[dict(zip(("hash","date","msg"),l.split("|",2))) for l in hist.splitlines() if l] if hist else []
    return out

# ===== GitHub 推送(复刻 coinadmin 版本管理; 目标分支 qh; 仓库根 /opt/quanthedge; allowlist .gitignore 兜底) =====
import threading as _threading
_QH_REPO="/opt/quanthedge"; _QH_BRANCH="qh"; _QH_VERSION_FILE=_QH_REPO+"/VERSION"
_git_push_lock=_threading.Lock()
class GitPushReq(BaseModel):
    message: str
def _qh_read_ver():
    try:
        with open(_QH_VERSION_FILE) as f: return f.read().strip()
    except Exception: return "1.0.0"
def _qh_bump_ver(v):
    p=v.split(".")
    if len(p)==3 and p[2].isdigit(): p[2]=str(int(p[2])+1); return ".".join(p)
    return v
def _git(args, timeout=90):
    return _sp.check_output(["git","-C",_QH_REPO]+args, stderr=_sp.STDOUT, timeout=timeout).decode()
@app.post("/api/admin/datamgr/git-push", dependencies=[Depends(require_op("datamgr"))])
def dm_git_push(req: GitPushReq):
    """把当前服务器 /opt/quanthedge(app.py/engine/connector/web/admin/admin-src)提交并推送到 GitHub qh 分支。
       allowlist .gitignore 已排除 channels.json/venv/*.bak/密钥; 单飞锁防并发 git; FF rebase 对齐, 绝不 force。"""
    if not (req.message or "").strip():
        raise HTTPException(400,"推送备注不能为空")
    if not _git_push_lock.acquire(blocking=False):
        return {"status":"error","output":"上一次推送仍在进行中，请等其完成后再试(已加单飞锁防并发 git 撞锁)。"}
    try:
        # 备份标签(best-effort)
        ts=_dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        try: _git(["tag","backup-"+ts], timeout=8)
        except Exception: pass
        # 暂存(allowlist .gitignore 负责过滤); 再兜底剔除任何 .bak/backup_ 混入
        _git(["add","-A"], timeout=90)
        staged=_git(["diff","--cached","--name-only"], timeout=20).splitlines()
        junk=[p for p in staged if (".bak" in p or "/backup_" in p or p.startswith("backup_") or "channels.json" in p)]
        if junk:
            _sp.run(["git","-C",_QH_REPO,"reset","-q","--"]+junk, timeout=30, check=False)
        # 有变更才升版本
        has_changes=True
        try: _git(["diff","--cached","--quiet"], timeout=10); has_changes=False
        except _sp.CalledProcessError: has_changes=True
        if has_changes:
            newv=_qh_bump_ver(_qh_read_ver())
            with open(_QH_VERSION_FILE,"w") as f: f.write(newv+"\n")
            _git(["add","VERSION"], timeout=8)
            try:
                _git(["commit","-m",req.message], timeout=30)
            except _sp.CalledProcessError as e:
                out=(e.output.decode() if e.output else "")
                if "nothing to commit" not in out:
                    return {"status":"error","output":"提交失败:\n"+out[:600]}
        # 与 origin 对齐: fetch → 落后则 rebase(autostash), 冲突则 abort 回滚, 绝不 force
        try: _git(["fetch","origin",_QH_BRANCH], timeout=60)
        except _sp.CalledProcessError as e:
            return {"status":"error","output":"拉取 origin 失败(检查网络/deploy key):\n"+(e.output.decode() if e.output else str(e))[:500]}
        behind="0"
        try: behind=_git(["rev-list","--count","HEAD..origin/"+_QH_BRANCH], timeout=15).strip()
        except Exception: behind="0"
        if behind.isdigit() and int(behind)>0:
            try: _git(["rebase","--autostash","origin/"+_QH_BRANCH], timeout=90)
            except _sp.CalledProcessError as e:
                _sp.run(["git","-C",_QH_REPO,"rebase","--abort"], timeout=30, check=False)
                return {"status":"error","output":("本地 qh 落后 origin %s 个提交且自动 rebase 冲突(已回滚,未改动工作区)。\n"
                        "请在服务器 /opt/quanthedge 执行 `git pull --rebase origin qh` 人工解决后再推。\n"%behind)+(e.output.decode() if e.output else "")[:400]}
        if not has_changes and (not behind.isdigit() or int(behind)==0):
            return {"status":"success","output":"无变更可推送(工作区与 origin/qh 一致)。","version":_qh_read_ver(),"no_change":True}
        # 推送(经对齐后应为 FF)
        result=_git(["push","origin",_QH_BRANCH], timeout=180)
        return {"status":"success","output":result[:800],"version":_qh_read_ver()}
    except _sp.CalledProcessError as e:
        return {"status":"error","output":(e.output.decode() if e.output else str(e))[:800]}
    except Exception as e:
        return {"status":"error","output":str(e)[:800]}
    finally:
        _git_push_lock.release()


@app.get("/api/admin/datamgr/db/stats", dependencies=[Depends(require_op("datamgr"))])
def dm_db_stats():
    c=db(); cur=c.cursor()
    try:
        cur.execute("SELECT pg_size_pretty(pg_database_size(current_database()))"); size=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"); tc=cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"); conn=cur.fetchone()[0]
        c.close(); return {"size":size,"table_count":tc,"active_connections":conn}
    except Exception as e:
        c.close(); return {"size":"error","table_count":0,"active_connections":0,"err":str(e)}
@app.get("/api/admin/datamgr/db/tables", dependencies=[Depends(require_op("datamgr"))])
def dm_db_tables():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT t.table_name AS name, COALESCE(s.n_live_tup,0) AS row_count,
                     pg_size_pretty(pg_total_relation_size(quote_ident(t.table_name))) AS size
                   FROM information_schema.tables t LEFT JOIN pg_stat_user_tables s ON s.relname=t.table_name
                   WHERE t.table_schema='public' ORDER BY COALESCE(s.n_live_tup,0) DESC""")
    rows=[dict(r) for r in cur.fetchall()]; c.close(); return {"tables":rows}
@app.get("/api/admin/datamgr/db/table/{name}", dependencies=[Depends(require_op("datamgr"))])
def dm_db_table_data(name:str):
    if not all(ch in "abcdefghijklmnopqrstuvwxyz_0123456789" for ch in name.lower()):
        raise HTTPException(400,"非法表名")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("SELECT * FROM %s LIMIT 100"%name)   # 表名已白名单校验
        rows=[{k:(str(v) if v is not None else None) for k,v in dict(r).items()} for r in cur.fetchall()]
        cols=list(rows[0].keys()) if rows else []
        c.close(); return {"columns":cols,"rows":rows}
    except Exception as e:
        c.close(); raise HTTPException(400,str(e))
class DmConfirm(BaseModel):
    license_key:str=""; confirm:bool=False
@app.post("/api/admin/datamgr/db/backup", dependencies=[Depends(require_op("datamgr"))])
def dm_db_backup(r:DmConfirm):
    """pg_dump 到本地 backups 目录(不推 git)。"""
    if not r.confirm: raise HTTPException(400,"需 confirm=true")
    ts=_sp.run(["date","+%Y%m%d_%H%M%S"],capture_output=True,text=True).stdout.strip()
    bdir="/opt/quanthedge/backups"; os.makedirs(bdir,exist_ok=True)
    dest="%s/quanthedge_%s.sql"%(bdir,ts)
    try:
        env={**os.environ,"PGPASSWORD":os.environ.get("QH_DB_PASS","")}
        _sp.check_output(["pg_dump","-h","127.0.0.1","-U","quanthedge","-d","quanthedge","-f",dest],stderr=_sp.STDOUT,timeout=180,env=env)
        size=os.path.getsize(dest)
        _audit("",_actor(r.license_key),"db_backup",{"file":dest,"mb":round(size/1048576,2)},DEMO_MODE,"done")
        return {"status":"success","file":dest,"size_mb":round(size/1048576,2)}
    except _sp.CalledProcessError as e:
        return {"status":"error","output":(e.output.decode()[:500] if e.output else str(e))}
@app.post("/api/admin/datamgr/db/cleanup", dependencies=[Depends(require_op("datamgr"))])
def dm_db_cleanup(r:DmConfirm):
    """清理 QH 过期日志(audit_log>90d, notification_logs>90d)。coin 的 trade_logs/proxy_health_logs 在 QH 不存在。"""
    if not r.confirm: raise HTTPException(400,"需 confirm=true")
    c=db(); cur=c.cursor(); res={}
    for t,col,days in (("audit_log","ts",90),("notification_logs","created_at",90)):
        try:
            cur.execute("DELETE FROM %s WHERE %s < now()-interval '%d days'"%(t,col,days)); res[t]=cur.rowcount
        except Exception as e: res[t]="skip:%s"%str(e)[:40]
    c.close()
    _audit("",_actor(r.license_key),"db_cleanup",res,DEMO_MODE,"done")
    return {"status":"success","deleted":res}

# ---- SSL 证书 ----
def _ssl_log(cid,action,detail=""):
    try:
        c=db(); cur=c.cursor(); cur.execute("INSERT INTO ssl_certificate_logs(certificate_id,action,detail) VALUES(%s,%s,%s)",(cid,action,detail)); c.close()
    except Exception as e: print("ssl_log err",e)
def _ssl_parse(cert_pem):
    from cryptography import x509
    from cryptography.hazmat.backends import default_backend
    crt=x509.load_pem_x509_certificate(cert_pem.encode(),default_backend())
    san=[]
    try:
        ext=crt.extensions.get_extension_for_class(x509.SubjectAlternativeName); san=ext.value.get_values_for_type(x509.DNSName)
    except Exception: pass
    return {"issuer":crt.issuer.rfc4514_string(),"subject":crt.subject.rfc4514_string(),
            "serial_number":str(crt.serial_number),"issued_at":crt.not_valid_before_utc.isoformat(),
            "expires_at":crt.not_valid_after_utc.isoformat(),"san":san}
@app.get("/api/admin/datamgr/ssl", dependencies=[Depends(require_op("datamgr"))])
def dm_ssl_list():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,cert_name,domain_name,cert_type,issuer,subject,issued_at,expires_at,is_deployed,deploy_path,status FROM ssl_certificates ORDER BY id DESC")
    rows=[dict(r) for r in cur.fetchall()]; c.close()
    now=datetime.datetime.now(datetime.timezone.utc)
    for r in rows:
        if r.get("expires_at"):
            try: r["days_left"]=(r["expires_at"]-now).days
            except Exception: r["days_left"]=None
    return {"certificates":rows}
class SSLUpload(BaseModel):
    license_key:str=""; cert_name:str; domain_name:str=""; cert_content:str; key_content:str
@app.post("/api/admin/datamgr/ssl/upload", dependencies=[Depends(require_op("datamgr"))])
def dm_ssl_upload(r:SSLUpload):
    try: p=_ssl_parse(r.cert_content)
    except Exception as e: raise HTTPException(400,"证书解析失败: %s"%e)
    if "PRIVATE KEY" not in r.key_content: raise HTTPException(400,"私钥格式不对(应含 PRIVATE KEY)")
    c=db(); cur=c.cursor()
    cur.execute("""INSERT INTO ssl_certificates(cert_name,domain_name,cert_type,cert_content,key_content,issuer,subject,serial_number,issued_at,expires_at)
                   VALUES(%s,%s,'upload',%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (r.cert_name,r.domain_name or (p["san"][0] if p["san"] else ""),r.cert_content,r.key_content,
                 p["issuer"],p["subject"],p["serial_number"],p["issued_at"],p["expires_at"]))
    cid=cur.fetchone()[0]; c.close(); _ssl_log(cid,"upload","手工上传")
    return {"ok":True,"id":cid}
@app.post("/api/admin/datamgr/ssl/scan", dependencies=[Depends(require_op("datamgr"))])
def dm_ssl_scan():
    """扫描 /etc/letsencrypt/live 导入现网证书(只读导入, 不覆盖已存在)。
       LE 目录 root-only, 经 sudo 读取(服务以 ubuntu 运行)。"""
    added=[]; base="/etc/letsencrypt/live"
    def _sudo_ls(p):
        try: r=_sp.run(["sudo","ls",p],capture_output=True,text=True,timeout=8); return [x for x in r.stdout.split() if x!="README"] if r.returncode==0 else []
        except Exception: return []
    def _sudo_cat(p):
        try: r=_sp.run(["sudo","cat",p],capture_output=True,text=True,timeout=8); return r.stdout if r.returncode==0 else ""
        except Exception: return ""
    doms=_sudo_ls(base)
    if not doms: return {"scanned":0,"added":0,"domains":[],"note":"未发现 LE 证书或无 sudo 读权限"}
    c=db(); cur=c.cursor()
    for dom in doms:
        cf="%s/%s/fullchain.pem"%(base,dom); kf="%s/%s/privkey.pem"%(base,dom)
        cc=_sudo_cat(cf); kk=_sudo_cat(kf)
        if not cc or not kk: continue
        try:
            cur.execute("SELECT 1 FROM ssl_certificates WHERE domain_name=%s AND cert_type='letsencrypt'",(dom,))
            if cur.fetchone(): continue
            p=_ssl_parse(cc)
            cur.execute("""INSERT INTO ssl_certificates(cert_name,domain_name,cert_type,cert_content,key_content,issuer,subject,serial_number,issued_at,expires_at,is_deployed,deploy_path,status,auto_renew)
                           VALUES(%s,%s,'letsencrypt',%s,%s,%s,%s,%s,%s,%s,true,%s,'active',true) RETURNING id""",
                        (("LE-"+dom),dom,cc,kk,p["issuer"],p["subject"],p["serial_number"],p["issued_at"],p["expires_at"],cf))
            cid=cur.fetchone()[0]; _ssl_log(cid,"scan_import",cf); added.append(dom)
        except Exception as e: print("ssl scan err",dom,e)
    c.close(); return {"scanned":len(doms),"added":len(added),"domains":added}
class SSLId(BaseModel):
    license_key:str=""; id:int
@app.post("/api/admin/datamgr/ssl/deploy", dependencies=[Depends(require_op("datamgr"))])
def dm_ssl_deploy(r:SSLId):
    """部署证书到 /etc/ssl/quanthedge(sudo 写)+ nginx -t + reload。高危, 落审计。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM ssl_certificates WHERE id=%s",(r.id,)); cert=cur.fetchone()
    if not cert: c.close(); raise HTTPException(404,"证书不存在")
    safe=cert["domain_name"].replace("*","wildcard").replace(" ","_") or ("cert%d"%r.id)
    os.makedirs(_SSL_STAGE,exist_ok=True)
    scrt=os.path.join(_SSL_STAGE,safe+".crt"); skey=os.path.join(_SSL_STAGE,safe+".key")
    open(scrt,"w").write(cert["cert_content"]); open(skey,"w").write(cert["key_content"])
    dcrt=os.path.join(_SSL_DEPLOY,safe+".crt"); dkey=os.path.join(_SSL_DEPLOY,safe+".key")
    try:
        _sp.run(["sudo","mkdir","-p",_SSL_DEPLOY],check=True,capture_output=True,timeout=10)
        _sp.run(["sudo","cp",scrt,dcrt],check=True,capture_output=True,timeout=10)
        _sp.run(["sudo","cp",skey,dkey],check=True,capture_output=True,timeout=10)
        _sp.run(["sudo","chmod","600",dkey],check=True,capture_output=True,timeout=10)
        nt=_sp.run(["sudo","nginx","-t"],capture_output=True,timeout=15)
        reloaded=False
        if nt.returncode==0:
            _sp.run(["sudo","systemctl","reload","nginx"],check=True,capture_output=True,timeout=15); reloaded=True
        cur.execute("UPDATE ssl_certificates SET is_deployed=true,deploy_path=%s,status='active' WHERE id=%s",(dcrt,r.id)); c.close()
        _ssl_log(r.id,"deploy","→ %s (nginx reload=%s)"%(dcrt,reloaded))
        _audit("",_actor(r.license_key),"ssl_deploy",{"id":r.id,"path":dcrt,"reloaded":reloaded},DEMO_MODE,"done")
        return {"ok":True,"deploy_path":dcrt,"nginx_reloaded":reloaded,"nginx_test":(nt.stderr.decode()[-200:] if nt.returncode!=0 else "ok")}
    except _sp.CalledProcessError as e:
        c.close(); _ssl_log(r.id,"deploy_failed",str(e)); raise HTTPException(500,"部署失败: %s"%((e.stderr.decode()[:300] if e.stderr else str(e))))
    finally:
        try: os.remove(scrt); os.remove(skey)
        except Exception: pass
@app.post("/api/admin/datamgr/ssl/delete", dependencies=[Depends(require_op("datamgr"))])
def dm_ssl_delete(r:SSLId):
    c=db(); cur=c.cursor()
    cur.execute("SELECT is_deployed FROM ssl_certificates WHERE id=%s",(r.id,)); row=cur.fetchone()
    if not row: c.close(); raise HTTPException(404,"不存在")
    if row[0]: c.close(); raise HTTPException(400,"已部署证书不能删除(请先在服务器撤下)")
    cur.execute("DELETE FROM ssl_certificates WHERE id=%s",(r.id,)); c.close()
    return {"ok":True}
@app.get("/api/admin/datamgr/ssl/{cid}/logs", dependencies=[Depends(require_op("datamgr"))])
def dm_ssl_logs(cid:int):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT action,detail,created_at FROM ssl_certificate_logs WHERE certificate_id=%s ORDER BY id DESC LIMIT 50",(cid,))
    rows=[dict(r) for r in cur.fetchall()]; c.close(); return {"logs":rows}

@app.get("/api/admin/datamgr/ws_stats", dependencies=[Depends(require_op("datamgr"))])
def dm_ws_stats():
    """WS/引擎心跳只读面板(QH 单广播器架构: 读 WS hub 连接数/快照新鲜度 + Redis 引擎心跳 + 桥状态)。"""
    import time as _t
    out={"engine":{},"redis":{},"ws":{}}
    # WS hub 实时态: 连接数取 Rust HUB 上报 qh:ws:hub_clients(切 HUB 后本地恒空), 回落本地
    try:
        now=int(_t.time())
        fast_ts=_WS_SNAP.get("fast_ts",0) or 0; slow_ts=_WS_SNAP.get("slow_ts",0) or 0
        _hub_clients=R.get(RNS+"ws:hub_clients")
        if _hub_clients is not None: clients=int(_hub_clients); src="hub"
        else: clients=len(_WS_CLIENTS); src="local"
        out["ws"]={
            "clients": clients, "src": src, "hub_alive": (R.get(RNS+"ws:hub_alive")=="1"),
            "fast_age": (now-fast_ts) if fast_ts else None,
            "slow_age": (now-slow_ts) if slow_ts else None,
            "fast_ts": fast_ts, "slow_ts": slow_ts,
            "broadcaster": "running" if (clients>0 and fast_ts and (now-fast_ts)<15) else ("idle" if clients==0 else "stale"),
        }
    except Exception as e:
        out["ws"]={"err":str(e)}
    for k in ("engine:cycle","auto_exit:last","auto_entry:last"):
        try: out["engine"][k.split(":")[-1]]=R.get(RNS+k)
        except Exception: pass
    out["engine"]["market"]=_json_hash_state(RNS+"engine:market:user")
    try:
        info=R.info(); out["redis"]={"connected_clients":info.get("connected_clients"),"uptime_sec":info.get("uptime_in_seconds"),"used_memory_human":info.get("used_memory_human")}
    except Exception as e: out["redis"]={"err":str(e)}
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"); out["db_connections"]=cur.fetchone()[0]; c.close()
    except Exception: pass
    return out









class CmdReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
@app.post("/api/cmd/close_all", dependencies=[Depends(require_license),Depends(require_trade_writer)])
async def cmd_close_all(r:CmdReq):
    _assert_subject(r.username,r.license_key or "")
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    _maint_block_trading()   # 维护态禁下单前置闸
    await _conn_gate_exec(r.username)   # P0: 按用户桥判健康(修 hedge_pro 被 no123 桥误伤)
    await _exec_owner_gate(r.username)   # 多用户串账墙: 登记账户须==执行桥账户
    items=await _collect_close_items(r.username,"XAUUSD",profit_only=False)
    if DEMO_MODE:
        return {"ok":True,"demo":True,"total":len(items),
                "msg":"演示模式：将按精确 ticket 平仓 %d 个坑，未真实下单"%len(items)}
    return await _enqueue_close_items(r.username,"XAUUSD",actor,items,"close_all")
    if DEMO_MODE:
        # 演示模式：不真实下单，但真实查询双腿当前持仓，回显"将平掉哪些"
        preview={"main":0,"hedge":0}
        try:
            pos=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
            if pos:
                preview["main"]=len((pos.get("main") or {}).get("positions",[]) if isinstance(pos.get("main"),dict) else (pos.get("main") or []))
                preview["hedge"]=len((pos.get("hedge") or {}).get("positions",[]) if isinstance(pos.get("hedge"),dict) else (pos.get("hedge") or []))
        except Exception: pass
        _audit(r.username,actor,"close_all",{"legs":"both","preview":preview},True,"demo:not_sent")
        return {"ok":True,"demo":True,"preview":preview,
                "msg":"演示模式：将平掉 主腿%d/对冲腿%d 笔，未真实下单"%(preview["main"],preview["hedge"])}
    # 真发：双腿 close-all（真金！）— 单腿重试 + 裸空守护 + 绝不自动反开
    async def _close_leg(leg_obj, name, tries=2):
        last=None
        for k in range(tries):
            try:
                r=await leg_obj.close_all()
                if r.get("failed",0)==0: return r,True
                last=r
            except Exception as ex: last={"error":str(ex)}
            if k<tries-1: await _aio.sleep(0.3)   # 重试间隔收紧(0.6→0.3, 平仓延迟砍1-2s); 末轮不sleep
        return last,False
    _uec=_user_exec_conn(r.username)
    from connector import _gen_rid
    account_token="close-all:%s"%_gen_rid()
    _begin_account_op(r.username,account_token)
    try:
        main_r,main_ok = await _close_leg(_uec.main,"main")
        hedge_r,hedge_ok = (await _close_leg(_uec.hedge,"hedge")) if getattr(_uec,"hedge",None) else ({"closed":0},True)
    finally:
        _release_account_op(r.username,account_token)
    _persist_after_close()   # 平仓账本即时落库(云端会话级缓存不可靠)
    mc=(main_r or {}).get("closed",0); hc=(hedge_r or {}).get("closed",0)
    # 裸空判定：一腿成功平、另一腿失败 = 单边暴露
    naked=None
    if main_ok and not hedge_ok: naked="hedge"
    elif hedge_ok and not main_ok: naked="main"
    if naked:
        _halt_auto_entry(r.username,"single_leg_exposed",{"naked":naked,"main":main_r,"hedge":hedge_r,"op":"close_all"})
        # 绝不自动反开（testgo 回滚静默失败=裸空真凶教训）→ 留痕 + CRITICAL 告警 + 人工介入
        try:
            c=db(); cur=c.cursor(); cur.execute("SELECT id FROM users WHERE username=%s",(r.username,)); u=cur.fetchone()
            cur.execute("INSERT INTO naked_alerts(user_id,leg,detail) VALUES(%s,%s,%s)",
                        (u[0] if u else None, naked, json.dumps({"main":main_r,"hedge":hedge_r})))
            c.close()
        except Exception: pass
        _push_alert("err","裸空告警：%s腿平仓失败，另一腿已平，单边暴露！需人工处理"%naked,r.username)
        _audit(r.username,actor,"close_all",{"naked":naked,"main":main_r,"hedge":hedge_r},False,"NAKED_RISK")
        raise HTTPException(409, "裸空风险：%s腿平仓失败，已告警留人工处理（未自动反开）"%naked)
    _audit(r.username,actor,"close_all",{"main":main_r,"hedge":hedge_r},False,"sent:main%d/hedge%d"%(mc,hc))
    # 全平 → 清空两方向开仓点差账本
    try: R.delete(RNS+"ledger:"+r.username+":reverse", RNS+"ledger:"+r.username+":forward")
    except Exception: pass
    return {"ok":True,"demo":False,"closed":{"main":mc,"hedge":hc},
            "msg":"已强制平仓 主腿%d/对冲腿%d 笔"%(mc,hc),"detail":{"main":main_r,"hedge":hedge_r}}

@app.post("/api/cmd/close_profit", dependencies=[Depends(require_license),Depends(require_trade_writer)])
async def cmd_close_profit(r:CmdReq):
    _assert_subject(r.username,r.license_key or "")
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过")
    _maint_block_trading()
    await _conn_gate_exec(r.username)
    await _exec_owner_gate(r.username)
    items=await _collect_close_items(r.username,"XAUUSD",profit_only=True)
    if DEMO_MODE:
        return {"ok":True,"demo":True,"total":len(items),
                "msg":"演示模式：将按精确 ticket 平掉 %d 个盈利坑，未真实下单"%len(items)}
    return await _enqueue_close_items(r.username,"XAUUSD",actor,items,"close_profit")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT d.ticket,d.profit FROM deals d JOIN users u ON u.id=d.user_id WHERE u.username=%s AND d.is_trade=true ORDER BY d.dealt_at DESC LIMIT 50",(r.username,))
    rows=cur.fetchall(); c.close()
    win=[x for x in rows if float(x["profit"] or 0)>0]
    if DEMO_MODE:
        _audit(r.username,actor,"close_profit",{"candidates":len(win)},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式：盈利平仓候选 %d 笔(利润>0)，未真实下单"%len(win),"candidates":len(win)}
    _audit(r.username,actor,"close_profit",{"candidates":len(win)},False,"sent")
    return {"ok":True,"demo":False,"closed":len(win)}

# ================= 套利开仓 / 按对平仓 (手动按钮, 真金, 全闸) =================
_TRADE_TMPL_CACHE={}

def _trade_tmpl_cache_bust(username=None, symbol=None):
    username=str(username or "").strip(); symbol=str(symbol or "").strip()
    if username and symbol:
        _TRADE_TMPL_CACHE.pop((username,symbol),None)
    elif username:
        for key in [key for key in _TRADE_TMPL_CACHE if key[0]==username]:
            _TRADE_TMPL_CACHE.pop(key,None)
    else:
        _TRADE_TMPL_CACHE.clear()

def _load_tmpl(username, symbol="XAUUSD"):
    """取用户该品种参数模板；配置写入时显式失效，交易热路径不查库。"""
    key=(str(username or "").strip(),str(symbol or "XAUUSD").strip())
    cached=_TRADE_TMPL_CACHE.get(key)
    if cached is not None:
        return dict(cached)
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT pt.* FROM param_templates pt JOIN users u ON u.id=pt.user_id
                   WHERE u.username=%s AND pt.symbol=%s LIMIT 1""",(username,symbol))
    row=cur.fetchone(); c.close()
    if not row:
        return None
    out=dict(row); out.setdefault("username",username)
    _TRADE_TMPL_CACHE[key]=dict(out)
    return dict(out)

def _warm_trade_routing_caches():
    """Load routing/config facts before the first operator click."""
    c=None
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT u.username,m.role,m.platform,m.login,m.server,m.bridge_url,m.conn_mode
                       FROM mt_accounts m JOIN users u ON u.id=m.user_id
                       WHERE m.role IN ('main','hedge') AND m.enabled""")
        reg={}
        for row in cur.fetchall():
            item=dict(row); username=str(item.pop("username")); role=str(item.pop("role"))
            reg.setdefault(username,{})[role]=item
        cur.execute("""SELECT u.username,pt.* FROM param_templates pt
                       JOIN users u ON u.id=pt.user_id""")
        templates={}
        for row in cur.fetchall():
            item=dict(row); username=str(item.pop("username")); symbol=str(item.get("symbol") or "XAUUSD")
            item["username"]=username; templates[(username,symbol)]=item
        _USER_REG_ROWS_CACHE.update(reg)
        _TRADE_TMPL_CACHE.update(templates)
    except Exception as ex:
        print("trade routing cache warm err",ex)
    finally:
        if c is not None:
            try: c.close()
            except Exception: pass

@app.on_event("startup")
async def _trade_routing_cache_boot():
    await _aio.to_thread(_warm_trade_routing_caches)

def _poslist(pl):
    """归一化 bridge 持仓返回为 list。"""
    if isinstance(pl,dict): return pl.get("positions",pl) if isinstance(pl.get("positions",pl),list) else []
    return pl or []


def _normalize_position_legs(pos):
    """Normalize broker leg rows and mark ambiguous cross-leg tickets.

    Ticket identifiers are only authoritative within one broker account.  A
    bridge bug can nevertheless echo one leg into the other; retaining the
    rows is useful for recovery, but they must never be counted as a pair.
    The marker is consumed by the UI and by reconciliation helpers.
    """
    out = {"main": [], "hedge": []}
    for leg in ("main", "hedge"):
        rows = []
        seen = {}
        for value in _poslist((pos or {}).get(leg)):
            if not isinstance(value, dict):
                continue
            row = dict(value)
            ticket = str(row.get("ticket") or row.get("order") or "").strip()
            if ticket:
                row["ticket"] = row.get("ticket") or ticket
                previous = seen.get(ticket)
                if previous is not None:
                    # Keep the freshest duplicate; duplicate rows otherwise
                    # inflate lots and can make a single leg look paired.
                    def _fresh(item):
                        try:
                            return float(item.get("time") or item.get("time_open") or 0)
                        except (TypeError, ValueError):
                            return 0.0
                    if _fresh(row) > _fresh(previous):
                        index = rows.index(previous)
                        rows[index] = row
                        seen[ticket] = row
                    continue
                seen[ticket] = row
            rows.append(row)
        out[leg] = rows

    main_by_ticket = {
        str(row.get("ticket") or row.get("order") or "").strip(): row
        for row in out["main"]
        if str(row.get("ticket") or row.get("order") or "").strip()
    }
    for row in out["hedge"]:
        ticket = str(row.get("ticket") or row.get("order") or "").strip()
        if ticket and ticket in main_by_ticket:
            row["pair_ticket_conflict"] = True
            main_by_ticket[ticket]["pair_ticket_conflict"] = True
    return out


def _ambiguous_pair_tickets(main, hedge):
    """A pair action requires two present, distinct, conflict-free tickets."""
    if not isinstance(main,dict) or not isinstance(hedge,dict):
        return False
    mt=str(main.get("ticket") or main.get("order") or "").strip()
    ht=str(hedge.get("ticket") or hedge.get("order") or "").strip()
    return (not mt or not ht or mt==ht or bool(main.get("pair_ticket_conflict"))
            or bool(hedge.get("pair_ticket_conflict")))

def _entry_position_limits(username):
    """Return configured per-leg position limits. None marks an invalid configured value."""
    limits={}
    for leg in ("main","hedge"):
        raw=R.get(RNS+"position_limit:%s:%s"%(username,leg))
        if raw is None or str(raw).strip()=="":
            continue
        try:
            value=int(str(raw).strip())
            limits[leg]=value if value>=0 else None
        except (TypeError,ValueError):
            limits[leg]=None
    return limits

_ENTRY_CAPACITY_RESERVATION_TTL=max(30,min(300,int(os.environ.get(
    "QH_ENTRY_CAPACITY_RESERVATION_TTL","180"))))
_ENTRY_CAPACITY_LOCAL_HOLD_FAILURES=set()

def _entry_capacity_reservation_keys(username):
    scope=(username or "").strip()
    return (RNS+"entry_capacity:reservations:"+scope,
            RNS+"entry_capacity:reservation_expiry:"+scope,
            RNS+"entry_capacity:epoch:"+scope)

def _entry_capacity_hold_failure_key(username):
    return RNS+"entry_capacity:hold_failures:"+((username or "").strip())

def _entry_capacity_hold_failures(username):
    scope=(username or "").strip()
    if any(item[0]==scope for item in _ENTRY_CAPACITY_LOCAL_HOLD_FAILURES):
        return True
    try:
        return bool(R.hlen(_entry_capacity_hold_failure_key(scope)))
    except Exception:
        # Admission must stop when the durable ambiguity latch cannot be read.
        return True

def _record_entry_capacity_hold_failure(username, reservation_id, reason):
    scope=(username or "").strip(); reservation_id=str(reservation_id or "")
    if not scope or not reservation_id:
        return
    _ENTRY_CAPACITY_LOCAL_HOLD_FAILURES.add((scope,reservation_id))
    payload={"reservation_id":reservation_id,"username":scope,
             "reason":str(reason or "capacity_hold_failed")[:180],
             "ts":_dt.datetime.utcnow().isoformat()}
    try:
        R.hset(_entry_capacity_hold_failure_key(scope),reservation_id,
               json.dumps(payload,sort_keys=True,separators=(",",":")))
    except Exception:
        pass
    try: _halt_auto_entry(scope,"capacity_hold_failed",payload)
    except Exception: pass

def _clear_entry_capacity_hold_failure(username, reservation_id):
    scope=(username or "").strip(); reservation_id=str(reservation_id or "")
    _ENTRY_CAPACITY_LOCAL_HOLD_FAILURES.discard((scope,reservation_id))
    try: R.hdel(_entry_capacity_hold_failure_key(scope),reservation_id)
    except Exception: pass

def _entry_owner_tickets(username, leg):
    """Return persisted account ticket ownership, or None when Redis is unreadable."""
    scope=(username or "").strip()
    if not scope:
        return None
    tickets=set()
    try:
        pattern=RNS+"slotowner:"+scope+":"+leg+":*"
        for key in R.scan_iter(match=pattern,count=100):
            for raw_ticket in (R.hgetall(key) or {}).keys():
                try: ticket=int(raw_ticket)
                except (TypeError,ValueError): continue
                if ticket>0: tickets.add(ticket)
        return tickets
    except Exception:
        return None

def _entry_capacity_counts(username, positions):
    """Count the union of broker-visible and durably owned tickets per leg."""
    counts={}
    for leg in ("main","hedge"):
        raw=(positions or {}).get(leg) if isinstance(positions,dict) else None
        items=raw.get("positions") if isinstance(raw,dict) else raw
        if not isinstance(items,list):
            counts[leg]=None
            continue
        tickets=set(); anonymous=0
        for row in items:
            if not isinstance(row,dict):
                anonymous+=1; continue
            try: ticket=int(row.get("ticket") or row.get("order") or 0)
            except (TypeError,ValueError): ticket=0
            if ticket>0: tickets.add(ticket)
            else: anonymous+=1
        owners=_entry_owner_tickets(username,leg)
        counts[leg]=(None if owners is None else len(tickets|owners)+anonymous)
    return counts

def _entry_capacity_guard_from_positions(username, positions, requested=1, limits=None):
    """Return a fail-closed capacity violation, or None when dispatch is allowed."""
    limits=_entry_position_limits(username) if limits is None else limits
    if not limits:
        return None
    try: requested=int(requested)
    except (TypeError,ValueError):
        return {"reason":"invalid_capacity_request","requested":requested}
    if requested<1:
        return {"reason":"invalid_capacity_request","requested":requested}
    counts=_entry_capacity_counts(username,positions)
    for leg,limit in limits.items():
        if limit is None:
            return {"reason":"invalid_position_limit","leg":leg,"limit":None,"requested":requested}
        occupied=counts.get(leg)
        if occupied is None:
            return {"reason":"position_read_unavailable","leg":leg,"limit":limit,"requested":requested}
        if occupied+requested>limit:
            return {"reason":"position_limit_reached","leg":leg,"occupied":occupied,
                    "limit":limit,"requested":requested}
    return None

def _reserve_entry_capacity(username, positions, reservations, limits=None):
    """Atomically admit actual queued jobs against positions plus pending opens."""
    limits=_entry_position_limits(username) if limits is None else limits
    reservations=[dict(item) for item in (reservations or []) if isinstance(item,dict)]
    if not limits:
        return None
    if _entry_capacity_hold_failures(username):
        return {"reason":"capacity_hold_unresolved","requested":len(reservations)}
    if not reservations:
        return {"reason":"invalid_capacity_request","requested":0}
    for leg,limit in limits.items():
        if limit is None:
            return {"reason":"invalid_position_limit","leg":leg,"limit":None,
                    "requested":len(reservations)}
        raw=(positions or {}).get(leg) if isinstance(positions,dict) else None
        items=raw.get("positions") if isinstance(raw,dict) else raw
        if not isinstance(items,list):
            return {"reason":"position_read_unavailable","leg":leg,"limit":limit,
                    "requested":len(reservations)}
    now_ms=int(_t_conn.time()*1000); expires_ms=now_ms+_ENTRY_CAPACITY_RESERVATION_TTL*1000
    records={}
    for item in reservations:
        reservation_id=str(item.get("reservation_id") or item.get("job_id") or "")
        if not reservation_id:
            return {"reason":"invalid_capacity_reservation","requested":len(reservations)}
        record={
            "reservation_id":reservation_id,"job_id":str(item.get("job_id") or reservation_id),
            "batch_id":str(item.get("batch_id") or ""),"username":str(username or ""),
            "symbol":str(item.get("symbol") or ""),"slot":int(item.get("slot") or 0),
            "slot_token":str(item.get("slot_token") or ""),
            "position_limits":limits,"created_ms":now_ms,
        }
        if record["slot"]<1 or not record["slot_token"]:
            return {"reason":"invalid_capacity_reservation","requested":len(reservations)}
        records[reservation_id]=json.dumps(record,sort_keys=True,separators=(",",":"))
    keys=_entry_capacity_reservation_keys(username)
    for _attempt in range(8):
        pipe=R.pipeline(transaction=True)
        try:
            pipe.watch(*keys)
            # Owner persistence and reservation release share the epoch key.
            # Recount after WATCH so an A-fill/release cannot leave B admitting
            # against a snapshot taken before A became durably owned.
            counts=_entry_capacity_counts(username,positions)
            for leg,limit in limits.items():
                if counts.get(leg) is None:
                    pipe.unwatch()
                    return {"reason":"position_owner_read_unavailable","leg":leg,
                            "limit":limit,"requested":len(reservations)}
            raw_records=pipe.hgetall(keys[0]) or {}
            expired_raw=pipe.zrangebyscore(keys[1],"-inf",now_ms) or []
            active_z_raw=pipe.zrangebyscore(keys[1],now_ms,"+inf") or []
            def _text(value):
                return value.decode("utf-8","replace") if isinstance(value,bytes) else str(value)
            expired={_text(value) for value in expired_raw}
            active_ids=({_text(value) for value in raw_records.keys()}|
                        {_text(value) for value in active_z_raw})-expired
            adding={reservation_id for reservation_id in records if reservation_id not in active_ids}
            pending=len(active_ids)
            for leg,limit in limits.items():
                occupied=int(counts.get(leg) or 0)
                if occupied+pending+len(adding)>limit:
                    pipe.unwatch()
                    return {"reason":"position_limit_reserved","leg":leg,
                            "occupied":occupied,"pending":pending,
                            "requested":len(adding),"limit":limit}
            pipe.multi()
            if expired:
                pipe.hdel(keys[0],*sorted(expired))
                pipe.zrem(keys[1],*sorted(expired))
            pipe.hset(keys[0],mapping=records)
            pipe.zadd(keys[1],{reservation_id:expires_ms for reservation_id in records})
            pipe.execute()
            return None
        except redis.exceptions.WatchError:
            continue
        except Exception as ex:
            return {"reason":"capacity_reservation_unavailable","detail":ex.__class__.__name__,
                    "requested":len(reservations)}
        finally:
            pipe.reset()
    return {"reason":"capacity_reservation_contention","requested":len(reservations)}

def _entry_capacity_reservation_valid(job, limits=None):
    if not isinstance(job,dict) or not job.get("job_id"):
        return False
    limits=_entry_position_limits(job.get("username")) if limits is None else limits
    if not limits:
        return True
    reservation_id=str(job.get("job_id"))
    try:
        keys=_entry_capacity_reservation_keys(job.get("username"))
        raw=R.hget(keys[0],reservation_id); score=R.zscore(keys[1],reservation_id)
        record=json.loads(raw) if raw else None
        if not isinstance(record,dict) or score is None or float(score)<=_t_conn.time()*1000:
            return False
        return (
            record.get("reservation_id")==reservation_id and
            record.get("job_id")==reservation_id and
            record.get("batch_id")==str(job.get("batch_id") or "") and
            record.get("username")==str(job.get("username") or "") and
            record.get("symbol")==str(job.get("symbol") or "") and
            int(record.get("slot") or 0)==int(job.get("slot") or 0) and
            record.get("slot_token")==str(job.get("slot_token") or "") and
            record.get("position_limits")==limits)
    except Exception:
        return False

def _reserve_entry_capacity_for_job(username, positions, job, limits=None):
    if not isinstance(job,dict):
        return {"reason":"invalid_capacity_reservation","requested":1}
    return _reserve_entry_capacity(username,positions,[{
        "reservation_id":job.get("job_id"),"job_id":job.get("job_id"),
        "batch_id":job.get("batch_id"),"symbol":job.get("symbol"),
        "slot":job.get("slot"),"slot_token":job.get("slot_token"),
    }],limits=limits)

def _release_entry_capacity_reservation(username, reservation_id):
    if not username or not reservation_id:
        return False
    try:
        keys=_entry_capacity_reservation_keys(username)
        pipe=R.pipeline(transaction=True)
        pipe.hdel(keys[0],str(reservation_id))
        pipe.zrem(keys[1],str(reservation_id))
        pipe.hdel(_entry_capacity_hold_failure_key(username),str(reservation_id))
        pipe.incr(keys[2])
        result=pipe.execute()
        _ENTRY_CAPACITY_LOCAL_HOLD_FAILURES.discard(
            ((username or "").strip(),str(reservation_id)))
        return bool(result and result[0])
    except Exception:
        return False

def _hold_entry_capacity_reservation(username, reservation_id):
    """Keep ambiguous broker outcomes reserved until authoritative repair."""
    if not username or not reservation_id:
        return False
    reservation_id=str(reservation_id)
    try:
        limits=_entry_position_limits(username)
    except Exception as ex:
        _record_entry_capacity_hold_failure(
            username,reservation_id,"limit_read:%s"%ex.__class__.__name__)
        return False
    if not limits:
        _clear_entry_capacity_hold_failure(username,reservation_id)
        return True
    keys=_entry_capacity_reservation_keys(username); now_ms=int(_t_conn.time()*1000)
    for _attempt in range(8):
        pipe=R.pipeline(transaction=True)
        try:
            pipe.watch(*keys)
            raw=pipe.hget(keys[0],reservation_id)
            if raw is None:
                # A process can die after broker dispatch but after the normal
                # reservation TTL boundary.  Reconstruct a conservative
                # placeholder so unresolved exposure continues to count.
                record={
                    "reservation_id":reservation_id,"job_id":reservation_id,
                    "batch_id":"","username":str(username),"symbol":"",
                    "slot":0,"slot_token":"","position_limits":limits,
                    "created_ms":now_ms,"recovered_hold":True,
                }
            pipe.multi()
            if raw is None:
                pipe.hset(keys[0],reservation_id,
                          json.dumps(record,sort_keys=True,separators=(",",":")))
            # 9999-12-31 UTC in epoch milliseconds; cleanup must be explicit.
            pipe.zadd(keys[1],{reservation_id:253402300799000})
            pipe.hdel(_entry_capacity_hold_failure_key(username),reservation_id)
            pipe.incr(keys[2])
            pipe.execute()
            _ENTRY_CAPACITY_LOCAL_HOLD_FAILURES.discard(
                ((username or "").strip(),reservation_id))
            return True
        except redis.exceptions.WatchError:
            continue
        except Exception as ex:
            _record_entry_capacity_hold_failure(
                username,reservation_id,"hold:%s"%ex.__class__.__name__)
            return False
        finally:
            pipe.reset()
    _record_entry_capacity_hold_failure(username,reservation_id,"hold_contention")
    return False

def _ensure_entry_capacity_hold(username, reservation_id, job):
    """Restore a lost dispatched-open reservation and make it permanent."""
    try:
        limits=_entry_position_limits(username)
    except Exception as ex:
        _record_entry_capacity_hold_failure(
            username,reservation_id,"ensure_limit_read:%s"%ex.__class__.__name__)
        return False
    if not limits:
        return True
    if not username or not reservation_id or not isinstance(job,dict):
        return False
    reservation_id=str(reservation_id)
    try:
        slot=int(job.get("slot") or 0)
    except (TypeError,ValueError):
        return False
    record={
        "reservation_id":reservation_id,"job_id":str(job.get("job_id") or ""),
        "batch_id":str(job.get("batch_id") or ""),"username":str(username),
        "symbol":str(job.get("symbol") or ""),"slot":slot,
        "slot_token":str(job.get("slot_token") or ""),
        "position_limits":limits,"created_ms":int(_t_conn.time()*1000),
    }
    if (record["job_id"]!=reservation_id or slot<1 or not record["batch_id"] or
            not record["symbol"] or not record["slot_token"]):
        return False
    keys=_entry_capacity_reservation_keys(username)
    encoded=json.dumps(record,sort_keys=True,separators=(",",":"))
    for _attempt in range(8):
        pipe=R.pipeline(transaction=True)
        try:
            pipe.watch(*keys)
            current=pipe.hget(keys[0],reservation_id)
            if current:
                try: existing=json.loads(current)
                except (TypeError,ValueError): existing=None
                identity=("reservation_id","job_id","batch_id","username",
                          "symbol","slot","slot_token","position_limits")
                if (not isinstance(existing,dict) or
                        any(existing.get(name)!=record.get(name) for name in identity)):
                    pipe.unwatch()
                    _record_entry_capacity_hold_failure(
                        username,reservation_id,"reservation_identity_mismatch")
                    return False
            pipe.multi()
            if not current:
                pipe.hset(keys[0],reservation_id,encoded)
            pipe.zadd(keys[1],{reservation_id:253402300799000})
            pipe.hdel(_entry_capacity_hold_failure_key(username),reservation_id)
            pipe.incr(keys[2])
            pipe.execute()
            stored=R.hget(keys[0],reservation_id); score=R.zscore(keys[1],reservation_id)
            held=bool(stored and score is not None and float(score)>=253402300799000)
            if held:
                _ENTRY_CAPACITY_LOCAL_HOLD_FAILURES.discard(
                    ((username or "").strip(),reservation_id))
            return held
        except redis.exceptions.WatchError:
            continue
        except Exception as ex:
            _record_entry_capacity_hold_failure(
                username,reservation_id,"ensure:%s"%ex.__class__.__name__)
            return False
        finally:
            pipe.reset()
    _record_entry_capacity_hold_failure(username,reservation_id,"ensure_contention")
    return False

def _entry_result_capacity_violation(res):
    """Recognize MT5 position-limit terminal failures without depending on result shape."""
    for leg in ("main","hedge"):
        payload=(res or {}).get(leg) if isinstance(res,dict) else None
        try: text=json.dumps(payload,ensure_ascii=False,default=str).lower()
        except Exception: text=str(payload).lower()
        if "10040" in text or "position limit reached" in text:
            return {"reason":"broker_position_limit","leg":leg,"broker_detail":text[:500]}
    return None

def _halt_auto_entry(username, reason, detail=None):
    """Latch account-wide faults globally and slot risks only to their slot."""
    if not username: return
    detail=detail if isinstance(detail,dict) else {}
    try: slot=int(detail.get("slot") or 0)
    except (TypeError,ValueError): slot=0
    slot_scoped=(slot>0 and reason in (
        "single_leg_exposed","slotowner_persist_failed"))
    payload={"ts":_dt.datetime.utcnow().isoformat(),"username":username,"reason":reason,
             "scope":("slot" if slot_scoped else "account"),"slot":slot or None,
             "detail":detail}
    try:
        if slot_scoped:
            symbol=str(detail.get("symbol") or "XAUUSD")
            R.set(RNS+"auto_entry:slot_halt:%s:%s:%d"%(username,symbol,slot),
                  json.dumps(payload,ensure_ascii=False,default=str))
        else:
            R.set(RNS+"auto_entry:"+username,"off")
        R.set(RNS+"auto_entry:halt:"+username,json.dumps(payload,ensure_ascii=False,default=str))
        warn_key=RNS+"auto_entry:halt_warn:%s:%s"%(username,reason)
        if R.set(warn_key,"1",nx=True,ex=300):
            message=("坑%d自动进场已暂停: %s"%(slot,reason) if slot_scoped else
                     "自动进场已熔断: %s"%reason)
            _push_alert("err",message,username)
    except Exception: pass

def _latch_entry_capacity(username, violation, source):
    if not violation: return False
    payload=dict(violation); payload["source"]=source
    payload["ts"]=_dt.datetime.utcnow().isoformat(); payload["username"]=username
    try:
        R.set(RNS+"position_limit:blocked:"+username,
              json.dumps(payload,ensure_ascii=False,default=str))
    except Exception: pass
    _halt_auto_entry(username,"position_capacity",payload)
    return True

def _entry_capacity_latch_result(username, res, source="broker_result"):
    return _latch_entry_capacity(username,_entry_result_capacity_violation(res),source)

async def _count_filled_slots(symbol="XAUUSD"):
    """当前已填坑位数 = 主腿持仓笔数(每坑=一笔配对, 顺序填充)。取不到→None(fail-closed)。
       api 模式并入 in-flight 票(A2T 读滞后期间防重复开仓)。"""
    try:
        pos=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        if not pos: return None
        return len(_poslist(pos.get("main")))
    except Exception:
        return None

_POSITION_READ_RETRY_DELAYS=(0.05,)
_POSITION_READ_ATTEMPT_TIMEOUT=0.45

async def _read_position_leg(legobj, authoritative=False):
    """Read a leg, requesting broker truth when the connector supports it."""
    if legobj is None:
        raise RuntimeError("bridge unavailable")
    positions=getattr(legobj,"positions",None)
    if not callable(positions):
        raise RuntimeError("positions unavailable")
    if authoritative:
        explicit=getattr(legobj,"positions_authoritative",None)
        if callable(explicit):
            return await explicit()
        try:
            if "authoritative" in _inspect.signature(positions).parameters:
                return await positions(authoritative=True)
        except (TypeError,ValueError):
            pass
        # Compatibility with the current MT4/MT5 bridge connector. UI reads
        # keep using positions(); only a pre-dispatch worker reaches this path.
        if (legobj.__class__.__name__=="_BridgeLeg" and
                callable(getattr(legobj,"_get",None))):
            return await legobj._get("/mt5/positions",authoritative="true")
    return await positions()


async def _read_both_positions_with_retry(conn, authoritative=False):
    """Bounded read-only retry for a bridge snapshot that is converging."""
    last_error=None
    for attempt in range(len(_POSITION_READ_RETRY_DELAYS)+1):
        try:
            if authoritative:
                main=getattr(conn,"main",None); hedge=getattr(conn,"hedge",None)
                if main is None:
                    return None
                if hedge is not None:
                    values=await _aio.wait_for(_aio.gather(
                        _read_position_leg(main,True),
                        _read_position_leg(hedge,True)),
                        timeout=_POSITION_READ_ATTEMPT_TIMEOUT)
                    pos={"main":values[0],"hedge":values[1]}
                else:
                    pos={"main":await _aio.wait_for(
                        _read_position_leg(main,True),
                        timeout=_POSITION_READ_ATTEMPT_TIMEOUT),"hedge":None}
            else:
                if not hasattr(conn,"both_positions"):
                    return None
                pos=await _aio.wait_for(
                    conn.both_positions(),timeout=_POSITION_READ_ATTEMPT_TIMEOUT)
            if pos is None:
                raise RuntimeError("positions unavailable")
            return pos
        except Exception as ex:
            last_error=ex
            if attempt>=len(_POSITION_READ_RETRY_DELAYS):
                raise
            await _aio.sleep(_POSITION_READ_RETRY_DELAYS[attempt])
    raise last_error

async def _occupied_slots(symbol="XAUUSD", username=None, include_positions=False,
                          authoritative=False):
    """当前已占坑号 set(经稳定坑号映射; 支持跳空)。取不到→None(fail-closed)。多租户: username→读该用户腿。"""
    try:
        _cn=_user_exec_conn(username)
        pos=await _read_both_positions_with_retry(
            _cn,authoritative=authoritative)
        if pos is None: return (None,None) if include_positions else None
        ann=_annotate_slots(pos, symbol, username)
        occ=set()
        for leg in ("main","hedge"):
            for p in (ann.get(leg) or []):
                s=int(p.get("slot") or 0)
                if s>0: occ.add(s)
            # Authoritative owners remain occupied through transient empty
            # snapshots, preventing display-map gaps from admitting a second
            # live pair into the same slot.
            try:
                for key in (_slotmap_key(leg,symbol,username),
                            _slotowner_key(leg,symbol,username)):
                    for value in (R.hgetall(key) or {}).values():
                        s=int(value or 0)
                        if s>0: occ.add(s)
            except Exception: pass
        return (occ,pos) if include_positions else occ
    except Exception:
        return (None,None) if include_positions else None

def _durable_occupied_slots(symbol, username, ladders):
    """Return conservative local occupancy without performing bridge I/O."""
    try:
        limit=int(ladders)
        occupied=set()
        for leg in ("main","hedge"):
            for key in (_slotmap_key(leg,symbol,username),
                        _slotowner_key(leg,symbol,username)):
                for raw_slot in (R.hgetall(key) or {}).values():
                    slot=int(raw_slot or 0)
                    if 1<=slot<=limit:
                        occupied.add(slot)
        for job in TRADE_QUEUE.slot_states(
                username,symbol,range(1,limit+1)):
            state=str(job.get("state") or "UNKNOWN").upper()
            if state not in ("COMPLETED","FAILED"):
                slot=int(job.get("slot") or 0)
                if 1<=slot<=limit:
                    occupied.add(slot)
        return occupied
    except Exception as ex:
        raise HTTPException(
            503,"LOCAL_POSITION_OWNERSHIP_UNAVAILABLE: %s"%ex.__class__.__name__)

def _next_empty_slot(occ, ladders):
    """最小空缺坑号(1..ladders; ladders<=0 视为不限)。occ=已占坑号 set。"""
    occ=occ or set()
    k=1
    while (ladders<=0 or k<=ladders):
        if k not in occ: return k
        k+=1
    return None   # 阶梯已满

_CSIZE={"XAUUSD":100.0}   # Defaults plus per-user "username:symbol" contract metadata.

# ---- 报价归一(批33功能1):data_mult_main/hedge 按腿因子乘 bid/ask,对齐两券商价格标度 ----
_NORM_CACHE = {"ts": 0.0, "snapshot": {}}
def _norm_factors():
    try:
        rows = DB.execute("""
            SELECT u.username, pt.data_mult_main, pt.data_mult_hedge, pt.data_mult
            FROM param_templates pt JOIN users u ON pt.user_id=u.id ORDER BY pt.id
        """).fetchall()
        out = {}
        by_user = {}
        for r in rows:
            un = r[0]; key = (un, "main"); key_h = (un, "hedge")
            if key not in by_user:
                out[key] = float(r[1] or r[3] or 1.0) if r[1] or r[3] else 1.0
                out[key_h] = float(r[2] or r[3] or 1.0) if r[2] or r[3] else 1.0
                by_user[key] = by_user[key_h] = True
        if rows:
            r0 = rows[0]
            out[("*", "main")] = float(r0[1] or r0[3] or 1.0) if r0[1] or r0[3] else 1.0
            out[("*", "hedge")] = float(r0[2] or r0[3] or 1.0) if r0[2] or r0[3] else 1.0
        return out
    except Exception:
        return _NORM_CACHE.get("snapshot", {})
def _norm_pick(role, username):
    now = _t_conn.time()
    if now - _NORM_CACHE["ts"] > 5.0:
        _NORM_CACHE["snapshot"] = _norm_factors()
        _NORM_CACHE["ts"] = now
    un_k = (username if username else "*", role)
    f = _NORM_CACHE["snapshot"].get(un_k)
    try:
        f = float(f or 1.0)
        return f if f > 0 else 1.0
    except Exception:
        return 1.0
def _norm_tick(tk, role, username):
    if not tk or not isinstance(tk, dict):
        return tk
    f = _norm_pick(role, username)
    if abs(f - 1.0) < 1e-9:
        return tk
    out = dict(tk)
    if "bid" in out and out["bid"] is not None:
        try:
            out["bid"] = float(out["bid"]) * f
        except Exception:
            pass
    if "ask" in out and out["ask"] is not None:
        try:
            out["ask"] = float(out["ask"]) * f
        except Exception:
            pass
    return out
def _norm_price(price, role, username):
    if price is None:
        return price
    f = _norm_pick(role, username)
    try:
        return float(price) * f
    except Exception:
        return price

def _pnl_to_points(pnl, vol, symbol="XAUUSD", username=""):
    """配对净盈亏($) → 点差净盈亏点数 = pnl /(手数×面值)。盈利/止损点位按此口径比较, 跨坑手数一致。"""
    try:
        cs=float(_CSIZE.get((str(username)+":"+symbol) if username else "")
                 or _CSIZE.get(symbol) or 100.0)
        v=abs(float(vol or 0))
        return (float(pnl)/(v*cs)) if (v>0 and cs>0) else float(pnl)
    except Exception: return pnl
def _round_pts(pts, digits_main, digits_hedge):
    """按较粗腿精度round点数(批33功能2)。两字段都参与,min(dm,dh)定精度;非法→不round。"""
    try:
        dm = int(digits_main or 2)
        dh = int(digits_hedge or 2)
        d = min(dm, dh)
        if d < 0:
            return pts
        return round(float(pts), d)
    except Exception:
        return pts
def _bj_hm():
    """当前北京时间 分钟数(0..1439)。"""
    n=_dt.datetime.utcnow()+_dt.timedelta(hours=8)
    return n.hour*60+n.minute
def _in_window(start, end, now_min=None):
    """时间窗判定(北京 "HH:MM"): 空/未设→True; 支持跨零点(start>end)。start==end→True(视为全天)。"""
    def _p(s):
        try:
            s=(s or "").strip()
            if not s or ":" not in s: return None
            h,m=s.split(":",1); return int(h)*60+int(m)
        except Exception: return None
    a=_p(start); b=_p(end)
    if a is None or b is None: return True   # 未设=全时段
    if a==b: return True
    if now_min is None: now_min=_bj_hm()
    if a<b: return a<=now_min<b
    return now_min>=a or now_min<b            # 跨零点

def _open_saga_ticket_slots(username, symbol, positions=None):
    """Return exact ticket->target-slot claims from recoverable open sagas.

    Display mappings are intentionally not trusted on their own.  This small
    index is used when either a durable saga has already proven both broker
    fills or an active queue job has durably recorded its dispatch intent. The
    latter window is needed while a normal ``main_first`` request is between
    its broker ACKs; its exact pair marker still distinguishes it from an
    unrelated live position.
    """
    # Keep job provenance until the whole scan has finished.  Resolving each
    # row immediately would let Redis scan order choose an ambiguous slot.
    claim_records = []
    seen_records = set()
    seen_jobs = set()
    job_identities = set()
    observed = {"main": {}, "hedge": {}}
    for leg in ("main", "hedge"):
        for row in _poslist((positions or {}).get(leg)):
            if not isinstance(row, dict):
                continue
            ticket = _exact_positive_int(row.get("ticket") or row.get("order"))
            if ticket is not None:
                observed[leg][str(ticket)] = str(row.get("comment") or "")

    def add_claim(job_id, pair_rid, leg, ticket, target_slot):
        ticket = _exact_positive_int(ticket)
        target_slot = _exact_positive_int(target_slot)
        if (not job_id or not pair_rid or leg not in ("main", "hedge") or
                ticket is None or target_slot is None):
            return
        record = (str(job_id), str(pair_rid), str(leg), str(ticket),
                  int(target_slot))
        if record not in seen_records:
            seen_records.add(record)
            claim_records.append(record)

    def active_intent(job):
        """Validate the pre-saga broker boundary without trusting result data."""
        if str(job.get("state") or "").upper() not in (
                "EXECUTING", "DISPATCHING"):
            return None
        if not _trade_bool(job.get("dispatch_intent")):
            return None
        pair_rid = str(job.get("pair_rid") or "").strip()
        slot = _exact_positive_int(job.get("slot"))
        payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
        intended_slot = _exact_positive_int(payload.get("intended_slot"))
        if (not pair_rid or slot is None or intended_slot is None or
                int(slot) != int(intended_slot)):
            return None
        context = job.get("context") if isinstance(job.get("context"), dict) else {}
        if ("pair_rid" in context and
                str(context.get("pair_rid") or "").strip() != pair_rid):
            return None
        result = job.get("result") if isinstance(job.get("result"), dict) else {}
        evidence = result.get("evidence") if isinstance(result.get("evidence"), dict) else None
        for candidate in (result, evidence):
            if (isinstance(candidate, dict) and
                    candidate.get("request_id") not in (None, "") and
                    str(candidate.get("request_id") or "").strip() != pair_rid):
                return None
        return pair_rid, int(slot)

    queue = globals().get("TRADE_QUEUE")
    redis_client = getattr(queue, "redis", None)
    if redis_client is None or redis_client is not R:
        return {}
    try:
        namespace = str(getattr(queue, "namespace", RNS + "tradeq:"))
        # Slot pointers are bounded by the configured entry quantity (1..20)
        # and already track in-flight/review jobs.  Scanning all retained job
        # hashes on every positions poll would recreate avoidable UI latency.
        pattern = namespace + "slot:%s:%s:*" % (str(username), str(symbol))
        for raw_key in redis_client.scan_iter(match=pattern, count=50):
            key = (raw_key.decode("utf-8", "replace")
                   if isinstance(raw_key, bytes) else str(raw_key))
            raw_job_id = redis_client.get(key)
            if isinstance(raw_job_id, bytes):
                raw_job_id = raw_job_id.decode("utf-8", "replace")
            job = queue.get_job(str(raw_job_id or ""))
            if not isinstance(job, dict):
                continue
            if (str(job.get("op") or "") != "open_pair" or
                    str(job.get("username") or "") != str(username) or
                    str(job.get("symbol") or "XAUUSD") != str(symbol)):
                continue
            job_id = str(job.get("job_id") or raw_job_id or "").strip()
            if not job_id or job_id in seen_jobs:
                continue
            seen_jobs.add(job_id)
            durable = _open_saga_job(job)
            active = active_intent(job)
            if not durable and active is None:
                continue
            if durable:
                target_slot = _exact_positive_int(job.get("slot"))
                if target_slot is None:
                    continue
                context = _trade_queue_recovery_context(job)
                result = _trade_queue_recovery_result(job, context) or {}
                if not isinstance(result, dict):
                    result = {}
                pair_rid = str(job.get("pair_rid") or context.get("pair_rid") or
                               result.get("request_id") or "").strip()
                if pair_rid:
                    job_identities.add((job_id, pair_rid, int(target_slot)))
                for leg in ("main", "hedge"):
                    row = result.get(leg) if isinstance(result.get(leg), dict) else {}
                    tickets = result.get("open_tickets")
                    if not isinstance(tickets, dict):
                        tickets = result.get("tickets")
                    ticket = _exact_positive_int(
                        row.get("order") or row.get("ticket") or row.get("deal") or
                        (tickets or {}).get(leg) or job.get(leg + "_ticket"))
                    if ticket is not None:
                        add_claim(job_id, pair_rid, leg, ticket, target_slot)
                for leg in ("main", "hedge"):
                    request_id = pair_rid + ("m" if leg == "main" else "h")
                    token = "Q" + hashlib.sha1(request_id.encode()).hexdigest()[:9]
                    for ticket, comment in observed[leg].items():
                        marker_match = ("#" in comment and
                                        comment.rsplit("#", 1)[-1] == pair_rid)
                        token_match = bool(token and token in comment)
                        if marker_match or token_match:
                            add_claim(job_id, pair_rid, leg, ticket, target_slot)
            if active is not None:
                pair_rid, target_slot = active
                job_identities.add((job_id, pair_rid, int(target_slot)))
                for leg in ("main", "hedge"):
                    request_id = pair_rid + ("m" if leg == "main" else "h")
                    token = "Q" + hashlib.sha1(request_id.encode()).hexdigest()[:9]
                    for ticket, comment in observed[leg].items():
                        marker_match = ("#" in comment and
                                        comment.rsplit("#", 1)[-1] == pair_rid)
                        token_match = bool(token and token in comment)
                        if marker_match or token_match:
                            add_claim(job_id, pair_rid, leg, ticket, target_slot)
    except Exception:
        return {}
    invalid_jobs = set()
    by_job_leg = {}
    by_job_ticket = {}
    by_ticket = {}
    by_pair = {}
    by_slot = {}
    for job_id, pair_rid, leg, ticket, target_slot in claim_records:
        by_job_leg.setdefault((job_id, leg), set()).add(ticket)
        by_job_ticket.setdefault((job_id, leg, ticket), set()).add(
            (pair_rid, int(target_slot)))
        by_ticket.setdefault((leg, ticket), set()).add(job_id)
    for job_id, pair_rid, target_slot in job_identities:
        by_pair.setdefault(pair_rid, set()).add(job_id)
        by_slot.setdefault(int(target_slot), set()).add(job_id)
    for key, tickets in by_job_leg.items():
        if len(tickets) != 1:
            invalid_jobs.add(key[0])
    for key, identities in by_job_ticket.items():
        if len(identities) != 1:
            invalid_jobs.add(key[0])
    for groups in (by_ticket, by_pair, by_slot):
        for jobs_for_identity in groups.values():
            if len(jobs_for_identity) > 1:
                invalid_jobs.update(jobs_for_identity)
    claims = {}
    for job_id, _pair_rid, leg, ticket, target_slot in claim_records:
        if job_id not in invalid_jobs:
            claims[(leg, ticket)] = int(target_slot)
    return claims


def _allow_provisional_display_rebind(symbol, bindings, slot, username):
    """Approve only ownerless display collisions explained by another saga."""
    if not username or not bindings:
        return False
    try:
        claims = _open_saga_ticket_slots(username, symbol)
        for leg, ticket in bindings:
            mapkey = _slotmap_key(leg, symbol, username)
            ownerkey = _slotowner_key(leg, symbol, username)
            displays = R.hgetall(mapkey) or {}
            owners = R.hgetall(ownerkey) or {}
            for other, raw_slot in displays.items():
                if str(other) == str(ticket) or _exact_positive_int(raw_slot) != int(slot):
                    continue
                # Any authoritative owner wins.  An ownerless row is safe to
                # remove only when its exact ticket is durably claimed for a
                # different slot by another recoverable saga.
                if str(other) in owners:
                    return False
                source_slot = claims.get((leg, str(other)))
                if source_slot is None or int(source_slot) == int(slot):
                    return False
        return True
    except Exception:
        return False


def _reserve_slot(symbol, res, slot, username=None, grace_sec=60,
                  allow_provisional_display_rebind=False,
                  suppress_failure_side_effects=False):
    """定向开仓后写 ticket→坑号预留(供 _annotate_slots 尊重目标坑而非自动分配最小空缺)。
       票用 order(市价单 position 票); api 模式票不符时 _annotate_slots 回落最小空缺, graceful。"""
    bindings=[]
    for leg in ("main","hedge"):
        lr=((res or {}).get(leg) or {})
        tk=lr.get("order") or lr.get("deal") or lr.get("ticket")
        if tk:
            bindings.append((leg,str(tk)))
    if not bindings:
        return False
    try:
        pending_until=_dt.datetime.utcnow().timestamp()+max(1,int(grace_sec))
        keys=[]; args=[]
        for leg,ticket in bindings:
            keys.extend((_slotowner_key(leg,symbol,username),
                         _slotmap_key(leg,symbol,username),
                         _slotpending_key(leg,symbol,username)))
            args.extend((ticket,str(int(slot)),str(pending_until)))
        keys.append(RNS+"entry_capacity:epoch:"+((username or "").strip()))
        # The final argument is a capability supplied only by durable saga
        # reconciliation after the conflicting display tickets were checked
        # against their own exact saga identities.
        args.append("1" if allow_provisional_display_rebind else "0")
        script="""
        -- qh_atomic_slotowner_reservation
        local owner_key_count=#KEYS-1
        local allow_display_rebind=ARGV[#ARGV] == '1'
        for i=1,owner_key_count,3 do
            local ai=((i-1)/3)*3
            local ticket=ARGV[ai+1]
            local slot=ARGV[ai+2]
            local existing=redis.call('hget',KEYS[i],ticket)
            if existing and existing ~= slot then return -1 end
            local owners=redis.call('hgetall',KEYS[i])
            for j=1,#owners,2 do
                if owners[j] ~= ticket and owners[j+1] == slot then return -2 end
            end
            -- A display-only mapping for this exact fill is provisional.  The
            -- positions poll can observe a fast fill before this transaction
            -- and assign the ticket to the smallest visual gap.  With no
            -- conflicting authoritative owner, this write is the ownership
            -- decision and must atomically rebind that same ticket.
            local displays=redis.call('hgetall',KEYS[i+1])
            for j=1,#displays,2 do
                if displays[j] ~= ticket and displays[j+1] == slot then
                    if not allow_display_rebind or redis.call('hexists',KEYS[i],displays[j]) == 1 then
                        return -4
                    end
                    redis.call('hdel',KEYS[i+1],displays[j])
                end
            end
        end
        for i=1,owner_key_count,3 do
            local ai=((i-1)/3)*3
            redis.call('hset',KEYS[i],ARGV[ai+1],ARGV[ai+2])
            redis.call('hset',KEYS[i+1],ARGV[ai+1],ARGV[ai+2])
            redis.call('zadd',KEYS[i+2],ARGV[ai+3],ARGV[ai+1])
        end
        redis.call('incr',KEYS[#KEYS])
        return 1
        """
        # A fast position poll can create an ownerless display mapping for a
        # newly filled pair before the exact ticket->slot write reaches Redis.
        # That mapping is provisional evidence only.  Once both exact legs
        # are present, retry the same Lua transaction with the atomic rebind
        # capability and a very small bounded backoff.  The script still
        # refuses any authoritative owner collision, so this cannot overwrite
        # a real position claim.  Keeping the retry here means sync, queued,
        # and saga-recovery paths share identical ownership semantics.
        pair_confirmed=(len(bindings)==2 and
                        {leg for leg, _ticket in bindings}=={"main","hedge"} and
                        len({ticket for _leg, ticket in bindings})==2)
        attempts=3 if pair_confirmed else 1
        result=0; last_error=None; used_rebind=False
        for attempt in range(attempts):
            if attempt:
                # The first retry is the provisional-display rebind.  Later
                # retries absorb a concurrent position annotator/releaser
                # without adding visible trade latency.
                time.sleep(0.01 if attempt==1 else 0.03)
            call_args=list(args)
            capability=(allow_provisional_display_rebind or
                        (pair_confirmed and attempt>0))
            call_args[-1]="1" if capability else "0"
            try:
                result=int(R.eval(script,len(keys),*(keys+call_args)) or 0)
                used_rebind=used_rebind or (capability and result==1)
            except Exception as ex:
                last_error=ex
                continue
            if result==1:
                if used_rebind:
                    try:
                        R.incr(RNS+"slotowner:auto_rebind")
                    except Exception:
                        pass
                return True
            # -4 is the ownerless provisional-display race.  -1/-2 can also
            # clear during a concurrent close/reconciliation, so all three
            # conflict codes receive the same bounded retry window.  A final
            # authoritative conflict remains a normal fail-closed outcome.
            if result not in (-4,-2,-1):
                break
        if last_error is not None and result==0:
            raise last_error
        raise RuntimeError("slot ownership conflict (%s)"%result)
    except Exception as ex:
        detail={"username":username,"symbol":symbol,"slot":int(slot),
                "tickets":bindings,"error":ex.__class__.__name__,
                "reason":str(ex)[:160],
                "ts":_dt.datetime.utcnow().isoformat()}
        try:
            R.setex(RNS+"slotowner:persist_error:"+(username or "global"),86400,
                    json.dumps(detail,ensure_ascii=False,default=str))
        except Exception:
            pass
        if not suppress_failure_side_effects:
            try: _halt_auto_entry(username,"slotowner_persist_failed",detail)
            except Exception: pass
            try: _push_alert("err","SLOTOWNER_PERSIST_FAILED: broker fill requires manual ownership review",username)
            except Exception: pass
        return False


async def _reserve_slot_with_recovery(symbol, res, slot, username=None,
                                      grace_sec=60,
                                      allow_provisional_display_rebind=False):
    """Retry local ownership persistence before exposing a filled pair to review."""
    # Broker fills are already authoritative here.  A short async retry window
    # absorbs Redis contention and the positions annotator race without
    # overwriting an authoritative owner collision.
    delays = (0.0, 0.05, 0.15, 0.30, 0.50)
    for attempt, delay in enumerate(delays):
        if delay:
            await _aio.sleep(delay)
        saved = _reserve_slot(
            symbol, res, slot, username, grace_sec=grace_sec,
            allow_provisional_display_rebind=allow_provisional_display_rebind,
            suppress_failure_side_effects=attempt < len(delays) - 1,
        )
        if saved:
            if attempt:
                try:
                    R.incr(RNS + "slotowner:auto_recovery")
                except Exception:
                    pass
            return True
    return False

def _release_slot(symbol, leg, ticket, username=None):
    if not ticket: return False
    ticket=str(ticket)
    try:
        pipe=R.pipeline(transaction=True)
        pipe.hdel(_slotmap_key(leg,symbol,username),ticket)
        pipe.hdel(_slotowner_key(leg,symbol,username),ticket)
        pipe.zrem(_slotpending_key(leg,symbol,username),ticket)
        # 清理迁移前遗留键；ticket 全局唯一，不会误删其他用户仓位。
        if username:
            pipe.hdel(_slotmap_key(leg,symbol),ticket)
            pipe.hdel(_slotowner_key(leg,symbol),ticket)
            pipe.zrem(_slotpending_key(leg,symbol),ticket)
            pipe.incr(_entry_capacity_reservation_keys(username)[2])
        pipe.execute()
        return True
    except Exception:
        return False

def _finalize_closed_tickets_local(symbol, leg_tickets, username=None,
                                   ttl=_CLOSED_TICKET_TTL):
    """Publish close tombstones and release both legs in one Redis transaction."""
    normalized=[(str(leg),str(ticket)) for leg,ticket in (leg_tickets or ())
                if ticket]
    if not normalized:
        return False
    try:
        expires_at=_dt.datetime.utcnow().timestamp()+max(1,int(ttl))
        pipe=R.pipeline(transaction=True)
        for leg,ticket in normalized:
            pipe.zadd(_closed_ticket_key(username,leg,symbol),{ticket:expires_at})
            pipe.hdel(_position_overlay_key(username,leg,symbol),ticket)
            pipe.zrem(_position_overlay_exp_key(username,leg,symbol),ticket)
            pipe.hdel(_slotmap_key(leg,symbol,username),ticket)
            pipe.hdel(_slotowner_key(leg,symbol,username),ticket)
            pipe.zrem(_slotpending_key(leg,symbol,username),ticket)
            if username:
                # Preserve the legacy cleanup and one generation bump per leg.
                pipe.hdel(_slotmap_key(leg,symbol),ticket)
                pipe.hdel(_slotowner_key(leg,symbol),ticket)
                pipe.zrem(_slotpending_key(leg,symbol),ticket)
                pipe.incr(_entry_capacity_reservation_keys(username)[2])
        pipe.execute()
        return True
    except Exception:
        return False

async def _assert_live_tickets(username, symbol, expected, conn=None, expected_slot=None,
                               positions=None, authoritative=False):
    """Fail before dispatch unless exact tickets have an unambiguous live owner."""
    conn=conn or _user_exec_conn(username)
    if not isinstance(expected,dict) or not expected:
        raise HTTPException(400,"EXACT_TICKET_REQUIRED")
    normalized={}
    for leg,ticket in expected.items():
        if leg not in ("main","hedge"):
            raise HTTPException(400,"INVALID_CLOSE_LEG: %s"%leg)
        exact=_exact_positive_int(ticket)
        if exact is None:
            raise HTTPException(400,"EXACT_TICKET_REQUIRED: %s"%leg)
        normalized[leg]=exact
    if len(set(normalized.values()))!=len(normalized):
        raise HTTPException(409,"AMBIGUOUS_POSITION_OWNERSHIP: duplicate ticket across close legs")
    slot=_exact_positive_int(expected_slot) if expected_slot is not None else None
    if expected_slot is not None and slot is None:
        raise HTTPException(400,"SLOT_REQUIRED")

    # Pair closes must prove both accounts from one fresh read. A single-leg
    # emergency close remains scoped to its explicitly selected account. Batch
    # admission may pass one already-read snapshot so every requested slot is
    # checked against the same broker view instead of serializing N HTTP reads.
    read_legs=("main","hedge") if len(normalized)>1 else tuple(normalized)
    def _snapshot_rows(raw):
        if isinstance(raw,list):
            rows=raw
        elif isinstance(raw,dict) and isinstance(raw.get("positions"),list):
            rows=raw.get("positions")
        else:
            return None,"invalid positions payload"
        if any(not isinstance(row,dict) for row in rows):
            return None,"invalid position row"
        return rows,None
    async def _read(leg):
        legobj=getattr(conn,leg,None)
        if legobj is None:
            return leg,None,"bridge unavailable"
        try:
            rows,error=_snapshot_rows(await _read_position_leg(
                legobj,authoritative=authoritative))
            return leg,rows,error
        except Exception as ex:
            return leg,None,ex.__class__.__name__

    def _requested_owners_are_persisted():
        if len(normalized)<=1 or slot is None:
            return False
        try:
            return all(_exact_positive_int(R.hget(
                _slotowner_key(leg,symbol,username),str(ticket)))==slot
                for leg,ticket in normalized.items())
        except Exception:
            return False

    last_failure=None
    attempts=(1 if positions is not None else len(_POSITION_READ_RETRY_DELAYS)+1)
    for attempt in range(attempts):
        if positions is not None:
            reads=[]
            for leg in read_legs:
                raw=(positions or {}).get(leg) if isinstance(positions,dict) else None
                rows,error=_snapshot_rows(raw)
                reads.append((leg,rows,error))
        else:
            try:
                reads=await _aio.wait_for(
                    _aio.gather(*(_read(leg) for leg in read_legs)),
                    timeout=_POSITION_READ_ATTEMPT_TIMEOUT)
            except _aio.TimeoutError:
                reads=[(leg,None,"TimeoutError") for leg in read_legs]
        live={leg:rows for leg,rows,_ in reads}
        failed=["%s:%s"%(leg,error) for leg,_,error in reads if error]
        if failed:
            last_failure=HTTPException(
                502,"持仓校验失败，未发送平仓命令: "+", ".join(failed))
            retryable=True
        else:
            try:
                if len(normalized)>1:
                    return _assert_requested_close_pair({
                        "main":live.get("main") or [],"hedge":live.get("hedge") or [],
                    },symbol,username,normalized,slot)

                leg,ticket=next(iter(normalized.items()))
                live_tickets=[]
                for row in live.get(leg) or []:
                    exact=_exact_positive_int(row.get("ticket") or row.get("order"))
                    if exact is None:
                        raise HTTPException(
                            409,"AMBIGUOUS_POSITION_OWNERSHIP: live row has no exact ticket")
                    live_tickets.append(exact)
                count=live_tickets.count(ticket)
                if count==0:
                    raise HTTPException(
                        409,"持仓已关闭或 ticket 不存在，本次未执行: %s #%s"%(
                            "主腿" if leg=="main" else "对冲腿",ticket))
                if count!=1:
                    raise HTTPException(
                        409,"AMBIGUOUS_POSITION_OWNERSHIP: duplicate live ticket on %s"%leg)
                return True
            except HTTPException as ex:
                last_failure=ex
                retryable=(
                    len(normalized)>1 and ex.status_code==409 and
                    str(ex.detail).startswith("position already closed or ticket missing") and
                    _requested_owners_are_persisted()
                )
        if not retryable or attempt>=len(_POSITION_READ_RETRY_DELAYS):
            raise last_failure
        await _aio.sleep(_POSITION_READ_RETRY_DELAYS[attempt])
    raise last_failure

_SUBSECOND_DEFAULT_USERS = frozenset(("no123", "hedge_pro"))
_SUBSECOND_MT5_DEFAULT_USERS = frozenset(("hedge_pro",))


def _subsecond_user(username):
    """Return users that use the low-latency ordered-trade profile.

    ``hedge_pro`` is the MT5 account paired with the v3 bridge.  It was
    missing from the default allow-list, so its queue jobs retained the
    template's ``fast`` (200 ms inter-leg) profile even though MT4/no123 had
    already been moved to the turbo path.  Keep the environment override for
    operators that need to narrow the profile during a staged rollout.
    """
    configured=os.environ.get("QH_SUBSECOND_USERS")
    raw=(configured if configured is not None else
         ",".join(sorted(_SUBSECOND_DEFAULT_USERS)))
    allowed={x.strip() for x in raw.split(",") if x.strip()}
    return str(username or "").strip() in allowed


def _subsecond_mt5_user(username):
    """Return whether a configured low-latency user is an MT5 account.

    This guard is intentionally separate from ``_subsecond_user``: no123's
    MT4 ordered-entry contract remains unchanged, while hedge_pro can reuse
    the MT5 burst admission path for a single slot.
    """
    normalized=str(username or "").strip()
    configured=os.environ.get("QH_SUBSECOND_MT5_USERS")
    raw=(configured if configured is not None else
         ",".join(sorted(_SUBSECOND_MT5_DEFAULT_USERS)))
    allowed={x.strip() for x in raw.split(",") if x.strip()}
    if normalized not in allowed or not _subsecond_user(normalized):
        return False
    try:
        rows=_reg_rows_for(normalized)
    except Exception:
        return False
    if set(rows or {})!={"main","hedge"}:
        return False
    from urllib.parse import urlsplit
    for leg in ("main","hedge"):
        row=rows.get(leg)
        if not isinstance(row,dict):
            return False
        if str(row.get("platform") or "").strip().upper()!="MT5":
            return False
        if str(row.get("conn_mode") or "").strip().lower()!="bridge":
            return False
        try:
            bridge=urlsplit(str(row.get("bridge_url") or "").strip())
            if (bridge.scheme not in ("http","https") or not bridge.hostname or
                    bridge.username or bridge.password):
                return False
            bridge.port
        except (TypeError,ValueError):
            return False
    return True

def _trade_bool(value):
    """Normalize Redis scalar flags and native booleans consistently."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")

def _entry_tick_cache_ms(username, manual_targeted=False, burst_admission=False):
    """Use pushed quotes for manual admission; the EA still refreshes at OrderSend."""
    if not manual_targeted or not (_subsecond_user(username) or burst_admission):
        return 500
    try:
        return max(500,min(3000,int(os.environ.get(
            "QH_MANUAL_ENTRY_TICK_CACHE_MS","2000"))))
    except (TypeError,ValueError):
        return 2000

def _pair_pending(res):
    res=res or {}; compensation=res.get("compensation") or {}
    durable_open_intent=bool(
        str(res.get("op") or "").lower()=="open" and
        _trade_bool(res.get("saga_durable")) and
        res.get("confirmed_no_fill") is not True and
        any(
            res.get(leg) is None or (
                isinstance(res.get(leg),dict) and
                (res.get(leg) or {}).get("dispatch_started") is False and
                str((res.get(leg) or {}).get("truth_confirmed") or "").lower()
                    not in ("not_filled","no_fill") and
                (res.get(leg) or {}).get("not_filled") is not True and
                not ((res.get(leg) or {}).get("not_sent") and
                     (res.get(leg) or {}).get("dispatch_durable") is False)
            )
            for leg in ("main","hedge")
        )
    )
    return bool(
        res.get("saga_unknown") or
        durable_open_intent or
        compensation.get("pending") or compensation.get("unknown") or
        any(bool((res.get(leg) or {}).get("pending") or
                 (res.get(leg) or {}).get("unknown"))
            for leg in ("main","hedge"))
    )


def _leg_recovered_from_unknown(result):
    """Separate a normal Agent status completion from actual UNKNOWN recovery."""
    result=result if isinstance(result,dict) else {}
    if result.get("recovered_from_unknown"):
        return True
    return bool(
        result.get("recovered") and
        result.get("unknown_resolved") in ("closed","filled","executed")
    )


def _open_pair_explicit_no_fill(res):
    """Accept terminal open failure only from explicit per-leg broker evidence."""
    res=res if isinstance(res,dict) else {}
    if res.get("confirmed_no_fill") is True:
        return not any(_resolved_leg_ok(res,leg) for leg in ("main","hedge"))
    for leg in ("main","hedge"):
        row=res.get(leg) if isinstance(res.get(leg),dict) else {}
        explicit_status=(
            str(row.get("truth_confirmed") or "").lower()=="not_filled" and
            (str(row.get("src") or "").lower()=="order-status" or
             row.get("not_sent") is True)
        )
        explicit_unsent=bool(
            row.get("not_sent") and row.get("dispatch_durable") is False)
        if not (explicit_status or explicit_unsent):
            return False
    return True

def _queue_preflight_ttl_from_env(name, default_ms, minimum, maximum):
    try:
        return max(minimum,min(maximum,float(os.environ.get(name,str(default_ms)))/1000.0))
    except (TypeError,ValueError):
        return float(default_ms)/1000.0

# Open proofs remain short-lived, but must cover the measured admission-to-dispatch
# path. Their slot lock, process nonce, batch identity and capacity reservation are
# still revalidated at dispatch. Close proofs can safely live longer because they
# are additionally bound to immutable exact tickets; an already-closed ticket is
# an idempotent close outcome.
_QUEUE_OPEN_PREFLIGHT_TTL_SECONDS=_queue_preflight_ttl_from_env(
    "QH_QUEUE_OPEN_PREFLIGHT_TTL_MS",2000,0.50,3.00)
_QUEUE_CLOSE_PREFLIGHT_TTL_SECONDS=_queue_preflight_ttl_from_env(
    "QH_QUEUE_CLOSE_PREFLIGHT_TTL_MS",5000,1.00,8.00)

def _queue_preflight_ttl(kind):
    if kind=="open": return _QUEUE_OPEN_PREFLIGHT_TTL_SECONDS
    if kind=="close": return _QUEUE_CLOSE_PREFLIGHT_TTL_SECONDS
    return 0.0

def _new_queue_preflight(kind, username, symbol, slot, slot_token, **evidence):
    proof={
        "version":2,"kind":str(kind),"username":str(username or ""),
        "symbol":str(symbol or ""),"slot":int(slot),
        "slot_token":str(slot_token or ""),"owner":_TRADE_QUEUE_OWNER,
        "process_nonce":_QUEUE_PROOF_PROCESS_NONCE,
        "created_mono":_t_conn.monotonic(),
    }
    proof.update(evidence)
    return proof

def _bind_queue_preflight(proof, batch_id, job_id, reserved_slots,
                          capacity_reservation=False):
    slots=[]
    for raw in (reserved_slots or []):
        try: slot=int(raw)
        except (TypeError,ValueError): continue
        if slot>0 and slot not in slots: slots.append(slot)
    proof.update({"batch_id":str(batch_id or ""),"job_id":str(job_id or ""),
                  "batch_size":len(slots),"requested":len(slots),
                  "reserved_slots":slots})
    if capacity_reservation:
        proof["capacity_reservation_id"]=str(job_id or "")
    else:
        proof.pop("capacity_reservation_id",None)
    return proof

def _queue_preflight_evidence(job, kind, username, symbol, slot, expected_tickets=None):
    """Validate a same-process, lock-bound read proof or require a fresh broker read."""
    if not isinstance(job,dict):
        return None
    payload=job.get("payload") or {}
    proof=payload.get("_queue_preflight") if isinstance(payload,dict) else None
    required={"version","kind","username","symbol","slot","slot_token","owner",
              "process_nonce","created_mono","batch_id","job_id","batch_size",
              "requested","reserved_slots"}
    if not isinstance(proof,dict) or not required.issubset(proof):
        return None
    try:
        proof_version=int(proof.get("version")); proof_slot=int(proof.get("slot")); requested_slot=int(slot)
        created=float(proof.get("created_mono")); age=_t_conn.monotonic()-created
        requested=int(proof.get("requested")); batch_size=int(proof.get("batch_size"))
        job_batch_size=int(job.get("batch_size"))
        reserved_slots=[int(value) for value in proof.get("reserved_slots")]
    except (TypeError,ValueError):
        return None
    slot_token=str(job.get("slot_token") or "")
    if (proof_version!=2 or proof.get("kind")!=kind or
            proof.get("username")!=str(username or "") or
            proof.get("symbol")!=str(symbol or "") or proof_slot!=requested_slot or
            not slot_token or proof.get("slot_token")!=slot_token or
            proof.get("owner")!=_TRADE_QUEUE_OWNER or age<0 or
            proof.get("process_nonce")!=_QUEUE_PROOF_PROCESS_NONCE or
            proof.get("batch_id")!=str(job.get("batch_id") or "") or
            proof.get("job_id")!=str(job.get("job_id") or "") or
            requested<1 or requested!=batch_size or requested!=job_batch_size or
            len(reserved_slots)!=requested or len(set(reserved_slots))!=requested or
            requested_slot not in reserved_slots or age>_queue_preflight_ttl(kind)):
        return None
    try:
        current_token=R.get(_slotop_key(username,symbol,requested_slot))
        if isinstance(current_token,bytes): current_token=current_token.decode("utf-8","replace")
        if str(current_token or "")!=slot_token:
            return None
    except Exception:
        return None
    if kind=="open":
        if not all(key in proof for key in ("occupied_slots","position_limits","requested")):
            return None
        try:
            occupied={int(value) for value in proof.get("occupied_slots")}
        except (TypeError,ValueError):
            return None
        if requested_slot in occupied:
            return None
        current_limits=_entry_position_limits(username)
        if proof.get("position_limits")!=current_limits:
            return None
        if current_limits:
            if (proof.get("capacity_reservation_id")!=str(job.get("job_id") or "") or
                    not _entry_capacity_reservation_valid(job,limits=current_limits)):
                return None
    elif kind=="close":
        if not isinstance(proof.get("tickets"),dict) or not isinstance(expected_tickets,dict):
            return None
        try:
            proven={leg:int(ticket) for leg,ticket in proof["tickets"].items()}
            expected={leg:int(ticket) for leg,ticket in expected_tickets.items()}
        except (TypeError,ValueError):
            return None
        if proven!=expected:
            return None
    else:
        return None
    return proof

class OpenPairReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    direction:str                      # 'reverse'(反向/1空2涨) | 'forward'(正向/2空1涨)
    symbol:str="XAUUSD"; slots:int=1   # slots = 本次要填的坑位数(按顺序填最前面的 N 个空坑, 每坑=一对, 每坑per-rung手数)
    slot:int=0                          # >0=定向开仓该坑(允许坑号跳空); 0=顺序填充(填最小空缺坑)
    target_slots:Optional[list[int]]=None # 手动连续点击合并后的有序坑位；顺序必须贯穿队列和 Agent 受理
    client_request_id:str=""              # 浏览器稳定受理 ID；POST 超时后只查询同一批次，绝不盲目重下单
    qty:float=0.0                       # 兼容旧字段(已废弃; slots 优先, 仅当 slots 缺省且 qty>0 时回退)

# === P1.3: 行情快照优先读取 ===
def _bridge_tick_cache_id(leg, username=None, role=None):
    username=str(username or "").strip()
    if username and role in ("main","hedge"):
        return "user:%s:%s"%(username,role)
    base=str(getattr(leg,"base","") or "")
    if "hedge" in base or ":8042" in base: return "hedge"
    return "main"

_BRIDGE_TICK_MEMORY={}

def _memory_bridge_tick_snapshot(leg, symbol, max_age_ms=500, username=None, role=None):
    """Read optional slippage evidence without any Redis or bridge I/O."""
    try:
        key=(_bridge_tick_cache_id(leg,username,role),str(symbol))
        entry=_BRIDGE_TICK_MEMORY.get(key)
        if not isinstance(entry,dict): return None
        age_ms=(_t_conn.monotonic()-float(entry.get("stored_mono")))*1000
        if age_ms<0 or age_ms>=max(0,float(max_age_ms)): return None
        tick=dict(entry.get("tick") or {})
        if tick.get("bid") is None or tick.get("ask") is None: return None
        tick.update({"from_cache":True,"age_ms":age_ms,"memory_cache":True})
        return tick
    except Exception:
        return None

def _store_bridge_tick_snapshot(bridge_id, symbol, tick):
    if not isinstance(tick,dict) or tick.get("bid") is None or tick.get("ask") is None:
        return
    _BRIDGE_TICK_MEMORY[(str(bridge_id),str(symbol))]={
        "tick":dict(tick),"stored_mono":_t_conn.monotonic()}
    try:
        key="bridge:%s:tick:%s"%(bridge_id,symbol)
        R.hset(key,mapping={"symbol":tick.get("symbol") or symbol,
                            "bid":tick.get("bid"),"ask":tick.get("ask"),
                            "time":tick.get("time") or 0,
                            "pushed_at":_dt.datetime.utcnow().isoformat()})
        R.expire(key,2)
    except Exception: pass

def _cached_bridge_tick_snapshot(leg, symbol, max_age_ms=500, username=None, role=None):
    """Return an already-pushed tick without issuing a bridge request."""
    from datetime import datetime
    memory=_memory_bridge_tick_snapshot(
        leg,symbol,max_age_ms=max_age_ms,username=username,role=role)
    if memory is not None:
        return memory
    try:
        bridge_id=_bridge_tick_cache_id(leg,username,role)
        snapshot=R.hgetall("bridge:%s:tick:%s"%(bridge_id,symbol))
        if not snapshot:
            return None
        pushed_at=snapshot.get("pushed_at")
        if not pushed_at:
            return None
        pushed_time=datetime.fromisoformat(str(pushed_at).replace("Z","+00:00"))
        age_ms=(datetime.utcnow()-pushed_time.replace(tzinfo=None)).total_seconds()*1000
        if age_ms<0 or age_ms>=max(0,float(max_age_ms)):
            return None
        return {
            "symbol":snapshot.get("symbol"),"bid":float(snapshot.get("bid",0)),
            "ask":float(snapshot.get("ask",0)),"time":int(snapshot.get("time",0)),
            "from_cache":True,"age_ms":age_ms,
        }
    except Exception:
        return None

async def _get_tick_with_fallback(leg, symbol, max_age_ms=500, username=None, role=None):
    """
    优先从Redis读取tick快照,过期则实时查询

    Args:
        leg: _BridgeLeg实例
        symbol: 币种,如"XAUUSD"
        max_age_ms: 最大允许的快照年龄(毫秒)

    Returns:
        tick字典或None
    """
    cached=_cached_bridge_tick_snapshot(
        leg,symbol,max_age_ms=max_age_ms,username=username,role=role)
    if cached is not None:
        return cached
    from datetime import datetime

    try:
        # 确定bridge_id (从leg的base URL判断)
        bridge_id = _bridge_tick_cache_id(leg,username,role)

        key = f"bridge:{bridge_id}:tick:{symbol}"
        snapshot = R.hgetall(key)

        if snapshot:
            # 检查快照年龄
            pushed_at = snapshot.get('pushed_at')
            if pushed_at:
                try:
                    pushed_time = datetime.fromisoformat(pushed_at.replace('Z', '+00:00'))
                    age_ms = (datetime.utcnow() - pushed_time.replace(tzinfo=None)).total_seconds() * 1000

                    if age_ms < max_age_ms:
                        # 快照新鲜,直接返回
                        return {
                            'symbol': snapshot.get('symbol'),
                            'bid': float(snapshot.get('bid', 0)),
                            'ask': float(snapshot.get('ask', 0)),
                            'time': int(snapshot.get('time', 0)),
                            'from_cache': True,
                            'age_ms': age_ms
                        }
                except Exception:
                    pass  # 时间解析失败,回退到实时查询
    except Exception:
        pass  # Redis读取失败,回退到实时查询

    # 快照不存在或过期,回退到实时查询
    try:
        tick = await leg._get(f"/mt5/tick/{symbol}")
        if tick:
            _store_bridge_tick_snapshot(_bridge_tick_cache_id(leg,username,role),symbol,tick)
            tick['from_cache'] = False
            tick['age_ms'] = 0
        return tick
    except Exception:
        return None

def _queue_worker_position_task(job):
    """Return the in-memory snapshot task attached to this dispatch wave."""
    task=(job or {}).get("_worker_positions_task") if isinstance(job,dict) else None
    return task if task is not None and hasattr(task,"__await__") else None

async def _execute_open_pair_job(r:OpenPairReq, command_id=None, pair_rid=None,
                                 actor_override=None, slot_token_override=None,
                                 queue_job_id=None, queue_job=None,
                                 manual_targeted=False):
    # === P0-D: 身份绑定校验 ===
    if not queue_job_id:
        _assert_subject(r.username, r.license_key or "")

    # === P0.1: 创建command追踪 ===
    tracer = get_tracer()
    command_id = command_id or tracer.create_command(
        cmd_type=CommandType.OPEN_PAIR,
        username=r.username,
        symbol=r.symbol,
        direction=r.direction,
        metadata={"slots": r.slots, "slot": r.slot}
    )

    try:

        actor=actor_override or _actor(r.license_key)
        if r.direction not in ("reverse","forward"):
            raise HTTPException(400,"direction 必须为 reverse 或 forward")
        if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
        _maint_block_trading()   # 维护态禁下单前置闸
        await _conn_gate_exec(r.username)   # P0: 按用户桥判健康(修 hedge_pro 被 no123 桥误伤)
        await _exec_owner_gate(r.username)   # 多用户串账墙: 登记账户须==执行桥账户
        tracer.record_timestamp(command_id, TraceTimestamp.AUTH_GATE_DONE)  # P0-A q01
        t=_load_tmpl(r.username, r.symbol)
        if not t: raise HTTPException(404,"参数模板未找到")
        if POL.gate_window(t,"entry",_bj_hm())[0]:   # 进单时段闸(北京) — P1-b enforce
            raise HTTPException(409,"当前不在进单时段(%s-%s 北京)，已拒绝开仓"%(t.get("entry_win_start") or "?", t.get("entry_win_end") or "?"))
        # 坑位数(红框): 本次开几个坑。兼容旧 qty(整数化)。
        slots=int(r.slots or 0)
        if slots<=0 and r.qty and r.qty>0: slots=int(round(r.qty))
        if slots<=0: slots=1
        ladders=int(t.get("ladders") or 0) or 0
        # 每坑下单量 = 每U手数 × 腿倍率 (顺序填充, 每坑一份, 不再乘 slots)
        _mm=float(t.get("main_lot_mult") or 1.0); _hm=float(t.get("hedge_lot_mult") or 1.0)
        base=float(t.get("base_lot") or 0.01)
        sizing=ENG.order_lots(base, _mm, _hm, rungs=1)
        if sizing.get("reason")!="ok":
            raise HTTPException(400,"下单量计算失败: %s(每U手数非法)"%sizing.get("reason"))
        main_vol=sizing["per_rung_main"]; hedge_vol=sizing["per_rung_hedge"]
        main_sym=r.symbol; hedge_sym=ENG.map_hedge_symbol(r.symbol, t.get("hedge_symbol")) or r.symbol
        if main_vol<=0 or hedge_vol<=0:
            raise HTTPException(400,"每坑下单量为0(检查每U手数/倍率)")
        _queue_batch_size=1
        try:
            _queue_batch_size=max(1,int((queue_job or {}).get("batch_size") or 1))
        except (TypeError,ValueError):
            pass
        _subsecond_mt5=_subsecond_mt5_user(r.username)
        _queue_burst_hint=bool(queue_job_id and (
            _trade_bool((queue_job or {}).get("temporal_burst_admission")) or
            _queue_batch_size>1))
        mode=(t.get("entry_mode") or "main_first"); speed=(t.get("speed_mode") or "fast")
        if mode not in ("concurrent","main_first","hedge_first"): mode="main_first"
        if _subsecond_user(r.username) or _queue_burst_hint:
            # NO123 must never dispatch the IC leg until the hedge broker has
            # confirmed its fill. Turbo removes only the artificial inter-leg
            # sleep; the broker-terminal barrier remains mandatory.
            mode="hedge_first"; speed="turbo"
        legmap={"reverse":("sell","buy"),"forward":("buy","sell")}
        # ── 前置读取并行化: 占坑/双腿账户/双腿tick 同时发起(原为串行冷调用, 跨洲链路累计 ~2.5s) ──
        _rm=float(t.get("margin_reserve_main") or 0); _rh=float(t.get("margin_reserve_hedge") or 0)
        async def _safe_coro(coro):
            try: return await coro
            except Exception as e: return e
        _ucn=_user_exec_conn(r.username)   # Preflight truth must match the connector that will execute.
        _target=int(r.slot or 0)
        _queue_proof=_queue_preflight_evidence(
            queue_job,"open",r.username,r.symbol,_target) if _target>0 else None
        _occ_task=_queue_worker_position_task(queue_job) if _queue_proof is None else None
        if _queue_proof is None and _occ_task is None:
            _occ_task=_aio.create_task(_occupied_slots(
                r.symbol,r.username,include_positions=True,authoritative=True))
        _accs_task=_aio.create_task(_safe_coro(_ucn.both_accounts())) if ((_rm>0 or _rh>0) and hasattr(_ucn,"both_accounts")) else None
        async def _tick_pair():
            cache_ms=_entry_tick_cache_ms(
                r.username,manual_targeted,burst_admission=_queue_burst_hint)
            async def one(leg,sym,role):
                try: return await _get_tick_with_fallback(
                    leg,sym,max_age_ms=cache_ms,username=r.username,role=role)
                except Exception: return None
            _h=getattr(_ucn,"hedge",None)
            if _h is not None:
                return await _aio.gather(one(_ucn.main,main_sym,"main"),
                                         one(_h,hedge_sym,"hedge"))
            return (await one(_ucn.main,main_sym,"main"), None)
        _tick_task=_aio.create_task(_tick_pair())
        # 已占坑号(gap-aware): 支持坑号跳空
        if _queue_proof is not None:
            occ={int(value) for value in _queue_proof["occupied_slots"]}
            _entry_positions=None
            tracer.update_field(command_id,"position_preflight","queue_proof")
        else:
            try:
                occ,_entry_positions=await _occ_task
            except HTTPException:
                raise
            except Exception as ex:
                raise HTTPException(
                    502,"无法读取当前持仓坑位，未发送开仓命令: %s"%
                    ex.__class__.__name__)
        if occ is None:
            raise HTTPException(502,"无法读取当前持仓坑位(fail-closed, 拒绝开仓避免超额填坑)")
        filled=len(occ)
        target=_target
        if target>0:
            # 定向开仓: 校验范围+未占用, 只开该坑
            if ladders>0 and (target<1 or target>ladders):
                raise HTTPException(400,"坑号 %d 超出阶梯范围(1..%d)"%(target,ladders))
            if target in occ:
                raise HTTPException(409,"坑 %d 已有持仓，不能重复开"%target)
            slot_seq=[target]
        else:
            # 顺序填充: 填最小空缺坑, 受阶梯上限约束, 实际可开 = min(请求坑数, 剩余空坑)
            remaining = (ladders - filled) if ladders>0 else slots
            if remaining<=0:
                raise HTTPException(409,"阶梯已满(%d/%d坑)，无空坑可开"%(filled,ladders))
            _tn=min(slots, remaining); slot_seq=[]; _occ2=set(occ)
            for _ in range(_tn):
                ns=_next_empty_slot(_occ2, ladders)
                if ns is None: break
                slot_seq.append(ns); _occ2.add(ns)
        to_open=len(slot_seq)
        if to_open<=0:
            raise HTTPException(409,"无空坑可开")
        _force_demo = (R.get(RNS+"force_demo:"+r.username)=="1")
        _entry_limits=_entry_position_limits(r.username)
        if not DEMO_MODE and not _force_demo and _queue_proof is None:
            if queue_job_id and _entry_limits:
                _cap=(None if _entry_capacity_reservation_valid(queue_job,limits=_entry_limits)
                      else _reserve_entry_capacity_for_job(
                          r.username,_entry_positions,queue_job,limits=_entry_limits))
            else:
                _cap=_entry_capacity_guard_from_positions(
                    r.username,_entry_positions,requested=to_open,limits=_entry_limits)
            if _cap:
                _latch_entry_capacity(r.username,_cap,"manual_preflight")
                raise HTTPException(409,"持仓容量闸已阻断开仓: %s"%json.dumps(_cap,ensure_ascii=False))
        # 数据波动闸: 近 match_count 条点差波动超 band → 拒绝开仓 — P1-b enforce: 判定统一走 policy
        _mc=int(t.get("match_count") or 0); _bd=float(t.get("fluctuation_band") or 0)
        _flb,_flw=POL.gate_fluctuation(t,_pol_hist(t))
        if _flb:
            raise HTTPException(409,"数据波动过大暂停入场: %s(近%d条幅度>阈值%.2f)"%(_flw,_mc,_bd))
        # 保证金预留闸 + 智能预判预算闸(批33功能3) — P1-b enforce: 判定统一走 policy, 文案/状态码原样
        _pb=float(t.get("predict_budget") or 0)
        if _rm>0 or _rh>0 or _pb>0:
            _accs=(await _accs_task) if _accs_task is not None else None
            _mb,_mw=POL.gate_margin_budget(t,_accs,fail_closed=True,hedge_requires_leg=True,hedge_exists=(getattr(_ucn,"hedge",None) is not None))
            if _mb:
                if _mw=="margin_read_fail_closed":
                    raise HTTPException(502,"无法读取账户保证金(fail-closed, 拒绝开仓): %s"%(_accs if _accs is not None else "no both_accounts"))
                if _mw.startswith("main_"):
                    raise HTTPException(409,"主账户保证金不足预留, 拒绝开仓: %s"%_mw)
                if _mw.startswith("hedge_"):
                    raise HTTPException(409,"对冲账户保证金不足预留, 拒绝开仓: %s"%_mw)
                _eq=float(((_accs.get("main") or {}).get("equity")) or 0)
                raise HTTPException(409,"智能预判: 主账户净值 %.2f < 预算 %.2f, 暂不可开仓"%(_eq,_pb))
        # 开仓点差(testgo pos_open_ledger 思路): 批前取一次双腿 tick 算 spreadAtExecution(前置并行任务取回)
        entry_spread=None; _mt=_ht=None
        try:
            _mt,_ht=await _tick_task
            if _mt and _ht and _mt.get("bid") is not None and _ht.get("ask") is not None:
                if r.direction=="reverse": entry_spread=round(float(_ht["ask"])-float(_mt["bid"]),4)   # 对冲ASK-主BID
                else:                      entry_spread=round(float(_mt["ask"])-float(_ht["bid"]),4)   # 主ASK-对冲BID
        except Exception: pass
        # 行情新鲜度闸(V1.1移植): 报价冻结/桥半开→陈旧价开仓, fail-closed 409
        _stq=await _quote_stale(_mt,_ht,_ucn,r.username)
        tracer.record_timestamp(command_id, TraceTimestamp.PREFLIGHT_COMPLETE)  # P0-A q02
        if _stq:
            raise HTTPException(409,"行情新鲜度闸: %s, 已拒绝开仓(阈值可调 qh:quote_gate:max_age)"%_stq)
        # 费用折算成点(抬高逐坑买入点位下限, 在下方逐坑闸并入)
        _fee=float(t.get("fee_per_lot") or 0); _nthr=float(t.get("entry_spread") or 0); _fee_pts=0.0
        if _fee>0:
            try: _,_fee_pts=ENG.effective_spread_threshold(_nthr,_fee,100.0,legs=2)
            except Exception: _fee_pts=0.0
        _ledger_key=RNS+"ledger:"+r.username+":"+r.direction
        if DEMO_MODE or _force_demo:
            _why = "demo:not_sent" if DEMO_MODE else "trial_force_demo"
            _audit(r.username,actor,"open_pair",{"direction":r.direction,"mode":mode,"slots_req":slots,"to_open":to_open,"filled":filled,"ladders":ladders,"per_main":main_vol,"per_hedge":hedge_vol,"force_demo":_force_demo},True,_why)
            _pfx = "演示模式" if DEMO_MODE else "试用模式(强制演示)"
            return {"ok":True,"demo":True,"trial_demo":_force_demo and not DEMO_MODE,"direction":r.direction,"mode":mode,"to_open":to_open,"filled":filled,"ladders":ladders,
                    "msg":"%s[%s/%s]：将按顺序填 %d 个坑(已填%d/%d)，每坑 主%s%s手/对冲%s%s手，未真实下单"%(_pfx,mode,speed,to_open,filled,ladders,legmap[r.direction][0],main_vol,legmap[r.direction][1],hedge_vol)}
        # 真发：逐坑顺序开仓; 任一坑裸空/失败即停(不继续填后续坑); 裸空守护绝不自动反开
        opened=0; details=[]; skipped=[]; ownership_review=False
        _slotcfg=R.hgetall(_slot_key(r.username,r.symbol)) or {}
        for i,slot_no in enumerate(slot_seq):   # slot_seq=定向[该坑] 或 顺序[最小空缺...]
            # 逐坑策略覆盖(右键"坑位规则设置"): 进单状态/交易数量/买入点位
            ov=None
            try:
                _raw=_slotcfg.get(str(slot_no)); ov=json.loads(_raw) if _raw else None
            except Exception: ov=None
            slot_mv, slot_hv = main_vol, hedge_vol
            _gthr=float(t.get("entry_spread") or 0)
            if ov:
                if ov.get("entry_enabled") is False:
                    if target>0:
                        raise HTTPException(409,"坑 %d 未开仓：该坑进单已禁用"%slot_no)
                    skipped.append(slot_no); continue   # 该坑被关闭→跳过(不开)
                if ov.get("lot_mode")=="fixed" and float(ov.get("qty") or 0)>0:
                    # 固定手数: 该坑用设定数量(主腿=qty×主倍率比, 对冲=qty×对冲倍率比, 以 base 为单位换算)
                    _q=float(ov["qty"]); slot_mv=round(_q*_mm,2); slot_hv=round(_q*_hm,2)
                    if slot_mv<=0 or slot_hv<=0: slot_mv,slot_hv=main_vol,hedge_vol
            # 买入点位=入场下限: 当前点差 >= 下限 才开(费用抬高下限); null=任意都开, 0=数字0(须≥0), 无覆盖=全局
            # Review ownership is per configured slot. A problem in one slot
            # must not serialize or block independent slots.
            _assert_slot_review_clear(r.username,r.symbol,slot_no)
            _pass,_lb=POL.gate_entry_spread(ov,_gthr,entry_spread,_fee_pts)
            if manual_targeted and target>0:
                # A deliberate operator click is an execution command, not an
                # automatic-entry signal. Keep freshness/capacity/margin and
                # ownership gates, but do not silently turn it into a strategy
                # buy-point decision after the click has already been accepted.
                if not _pass:
                    tracer.update_field(command_id,"manual_buy_point_override","true")
                _pass=True
            if not _pass:
                if target>0:
                    raise HTTPException(409,"坑 %d 未开仓：当前点差 %s < 买入点位 %.3f"%(
                        slot_no,("--" if entry_spread is None else "%.3f"%entry_spread),float(_lb or 0)))
                skipped.append(slot_no); continue   # 当前点差未达买入点位下限→跳过
            slot_token=slot_token_override or ("%s:%d"%(command_id,slot_no))
            _prelocked=(R.get(_slotop_key(r.username,r.symbol,slot_no))==slot_token)
            if not _prelocked and not _acquire_slot_op(r.username,r.symbol,slot_no,slot_token):
                raise HTTPException(409,"坑 %d 正在处理，请勿重复点击"%slot_no)
            _mark_slot_busy(r.symbol,slot_no,ttl=90,username=r.username)
            slot_lock_handoff=False
            try:
                await _trade_queue_wait_open_turn(queue_job)
                _assert_slot_review_clear(r.username,r.symbol,slot_no)
                if _queue_proof is not None and _queue_preflight_evidence(
                        queue_job,"open",r.username,r.symbol,slot_no) is None:
                    # The order barrier may outlive the short proof. Re-read at
                    # the actual dispatch boundary instead of extending trust.
                    dispatch_occ,dispatch_positions=await _occupied_slots(
                        r.symbol,r.username,include_positions=True,authoritative=True)
                    if dispatch_occ is None:
                        raise HTTPException(502,"无法读取当前持仓坑位，未发送开仓命令")
                    if slot_no in dispatch_occ:
                        raise HTTPException(409,"坑 %d 已有持仓，未重复开仓"%slot_no)
                    dispatch_limits=_entry_position_limits(r.username)
                    if queue_job_id and dispatch_limits:
                        dispatch_violation=(None if _entry_capacity_reservation_valid(
                            queue_job,limits=dispatch_limits) else
                            _reserve_entry_capacity_for_job(
                                r.username,dispatch_positions,queue_job,limits=dispatch_limits))
                    else:
                        dispatch_violation=_entry_capacity_guard_from_positions(
                            r.username,dispatch_positions,requested=1,limits=dispatch_limits)
                    if dispatch_violation:
                        _latch_entry_capacity(r.username,dispatch_violation,"dispatch_preflight")
                        raise HTTPException(409,"持仓容量闸已阻断开仓: %s"%
                            json.dumps(dispatch_violation,ensure_ascii=False))
                    tracer.update_field(command_id,"position_preflight","dispatch_refresh")
                    _queue_proof=None
                tracer.record_timestamp(command_id, TraceTimestamp.DISPATCH_PREPARED)  # P0-A q03
                tracer.record_timestamp(command_id, TraceTimestamp.LEG_TASKS_CREATED)   # P0-A q04
                _main_dev=_dev_for_price((_mt or {}).get("bid"))
                _hedge_dev=_dev_for_price((_ht or {}).get("bid"))
                _temporal_burst_admission=_trade_bool(
                    (queue_job or {}).get("temporal_burst_admission"))
                _dispatch_boundary_crossed=_trade_bool(
                    (queue_job or {}).get("_broker_dispatch_started"))
                if queue_job_id:
                    try:
                        _dispatch_snapshot=TRADE_QUEUE.get_job(queue_job_id) or {}
                        _dispatch_boundary_crossed=bool(
                            _dispatch_boundary_crossed or
                            _trade_bool(_dispatch_snapshot.get("dispatch_intent")))
                        # A later click may promote a still-queued predecessor
                        # into the cohort. Capture that promotion immediately
                        # before the intent write, but never rewrite a boundary
                        # that has already crossed.
                        if not _dispatch_boundary_crossed:
                            _temporal_burst_admission=_trade_bool(
                                _dispatch_snapshot.get("temporal_burst_admission"))
                    except Exception:
                        pass
                _ctx={"username":r.username,"symbol":r.symbol,"hedge_symbol":hedge_sym,
                      "direction":r.direction,"actor":actor,"slot":slot_no,
                      "command_id":command_id,
                      "main_vol":slot_mv,"hedge_vol":slot_hv,"entry_spread":entry_spread,
                      "ledger_key":_ledger_key,"target":target,"main_tick":_mt,
                      "hedge_tick":_ht,"threshold":_lb,"slot_token":slot_token,
                      "account_token":None,"queue_job_id":queue_job_id,
                      "capacity_reservation_id":(queue_job or {}).get("job_id"),
                      "pair_rid":pair_rid,"mode":mode,"speed":speed,
                      "main_dev":_main_dev,"hedge_dev":_hedge_dev,
                      "temporal_burst_admission":_temporal_burst_admission}
                if queue_job_id:
                    tracer.update_field(command_id,"pair_request_id",pair_rid)
                    tracer.update_field(command_id,"main_request_id",str(pair_rid)+"m")
                    tracer.update_field(command_id,"hedge_request_id",str(pair_rid)+"h")
                    tracer.update_field(command_id,"pending_context",_ctx)
                    tracer.update_status(command_id,CommandStatus.SUBMITTED)
                    if not _trade_queue_mark_dispatch_intent(queue_job_id,_ctx):
                        terminal_error=HTTPException(
                            503,"DISPATCH_INTENT_PERSIST_FAILED: 未发送开仓命令")
                        terminal_error.qh_terminal_state="FAILED"
                        raise terminal_error
                    if not _hold_entry_capacity_reservation(r.username,queue_job_id):
                        terminal_error=HTTPException(
                            503,"CAPACITY_HOLD_PERSIST_FAILED: 未发送开仓命令")
                        terminal_error.qh_terminal_state="FAILED"
                        raise terminal_error
                    if isinstance(queue_job,dict):
                        # This mirror is only set after Redis proves the intent
                        # and permanent capacity hold.  Exception handling may
                        # now conservatively classify the call as ambiguous.
                        queue_job["_broker_dispatch_started"]=True
                _batch_size=1
                try: _batch_size=max(1,int((queue_job or {}).get("batch_size") or 1))
                except (TypeError,ValueError): pass
                # The MT5 bridge has one native worker per account, but its
                # two independently registered terminals can accept the pair
                # together.  Reuse the durable burst saga for a lone
                # hedge_pro slot as well: the finalizer still waits for both
                # exact request ids and the existing compensation path handles
                # an explicit one-leg rejection.  MT4/no123 keeps the prior
                # ordered path, and multi-slot batches keep their own burst
                # admission regardless of account.
                _burst_admission=bool(
                    queue_job_id and (_batch_size>1 or _temporal_burst_admission or
                                      (_subsecond_mt5 and _batch_size==1)))
                _ctx["batch_size"]=_batch_size
                _ctx["burst_admission"]=_burst_admission
                _ctx["burst_cohort"]=(queue_job or {}).get("burst_cohort")
                _ctx["burst_depth"]=(queue_job or {}).get("burst_depth") or _batch_size
                _saga_hook=(_trade_queue_saga_phase_hook(queue_job_id,_ctx)
                            if queue_job_id and (_subsecond_user(r.username) or
                                                 _burst_admission) else None)
                # Batch jobs own independent slot locks and reservations.  Let
                # the connector admit both legs together so the QH worker does
                # not add a first-leg terminal barrier to every slot.  The MT5
                # bridge still serializes calls per terminal account.
                res=await _exec_open_pair(r.direction, main_sym, hedge_sym, slot_mv, slot_hv, mode, speed, username=r.username, command_id=command_id,
                                          main_dev=_main_dev, hedge_dev=_hedge_dev,
                                          pair_rid=pair_rid,async_accept=bool(queue_job_id),
                                          dispatch_only=_burst_admission,
                                          burst_admission=_burst_admission,
                                          phase_hook=_saga_hook)
                details.append(res)
                if _pair_pending(res):
                    tracer.update_status(command_id, CommandStatus.SUBMITTED)
                    tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
                    account_token=res.pop("_account_op_token",None)
                    _ctx["account_token"]=account_token
                    if queue_job_id:
                        _trade_queue_mark_dispatching(queue_job_id,res,_ctx)
                    _aio.create_task(_finalize_pending_open(command_id,res,_ctx))
                    slot_lock_handoff=True
                    return JSONResponse(status_code=202,content={"ok":True,"accepted":True,"state":"DISPATCHING",
                        "command_id":command_id,"status_url":"/api/command/"+command_id,"detail":res})
                if _open_compensation_succeeded(res):
                    tracer.update_field(command_id,"final_result",res)
                    tracer.update_field(command_id,"failure_reason","second_leg_failed_compensated")
                    _audit(r.username,actor,"open_pair",{"slot":slot_no,"res":res},False,
                           "FAILED_ROLLED_BACK:exact_ticket_compensation")
                    terminal_error=HTTPException(
                        502,"第二腿未成交；首腿已按原 ticket 自动平仓，未留下单腿持仓")
                    terminal_error.qh_terminal_state="FAILED"
                    terminal_error.qh_result=res
                    raise terminal_error
                mok=res.get("main_ok"); hok=res.get("hedge_ok")
                if mok and hok:
                    ledger_entry={"q":slot_hv,"m":slot_mv,
                                  "s":entry_spread if entry_spread is not None else 0,
                                  "ts":_dt.datetime.utcnow().isoformat(),"ladder":slot_no}
                    if not _open_ledger_commit_once(command_id,_ledger_key,
                                                    ledger_entry,tracer):
                        terminal_error=HTTPException(
                            503,"开仓账本提交失败，已保留UNKNOWN恢复状态")
                        terminal_error.qh_terminal_state="UNKNOWN"
                        terminal_error.qh_result=res
                        raise terminal_error
                    opened+=1
                    _slip_snap(r.direction,"open",_cap_at(_mt,_ht,r.direction,"open"),slot_no,_leg_tickets(res.get("main")),thr=_lb)   # 执行滑点决策快照(ticket精确键+逐单阈值)
                    owner_saved=await _reserve_slot_with_recovery(
                        r.symbol,res,slot_no,r.username)
                    if not owner_saved:
                        ownership_review=True
                    _remember_open_positions(r.symbol,hedge_sym,r.direction,res,slot_no,r.username,slot_mv,slot_hv)
                    if owner_saved and queue_job_id:
                        _release_entry_capacity_reservation(r.username,queue_job_id)
                    # === P0-C: UNKNOWN 检测 + Pair Ledger ===
                    try:
                        _m_res = res.get("main") or {}
                        _h_res = res.get("hedge") or {}
                        if command_id:
                            if (_leg_recovered_from_unknown(_m_res) or
                                    _leg_recovered_from_unknown(_h_res)):
                                tracer.record_timestamp(command_id, TraceTimestamp.UNKNOWN_COMMITTED)
                                tracer.update_field(command_id, "had_unknown", "true")
                            tracer.update_field(command_id, "main_retcode",  str(_m_res.get("retcode","")))
                            tracer.update_field(command_id, "hedge_retcode", str(_h_res.get("retcode","")))
                            tracer.update_field(command_id, "pair_slot",     str(slot_no))
                            tracer.update_field(command_id, "pair_direction", r.direction)
                    except Exception:
                        pass
                    if not owner_saved:
                        if queue_job_id:
                            _hold_entry_capacity_reservation(r.username,queue_job_id)
                        break
                    continue
                if not mok and not hok:
                    if queue_job_id:
                        _release_entry_capacity_reservation(r.username,queue_job_id)
                    _audit(r.username,actor,"open_pair",{"i":i,"opened":opened,"res":res},False,"slot_both_failed")
                    if opened>0:
                        return {"ok":True,"demo":False,"direction":r.direction,"mode":mode,"opened":opened,"requested":to_open,
                                "msg":"已开 %d/%d 坑后某坑双腿未成交，已停止(无裸空)"%(opened,to_open),"detail":details}
                    terminal_error=HTTPException(
                        502,"开仓失败，首坑双腿均未成交(无裸空): %s"%json.dumps(res))
                    terminal_error.qh_terminal_state="FAILED"
                    raise terminal_error
                # 恰一腿成 = 裸空, 留痕+告警+停止(绝不自动反开)
                naked_leg="hedge" if (mok and not hok) else "main"
                _halt_auto_entry(r.username,"single_leg_exposed",{"slot":slot_no,
                    "symbol":r.symbol,"naked":naked_leg,"res":res})
                try:
                    c=db(); cur=c.cursor(); cur.execute("SELECT id FROM users WHERE username=%s",(r.username,)); u=cur.fetchone()
                    cur.execute("INSERT INTO naked_alerts(user_id,leg,detail) VALUES(%s,%s,%s)",(u[0] if u else None, naked_leg, json.dumps(res))); c.close()
                except Exception: pass
                _push_alert("err","裸空告警[%s 第%d坑]：%s腿成交、另一腿失败，单边暴露！需人工处理(一键平仓)"%(mode,opened+1,"主" if naked_leg=="hedge" else "对冲"),r.username)
                _audit(r.username,actor,"open_pair",{"i":i,"opened":opened,"res":res},False,"NAKED_RISK_%s"%naked_leg)
                if queue_job_id:
                    _hold_entry_capacity_reservation(r.username,queue_job_id)
                terminal_error=HTTPException(
                    409,"裸空风险(已开%d坑, 第%d坑%s腿成交另一腿失败)，已告警留人工处理(未自动反开)"%(
                        opened,opened+1,"主" if naked_leg=="hedge" else "对冲"))
                terminal_error.qh_terminal_state="SINGLE_LEG_EXPOSED"
                raise terminal_error
            finally:
                if not slot_lock_handoff:
                    _clear_slot_busy(r.symbol,slot_no,r.username)
                    _release_slot_op(r.username,r.symbol,slot_no,slot_token)
        _record_trace_timestamp_once(tracer,command_id,TraceTimestamp.PAIR_JOIN_DONE)      # P0-A q11
        _record_trace_timestamp_once(tracer,command_id,TraceTimestamp.LEDGER_COMMITTED)    # P0-A q12
        _audit(r.username,actor,"open_pair",{"opened":opened,"to_open":to_open,"filled_before":filled,"ladders":ladders,"mode":mode,"skipped":skipped},False,"opened:%s:%dslots"%(r.direction,opened))
        _smsg = ("，跳过坑 %s(被禁用/未满足买入点位)"%skipped) if skipped else ""
        # P0.1: 更新状态
        if ownership_review:
            tracer.update_status(command_id, CommandStatus.MANUAL_REVIEW)
            tracer.update_field(command_id,"failure_reason","slotowner_persist_failed_after_fill")
        else:
            tracer.update_status(command_id, CommandStatus.COMPLETED)
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
        return {"ok":True,"demo":False,"command_id":command_id,"direction":r.direction,"mode":mode,"opened":opened,"skipped":skipped,"filled_before":filled,"ladders":ladders,"detail":details,
                "ownership_review":ownership_review,
                "msg":(("已成交 %d 个坑，但归属持久化失败，已暂停自动开仓并要求人工核对"%opened)
                       if ownership_review else ("已顺序开 %d 个坑[%s]%s"%(opened,mode,_smsg)))}

    except HTTPException as he:
        if (queue_job_id and isinstance(queue_job,dict) and
                queue_job.get("_broker_dispatch_started") and
                not getattr(he,"qh_terminal_state",None)):
            he.qh_terminal_state="UNKNOWN"
        if (queue_job_id and isinstance(queue_job,dict) and
                not queue_job.get("_broker_dispatch_started")):
            _release_entry_capacity_reservation(r.username,queue_job_id)
        elif queue_job_id:
            _hold_entry_capacity_reservation(r.username,queue_job_id)
        terminal_state=str(getattr(he,"qh_terminal_state","FAILED"))
        tracer.update_status(command_id,getattr(CommandStatus,terminal_state,CommandStatus.FAILED))
        tracer.update_field(command_id, "failure_reason", str(he.detail))
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
        raise
    except Exception as e:
        if (queue_job_id and isinstance(queue_job,dict) and
                not queue_job.get("_broker_dispatch_started")):
            _release_entry_capacity_reservation(r.username,queue_job_id)
        elif queue_job_id:
            _hold_entry_capacity_reservation(r.username,queue_job_id)
        tracer.update_status(command_id,
            CommandStatus.UNKNOWN if (queue_job_id and isinstance(queue_job,dict) and
                                      queue_job.get("_broker_dispatch_started"))
            else CommandStatus.FAILED)
        tracer.update_field(command_id, "error", str(e))
        tracer.record_timestamp(command_id, TraceTimestamp.HTTP_SENT)
        raise

@app.get("/api/admin/leg_deals", dependencies=[Depends(require_op("recon"))])
def admin_leg_deals(user:str="", leg:str="", days:int=7, limit:int=300):
    """成交记录(持久账本 leg_deals, 跨用户带用户名): 平仓即落库+120s对账, 不受云端会话清零影响。
       已并入 /recon 页(权限随页面=recon)。stats=同筛选条件的 SQL 全量聚合(不受 limit 截断)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cond=" FROM leg_deals ld LEFT JOIN users u ON u.id=ld.user_id WHERE ld.time_utc>=%s"
    p=[int(_t_conn.time()-max(1,min(days,90))*86400)]
    if user: cond+=" AND u.username=%s"; p.append(user)
    if leg in ("main","hedge"): cond+=" AND ld.leg=%s"; p.append(leg)
    cur.execute("SELECT ld.*, u.username"+cond+" ORDER BY ld.time_utc DESC LIMIT %s", tuple(p+[min(max(limit,1),1000)]))
    rows=cur.fetchall()
    # 统计(全量聚合, 与列表同筛选): 总计/分腿/胜率 + 按用户小计
    cur.execute("""SELECT COUNT(*) n, COALESCE(SUM(ld.profit),0) pf, COALESCE(SUM(ld.swap),0) sw,
                          COALESCE(SUM(ld.commission),0) cm, COALESCE(SUM(ld.volume),0) lots,
                          SUM(CASE WHEN ld.profit>0 THEN 1 ELSE 0 END) wins,
                          COALESCE(SUM(CASE WHEN ld.leg='main' THEN ld.profit ELSE 0 END),0) pf_main,
                          COALESCE(SUM(CASE WHEN ld.leg='hedge' THEN ld.profit ELSE 0 END),0) pf_hedge"""+cond, tuple(p))
    s=dict(cur.fetchone() or {})
    cur.execute("SELECT COALESCE(u.username,'-') username, COUNT(*) n, COALESCE(SUM(ld.profit),0) pf, COALESCE(SUM(ld.swap),0) sw, COALESCE(SUM(ld.commission),0) cm"
                +cond+" GROUP BY 1 ORDER BY pf DESC LIMIT 20", tuple(p))
    by_user=[{"username":r["username"],"n":int(r["n"]),"profit":round(float(r["pf"]),2),
              "swap":round(float(r["sw"]),2),"commission":round(float(r["cm"]),2)} for r in cur.fetchall()]
    c.close()
    out=[]
    for r in rows:
        ts=int(r["time_utc"] or 0)
        out.append({"time_bj":(_dt.datetime.utcfromtimestamp(ts+28800).strftime("%Y-%m-%d %H:%M:%S") if ts else "-"),
                    "username":r.get("username") or "-","leg":r["leg"],"ticket":r["ticket"],"symbol":r["symbol"],
                    "side":("buy" if r["type"]==0 else ("sell" if r["type"]==1 else "-")),
                    "lots":r["volume"],"price":r["price"],"price_open":r["price_open"],
                    "profit":r["profit"],"swap":r["swap"],"commission":r["commission"],"comment":r["comment"] or ""})
    n=int(s.get("n") or 0); wins=int(s.get("wins") or 0)
    stats={"n":n,"lots":round(float(s.get("lots") or 0),2),
           "profit":round(float(s.get("pf") or 0),2),"swap":round(float(s.get("sw") or 0),2),
           "commission":round(float(s.get("cm") or 0),2),
           "net":round(float(s.get("pf") or 0)+float(s.get("sw") or 0)+float(s.get("cm") or 0),2),
           "win_rate":(round(wins*100.0/n,1) if n else None),
           "profit_main":round(float(s.get("pf_main") or 0),2),"profit_hedge":round(float(s.get("pf_hedge") or 0),2),
           "by_user":by_user}
    return {"deals":out,"count":len(out),"stats":stats}

@app.post("/api/admin/leg_deals/sweep", dependencies=[Depends(require_op("recon"))])
async def admin_leg_deals_sweep():
    """手动触发一次云端→本地账本对账(平时 120s 自动跑)。"""
    n=await _persist_sweep_once()
    return {"ok":True,"added":n}

class RepairLegReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    symbol:str="XAUUSD"; direction:str="reverse"; leg:str="hedge"; volume:float=0.0; slot:int=0

async def _dispatch_repair_leg(leg_obj, truth_leg, sym, volume, side, direction, leg, rid, username=None):
    from connector import _is_unknown_exc, order_status_probe, verify_leg_open
    try:
        deviation=None
        try:
            tick=await leg_obj._get("/mt5/tick/"+sym)
            deviation=_dev_for_price((tick or {}).get("bid"))
        except Exception: pass
        res=await leg_obj.open_order(
            sym,volume,side,comment="QH-%s-%s#%s"%(direction,leg,rid),
            request_id=rid+leg[0],deviation=deviation)
        if isinstance(res,dict) and res.get("pending"):
            terminal=await order_status_probe(leg_obj,rid+leg[0],tries=600,delay=0.05)
            if terminal and terminal.get("ok"): return terminal
            if terminal and terminal.get("failed"):
                terminal=dict(terminal); terminal.pop("failed",None)
                return terminal
            raise HTTPException(502,"补腿已受理但终态等待超时，请先核对持仓，勿重复补开")
        return res
    except HTTPException:
        raise
    except Exception as ex:
        if not _is_unknown_exc(ex):
            raise HTTPException(502,"补腿下单失败: %s"%str(ex)[:150])
        rec=(await verify_leg_open(truth_leg,rid)) if truth_leg is not None else None
        if isinstance(rec,dict):
            _push_alert("warn","单腿修复: 响应超时但经真相源核实已成交, 已恢复结果(勿重复补开)",username)
            return rec
        if rec=="NOFILL":
            raise HTTPException(502,"补腿超时, 经真相源核实未成交(未双开), 可重试")
        raise HTTPException(502,"补腿结果未知且真相源核对未果, 请人工核对持仓后再操作, 勿立即重试")

@app.post("/api/cmd/repair_leg", dependencies=[Depends(require_license),Depends(require_trade_writer)])
async def cmd_repair_leg(r:RepairLegReq):
    """单腿修复: 一键补开缺失腿(人工确认的市价补开, 点差漂移成本由用户判断)。
       只开缺失的那条腿, 绝不动已有腿; 方向按持仓对方向映射(reverse=主sell/对冲buy, forward=主buy/对冲sell)。"""
    _assert_subject(r.username, r.license_key or "")
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    if r.leg not in ("main","hedge"): raise HTTPException(400,"leg 须为 main|hedge")
    if r.direction not in ("reverse","forward"): raise HTTPException(400,"direction 须为 reverse|forward")
    if not (r.volume and r.volume>0): raise HTTPException(400,"volume 须>0")
    if r.slot<1: raise HTTPException(400,"slot 须为原单腿持仓的有效坑号")
    _maint_block_trading()   # 维护态禁下单前置闸
    await _conn_gate_exec(r.username)   # P0: 按用户桥判健康
    await _exec_owner_gate(r.username)   # 多用户串账墙
    t=_load_tmpl(r.username, r.symbol)
    hedge_sym=ENG.map_hedge_symbol(r.symbol,(t or {}).get("hedge_symbol")) or r.symbol
    legmap={"reverse":("sell","buy"),"forward":("buy","sell")}
    side=legmap[r.direction][0 if r.leg=="main" else 1]
    sym=r.symbol if r.leg=="main" else hedge_sym
    _force_demo=(R.get(RNS+"force_demo:"+r.username)=="1")
    if DEMO_MODE or _force_demo:
        _audit(r.username,actor,"repair_leg",{"leg":r.leg,"side":side,"sym":sym,"vol":r.volume,"slot":r.slot},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式: 将补开%s腿 %s %s %.2f手, 未真实下单"%("主" if r.leg=="main" else "对冲",sym,side,r.volume)}
    _uec=_user_exec_conn(r.username)
    leg_obj=_uec.main if r.leg=="main" else getattr(_uec,"hedge",None)
    if leg_obj is None: raise HTTPException(502,"缺失腿执行连接不可用")
    from connector import _gen_rid
    _rid=_gen_rid()
    account_token="repair:%s"%_rid
    _begin_account_op(r.username,account_token)
    try:
        truth_leg=getattr(_user_conn(r.username),r.leg,None)
        res=await _dispatch_repair_leg(
            leg_obj,truth_leg,sym,r.volume,side,r.direction,r.leg,_rid,r.username)
    finally:
        _release_account_op(r.username,account_token)
    ok=bool((res or {}).get("ok",True)) and "error" not in (res or {})
    _audit(r.username,actor,"repair_leg",{"leg":r.leg,"side":side,"sym":sym,"vol":r.volume,"slot":r.slot,"res":res},False,"ok" if ok else "fail")
    _push_alert("warn" if ok else "err",
        "单腿修复: 补开%s腿 %s %s %.2f手 %s"%("主" if r.leg=="main" else "对冲",sym,side,r.volume,"成功" if ok else "失败"),r.username)
    if not ok: raise HTTPException(502,"补腿未成交: %s"%json.dumps(res)[:180])
    ownership_review=not await _reserve_slot_with_recovery(
        r.symbol,{r.leg:res},r.slot,r.username)
    _remember_open_positions(r.symbol,hedge_sym,r.direction,{r.leg:res},r.slot,r.username,
                             r.volume if r.leg=="main" else None,
                             r.volume if r.leg=="hedge" else None)
    return {"ok":True,"demo":False,"leg":r.leg,"side":side,"symbol":sym,"volume":r.volume,
            "ownership_review":ownership_review,
            "ticket":(res or {}).get("ticket") or (res or {}).get("order"),
            "msg":(("补腿已成交，但归属持久化失败，已暂停自动开仓并要求人工核对")
                   if ownership_review else
                   ("已补开%s腿 %s %s %.2f手"%("主" if r.leg=="main" else "对冲",sym,side,r.volume)))}

class CloseLegReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    symbol:str="XAUUSD"; leg:str; side:str; ticket:int=0; volume:float=0.0; slot:int=0
    client_request_id:str=""
@app.post("/api/cmd/close_leg", dependencies=[Depends(require_license),Depends(require_trade_writer)])
async def cmd_close_leg(r:CloseLegReq):
    """Close one existing leg by exact ticket. This endpoint never infers or closes a peer leg."""
    _assert_subject(r.username, r.license_key or "")
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    if r.leg not in ("main","hedge"): raise HTTPException(400,"leg 须为 main|hedge")
    if r.side not in ("buy","sell"): raise HTTPException(400,"side 须为 buy|sell")
    if not r.ticket: raise HTTPException(400,"EXACT_TICKET_REQUIRED: 单腿平仓必须提供 ticket")
    if r.slot<1: raise HTTPException(400,"slot 须为原单腿持仓的有效坑号")
    item={"op":"close_leg","slot":r.slot,"leg":r.leg,"side":r.side,
          "ticket":r.ticket,"volume":r.volume}
    client_request_id=_trade_client_request_id(r.client_request_id)
    close_intent=_validate_close_items([item])
    request_fingerprint=_trade_request_fingerprint(
        "close",r.username,r.symbol,close_intent)
    replay=_trade_queue_replay(
        client_request_id,r.username,"close",request_fingerprint)
    if replay is not None:
        return replay
    _maint_block_trading()
    if DEMO_MODE:
        exec_conn=await _exec_leg_gate(r.username,r.leg)
        await _assert_live_tickets(r.username,r.symbol,{r.leg:r.ticket},exec_conn,expected_slot=r.slot)
        _audit(r.username,actor,"close_leg",{"leg":r.leg,"ticket":r.ticket,"slot":r.slot},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式: 未真实平仓"}
    return await _enqueue_close_items(
        r.username,r.symbol,actor,close_intent,"manual",
        client_request_id=client_request_id)

class ClosePairReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    symbol:str="XAUUSD"; main_side:str; hedge_side:str
    main_ticket:int=0; hedge_ticket:int=0; main_vol:float=0.0; hedge_vol:float=0.0; slot:int=0
    client_request_id:str=""
async def _execute_close_pair_job(r:ClosePairReq, command_id=None, pair_rid=None,
                                  actor_override=None, slot_token_override=None,
                                  queue_job_id=None, queue_job=None):
    # === P0-D: 身份绑定校验 ===
    if not queue_job_id:
        _assert_subject(r.username, r.license_key or "")
    actor=actor_override or _actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    tracer=get_tracer()
    command_id=command_id or tracer.create_command(CommandType.CLOSE_PAIR,r.username,r.symbol,
        metadata={"main_ticket":r.main_ticket,"hedge_ticket":r.hedge_ticket,"slot":r.slot})
    if not r.main_ticket or not r.hedge_ticket:
        tracer.update_status(command_id,CommandStatus.FAILED)
        tracer.update_field(command_id,"failure_reason","EXACT_TICKET_REQUIRED")
        raise HTTPException(400,"EXACT_TICKET_REQUIRED: 平仓必须同时提供 main_ticket 和 hedge_ticket")
    if r.slot<1:
        tracer.update_status(command_id,CommandStatus.FAILED)
        tracer.update_field(command_id,"failure_reason","SLOT_REQUIRED")
        raise HTTPException(400,"slot 须为原持仓的有效坑号")
    _maint_block_trading()   # 维护态禁下单前置闸
    await _conn_gate_exec(r.username)   # P0: 按用户桥判健康(修 hedge_pro 被 no123 桥误伤)
    await _exec_owner_gate(r.username)   # 多用户串账墙: 登记账户须==执行桥账户
    exec_conn=_user_exec_conn(r.username)
    expected_tickets={"main":r.main_ticket,"hedge":r.hedge_ticket}
    _queue_proof=_queue_preflight_evidence(
        queue_job,"close",r.username,r.symbol,r.slot,expected_tickets=expected_tickets)
    _position_verified_mono=None
    if _queue_proof is None:
        shared_positions=None
        shared_task=_queue_worker_position_task(queue_job)
        if shared_task is not None:
            try:
                shared_positions=await shared_task
            except HTTPException:
                raise
            except Exception as ex:
                raise HTTPException(
                    502,"持仓校验失败，未发送平仓命令: %s"%
                    ex.__class__.__name__)
        await _assert_live_tickets(r.username,r.symbol,expected_tickets,
                                   exec_conn,expected_slot=r.slot,
                                   positions=shared_positions,authoritative=True)
        _position_verified_mono=_t_conn.monotonic()
    else:
        tracer.update_field(command_id,"position_preflight","queue_proof")
    t=_load_tmpl(r.username, r.symbol)
    hedge_sym=ENG.map_hedge_symbol(r.symbol, (t or {}).get("hedge_symbol")) or r.symbol
    xmode=((t or {}).get("exit_mode") or "concurrent"); speed=((t or {}).get("speed_mode") or "fast")
    if xmode not in ("concurrent","main_first","hedge_first"): xmode="concurrent"
    _subsecond_mt5=_subsecond_mt5_user(r.username)
    if _subsecond_mt5:
        # Exact-ticket MT5 closes are independent risk-reducing operations.
        # Keep both bridge requests concurrent and remove the template's
        # artificial leg delay; the pending finalizer still verifies every
        # ticket and auto-converges a surviving peer through the existing
        # exact-ticket repair path.
        xmode="concurrent"; speed="turbo"
    if DEMO_MODE:
        _audit(r.username,actor,"close_pair",{"symbol":r.symbol,"exit_mode":xmode,"main_side":r.main_side,"hedge_side":r.hedge_side},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式[%s]：将平 主腿%s/对冲腿%s 各一笔，未真实下单"%(xmode,r.main_side,r.hedge_side)}
    mv=r.main_vol or None; hv=r.hedge_vol or None
    mt=r.main_ticket or None; ht=r.hedge_ticket or None   # 按坑精确平(有票→只平该笔, 无票→回落按方向平)
    slot_token=slot_token_override or ("%s:close"%command_id)
    _prelocked=(R.get(_slotop_key(r.username,r.symbol,r.slot))==slot_token)
    if not _prelocked and not _acquire_slot_op(r.username,r.symbol,r.slot,slot_token):
        tracer.update_status(command_id,CommandStatus.FAILED)
        raise HTTPException(409,"坑 %d 正在处理，本次未执行"%r.slot)
    _mark_slot_busy(r.symbol,r.slot,ttl=90,username=r.username)
    _slip_dir="reverse" if r.main_side=="sell" else "forward"   # 持仓方向(平仓侧决策快照)
    # Closing is authorized by exact live tickets, not by quotes.  Slippage
    # capture may use an already-pushed tick but must never delay the close POST.
    _ucn=_user_conn(r.username)
    _hleg=getattr(_ucn,"hedge",None)
    _mtk=_memory_bridge_tick_snapshot(
        _ucn.main,r.symbol,max_age_ms=500,username=r.username,role="main")
    _htk=(_memory_bridge_tick_snapshot(
        _hleg,hedge_sym,max_age_ms=500,username=r.username,role="hedge")
        if _hleg is not None else None)
    if _mtk is None or (_hleg is not None and _htk is None):
        tracer.update_field(command_id,"slippage_snapshot","cache_miss")
    dispatch_intent_persisted=False
    _temporal_burst_admission=_trade_bool(
        (queue_job or {}).get("temporal_burst_admission"))
    _dispatch_boundary_crossed=_trade_bool(
        (queue_job or {}).get("_broker_dispatch_started"))
    if queue_job_id:
        try:
            _dispatch_snapshot=TRADE_QUEUE.get_job(queue_job_id) or {}
            _dispatch_boundary_crossed=bool(
                _dispatch_boundary_crossed or
                _trade_bool(_dispatch_snapshot.get("dispatch_intent")))
            if not _dispatch_boundary_crossed:
                _temporal_burst_admission=_trade_bool(
                    _dispatch_snapshot.get("temporal_burst_admission"))
        except Exception:
            pass
    _ctx={"username":r.username,"symbol":r.symbol,"hedge_symbol":hedge_sym,
          "main_side":r.main_side,"hedge_side":r.hedge_side,"actor":actor,
          "command_id":command_id,
          "main_ticket":mt,"hedge_ticket":ht,"main_vol":mv,"hedge_vol":hv,
          "main_tick":_mtk,"hedge_tick":_htk,"direction":_slip_dir,
          "slot":r.slot,"slot_token":slot_token,"account_token":None,
          "queue_job_id":queue_job_id,"pair_rid":pair_rid,
          "mode":xmode,"speed":speed,
          "temporal_burst_admission":_temporal_burst_admission}
    _batch_size=1
    try: _batch_size=max(1,int((queue_job or {}).get("batch_size") or 1))
    except (TypeError,ValueError): pass
    _burst_admission=bool(queue_job_id and
                          (_batch_size>1 or _temporal_burst_admission))
    _ctx["batch_size"]=_batch_size
    _ctx["burst_admission"]=_burst_admission
    _ctx["burst_cohort"]=(queue_job or {}).get("burst_cohort")
    _ctx["burst_depth"]=(queue_job or {}).get("burst_depth") or _batch_size
    try:
        current_slot_token=R.get(_slotop_key(r.username,r.symbol,r.slot))
        if isinstance(current_slot_token,bytes):
            current_slot_token=current_slot_token.decode("utf-8","replace")
        if str(current_slot_token or "")!=str(slot_token):
            raise HTTPException(409,"STALE_SLOT_LOCK: close dispatch ownership changed")
        proof_at_dispatch=(_queue_preflight_evidence(
            queue_job,"close",r.username,r.symbol,r.slot,
            expected_tickets=expected_tickets) if _queue_proof is not None else None)
        authority_expired=(_position_verified_mono is not None and
            _t_conn.monotonic()-_position_verified_mono>_QUEUE_CLOSE_PREFLIGHT_TTL_SECONDS)
        if (_queue_proof is not None and proof_at_dispatch is None) or authority_expired:
            await _assert_live_tickets(r.username,r.symbol,expected_tickets,
                                       exec_conn,expected_slot=r.slot,
                                       authoritative=True)
            tracer.update_field(command_id,"position_preflight","dispatch_refresh")
        if queue_job_id:
            tracer.update_field(command_id,"pair_request_id",pair_rid)
            tracer.update_field(command_id,"main_request_id",str(pair_rid)+"m")
            tracer.update_field(command_id,"hedge_request_id",str(pair_rid)+"h")
            tracer.update_field(command_id,"pending_context",_ctx)
            tracer.update_status(command_id,CommandStatus.SUBMITTED)
            if not _trade_queue_mark_dispatch_intent(queue_job_id,_ctx):
                terminal_error=HTTPException(
                    503,"DISPATCH_INTENT_PERSIST_FAILED: 未发送平仓命令")
                terminal_error.qh_terminal_state="FAILED"
                raise terminal_error
            dispatch_intent_persisted=True
        res=await _exec_close_pair(r.symbol, hedge_sym, r.main_side, r.hedge_side, mv, hv, xmode, speed, main_ticket=mt, hedge_ticket=ht, username=r.username, command_id=command_id,
                                   pair_rid=pair_rid,async_accept=bool(queue_job_id),
                                   burst_admission=_burst_admission)
    except Exception as ex:
        if (dispatch_intent_persisted and isinstance(ex,HTTPException) and
                not getattr(ex,"qh_terminal_state",None)):
            ex.qh_terminal_state="UNKNOWN"
        _clear_slot_busy(r.symbol,r.slot,r.username)
        _release_slot_op(r.username,r.symbol,r.slot,slot_token)
        raise
    if _pair_pending(res):
        tracer.update_status(command_id,CommandStatus.SUBMITTED)
        tracer.record_timestamp(command_id,TraceTimestamp.HTTP_SENT)
        account_token=res.pop("_account_op_token",None)
        _ctx["account_token"]=account_token
        if queue_job_id:
            _trade_queue_mark_dispatching(queue_job_id,res,_ctx)
        _aio.create_task(_finalize_pending_close(command_id,res,_ctx))
        return JSONResponse(status_code=202,content={"ok":True,"accepted":True,"state":"DISPATCHING",
            "command_id":command_id,"status_url":"/api/command/"+command_id,"detail":res})
    try:
        mok=_resolved_leg_ok(res,"main"); hok=_resolved_leg_ok(res,"hedge")
        _finalize_closed_tickets_local(r.symbol,(
            ("main",mt if mok else None),("hedge",ht if hok else None)),r.username)
        if mok != hok:
            _halt_auto_entry(r.username,"single_leg_exposed",{"slot":r.slot,
                "symbol":r.symbol,"res":res,"op":"close"})
            tracer.update_status(command_id,CommandStatus.SINGLE_LEG_EXPOSED)
            tracer.update_field(command_id,"failure_reason","single_leg_exposed")
            _push_alert("err","按对平仓仅一腿成功，已停止自动进单，需人工处理",r.username)
            _audit(r.username,actor,"close_pair",res,False,"NAKED_RISK_single_leg_close")
            terminal_error=HTTPException(409,"裸空风险：按对平仓仅一腿成功，已告警并停止自动进单")
            terminal_error.qh_terminal_state="SINGLE_LEG_EXPOSED"
            raise terminal_error
        if not mok and not hok:
            tracer.update_status(command_id,CommandStatus.FAILED)
            tracer.update_field(command_id,"failure_reason","both_legs_failed")
            _audit(r.username,actor,"close_pair",res,False,"both_legs_failed")
            raise HTTPException(502,"按对平仓失败，两腿均未确认关闭")
        _persist_after_close()   # 平仓账本即时落库(云端会话级缓存不可靠)
        _audit(r.username,actor,"close_pair",res,False,"closed_pair")
        _slip_snap(_slip_dir,"close",_cap_at(_mtk,_htk,_slip_dir,"close"),None,_leg_tickets((res or {}).get("main")))
        _dir="reverse" if r.main_side=="sell" else "forward"
        if not _close_ledger_commit_once(
                command_id,RNS+"ledger:"+r.username+":"+_dir,r.slot):
            tracer.update_status(command_id,CommandStatus.UNKNOWN)
            tracer.update_field(command_id,"failure_reason","close_ledger_commit_failed")
            terminal_error=HTTPException(
                503,"平仓已确认，但精确账本提交失败；已进入自动恢复")
            terminal_error.qh_terminal_state="UNKNOWN"
            terminal_error.qh_result=res
            raise terminal_error
        _record_trace_timestamp_once(
            tracer,command_id,TraceTimestamp.LEDGER_COMMITTED)
        tracer.update_status(command_id,CommandStatus.COMPLETED)
        tracer.record_timestamp(command_id,TraceTimestamp.HTTP_SENT)
        return {"ok":True,"demo":False,"command_id":command_id,"detail":res,"msg":"已按对平仓 主腿%s/对冲腿%s"%(r.main_side,r.hedge_side)}
    finally:
        _clear_slot_busy(r.symbol,r.slot,r.username)
        _release_slot_op(r.username,r.symbol,r.slot,slot_token)

def _trade_queue_mark_dispatch_intent(job_id, context):
    """Persist the broker-call boundary before any request can leave QH."""
    if not job_id or not isinstance(context,dict):
        return False
    try:
        persisted=TRADE_QUEUE.update_job(
            job_id,state="DISPATCHING",dispatch_intent=True,
            dispatch_phase="INTENT",dispatch_started_at=_dt.datetime.utcnow().isoformat(),
            temporal_burst_frozen=_trade_bool(
                context.get("temporal_burst_admission")),
            context=context)
    except Exception:
        return False
    if not isinstance(persisted,dict):
        return False
    if str(persisted.get("state") or "").upper()!="DISPATCHING":
        return False
    if str(persisted.get("dispatch_intent") or "").lower() not in ("true","1"):
        return False
    saved=persisted.get("context")
    if not isinstance(saved,dict):
        return False
    required=("username","symbol","slot","queue_job_id","pair_rid")
    valid=all(str(saved.get(key) or "")==str(context.get(key) or "")
              for key in required)
    if valid:
        command_id=str(persisted.get("command_id") or context.get("command_id") or "")
        if command_id:
            try:
                _record_trace_timestamp_once(
                    get_tracer(),command_id,TraceTimestamp.QUEUE_DISPATCH_STARTED)
            except Exception:
                pass
    return valid

def _trade_queue_mark_dispatching(job_id, result, context):
    """Attach the Agent acknowledgement to an already durable intent."""
    if not job_id:
        return False
    try:
        persisted=TRADE_QUEUE.update_job(
            job_id,state="DISPATCHING",dispatch_intent=True,
            dispatch_phase="ACK",result=result,context=context)
    except Exception:
        return False
    if not isinstance(persisted,dict):
        return False
    command_id=str(persisted.get("command_id") or context.get("command_id") or "")
    if command_id:
        try:
            _trace_pair_bridge_ack(get_tracer(),command_id,result)
        except Exception:
            pass
    state=str(persisted.get("state") or "").upper()
    if state in TRADE_QUEUE_TERMINAL_STATES:
        return True
    return (state=="DISPATCHING" and
            str(persisted.get("dispatch_intent") or "").lower() in ("true","1") and
            isinstance(persisted.get("result"),dict) and
            isinstance(persisted.get("context"),dict))


def _trade_queue_saga_phase_hook(job_id, context):
    """Build a fail-closed writer for the ordered pair saga snapshot."""
    if not job_id:
        return None
    durable_context=dict(context or {})

    def persist(phase, result):
        snapshot=dict(result or {})
        snapshot["saga_phase"]=str(phase)
        snapshot["saga_durable"]=True
        current=TRADE_QUEUE.get_job(job_id) or {}
        state=str(current.get("state") or "").upper()
        fields={"dispatch_intent":True,"dispatch_phase":str(phase),
                "saga_phase":str(phase),"saga_durable":True,
                "result":snapshot,"context":durable_context}
        review_state=state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED")
        if review_state:
            if state!="UNKNOWN" and not _open_saga_job(current):
                return False
            persisted=TRADE_QUEUE.update_review_job(job_id,**fields)
        else:
            persisted=TRADE_QUEUE.update_job(job_id,state="DISPATCHING",**fields)
        if not isinstance(persisted,dict):
            return False
        saved_result=persisted.get("result")
        durable=bool(
            str(persisted.get("state") or "").upper() in (
                "DISPATCHING","UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED") and
            str(persisted.get("saga_phase") or "")==str(phase) and
            isinstance(saved_result,dict) and
            str(saved_result.get("request_id") or "")==str(snapshot.get("request_id") or "") and
            str(saved_result.get("saga_phase") or "")==str(phase)
        )
        if durable:
            command_id=str(persisted.get("command_id") or durable_context.get("command_id") or "")
            if command_id:
                try:
                    tracer=get_tracer(); phase_name=str(phase or "").upper()
                    ack_legs=[]
                    if phase_name in ("BURST_ACK","PAIR_ACK"):
                        ack_legs=["main","hedge"]
                    elif phase_name=="FIRST_ACK":
                        ack_legs=["hedge" if durable_context.get("mode")=="hedge_first" else "main"]
                    elif phase_name=="SECOND_ACK":
                        ack_legs=["main" if durable_context.get("mode")=="hedge_first" else "hedge"]
                    for leg in ack_legs:
                        _trace_leg_bridge_ack(
                            tracer,command_id,leg,snapshot.get(leg))
                    _trace_pair_execution(tracer,command_id,snapshot)
                except Exception:
                    pass
        return durable

    return persist


def _trade_queue_release_slot(job):
    if not job:
        return
    slot=int(job.get("slot") or 0)
    if slot>0:
        username=job.get("username")
        symbol=job.get("symbol") or "XAUUSD"
        token=job.get("slot_token")
        # Do not clear a newer operation's visual lock when a stale queue task
        # finishes.  The Redis token is the ownership check; legacy jobs with
        # no token retain the previous best-effort cleanup behavior.
        try:
            owned=(not token or R.get(_slotop_key(username,symbol,slot)) == str(token))
        except Exception:
            owned=not token
        if owned:
            _clear_slot_busy(symbol,slot,username)
        _release_slot_op(username,symbol,slot,token)


def _trade_queue_response(batch, jobs, message):
    return JSONResponse(status_code=202,content={
        "ok":True,"accepted":True,"state":"QUEUED","batch_id":batch["batch_id"],
        "status_url":"/api/trade_queue/batch/"+batch["batch_id"],
        "total":len(jobs),"slots":[int(job.get("slot") or 0) for job in jobs],
        "command_ids":[job.get("command_id") for job in jobs],"msg":message,
    })


def _trade_client_request_id(value):
    request_id=str(value or "").strip()
    if not request_id:
        return ""
    if not 16<=len(request_id)<=64 or not request_id.isalnum():
        raise HTTPException(400,"client_request_id must be 16..64 alphanumeric characters")
    return request_id


def _trade_request_fingerprint(kind, username, symbol, intent):
    import hashlib as _hashlib
    payload={"kind":str(kind),"username":str(username),"symbol":str(symbol),
             "intent":intent}
    encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),
                       ensure_ascii=True,default=str).encode("utf-8")
    return _hashlib.sha256(encoded).hexdigest()


def _trade_queue_replay(client_request_id, username, kind, request_fingerprint):
    if not client_request_id:
        return None
    batch=TRADE_QUEUE.batch_status(client_request_id)
    if not batch:
        return None
    if (str(batch.get("username") or "")!=str(username) or
            str(batch.get("kind") or "")!=str(kind) or
            str(batch.get("request_fingerprint") or "")!=str(request_fingerprint)):
        raise HTTPException(409,"client_request_id was already used for a different trade intent")
    return _trade_queue_response(
        batch,batch.get("jobs") or [],"重复提交已关联到原受理批次，未重复下单")


def _trade_admission_lease_key(client_request_id):
    return RNS+"tradeq:admission:"+str(client_request_id or "")


def _claim_trade_admission(client_request_id, username, kind, request_fingerprint):
    """Single-flight an idempotent request before its slower broker preflight."""
    if not client_request_id:
        return None
    identity={"username":str(username),"kind":str(kind),
              "request_fingerprint":str(request_fingerprint)}
    lease=dict(identity,token=os.urandom(12).hex())
    encoded=json.dumps(lease,sort_keys=True,separators=(",",":"),ensure_ascii=True)
    key=_trade_admission_lease_key(client_request_id)
    if R.set(key,encoded,nx=True,ex=30):
        return encoded
    try: current=json.loads(R.get(key) or "{}")
    except Exception: current={}
    if any(str(current.get(name) or "")!=value for name,value in identity.items()):
        raise HTTPException(409,"client_request_id admission is owned by a different trade intent")
    return ""


def _release_trade_admission(client_request_id, lease):
    if not client_request_id or not lease:
        return False
    try:
        return bool(R.eval("""
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
        """,1,_trade_admission_lease_key(client_request_id),str(lease)))
    except Exception:
        return False


def _trade_admission_pending_response(client_request_id, slots):
    slots=[int(slot) for slot in (slots or []) if int(slot)>0]
    return JSONResponse(status_code=202,content={
        "ok":False,"accepted":True,"state":"ADMISSION_PENDING",
        "admission_uncertain":True,"batch_id":str(client_request_id),
        "admission_deadline":int(time.time()*1000)+15000,
        "total":len(slots),"slots":slots,"command_ids":[],
        "msg":"same request is still completing durable queue admission",
    })


def _wake_trade_queue():
    wake=_TRADE_QUEUE_WAKE
    if wake is not None:
        wake.set()


def _manual_trade_burst_key(job):
    """Stable cohort key for deliberate same-intent manual clicks."""
    if not isinstance(job,dict) or str(job.get("source") or "")!="manual":
        return ""
    kind=str(job.get("kind") or "").lower()
    payload=job.get("payload") if isinstance(job.get("payload"),dict) else {}
    if kind=="open":
        if payload.get("manual_targeted") is not True:
            return ""
        intent=str(payload.get("direction") or "").strip().lower()
        if intent not in ("forward","reverse"):
            return ""
    elif kind=="close":
        intent="close"
    else:
        return ""
    username=str(job.get("username") or "").strip()
    symbol=str(job.get("symbol") or "XAUUSD").strip()
    if not username or not symbol:
        return ""
    return "%smanual-burst:%s:%s:%s:%s"%(RNS,kind,username,symbol,intent)


def _mark_manual_trade_burst(jobs):
    """Upgrade queued siblings arriving within the manual-click window."""
    candidates=[job for job in (jobs or ()) if _manual_trade_burst_key(job)]
    if not candidates:
        return False
    key=_manual_trade_burst_key(candidates[0])
    now=time.time(); marker=None; marker_present=False
    try:
        raw=R.get(key)
        marker_present=raw not in (None,"")
        if marker_present:
            marker=float(raw)
    except (TypeError,ValueError):
        marker=None
    active=bool(marker is not None and now-marker<=_MANUAL_TRADE_BURST_WINDOW_SEC)
    if marker is None:
        try:
            # NX makes the first request deterministic under concurrent HTTP
            # arrivals; the winner remains ordered until a sibling appears.
            won=bool(R.set(key,str(now),ex=_MANUAL_TRADE_BURST_TTL_SEC,nx=True))
            if won:
                marker=now; marker_present=True; active=False
            else:
                marker=float(R.get(key) or 0)
                active=bool(marker and now-marker<=_MANUAL_TRADE_BURST_WINDOW_SEC)
        except (TypeError,ValueError):
            active=False
        except Exception:
            active=False
    elif not active:
        try:
            # Keep a lone click ordered and start a fresh marker window.
            R.set(key,str(now),ex=_MANUAL_TRADE_BURST_TTL_SEC,xx=True)
        except Exception:
            pass
    cohort_jobs_key=key+":jobs"
    try:
        if marker_present and not active:
            R.delete(cohort_jobs_key)
        for job in candidates:
            R.rpush(cohort_jobs_key,str(job.get("job_id") or ""))
        R.expire(cohort_jobs_key,_MANUAL_TRADE_BURST_TTL_SEC)
        sibling_ids=[str(value) for value in (R.lrange(cohort_jobs_key,0,-1) or [])]
    except Exception:
        sibling_ids=[str(job.get("job_id") or "") for job in candidates]
    if active:
        sibling_ids.extend(str(job.get("job_id") or "") for job in candidates)
    unique_ids=[]; seen=set()
    for job_id in sibling_ids:
        if not job_id or job_id in seen:
            continue
        seen.add(job_id); unique_ids.append(job_id)
    cohort_depth=max(1,len(unique_ids))
    for job_id in unique_ids:
        try:
            current=TRADE_QUEUE.get_job(job_id) or {}
            state=str(current.get("state") or "").upper()
            # A sibling may arrive after the dispatcher claimed the first
            # click.  EXECUTING is still promotable only until the durable
            # dispatch intent is written; DISPATCHING and terminal jobs have
            # already frozen their broker semantics.
            promotable=(state=="QUEUED" or (
                state=="EXECUTING" and
                not _trade_bool(current.get("dispatch_intent"))))
            if not promotable:
                continue
            fields={"burst_cohort":key,"burst_depth":cohort_depth}
            if active:
                fields["temporal_burst_admission"]=True
            updated=TRADE_QUEUE.update_job(job_id,**fields)
            for candidate in candidates:
                if str(candidate.get("job_id") or "")==job_id and updated:
                    candidate.update(updated)
        except Exception:
            # Optimization failure must never reject the durable queue write.
            continue
    return active


def _commit_trade_queue_batch(tracer, username, kind, jobs, source, batch_id=None,
                              request_fingerprint=None):
    """Link commands before the Redis transaction makes broker work claimable."""
    from connector import _gen_rid
    batch_id=batch_id or _gen_rid(); linked=[]
    batch_size=max(1,len(jobs or ()))
    for raw in jobs:
        job=dict(raw); command_id=job.get("command_id")
        if not command_id:
            raise RuntimeError("trade queue job missing command_id")
        job_id=str(job.get("job_id") or _gen_rid())
        job["job_id"]=job_id
        # Every queue-created multi-slot batch uses the same dispatch-only
        # admission protocol.  Some automatic-entry callers do not construct
        # ``batch_size`` themselves, so normalize it at the single commit
        # boundary instead of relying on each producer to remember it.
        try:
            declared_size=max(1,int(job.get("batch_size") or 0))
        except (TypeError,ValueError):
            declared_size=0
        if declared_size<=1 and batch_size>1:
            job["batch_size"]=batch_size
        tracer.update_field(command_id,"batch_id",batch_id)
        tracer.update_field(command_id,"queue_job_id",job_id)
        linked.append(job)
    created=TRADE_QUEUE.create_batch(
        username,kind,linked,batch_id=batch_id,source=source,
        request_fingerprint=request_fingerprint)
    for job in created[1]:
        command_id=job.get("command_id")
        if command_id:
            try:
                _record_trace_timestamp_once(
                    tracer,command_id,TraceTimestamp.QUEUE_ADMITTED)
            except Exception:
                pass
    _mark_manual_trade_burst(created[1])
    _wake_trade_queue()
    return created


async def _enqueue_open_batch(r, _admission_lease=None):
    _assert_subject(r.username,r.license_key or "")
    if not r.confirm:
        raise HTTPException(400,"二次确认未通过(confirm=true)")
    if r.direction not in ("reverse","forward"):
        raise HTTPException(400,"direction 必须为 reverse 或 forward")
    client_request_id=_trade_client_request_id(r.client_request_id)
    requested_targets=[]
    for raw_slot in (r.target_slots or []):
        try: requested_slot=int(raw_slot)
        except (TypeError,ValueError):
            raise HTTPException(400,"target_slots 必须是有效坑号列表")
        if requested_slot not in requested_targets:
            requested_targets.append(requested_slot)
    if len(requested_targets)>20:
        raise HTTPException(400,"target_slots 最多允许 20 个坑位")
    target=int(r.slot or 0)
    if target and requested_targets:
        raise HTTPException(400,"slot 与 target_slots 不能同时提交")
    request_fingerprint=_trade_request_fingerprint("open",r.username,r.symbol,{
        "direction":r.direction,"slot":target,"target_slots":requested_targets,
        "slots":int(r.slots or 0),"qty":float(r.qty or 0),
    })
    replay=_trade_queue_replay(
        client_request_id,r.username,"open",request_fingerprint)
    if replay is not None:
        return replay
    if client_request_id and _admission_lease is None:
        lease=_claim_trade_admission(
            client_request_id,r.username,"open",request_fingerprint)
        if not lease:
            pending_slots=requested_targets or ([target] if target else [])
            return _trade_admission_pending_response(client_request_id,pending_slots)
        try:
            return await _enqueue_open_batch(r,_admission_lease=lease)
        finally:
            _release_trade_admission(client_request_id,lease)
    _maint_block_trading()
    t=_load_tmpl(r.username,r.symbol)
    if not t:
        raise HTTPException(404,"参数模板未找到")
    if POL.gate_window(t,"entry",_bj_hm())[0]:
        raise HTTPException(409,"当前不在进单时段(%s-%s 北京)，已拒绝开仓"%(
            t.get("entry_win_start") or "?",t.get("entry_win_end") or "?"))
    ladders=int(t.get("ladders") or 0)
    if not 1<=ladders<=20:
        raise HTTPException(409,"对冲参数配置中的进单量无效，须为 1..20")
    targeted=bool(target or requested_targets)
    if requested_targets:
        invalid=[slot for slot in requested_targets if not 1<=slot<=ladders]
        if invalid:
            raise HTTPException(400,"坑号 %s 超出进单量范围(1..%d)"%(invalid,ladders))
    elif target and not 1<=target<=ladders:
        raise HTTPException(400,"坑号 %d 超出进单量范围(1..%d)"%(target,ladders))
    force_demo=(R.get(RNS+"force_demo:"+r.username)=="1")
    positions=None
    if DEMO_MODE or force_demo:
        async def _execution_gates():
            await _conn_gate_exec(r.username)
            await _exec_owner_gate(r.username)
        _,position_read=await _aio.gather(
            _execution_gates(),
            _occupied_slots(r.symbol,r.username,include_positions=True))
        occ,positions=position_read
        if occ is None:
            raise HTTPException(502,"无法读取当前持仓坑位，未受理开仓")
    else:
        # Durable acceptance must not wait for a remote /positions read. The
        # worker revalidates broker truth before writing its dispatch intent.
        occ=_durable_occupied_slots(r.symbol,r.username,ladders)
    if requested_targets:
        occupied=[slot for slot in requested_targets if slot in set(occ)]
        if occupied:
            raise HTTPException(409,"坑 %s 已有持仓，不能重复开"%occupied)
        candidates=requested_targets
    elif target:
        if target in set(occ):
            raise HTTPException(409,"坑 %d 已有持仓，不能重复开"%target)
        candidates=[target]
    else:
        # The configured entry quantity is authoritative. The request's legacy
        # slots/qty fields no longer limit a bulk click.
        candidates=[slot for slot in range(1,ladders+1) if slot not in set(occ)]
    review_blocked=[slot for slot in candidates if _slot_review_record(r.username,r.symbol,slot)]
    if targeted and review_blocked:
        for blocked_slot in review_blocked:
            _assert_slot_review_clear(r.username,r.symbol,blocked_slot)
    if review_blocked:
        candidates=[slot for slot in candidates if slot not in set(review_blocked)]
    if not candidates:
        if review_blocked:
            raise HTTPException(409,"RECONCILIATION_REQUIRED: 所有空坑均在等待成交结果核对")
        raise HTTPException(409,"进单量对应的坑位已满(%d/%d)，无空坑可开"%(len(occ),ladders))
    preflight_limits=_entry_position_limits(r.username)
    if DEMO_MODE or force_demo:
        violation=_entry_capacity_guard_from_positions(
            r.username,positions,requested=len(candidates),limits=preflight_limits)
        if violation:
            _latch_entry_capacity(r.username,violation,"queue_preflight_demo")
            raise HTTPException(409,"持仓容量闸已阻断开仓: %s"%json.dumps(violation,ensure_ascii=False))
        return {"ok":True,"demo":True,"ladders":ladders,"to_open":len(candidates),
                "slots":candidates,"msg":"演示模式：将按进单量受理 %d 个空坑，未真实下单"%len(candidates)}
    from connector import _gen_rid
    tracer=get_tracer(); actor=_actor(r.license_key); jobs=[]; locked=[]
    batch_id=client_request_id or _gen_rid(); command_ids=[]
    try:
        for slot in candidates:
            command_id=tracer.create_command(CommandType.OPEN_PAIR,r.username,r.symbol,
                direction=r.direction,metadata={"slot":slot,"ladders":ladders,"source":"trade_queue"})
            command_ids.append(command_id)
            slot_token="queue:%s:open"%command_id
            if not _acquire_slot_op(r.username,r.symbol,slot,slot_token,ttl=180):
                if targeted:
                    raise HTTPException(409,"坑 %d 正在排队或执行，本次未重复受理"%slot)
                tracer.update_status(command_id,CommandStatus.FAILED)
                tracer.update_field(command_id,"failure_reason","slot_lock_unavailable")
                continue
            locked.append((slot,slot_token))
            _mark_slot_busy(r.symbol,slot,ttl=180,username=r.username)
            job_id=_gen_rid()
            jobs.append({"op":"open_pair","slot":slot,"symbol":r.symbol,
                "job_id":job_id,"batch_id":batch_id,"command_id":command_id,
                "pair_rid":_gen_rid(),"slot_token":slot_token,"actor":actor})
        if not jobs:
            raise HTTPException(409,"所有空坑均已在排队或执行，本次未重复受理")
        batch_size=len(jobs)
        for job in jobs: job["batch_size"]=batch_size
        for job in jobs:
            job["payload"]={"direction":r.direction,"ladders":ladders,
                            "manual_targeted":targeted,
                            "intended_slot":int(job["slot"])}
        batch,prepared=_commit_trade_queue_batch(
            tracer,r.username,"open",jobs,"manual",batch_id=batch_id,
            request_fingerprint=(request_fingerprint if client_request_id else None))
        return _trade_queue_response(batch,prepared,
            "已按进单量 %d 受理 %d 个空坑，关仓命令可优先抢占排队"%(ladders,len(prepared)))
    except Exception as ex:
        for job in jobs:
            _release_entry_capacity_reservation(r.username,job.get("job_id"))
        for command_id in command_ids:
            try:
                tracer.update_status(command_id,CommandStatus.FAILED)
                tracer.update_field(command_id,"failure_reason","queue_admission_abort:%s"%ex.__class__.__name__)
            except Exception: pass
        for slot,token in locked:
            _clear_slot_busy(r.symbol,slot,r.username)
            _release_slot_op(r.username,r.symbol,slot,token)
        raise


async def _trade_queue_wait_open_turn(job, timeout=30.0):
    """Keep legacy dispatch ordering without coupling intent-v1 preflights.

    Intent-v1 persists the broker identity before preflight and each slot owns
    an independent lock/capacity reservation. Once a predecessor has entered
    EXECUTING it can no longer require a later slot to wait for its network
    checks. Older jobs retain the DISPATCHING/terminal barrier.
    """
    if not isinstance(job,dict):
        return
    try: seq=int(job.get("seq") or 0)
    except (TypeError,ValueError): seq=0
    batch_id=str(job.get("batch_id") or "")
    if seq<=1 or not batch_id:
        return
    deadline=_t_conn.monotonic()+max(1.0,float(timeout or 30.0))
    released_states=set(TRADE_QUEUE_TERMINAL_STATES)|{"DISPATCHING"}
    while True:
        batch=TRADE_QUEUE.batch_status(batch_id)
        if not batch:
            raise HTTPException(503,"ORDER_BARRIER_UNAVAILABLE: batch state missing")
        blocked=[]
        for predecessor in (batch.get("jobs") or []):
            try: predecessor_seq=int(predecessor.get("seq") or 0)
            except (TypeError,ValueError): predecessor_seq=0
            state=str(predecessor.get("state") or "UNKNOWN").upper()
            protocol=str(predecessor.get("dispatch_protocol") or "")
            released=(state in released_states or
                      (state=="EXECUTING" and protocol=="intent-v1"))
            if 0<predecessor_seq<seq and not released:
                blocked.append((predecessor_seq,state))
        if not blocked:
            return
        if _t_conn.monotonic()>=deadline:
            raise HTTPException(503,"ORDER_BARRIER_TIMEOUT: predecessors=%s"%blocked)
        await _aio.sleep(0.005)


@app.post("/api/cmd/open_pair", dependencies=[Depends(require_license),Depends(require_trade_writer)])
async def cmd_open_pair(r:OpenPairReq):
    return await _enqueue_open_batch(r)


async def _enqueue_open_items(username, symbol, actor, items, source="auto_entry"):
    """Queue prequalified, explicitly slotted automatic entries as one batch."""
    if not items:
        return None
    from connector import _gen_rid
    tracer=get_tracer(); jobs=[]; locked=[]
    try:
        for item in items:
            slot=int(item.get("slot") or 0); direction=item.get("direction")
            if slot<1 or direction not in ("reverse","forward"):
                continue
            if _slot_review_record(username,symbol,slot):
                continue
            command_id=tracer.create_command(CommandType.OPEN_PAIR,username,symbol,direction=direction,
                metadata={"slot":slot,"source":"trade_queue","auto":True})
            slot_token="queue:%s:open"%command_id
            if not _acquire_slot_op(username,symbol,slot,slot_token,ttl=180):
                continue
            locked.append((slot,slot_token)); _mark_slot_busy(symbol,slot,ttl=180,username=username)
            payload=dict(item); payload["intended_slot"]=slot
            jobs.append({"op":"open_pair","slot":slot,"symbol":symbol,"command_id":command_id,
                "pair_rid":_gen_rid(),"slot_token":slot_token,"payload":payload,"actor":actor})
        if not jobs:
            return None
        batch,prepared=_commit_trade_queue_batch(tracer,username,"open",jobs,source)
        return batch,prepared
    except Exception:
        for slot,token in locked:
            _clear_slot_busy(symbol,slot,username); _release_slot_op(username,symbol,slot,token)
        raise


def _position_side(position, default="buy"):
    if not position:
        return default
    return "sell" if (str(position.get("type"))=="1" or position.get("side")=="sell") else "buy"


def _exact_positive_int(value):
    if value is None or isinstance(value,bool):
        return None
    text=str(value).strip()
    if not text or not text.isdigit():
        return None
    number=int(text)
    return number if number>0 else None


def _index_close_positions(positions, symbol, username):
    """Return slot -> leg -> row only when every live row has one exact owner."""
    if not isinstance(positions,dict):
        raise HTTPException(502,"POSITION_SNAPSHOT_UNAVAILABLE: invalid pair payload")
    for leg in ("main","hedge"):
        raw=positions.get(leg)
        if isinstance(raw,list):
            continue
        if isinstance(raw,dict) and isinstance(raw.get("positions"),list):
            continue
        raise HTTPException(502,"POSITION_SNAPSHOT_UNAVAILABLE: %s leg unreadable"%leg)
    normalized=_normalize_position_legs(positions)
    ticket_legs={}
    for leg in ("main","hedge"):
        for row in normalized.get(leg) or []:
            if row.get("pair_ticket_conflict"):
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: pair_ticket_conflict")
            ticket=_exact_positive_int(row.get("ticket") or row.get("order"))
            if ticket is None:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: %s live row has no exact ticket"%leg)
            previous=ticket_legs.get(ticket)
            if previous is not None:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: ticket #%s is repeated on %s/%s"%(
                        ticket,previous,leg))
            ticket_legs[ticket]=leg
            row["ticket"]=ticket

    # Closing must consume ownership established when QH opened/reserved the
    # ticket. The display slot map alone is not proof because _annotate_slots()
    # may assign fresh slots to unrelated legacy positions by time order.
    try:
        slot_maps={leg:(R.hgetall(_slotmap_key(leg,symbol,username)) or {})
                   for leg in ("main","hedge")}
        owner_maps={leg:(R.hgetall(_slotowner_key(leg,symbol,username)) or {})
                    for leg in ("main","hedge")}
    except Exception as ex:
        raise HTTPException(502,
            "POSITION_OWNERSHIP_UNAVAILABLE: %s"%ex.__class__.__name__)
    by_slot={}; ticket_locations={}
    for leg in ("main","hedge"):
        for row in normalized.get(leg) or []:
            if row.get("pair_ticket_conflict"):
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: pair_ticket_conflict")
            ticket=_exact_positive_int(row.get("ticket") or row.get("order"))
            slot=_exact_positive_int(owner_maps[leg].get(str(ticket)))
            display_slot=_exact_positive_int(slot_maps[leg].get(str(ticket)))
            if ticket is None or slot is None:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: %s ticket #%s has no persisted slot owner (authoritative)"%(
                        leg,ticket or "?"))
            if display_slot!=slot:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: %s ticket #%s slot ownership mismatch"%(
                        leg,ticket))
            location=(leg,slot)
            if ticket in ticket_locations:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: ticket #%s has multiple locations"%ticket)
            pair=by_slot.setdefault(slot,{})
            if leg in pair:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: slot %s has multiple %s tickets"%(slot,leg))
            row["ticket"]=ticket; row["slot"]=slot
            pair[leg]=row; ticket_locations[ticket]=location
    return by_slot


def _assert_requested_close_pair(positions, symbol, username, expected, expected_slot):
    """Prove only the requested live pair without trusting unrelated rows."""
    slot=_exact_positive_int(expected_slot)
    if slot is None:
        raise HTTPException(400,"SLOT_REQUIRED")
    if set(expected or {})!={"main","hedge"}:
        raise HTTPException(400,"EXACT_TICKET_REQUIRED: close_pair")
    requested={leg:_exact_positive_int((expected or {}).get(leg)) for leg in ("main","hedge")}
    if None in requested.values():
        raise HTTPException(400,"EXACT_TICKET_REQUIRED: close_pair")
    if requested["main"]==requested["hedge"]:
        raise HTTPException(409,"AMBIGUOUS_POSITION_OWNERSHIP: duplicate ticket across close legs")
    if not isinstance(positions,dict):
        raise HTTPException(502,"POSITION_SNAPSHOT_UNAVAILABLE: invalid pair payload")
    for leg in ("main","hedge"):
        if not isinstance(positions.get(leg),list):
            raise HTTPException(502,"POSITION_SNAPSHOT_UNAVAILABLE: %s leg unreadable"%leg)

    normalized=_normalize_position_legs(positions)
    try:
        slot_maps={leg:(R.hgetall(_slotmap_key(leg,symbol,username)) or {})
                   for leg in ("main","hedge")}
        owner_maps={leg:(R.hgetall(_slotowner_key(leg,symbol,username)) or {})
                    for leg in ("main","hedge")}
    except Exception as ex:
        raise HTTPException(502,"POSITION_OWNERSHIP_UNAVAILABLE: %s"%ex.__class__.__name__)

    occurrences={ticket:[] for ticket in set(requested.values())}
    for leg in ("main","hedge"):
        for row in normalized.get(leg) or []:
            ticket=_exact_positive_int(row.get("ticket") or row.get("order"))
            if ticket in occurrences:
                occurrences[ticket].append((leg,row))
    missing=[]
    for leg,ticket in requested.items():
        matches=occurrences.get(ticket) or []
        if len(matches)!=1 or matches[0][0]!=leg:
            if len(matches)>1 or (matches and matches[0][0]!=leg):
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: requested ticket #%s has multiple locations"%ticket)
            missing.append("%s #%s"%("main" if leg=="main" else "hedge",ticket))
            continue
        if matches[0][1].get("pair_ticket_conflict"):
            raise HTTPException(409,"AMBIGUOUS_POSITION_OWNERSHIP: pair_ticket_conflict")
    if missing:
        raise HTTPException(409,
            "position already closed or ticket missing; no close sent: "+", ".join(missing))

    wrong_slot=[]
    for leg,ticket in requested.items():
        owner_slot=_exact_positive_int(owner_maps[leg].get(str(ticket)))
        display_slot=_exact_positive_int(slot_maps[leg].get(str(ticket)))
        if owner_slot is None:
            raise HTTPException(409,
                "AMBIGUOUS_POSITION_OWNERSHIP: %s ticket #%s has no persisted slot owner (authoritative)"%(
                    leg,ticket))
        if owner_slot!=slot or display_slot!=owner_slot:
            wrong_slot.append("%s #%s->owner%s/display%s"%(
                leg,ticket,owner_slot or "?",display_slot or "?"))
    if wrong_slot:
        raise HTTPException(409,
            "AMBIGUOUS_POSITION_OWNERSHIP: ticket/slot mismatch: "+", ".join(wrong_slot))

    # Owner-less unrelated rows cannot block an exact-ticket close. A second
    # live ticket claiming this slot still makes the requested slot ambiguous.
    for leg in ("main","hedge"):
        contenders=[]
        for row in normalized.get(leg) or []:
            ticket=_exact_positive_int(row.get("ticket") or row.get("order"))
            if ticket is None:
                continue
            if _exact_positive_int(owner_maps[leg].get(str(ticket)))==slot:
                contenders.append(ticket)
        if contenders.count(requested[leg])!=1 or len(set(contenders))!=1:
            raise HTTPException(409,
                "AMBIGUOUS_POSITION_OWNERSHIP: slot %s has multiple %s tickets"%(slot,leg))
    return True


def _validate_close_items(items):
    """Validate a close batch before creating commands or acquiring slot locks."""
    if not isinstance(items,(list,tuple)):
        raise HTTPException(400,"INVALID_CLOSE_BATCH")
    validated=[]; seen_slots={}; seen_tickets={}
    for index,item in enumerate(items):
        if not isinstance(item,dict):
            raise HTTPException(400,"INVALID_CLOSE_ITEM: index %s"%index)
        if item.get("pair_ticket_conflict"):
            raise HTTPException(409,
                "AMBIGUOUS_POSITION_OWNERSHIP: pair_ticket_conflict")
        slot=_exact_positive_int(item.get("slot"))
        if slot is None:
            raise HTTPException(400,"SLOT_REQUIRED: close item %s"%index)
        if slot in seen_slots:
            raise HTTPException(409,
                "AMBIGUOUS_POSITION_OWNERSHIP: multiple close tasks for slot %s"%slot)
        op=str(item.get("op") or "").strip()
        if op not in ("close_pair","close_leg"):
            raise HTTPException(400,"INVALID_CLOSE_OP: %s"%(op or "missing"))
        clean=dict(item); clean["op"]=op; clean["slot"]=slot
        owned=[]
        if op=="close_pair":
            if item.get("leg") or item.get("ticket"):
                raise HTTPException(400,"INVALID_CLOSE_ITEM: close_pair contains leg ticket fields")
            main_ticket=_exact_positive_int(item.get("main_ticket"))
            hedge_ticket=_exact_positive_int(item.get("hedge_ticket"))
            if main_ticket is None or hedge_ticket is None:
                raise HTTPException(400,"EXACT_TICKET_REQUIRED: close_pair")
            if main_ticket==hedge_ticket:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: pair legs share ticket #%s"%main_ticket)
            if item.get("main_side") not in ("buy","sell") or item.get("hedge_side") not in ("buy","sell"):
                raise HTTPException(400,"INVALID_CLOSE_SIDE: close_pair")
            clean["main_ticket"]=main_ticket; clean["hedge_ticket"]=hedge_ticket
            owned=[("main",main_ticket),("hedge",hedge_ticket)]
        else:
            if item.get("main_ticket") or item.get("hedge_ticket"):
                raise HTTPException(400,"INVALID_CLOSE_ITEM: close_leg contains pair ticket fields")
            leg=item.get("leg"); ticket=_exact_positive_int(item.get("ticket"))
            if leg not in ("main","hedge"):
                raise HTTPException(400,"INVALID_CLOSE_LEG: %s"%leg)
            if ticket is None:
                raise HTTPException(400,"EXACT_TICKET_REQUIRED: close_leg")
            if item.get("side") not in ("buy","sell"):
                raise HTTPException(400,"INVALID_CLOSE_SIDE: close_leg")
            clean["leg"]=leg; clean["ticket"]=ticket
            owned=[(leg,ticket)]
        for leg,ticket in owned:
            previous=seen_tickets.get(ticket)
            if previous is not None:
                raise HTTPException(409,
                    "AMBIGUOUS_POSITION_OWNERSHIP: ticket #%s reused by %s/%s"%(
                        ticket,previous[0],leg))
            seen_tickets[ticket]=(leg,slot)
        seen_slots[slot]=index; validated.append(clean)
    return validated


async def _close_batch_position_snapshot(conn, items, authoritative=False):
    """Read one broker snapshot for a multi-slot worker dispatch wave."""
    required={
        (item.get("leg") if item.get("op")=="close_leg" else "main")
        for item in (items or ())
    }
    if any(item.get("op")=="close_pair" for item in (items or ())):
        required.add("hedge")
    if required=={"main","hedge"} and hasattr(conn,"both_positions"):
        return await _read_both_positions_with_retry(
            conn,authoritative=authoritative)

    async def _read_one(leg):
        legobj=getattr(conn,leg,None)
        if legobj is None:
            raise HTTPException(502,"持仓校验失败，%s bridge unavailable"%leg)
        return leg,await _read_position_leg(
            legobj,authoritative=authoritative)

    last_error=None
    for attempt in range(len(_POSITION_READ_RETRY_DELAYS)+1):
        try:
            reads=await _aio.wait_for(
                _aio.gather(*(_read_one(leg) for leg in sorted(required))),
                timeout=_POSITION_READ_ATTEMPT_TIMEOUT)
            return dict(reads)
        except _aio.TimeoutError as ex:
            last_error=ex
        except Exception as ex:
            last_error=ex
        if attempt<len(_POSITION_READ_RETRY_DELAYS):
            await _aio.sleep(_POSITION_READ_RETRY_DELAYS[attempt])
    raise HTTPException(
        502,"持仓校验失败，未发送平仓命令: %s"%(
            last_error.__class__.__name__ if last_error else "unknown"))


async def _enqueue_close_items(username, symbol, actor, items, source="manual",
                               client_request_id="", _admission_lease=None):
    if not items:
        return {"ok":True,"accepted":False,"total":0,"msg":"没有符合条件的持仓可平"}
    items=_validate_close_items(items)
    client_request_id=_trade_client_request_id(client_request_id)
    request_fingerprint=_trade_request_fingerprint(
        "close",username,symbol,items)
    replay=_trade_queue_replay(
        client_request_id,username,"close",request_fingerprint)
    if replay is not None:
        return replay
    if client_request_id and _admission_lease is None:
        lease=_claim_trade_admission(
            client_request_id,username,"close",request_fingerprint)
        if not lease:
            return _trade_admission_pending_response(
                client_request_id,[item.get("slot") for item in items])
        try:
            return await _enqueue_close_items(
                username,symbol,actor,items,source,
                client_request_id=client_request_id,_admission_lease=lease)
        finally:
            _release_trade_admission(client_request_id,lease)
    from connector import _gen_rid
    tracer=get_tracer(); jobs=[]; locked=[]; preflight=[]; command_ids=[]; review_blocked=[]
    batch_id=client_request_id or _gen_rid()
    try:
        for item in items:
            slot=item["slot"]
            review=_slot_review_record(username,symbol,slot)
            if review:
                if _authoritative_single_leg_review_close(username,symbol,item,review):
                    item=dict(item)
                    item.update(_single_leg_review_close_source(item,review))
                else:
                    review_blocked.append((slot,review))
                    continue
            slot_token="queue:preflight:%s"%_gen_rid()
            if not _acquire_slot_op(username,symbol,slot,slot_token,ttl=180):
                continue
            locked.append((slot,slot_token))
            preflight.append((item,slot_token))
        if not preflight:
            if review_blocked:
                slot,review=review_blocked[0]
                raise HTTPException(409,"RECONCILIATION_REQUIRED: 坑 %d %s，禁止重复平仓"%(
                    slot,review.get("state") or "MANUAL_REVIEW"))
            raise HTTPException(409,"所选坑位均已在排队或执行，本次未重复受理")
        batch_size=len(preflight)
        for item,slot_token in preflight:
            slot=item["slot"]
            op=item["op"]
            cmd_type=CommandType.CLOSE_LEG if op=="close_leg" else CommandType.CLOSE_PAIR
            source_metadata={name:item.get(name) for name in _SOURCE_REVIEW_FIELDS
                             if item.get(name) not in (None,"")}
            command_id=tracer.create_command(cmd_type,username,symbol,
                metadata={"slot":slot,"source":"trade_queue",
                          "main_ticket":item.get("main_ticket"),"hedge_ticket":item.get("hedge_ticket"),
                          "leg":item.get("leg"),"ticket":item.get("ticket"),
                          "single_leg_review_authorized":item.get("single_leg_review_authorized"),
                          "preflight":"worker_exact_ticket",**source_metadata})
            command_ids.append(command_id)
            _mark_slot_busy(symbol,slot,ttl=180,username=username)
            job_id=_gen_rid()
            payload=dict(item); payload["intended_slot"]=slot
            jobs.append({"op":op,"slot":slot,"symbol":symbol,"command_id":command_id,
                         "job_id":job_id,"batch_id":batch_id,"batch_size":batch_size,
                         "pair_rid":_gen_rid(),"slot_token":slot_token,"payload":payload,
                         "actor":actor})
        batch,prepared=_commit_trade_queue_batch(
            tracer,username,"close",jobs,source,batch_id=batch_id,
            request_fingerprint=(request_fingerprint if client_request_id else None))
        return _trade_queue_response(batch,prepared,"已优先受理 %d 个精确 ticket 平仓任务"%len(prepared))
    except Exception as ex:
        for command_id in command_ids:
            try:
                tracer.update_status(command_id,CommandStatus.FAILED)
                tracer.update_field(command_id,"failure_reason","queue_preflight_abort:%s"%ex.__class__.__name__)
            except Exception:
                pass
        for slot,token in locked:
            _clear_slot_busy(symbol,slot,username)
            _release_slot_op(username,symbol,slot,token)
        raise


async def _collect_close_items(username, symbol, profit_only=False):
    both=await _user_exec_conn(username).both_positions()
    by_slot=_index_close_positions(both,symbol,username)
    items=[]
    for slot in sorted(by_slot):
        pair=by_slot[slot]; main=pair.get("main"); hedge=pair.get("hedge")
        net=float((main or {}).get("profit") or 0)+float((hedge or {}).get("profit") or 0)
        if profit_only and net<=0:
            continue
        if main and hedge:
            items.append({"op":"close_pair","slot":slot,
                "main_side":_position_side(main),"hedge_side":_position_side(hedge,"sell"),
                "main_ticket":int(main.get("ticket") or 0),"hedge_ticket":int(hedge.get("ticket") or 0),
                "main_vol":float(main.get("volume") or 0),"hedge_vol":float(hedge.get("volume") or 0),
                "net":net})
        else:
            leg="main" if main else "hedge"; pos=main or hedge
            if pos and pos.get("ticket"):
                items.append({"op":"close_leg","slot":slot,"leg":leg,"side":_position_side(pos),
                    "ticket":int(pos.get("ticket")),"volume":float(pos.get("volume") or 0),"net":net})
    return items


@app.post("/api/cmd/close_pair", dependencies=[Depends(require_license),Depends(require_trade_writer)])
async def cmd_close_pair(r:ClosePairReq):
    _assert_subject(r.username,r.license_key or "")
    if not r.confirm:
        raise HTTPException(400,"二次确认未通过(confirm=true)")
    if not r.main_ticket or not r.hedge_ticket or r.slot<1:
        raise HTTPException(400,"EXACT_TICKET_REQUIRED: 平仓必须提供原坑位及双腿 ticket")
    item={"op":"close_pair","slot":r.slot,"main_side":r.main_side,"hedge_side":r.hedge_side,
          "main_ticket":r.main_ticket,"hedge_ticket":r.hedge_ticket,
          "main_vol":r.main_vol,"hedge_vol":r.hedge_vol}
    client_request_id=_trade_client_request_id(r.client_request_id)
    close_intent=_validate_close_items([item])
    request_fingerprint=_trade_request_fingerprint(
        "close",r.username,r.symbol,close_intent)
    replay=_trade_queue_replay(
        client_request_id,r.username,"close",request_fingerprint)
    if replay is not None:
        return replay
    _maint_block_trading()
    return await _enqueue_close_items(
        r.username,r.symbol,_actor(r.license_key),close_intent,"manual",
        client_request_id=client_request_id)


async def _execute_queued_close_leg(job):
    payload=job.get("payload") or {}; username=job["username"]; symbol=job.get("symbol") or "XAUUSD"
    leg=payload.get("leg"); ticket=int(payload.get("ticket") or 0); slot=int(job.get("slot") or 0)
    pair_rid=str(job.get("pair_rid") or "")
    if leg not in ("main","hedge") or not ticket or slot<1 or not pair_rid:
        raise HTTPException(400,"queued close_leg requires exact leg and ticket")
    slot_token=str(job.get("slot_token") or "")
    if not slot_token:
        raise HTTPException(409,"STALE_SLOT_LOCK: queued close_leg has no lock owner")
    prelocked=(R.get(_slotop_key(username,symbol,slot))==slot_token)
    if not prelocked and not _acquire_slot_op(username,symbol,slot,slot_token,ttl=180):
        raise HTTPException(409,"STALE_SLOT_LOCK: slot %d belongs to a newer operation"%slot)
    _mark_slot_busy(symbol,slot,ttl=90,username=username)
    _maint_block_trading(); exec_conn=await _exec_leg_gate(username,leg)
    expected_tickets={leg:ticket}
    queue_proof=_queue_preflight_evidence(
        job,"close",username,symbol,slot,expected_tickets=expected_tickets)
    position_verified_mono=None
    if queue_proof is None:
        shared_positions=None
        shared_task=_queue_worker_position_task(job)
        if shared_task is not None:
            try:
                shared_positions=await shared_task
            except HTTPException:
                raise
            except Exception as ex:
                raise HTTPException(
                    502,"持仓校验失败，未发送单腿平仓命令: %s"%
                    ex.__class__.__name__)
        await _assert_live_tickets(
            username,symbol,expected_tickets,exec_conn,expected_slot=slot,
            positions=shared_positions,authoritative=True)
        position_verified_mono=_t_conn.monotonic()
    t=_load_tmpl(username,symbol); hedge_sym=ENG.map_hedge_symbol(symbol,(t or {}).get("hedge_symbol")) or symbol
    leg_symbol=symbol if leg=="main" else hedge_sym
    tracer=get_tracer(); command_id=job["command_id"]
    tracer.update_field(command_id,"pair_request_id",pair_rid)
    tracer.update_field(command_id,leg+"_request_id",pair_rid+("m" if leg=="main" else "h"))
    current_slot_token=R.get(_slotop_key(username,symbol,slot))
    if isinstance(current_slot_token,bytes):
        current_slot_token=current_slot_token.decode("utf-8","replace")
    if str(current_slot_token or "")!=slot_token:
        raise HTTPException(409,"STALE_SLOT_LOCK: close dispatch ownership changed")
    proof_at_dispatch=(_queue_preflight_evidence(
        job,"close",username,symbol,slot,expected_tickets=expected_tickets)
        if queue_proof is not None else None)
    authority_expired=(position_verified_mono is not None and
        _t_conn.monotonic()-position_verified_mono>_QUEUE_CLOSE_PREFLIGHT_TTL_SECONDS)
    if (queue_proof is not None and proof_at_dispatch is None) or authority_expired:
        await _assert_live_tickets(
            username,symbol,expected_tickets,exec_conn,expected_slot=slot,
            authoritative=True)
        tracer.update_field(command_id,"position_preflight","dispatch_refresh")
    ctx={"username":username,"actor":job.get("actor") or username,"leg":leg,
         "command_id":command_id,
         "ticket":ticket,"side":payload.get("side") or "buy",
         "volume":payload.get("volume") or None,"leg_symbol":leg_symbol,
         "slot":slot,"symbol":symbol,"slot_token":job.get("slot_token"),
         "account_token":None,"queue_job_id":job["job_id"],
         "pair_rid":pair_rid}
    ctx["single_leg_review_authorized"]=payload.get("single_leg_review_authorized")
    for name in _SOURCE_REVIEW_FIELDS:
        if payload.get(name) not in (None,""):
            ctx[name]=payload.get(name)
    tracer.update_field(command_id,"pending_context",ctx)
    tracer.update_status(command_id,CommandStatus.SUBMITTED)
    if not _trade_queue_mark_dispatch_intent(job["job_id"],ctx):
        terminal_error=HTTPException(
            503,"DISPATCH_INTENT_PERSIST_FAILED: 未发送单腿平仓命令")
        terminal_error.qh_terminal_state="FAILED"
        raise terminal_error
    try:
        res=await exec_conn.close_leg(leg,leg_symbol,ctx["side"],ctx["volume"],
            ticket=ticket,rid=pair_rid,ordered_ack=True)
    except HTTPException as ex:
        if not getattr(ex,"qh_terminal_state",None):
            ex.qh_terminal_state="UNKNOWN"
        raise
    if _pair_pending(res):
        tracer.update_status(command_id,CommandStatus.SUBMITTED)
        _trade_queue_mark_dispatching(job["job_id"],res,ctx)
        _aio.create_task(_finalize_pending_leg_close(command_id,res,ctx))
        return JSONResponse(status_code=202,content={"ok":True,"accepted":True,
            "command_id":command_id,"state":"DISPATCHING"})
    try:
        truth_deadline=time.monotonic()+_PENDING_FINALIZER_TRUTH_BUDGET_SEC
        res=await _pending_finalizer_deadline_call(
            truth_deadline,
            lambda _remaining: _reconcile_pending_close_truth(
                exec_conn,res,res,{leg:ticket}),
        )
    except Exception:
        terminal_error=HTTPException(
            503,"CLOSE_TRUTH_UNAVAILABLE: exact ticket close requires broker confirmation")
        terminal_error.qh_terminal_state="UNKNOWN"
        terminal_error.qh_result=res
        raise terminal_error
    tracer.update_field(command_id,"final_result",res)
    if (not _resolved_leg_ok(res,leg) and
            bool((res.get(leg) or {}).get("unknown"))):
        terminal_error=HTTPException(
            503,"CLOSE_TRUTH_UNAVAILABLE: exact ticket outcome unknown")
        terminal_error.qh_terminal_state="UNKNOWN"
        terminal_error.qh_result=res
        raise terminal_error
    if not _resolved_leg_ok(res,leg):
        raise HTTPException(502,"单 ticket 平仓失败")
    _mark_ticket_closed(symbol,leg,ticket,username)
    _release_slot(symbol,leg,ticket,username)
    source_ok,source_reason=_resolve_source_single_leg_review_after_close(
        username,symbol,command_id,ctx)
    if not source_ok:
        terminal_error=HTTPException(
            409,"LOCAL_CLOSE_FINALIZATION_FAILED: %s"%source_reason)
        terminal_error.qh_terminal_state="MANUAL_REVIEW"
        terminal_error.qh_result=res
        raise terminal_error
    _persist_after_close(); tracer.update_status(command_id,CommandStatus.COMPLETED)
    return {"ok":True,"command_id":command_id,"detail":res}


async def _await_trade_queue_terminal(job, timeout=75.0):
    """Keep this slot's worker task alive through broker terminal state."""
    loop=_aio.get_running_loop(); deadline=loop.time()+max(1.0,float(timeout))
    job_id=job.get("job_id")
    while loop.time()<deadline:
        current=TRADE_QUEUE.get_job(job_id) or {}
        if str(current.get("state") or "").upper() in TRADE_QUEUE_TERMINAL_STATES:
            return current
        await _aio.sleep(0.02)
    current=TRADE_QUEUE.get_job(job_id) or {}
    if str(current.get("state") or "").upper() not in TRADE_QUEUE_TERMINAL_STATES:
        reason="broker terminal deadline exceeded while account dispatch remained blocked"
        if job.get("op")=="open_pair":
            _hold_entry_capacity_reservation(job.get("username"),job_id)
        current=TRADE_QUEUE.finish(job_id,"UNKNOWN",error={"detail":reason},
            finished_at=_dt.datetime.utcnow().isoformat()) or current
        _set_slot_review(job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),
                         "UNKNOWN",job.get("command_id"),job_id,reason)
    return current


def _open_ownership_recovery_snapshot(job, body=None):
    """Build the durable snapshot needed to retry owner writes after a fill.

    The synchronous open path can finish both broker legs before the queue
    wrapper sees ``ownership_review``.  Keep that outcome recoverable by
    reusing the phase-hook snapshot (or the deterministic request-id based
    fallback) and never by dispatching another broker open.
    """
    job = dict(job or {})
    job_id = str(job.get("job_id") or "")
    current = (TRADE_QUEUE.get_job(job_id) or job) if job_id else job
    context = _trade_queue_recovery_context(current)
    result = None

    def _complete_pair_evidence(candidate):
        if not isinstance(candidate, dict):
            return False
        tickets = {}
        for leg in ("main", "hedge"):
            leg_result = candidate.get(leg)
            raw_ticket = ((leg_result.get("order") or leg_result.get("deal") or
                           leg_result.get("ticket"))
                          if isinstance(leg_result, dict) else None)
            ticket = _exact_positive_int(raw_ticket)
            if not _resolved_leg_ok(candidate, leg) or ticket is None:
                return False
            tickets[leg] = ticket
        return tickets["main"] != tickets["hedge"]

    # The phase hook normally leaves the exact pair result on the queue job.
    raw_result = current.get("result") if isinstance(current, dict) else None
    if isinstance(raw_result, dict):
        evidence = raw_result.get("evidence")
        candidate = (evidence if raw_result.get("reconciled") and
                     isinstance(evidence, dict) else raw_result)
        if _complete_pair_evidence(candidate):
            result = dict(candidate)

    # A worker test/legacy queue may have only returned the response body.  A
    # successful open response stores the exact pair result in ``detail``.
    if result is None and isinstance(body, dict):
        detail = body.get("detail")
        candidates = detail if isinstance(detail, list) else [detail]
        for candidate in reversed(candidates):
            if _complete_pair_evidence(candidate):
                result = dict(candidate)
                break

    # Do not auto-recover from an intent-only/pending snapshot.  This branch
    # is entered only after both legs were synchronously reported filled, so
    # a durable pair with two exact tickets is the minimum safe evidence.
    if result is None or not context.get("pair_rid"):
        return None

    result = dict(result)
    result["saga_durable"] = True
    result["saga_phase"] = str(
        result.get("saga_phase") or current.get("saga_phase") or "SECOND_DONE")
    result["ownership_recovery"] = True
    context["queue_job_id"] = job_id or context.get("queue_job_id")
    return current, context, result


async def _run_trade_queue_job(job):
    job_id=job["job_id"]; tracer=get_tracer(); command_id=job.get("command_id")
    started_epoch=_dt.datetime.utcnow().timestamp()
    try: queue_wait_ms=max(0,int((started_epoch-float(job.get("created_at") or started_epoch))*1000))
    except (TypeError,ValueError): queue_wait_ms=0
    started=TRADE_QUEUE.update_job(job_id,state="EXECUTING",
        started_at=_dt.datetime.utcnow().isoformat(),started_epoch=started_epoch,
        queue_wait_ms=queue_wait_ms,dispatch_protocol="intent-v1")
    # A duplicate task or a late dispatcher callback may observe a job that is
    # already DISPATCHING/terminal.  Do not send another broker request for
    # that job; the durable queue state is the ownership decision.
    if not started:
        _trade_queue_release_slot(job)
        return
    started_state=str(started.get("state") or "").upper()
    if started_state in TRADE_QUEUE_TERMINAL_STATES:
        _trade_queue_release_slot(job)
        return
    if started_state != "EXECUTING":
        return
    if command_id:
        tracer.update_status(command_id,CommandStatus.PREFLIGHT)
    try:
        payload=job.get("payload") or {}; op=job.get("op")
        intended_slot=payload.get("intended_slot") if isinstance(payload,dict) else None
        if intended_slot is not None:
            exact_intended=_exact_positive_int(intended_slot)
            if exact_intended is None or exact_intended!=int(job.get("slot") or 0):
                raise HTTPException(
                    409,"STALE_INTENDED_SLOT: persisted payload does not match queue slot")
        if op in ("close_pair","close_leg"):
            close_input=dict(payload); close_input["op"]=op
            close_input["slot"]=job.get("slot")
            payload=_validate_close_items([close_input])[0]
            job=dict(job); job["payload"]=payload
        if op=="open_pair":
            req=OpenPairReq(username=job["username"],confirm=True,
                direction=payload.get("direction"),symbol=job.get("symbol") or "XAUUSD",
                slots=1,slot=int(job.get("slot") or 0))
            result=await _execute_open_pair_job(req,command_id=command_id,pair_rid=job.get("pair_rid"),
                actor_override=job.get("actor"),slot_token_override=job.get("slot_token"),queue_job_id=job_id,
                queue_job=job,manual_targeted=(payload.get("manual_targeted") is True))
        elif op=="close_pair":
            req=ClosePairReq(username=job["username"],confirm=True,symbol=job.get("symbol") or "XAUUSD",
                main_side=payload.get("main_side") or "buy",hedge_side=payload.get("hedge_side") or "sell",
                main_ticket=int(payload.get("main_ticket") or 0),hedge_ticket=int(payload.get("hedge_ticket") or 0),
                main_vol=float(payload.get("main_vol") or 0),hedge_vol=float(payload.get("hedge_vol") or 0),
                slot=int(job.get("slot") or 0))
            result=await _execute_close_pair_job(req,command_id=command_id,pair_rid=job.get("pair_rid"),
                actor_override=job.get("actor"),slot_token_override=job.get("slot_token"),
                queue_job_id=job_id,queue_job=job)
        elif op=="close_leg":
            result=await _execute_queued_close_leg(job)
        else:
            raise HTTPException(400,"unknown queued operation: %s"%op)
        current=TRADE_QUEUE.get_job(job_id) or {}
        current_state=str(current.get("state") or "").upper()
        body=result
        if isinstance(result,JSONResponse):
            try: body=json.loads(result.body.decode("utf-8"))
            except Exception: body={"status_code":result.status_code}
        async_handoff=(isinstance(body,dict) and
                       str(body.get("state") or "").upper()=="DISPATCHING")
        if current_state in TRADE_QUEUE_TERMINAL_STATES:
            _trade_queue_release_slot(job)
        elif not async_handoff:
            queue_state=("MANUAL_REVIEW" if isinstance(body,dict)
                         and body.get("ownership_review") is True else "COMPLETED")
            if queue_state=="MANUAL_REVIEW":
                # Both broker legs are already filled here.  Preserve the
                # durable pair snapshot and let the saga retry only the
                # slotowner/slotmap write; publishing MANUAL_REVIEW without a
                # recovery task stranded otherwise valid positions forever.
                recovery=_open_ownership_recovery_snapshot(current or job,body)
                if recovery is not None:
                    recovery_job,recovery_context,recovery_result=recovery
                    recovery_phase=str(recovery_result.get("saga_phase") or "SECOND_DONE")
                    recovery_finished=TRADE_QUEUE.finish(
                        job_id,"UNKNOWN",result=recovery_result,
                        context=recovery_context,saga_durable=True,
                        saga_phase=recovery_phase,dispatch_intent=True,
                        dispatch_phase=recovery_phase,
                        error={"detail":"slotowner persistence failed; automatic recovery scheduled"},
                        finished_at=_dt.datetime.utcnow().isoformat())
                    if (isinstance(recovery_finished,dict) and
                            str(recovery_finished.get("state") or "").upper()=="UNKNOWN"):
                        tracer.update_status(command_id,CommandStatus.UNKNOWN)
                        tracer.update_field(
                            command_id,"failure_reason",
                            "slotowner_persist_failed_after_fill:auto_recovery")
                        _set_slot_review(
                            job.get("username"),job.get("symbol") or "XAUUSD",
                            job.get("slot"),"UNKNOWN",command_id,job_id,
                            "slotowner persistence failed; automatic recovery scheduled")
                        _trade_queue_release_slot(recovery_job)
                        _schedule_open_saga_recovery(
                            command_id,recovery_result,recovery_context,delay=0.0)
                        return
                _set_slot_review(job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),
                                 queue_state,command_id,job_id,"slot ownership persistence requires review")
            else:
                _clear_slot_review(job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),command_id)
            TRADE_QUEUE.finish(job_id,queue_state,result=body,
                               finished_at=_dt.datetime.utcnow().isoformat())
            _trade_queue_release_slot(job)
        else:
            await _await_trade_queue_terminal(job)
    except HTTPException as ex:
        reason=str(ex.detail)
        terminal_state=str(getattr(ex,"qh_terminal_state","FAILED") or "FAILED").upper()
        if terminal_state not in TRADE_QUEUE_TERMINAL_STATES:
            terminal_state="FAILED"
        if command_id:
            tracer.update_status(
                command_id,getattr(CommandStatus,terminal_state,CommandStatus.FAILED))
            tracer.update_field(command_id,"failure_reason",reason)
        if job.get("op")=="open_pair":
            if terminal_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                _hold_entry_capacity_reservation(job.get("username"),job_id)
            else:
                _release_entry_capacity_reservation(job.get("username"),job_id)
        failure_result=getattr(ex,"qh_result",None)
        TRADE_QUEUE.finish(job_id,terminal_state,
                           result=(failure_result if isinstance(failure_result,dict) else None),
                           error={"status":ex.status_code,"detail":reason})
        if terminal_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
            _set_slot_review(job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),
                             terminal_state,command_id,job_id,reason)
        else:
            _clear_slot_review(
                job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),command_id)
        _trade_queue_release_slot(job)
    except Exception as ex:
        if command_id:
            tracer.update_status(command_id,CommandStatus.UNKNOWN)
            tracer.update_field(command_id,"failure_reason","queue:%s"%ex.__class__.__name__)
        if job.get("op")=="open_pair":
            _hold_entry_capacity_reservation(job.get("username"),job_id)
        TRADE_QUEUE.finish(job_id,"UNKNOWN",error={"type":ex.__class__.__name__,"detail":str(ex)[:300]})
        _set_slot_review(job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),
                         "UNKNOWN",command_id,job_id,"queue:%s"%ex.__class__.__name__)
        _trade_queue_release_slot(job)


def _trade_queue_recovery_context(job):
    context=dict(job.get("context") or {}) if isinstance(job.get("context"),dict) else {}
    payload=job.get("payload") if isinstance(job.get("payload"),dict) else {}
    context.setdefault("username",job.get("username"))
    context.setdefault("symbol",job.get("symbol") or "XAUUSD")
    context.setdefault("slot",job.get("slot"))
    context.setdefault("slot_token",job.get("slot_token"))
    context.setdefault("queue_job_id",job.get("job_id"))
    context.setdefault("capacity_reservation_id",job.get("job_id"))
    context.setdefault("pair_rid",job.get("pair_rid"))
    context.setdefault("actor",job.get("actor") or job.get("username"))
    context.setdefault("direction",payload.get("direction"))
    context.setdefault("main_side",payload.get("main_side"))
    context.setdefault("hedge_side",payload.get("hedge_side"))
    context.setdefault("main_ticket",payload.get("main_ticket"))
    context.setdefault("hedge_ticket",payload.get("hedge_ticket"))
    context.setdefault("leg",payload.get("leg"))
    context.setdefault("ticket",payload.get("ticket"))
    context.setdefault("account_token",None)
    return context

def _trade_queue_recovery_result(job, context):
    result=job.get("result")
    if isinstance(result,dict):
        # Reconciled review jobs wrap the original durable saga snapshot in
        # `evidence`.  Recovery must continue from that snapshot instead of
        # treating the wrapper as a connector result with no leg contexts.
        evidence=result.get("evidence")
        if (result.get("reconciled") and isinstance(evidence,dict) and
                evidence.get("saga_durable")):
            return evidence
        return result
    rid=str(context.get("pair_rid") or job.get("pair_rid") or "")
    op=str(job.get("op") or "")
    if not rid:
        return None
    if op=="open_pair":
        direction=str(context.get("direction") or "")
        mode=str(context.get("mode") or "main_first")
        if direction not in ("reverse","forward"):
            return None
        main_side,hedge_side=(("sell","buy") if direction=="reverse" else
                              ("buy","sell"))
        burst=(_trade_bool(context.get("burst_admission")) or
               _trade_bool(context.get("temporal_burst_admission")) or
               int(context.get("batch_size") or job.get("batch_size") or 1)>1)
        result={"direction":direction,"mode":mode,"main":None,"hedge":None,
                "main_ok":False,"hedge_ok":False,"request_id":rid,
                "op":"open","ordered_ack":True,"dispatch_only":burst,
                "burst_admission":burst,"saga_durable":True,
                "saga_phase":str(job.get("saga_phase") or "PAIR_INTENT"),
                "leg_contexts":{
                    "main":{"symbol":context.get("symbol"),
                            "volume":context.get("main_vol"),"side":main_side,
                            "deviation":context.get("main_dev")},
                    "hedge":{"symbol":context.get("hedge_symbol") or context.get("symbol"),
                             "volume":context.get("hedge_vol"),"side":hedge_side,
                             "deviation":context.get("hedge_dev")}}}
        pending={"accepted":True,"pending":True,"op":"open"}
        if burst:
            result["main"]=dict(pending,request_id=rid+"m")
            result["hedge"]=dict(pending,request_id=rid+"h")
        elif mode=="hedge_first":
            result["hedge"]=dict(pending,request_id=rid+"h")
        elif mode=="concurrent":
            result["main"]=dict(pending,request_id=rid+"m")
            result["hedge"]=dict(pending,request_id=rid+"h")
        else:
            result["main"]=dict(pending,request_id=rid+"m")
        return result
    if op in ("close_pair","close_leg"):
        durable_pair=(op=="close_pair")
        burst=bool(durable_pair and (
               _trade_bool(context.get("burst_admission")) or
               _trade_bool(context.get("temporal_burst_admission")) or
               int(context.get("batch_size") or job.get("batch_size") or 1)>1))
        result={"main":None,"hedge":None,"main_ok":False,"hedge_ok":False,
                "request_id":rid,"op":"close","tickets":{},
                "ordered_ack":durable_pair,"burst_admission":burst,
                "saga_durable":durable_pair,"leg_contexts":{}}
        legs=("main","hedge") if op=="close_pair" else (str(context.get("leg") or ""),)
        for leg in legs:
            ticket=(context.get(leg+"_ticket") if op=="close_pair" else
                    context.get("ticket"))
            if leg not in ("main","hedge") or not ticket:
                return None
            result["tickets"][leg]=ticket
            result["leg_contexts"][leg]={
                "symbol":(context.get("hedge_symbol") if leg=="hedge" else
                          context.get("symbol")),
                "side":context.get(leg+"_side"),
                "volume":context.get(leg+"_vol"),"ticket":ticket,
            }
            result[leg]={"accepted":True,"pending":True,"op":"close",
                         "request_id":rid+leg[0],"ticket":ticket}
        return result
    return None


def _open_saga_job(job):
    job=job or {}
    raw_result=job.get("result")
    raw_result=raw_result if isinstance(raw_result,dict) else {}
    evidence=raw_result.get("evidence")
    result=(evidence if raw_result.get("reconciled") and
            isinstance(evidence,dict) else raw_result)
    durable=(_trade_bool(job.get("saga_durable")) or
             _trade_bool(result.get("saga_durable")))
    if str(job.get("op") or "")!="open_pair" or not durable:
        return False
    state=str(job.get("state") or "").upper()
    if state in ("DISPATCHING","UNKNOWN"):
        return True
    if state not in ("MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
        return False

    # A review state is automatically recoverable only when the durable saga
    # itself is still in an idempotent write/status phase, or both fills are
    # already proven and only local ownership persistence remains.  A genuine
    # terminal one-leg fill stays blocked for operator risk handling.
    phase=str(result.get("saga_phase") or job.get("saga_phase") or "").upper()
    retryable_phase=phase in (
        "PAIR_INTENT","FIRST_INTENT","FIRST_ACK","FIRST_UNKNOWN","FIRST_DONE",
        "SECOND_INTENT","SECOND_ACK","SECOND_UNKNOWN",
        "BURST_INTENT","BURST_ACK","BURST_UNKNOWN",
    )
    # A restart can retain an intent-only leg snapshot instead of the newer
    # ``pending`` marker.  It is still recoverable when dispatch was not
    # durably acknowledged; the same request id must be checked before any
    # operator/manual-review latch is applied.
    unresolved=bool(result.get("saga_unknown")) or any(
        result.get(leg) is None or bool((result.get(leg) or {}).get("pending")) or
        bool((result.get(leg) or {}).get("unknown")) or
        bool((result.get(leg) or {}).get("truth_unavailable")) or
        ((result.get(leg) or {}).get("dispatch_started") is False and
         not (result.get(leg) or {}).get("truth_confirmed"))
            for leg in ("main","hedge")
    )
    both_confirmed=bool(result.get("main_ok") and result.get("hedge_ok"))
    return bool((retryable_phase and unresolved) or both_confirmed)


def _pending_finalizer_budget(ctx=None):
    """Give a real burst enough truth time without delaying a lone click.

    MT5 native calls are serialized per terminal.  A five-slot burst can
    therefore have a legitimate tail after the first durable ACK; publishing
    UNKNOWN at the fixed 1.5s budget creates the red manual-review latch even
    though every request is still progressing.  Scale only burst cohorts and
    keep a hard upper bound for network stalls.
    """
    base=float(_PENDING_FINALIZER_TRUTH_BUDGET_SEC)
    context=ctx if isinstance(ctx,dict) else {}
    try:
        depth=max(1,int(context.get("batch_size") or 1),
                  int(context.get("burst_depth") or 1))
    except (TypeError,ValueError):
        depth=1
    burst=(_trade_bool(context.get("burst_admission")) or
           _trade_bool(context.get("temporal_burst_admission")) or
           (int(context.get("batch_size") or 1)>1))
    job_id=str(context.get("queue_job_id") or "")
    if job_id:
        try:
            job=TRADE_QUEUE.get_job(job_id) or {}
            burst=bool(burst or _trade_bool(job.get("temporal_burst_admission")) or
                       int(job.get("batch_size") or 1)>1)
            depth=max(depth,int(job.get("batch_size") or 1),
                      int(job.get("burst_depth") or 1))
            cohort_key=str(context.get("burst_cohort") or
                           job.get("burst_cohort") or "")
            if cohort_key:
                depth=max(depth,int(R.llen(cohort_key+":jobs") or 0))
                burst=bool(burst or depth>1)
            batch_id=str(job.get("batch_id") or "")
            if batch_id:
                batch=TRADE_QUEUE.batch_status(batch_id) or {}
                declared=int(batch.get("total") or 0)
                depth=max(depth,declared,len(batch.get("jobs") or []))
        except (TypeError,ValueError):
            pass
        except Exception:
            # Budget selection must not turn a valid broker request into an
            # error when Redis is briefly unavailable.
            pass
    if not burst:
        return base
    # The two terminals each serialize native calls; reserve roughly one
    # broker round-trip per queued pair plus a small network margin.
    return min(15.0,max(base,0.75+0.65*float(depth)))


def _pending_open_truth_reserve(total_budget):
    """Keep a final broker-position window after Agent status polling."""
    try:
        budget=max(0.0,float(total_budget))
    except (TypeError,ValueError):
        budget=0.0
    if budget<=0:
        return 0.0
    return min(budget*0.80,min(0.75,max(0.35,budget*0.30)))


def _pending_close_truth_reserve(total_budget):
    """Reserve most of a short close budget for exact-ticket position truth."""
    try:
        budget=max(0.0,float(total_budget))
    except (TypeError,ValueError):
        budget=0.0
    if budget<=0:
        return 0.0
    return min(budget*0.80,min(1.0,max(0.50,budget*0.60)))


def _open_saga_finalizer_lease_key(job_id):
    return RNS+"tradeq:saga-recovery:"+str(job_id or "")


def _claim_open_saga_finalizer_lease(job_id):
    """Claim the one writer allowed to advance a durable open saga."""
    if not job_id:
        return None
    token=_TRADE_QUEUE_OWNER+":"+os.urandom(8).hex()
    try:
        claimed=bool(R.set(_open_saga_finalizer_lease_key(job_id),token,
                           nx=True,ex=_OPEN_SAGA_FINALIZER_LEASE_TTL))
    except Exception:
        claimed=False
    return token if claimed else None


def _release_open_saga_finalizer_lease(job_id, token):
    if not job_id or not token:
        return False
    try:
        return bool(R.eval("""
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
        """,1,_open_saga_finalizer_lease_key(job_id),token))
    except Exception:
        # Never delete a lease without an atomic ownership check. Its TTL is
        # the fail-safe when Redis scripting is temporarily unavailable.
        return False


def _schedule_open_saga_recovery(command_id, result, context, delay=0.25):
    """Keep a durable UNKNOWN pair moving across QH restarts/network recovery."""
    job_id=str((context or {}).get("queue_job_id") or "")
    if not job_id or not command_id:
        return None
    existing=_OPEN_SAGA_RECOVERY_TASKS.get(job_id)
    if existing is not None and not existing.done():
        return existing

    async def run():
        await _aio.sleep(max(0.0,float(delay)))
        backoff=0.5
        while True:
            job=TRADE_QUEUE.get_job(job_id) or {}
            if not _open_saga_job(job):
                return
            recovery_context=_trade_queue_recovery_context(job)
            recovery_context.update(dict(context or {}))
            recovery_result=_trade_queue_recovery_result(job,recovery_context) or result
            if not isinstance(recovery_result,dict):
                return
            try:
                advanced=await _finalize_pending_open(
                    command_id,recovery_result,recovery_context)
            except _aio.CancelledError:
                raise
            except Exception:
                advanced=None
            if advanced is False:
                await _aio.sleep(backoff)
                backoff=min(5.0,backoff*2.0)
                continue
            current=TRADE_QUEUE.get_job(job_id) or {}
            if not _open_saga_job(current):
                return
            await _aio.sleep(backoff)
            backoff=min(5.0,backoff*2.0)

    task=_aio.create_task(run())
    _OPEN_SAGA_RECOVERY_TASKS[job_id]=task
    def cleanup(done):
        if _OPEN_SAGA_RECOVERY_TASKS.get(job_id) is done:
            _OPEN_SAGA_RECOVERY_TASKS.pop(job_id,None)
    task.add_done_callback(cleanup)
    return task


def _close_pair_review_recoverable(job):
    job=job or {}
    if str(job.get("op") or "")!="close_pair":
        return False
    state=str(job.get("state") or "").upper()
    if state not in ("DISPATCHING","SINGLE_LEG_EXPOSED","MANUAL_REVIEW"):
        return False
    payload=job.get("payload") if isinstance(job.get("payload"),dict) else {}
    if (_exact_positive_int(job.get("slot")) is None or
            _exact_positive_int(payload.get("main_ticket")) is None or
            _exact_positive_int(payload.get("hedge_ticket")) is None):
        return False
    result=job.get("result") if isinstance(job.get("result"),dict) else {}
    # Exact-ticket closes are replayable with the same Agent request ids.  This
    # covers both a normal ACK that is still draining the MT5 account queue and
    # a QH restart after the durable intent but before the ACK was persisted.
    durable=(_trade_bool(job.get("saga_durable")) or
             _trade_bool(result.get("saga_durable")) or
             _trade_bool(result.get("ordered_ack")) or
             _trade_bool(job.get("temporal_burst_admission")) or
             int(job.get("batch_size") or 1)>1)
    if durable and _pair_pending(result):
        return True
    if state=="DISPATCHING":
        dispatch_intent=_trade_bool(job.get("dispatch_intent"))
        pair_rid=str(job.get("pair_rid") or payload.get("pair_rid") or "")
        return bool(durable and dispatch_intent and pair_rid)
    closed=result.get("closed") if isinstance(result.get("closed"),dict) else {}
    if len(closed)==1:
        return True
    main_ok=_resolved_leg_ok(result,"main")
    hedge_ok=_resolved_leg_ok(result,"hedge")
    return bool(main_ok != hedge_ok)


def _recoverable_close_pair_reviews():
    redis_client=getattr(TRADE_QUEUE,"redis",None)
    namespace=str(getattr(TRADE_QUEUE,"namespace",RNS+"tradeq:"))
    if redis_client is None:
        return []
    jobs=[]
    try:
        for raw_key in redis_client.scan_iter(match=namespace+"job:*",count=100):
            key=(raw_key.decode("utf-8","replace")
                 if isinstance(raw_key,bytes) else str(raw_key))
            job=TRADE_QUEUE.get_job(key[len(namespace+"job:"):])
            if _close_pair_review_recoverable(job):
                jobs.append(job)
    except Exception:
        return jobs
    return jobs


def _schedule_close_pair_review_recovery(command_id, result, context, delay=0.5):
    """Keep exact-ticket close convergence moving until the review is retired."""
    job_id=str((context or {}).get("queue_job_id") or "")
    if not job_id or not command_id:
        return None
    existing=_CLOSE_REVIEW_RECOVERY_TASKS.get(job_id)
    if existing is not None and not existing.done():
        return existing

    async def run():
        await _aio.sleep(max(0.0,float(delay)))
        backoff=0.5
        while True:
            job=TRADE_QUEUE.get_job(job_id) or {}
            if not _close_pair_review_recoverable(job):
                return
            recovery_context=_trade_queue_recovery_context(job)
            recovery_context.update(dict(context or {}))
            recovery_result=_trade_queue_recovery_result(job,recovery_context) or result
            if not isinstance(recovery_result,dict):
                return
            try:
                advanced=await _finalize_pending_close(
                    command_id,recovery_result,recovery_context)
            except _aio.CancelledError:
                raise
            except Exception:
                advanced=None
            if advanced is False:
                await _aio.sleep(backoff)
                backoff=min(5.0,backoff*2.0)
                continue
            current=TRADE_QUEUE.get_job(job_id) or {}
            if not _close_pair_review_recoverable(current):
                return
            await _aio.sleep(backoff)
            backoff=min(5.0,backoff*2.0)

    task=_aio.create_task(run())
    _CLOSE_REVIEW_RECOVERY_TASKS[job_id]=task
    def cleanup(done):
        if _CLOSE_REVIEW_RECOVERY_TASKS.get(job_id) is done:
            _CLOSE_REVIEW_RECOVERY_TASKS.pop(job_id,None)
    task.add_done_callback(cleanup)
    return task


async def _recover_trade_queue():
    tracer=get_tracer()
    for username in TRADE_QUEUE.accounts():
        for job in (TRADE_QUEUE.processing(username) or []):
            if not job:
                continue
            state=str(job.get("state") or "").upper()
            op=str(job.get("op") or "")
            job_id=str(job.get("job_id") or "")
            command_id=job.get("command_id")
            uncertain_state=state in ("EXECUTING","DISPATCHING")

            if op=="open_pair" and uncertain_state:
                # Startup readiness is conditional on making every possibly
                # dispatched open consume durable capacity indefinitely.
                if not _ensure_entry_capacity_hold(username,job_id,job):
                    raise RuntimeError(
                        "startup capacity hold failed for open job %s"%job_id)

            if state=="DISPATCHING":
                context=_trade_queue_recovery_context(job)
                result=_trade_queue_recovery_result(job,context)
                finalize={"open_pair":_finalize_pending_open,
                          "close_pair":_finalize_pending_close,
                          "close_leg":_finalize_pending_leg_close}.get(op)
                if finalize and result and command_id:
                    close_burst_pending=(op=="close_pair" and
                        _close_pair_review_recoverable(job))
                    if not close_burst_pending:
                        _set_slot_review(username,job.get("symbol") or "XAUUSD",job.get("slot"),
                                         "UNKNOWN",command_id,job_id,"restart during broker dispatch")
                        tracer.update_status(command_id,CommandStatus.UNKNOWN)
                    else:
                        tracer.update_status(command_id,CommandStatus.SUBMITTED)
                    tracer.update_field(command_id,"pending_context",context)
                    if op=="open_pair" and _open_saga_job(job):
                        _schedule_open_saga_recovery(command_id,result,context,delay=0.0)
                    elif close_burst_pending:
                        _schedule_close_pair_review_recovery(
                            command_id,result,context,delay=0.0)
                    else:
                        _aio.create_task(finalize(command_id,result,context))
                    continue

            if state=="EXECUTING":
                if job.get("dispatch_protocol")=="intent-v1":
                    # New workers only enter broker code after DISPATCHING is
                    # durable; EXECUTING is therefore still replay-safe.
                    TRADE_QUEUE.requeue(job_id,"qh_restart_before_dispatch")
                    continue
                # Legacy EXECUTING had an in-memory-only dispatch marker, so it
                # cannot be replayed safely after an upgrade.
                state="UNKNOWN"
                if command_id:
                    tracer.update_status(command_id,CommandStatus.UNKNOWN)
                    tracer.update_field(command_id,"failure_reason","legacy executing state at restart")
                TRADE_QUEUE.finish(job_id,state,error={"detail":"legacy dispatch boundary unknown"})
                _set_slot_review(username,job.get("symbol") or "XAUUSD",job.get("slot"),
                                 state,command_id,job_id,"legacy executing state at restart")
                continue

            if state in TRADE_QUEUE_TERMINAL_STATES:
                if state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                    _set_slot_review(username,job.get("symbol") or "XAUUSD",job.get("slot"),
                                     state,command_id,job_id,"queue recovery")
                TRADE_QUEUE.finish(job_id,state)
            elif state=="DISPATCHING":
                if command_id:
                    tracer.update_status(command_id,CommandStatus.UNKNOWN)
                    tracer.update_field(command_id,"failure_reason","dispatch recovery context unavailable")
                TRADE_QUEUE.finish(job_id,"UNKNOWN",
                                   error={"detail":"dispatch recovery context unavailable"})
                _set_slot_review(username,job.get("symbol") or "XAUUSD",job.get("slot"),
                                 "UNKNOWN",command_id,job_id,
                                 "dispatch recovery context unavailable")
            else:
                TRADE_QUEUE.requeue(job_id,"qh_restart")

    # Review jobs are deliberately removed from the processing list. Scan their
    # durable saga snapshots so a QH restart cannot strand compensation forever.
    for job in TRADE_QUEUE.recoverable_sagas():
        command_id=job.get("command_id")
        context=_trade_queue_recovery_context(job)
        result=_trade_queue_recovery_result(job,context)
        if command_id and result:
            _schedule_open_saga_recovery(command_id,result,context,delay=0.0)

    # A terminal close-pair review can contain one broker-confirmed survivor.
    # Resume its exact-ticket risk close after every QH restart.
    for job in _recoverable_close_pair_reviews():
        command_id=job.get("command_id")
        context=_trade_queue_recovery_context(job)
        result=_trade_queue_recovery_result(job,context)
        if command_id and result:
            _schedule_close_pair_review_recovery(
                command_id,result,context,delay=0.0)


async def _run_trade_queue_job_guarded(job):
    """Keep a claimed job recoverable even if dispatch setup fails unexpectedly."""
    try:
        await _run_trade_queue_job(job)
    except _aio.CancelledError:
        raise
    except Exception as ex:
        job_id=job.get("job_id")
        try:
            current=TRADE_QUEUE.get_job(job_id) or {}
            if str(current.get("state") or "").upper() not in TRADE_QUEUE_TERMINAL_STATES:
                TRADE_QUEUE.finish(job_id,"UNKNOWN",
                    error={"type":ex.__class__.__name__,"detail":str(ex)[:300]},
                    finished_at=_dt.datetime.utcnow().isoformat())
                _set_slot_review(job.get("username"),job.get("symbol") or "XAUUSD",job.get("slot"),
                                 "UNKNOWN",job.get("command_id"),job_id,
                                 "queue_guard:%s"%ex.__class__.__name__)
            _trade_queue_release_slot(job)
        except Exception:
            pass
        try: R.setex(RNS+"tradeq:error",60,"%s:%s"%(ex.__class__.__name__,str(ex)[:200]))
        except Exception: pass


def _trade_queue_reap(username):
    tasks=_TRADE_QUEUE_TASKS.setdefault(username,set())
    done={task for task in tasks if task.done()}
    tasks.difference_update(done)
    for task in done:
        try: task.result()
        except _aio.CancelledError: pass
        except Exception as ex:
            try: R.setex(RNS+"tradeq:error",60,"task:%s:%s"%(ex.__class__.__name__,str(ex)[:180]))
            except Exception: pass
    return tasks


def _trade_queue_job_task_active(job_id):
    """Return whether this process is still dispatching the exact queue job."""
    wanted=str(job_id or "")
    if not wanted:
        return False
    for tasks in list(_TRADE_QUEUE_TASKS.values()):
        for task in list(tasks):
            if (not task.done() and
                    str(getattr(task,"_qh_trade_job_id","") or "")==wanted):
                return True
    return False


def _trade_queue_command_task_active(command_id, command=None):
    """Match an in-process dispatcher by command id or its durable job id."""
    wanted_command=str(command_id or "")
    wanted_job=str((command or {}).get("queue_job_id") or "")
    for tasks in list(_TRADE_QUEUE_TASKS.values()):
        for task in list(tasks):
            if task.done():
                continue
            if (wanted_command and
                    str(getattr(task,"_qh_trade_command_id","") or "")==wanted_command):
                return True
            if (wanted_job and
                    str(getattr(task,"_qh_trade_job_id","") or "")==wanted_job):
                return True
    return False


def _consume_worker_snapshot_error(task):
    """Retrieve background snapshot errors even when every job exits at a gate."""
    try:
        if not task.cancelled():
            task.exception()
    except BaseException:
        pass


def _attach_trade_queue_worker_position_tasks(username, jobs):
    """Share one broker position read across each newly claimed dispatch wave."""
    groups={}
    for job in (jobs or ()):
        payload=job.get("payload") if isinstance(job,dict) else None
        if not isinstance(payload,dict) or isinstance(payload.get("_queue_preflight"),dict):
            continue
        kind=str(job.get("kind") or "")
        if kind not in ("open","close"):
            continue
        symbol=str(job.get("symbol") or "XAUUSD")
        groups.setdefault((kind,symbol),[]).append(job)
    for (kind,symbol),group in groups.items():
        try:
            if kind=="open":
                task=_aio.create_task(_occupied_slots(
                    symbol,username,include_positions=True,authoritative=True))
            else:
                items=[]
                for job in group:
                    item=dict(job.get("payload") or {})
                    item["op"]=job.get("op")
                    item["slot"]=job.get("slot")
                    items.append(item)
                task=_aio.create_task(_close_batch_position_snapshot(
                    _user_exec_conn(username),items,authoritative=True))
            task.add_done_callback(_consume_worker_snapshot_error)
            for job in group:
                job["_worker_positions_task"]=task
        except Exception:
            # Each worker retains its bounded fail-closed fallback read.
            continue


async def _trade_queue_dispatch_once():
    """Dispatch independent slots concurrently while preserving close priority."""
    worked=False
    def _queue_snapshot():
        accounts=TRADE_QUEUE.accounts()
        bulk=getattr(TRADE_QUEUE,"queued_depths_many",None)
        if callable(bulk):
            return accounts,bulk(accounts)
        return accounts,{username:TRADE_QUEUE.depths(username)
                         for username in accounts}

    def _claim_wave(username,count):
        if not TRADE_QUEUE.claim_consumer_lease(
                username,_TRADE_QUEUE_OWNER,ttl=10):
            return []
        claimed=[]
        for _ in range(max(0,int(count))):
            job=TRADE_QUEUE.claim(username)
            if not job:
                break
            claimed.append(job)
        return claimed

    # Redis' Python client is synchronous. Keeping the account scan and claim
    # wave off the event loop prevents an idle account set from delaying MT5
    # terminal HTTP callbacks and independently dispatched slot tasks.
    accounts,queued_depths=await _aio.to_thread(_queue_snapshot)
    for username in accounts:
        tasks=_trade_queue_reap(username)
        account_limit=_TRADE_QUEUE_DISPATCH_LIMIT
        capacity=account_limit-len(tasks)
        if capacity<=0:
            continue
        # A queued close must reach the Agent's durable ACK barrier before any
        # not-yet-started open for the same account is released.
        if any(getattr(task,"_qh_trade_kind",None)=="close" for task in tasks):
            continue
        depths=queued_depths.get(username) or {}
        try: close_depth=max(0,int(depths.get("close") or 0))
        except (TypeError,ValueError): close_depth=0
        try: open_depth=max(0,int(depths.get("open") or 0))
        except (TypeError,ValueError): open_depth=0
        if close_depth<=0 and open_depth<=0:
            continue
        # Review latches are enforced against the exact target slot at open
        # dispatch. Other configured slots remain independently executable.
        queued_count=close_depth if close_depth>0 else open_depth
        dispatch_count=min(capacity,queued_count)
        claimed=await _aio.to_thread(
            _claim_wave,username,dispatch_count)
        worked=bool(claimed) or worked
        _attach_trade_queue_worker_position_tasks(username,claimed)
        for job in claimed:
            task=_aio.create_task(_run_trade_queue_job_guarded(job))
            task._qh_trade_kind=job.get("kind")
            task._qh_trade_job_id=job.get("job_id")
            task._qh_trade_command_id=job.get("command_id")
            tasks.add(task)
    return worked


async def _trade_queue_cycle():
    global _TRADE_QUEUE_WAKE
    if _TRADE_QUEUE_WAKE is None:
        _TRADE_QUEUE_WAKE=_aio.Event()
    # Clear before looking at Redis. An enqueue during dispatch leaves the
    # event set; an enqueue just before clear is still visible to dispatch.
    _TRADE_QUEUE_WAKE.clear()
    worked=False
    try:
        worked=await _trade_queue_dispatch_once()
    except Exception as ex:
        try: R.setex(RNS+"tradeq:error",60,"%s:%s"%(ex.__class__.__name__,str(ex)[:200]))
        except Exception: pass
    if worked:
        await _aio.sleep(0.005)
        return True
    try:
        await _aio.wait_for(_TRADE_QUEUE_WAKE.wait(),timeout=0.10)
    except _aio.TimeoutError:
        pass
    return False


async def _trade_queue_loop():
    global _TRADE_QUEUE_WAKE
    if _TRADE_QUEUE_WAKE is None:
        _TRADE_QUEUE_WAKE=_aio.Event()
    while True:
        await _trade_queue_cycle()


def _trade_queue_loop_done(task):
    if task.cancelled():
        return
    try: error=task.exception()
    except BaseException as ex: error=ex
    if error is not None:
        print(json.dumps({
            "event":"qh_trade_queue_loop_failed","level":"CRITICAL",
            "error_type":error.__class__.__name__,"error":str(error)[:300],
        },separators=(",",":")),flush=True)


@app.on_event("startup")
async def _startup_trade_queue():
    global _TRADE_QUEUE_LOOP_TASK
    # Recovery is part of readiness.  The API must not accept a new open while
    # a pre-restart broker dispatch is still missing its durable capacity hold.
    await _recover_trade_queue()
    _TRADE_QUEUE_LOOP_TASK=_aio.create_task(_trade_queue_loop())
    _TRADE_QUEUE_LOOP_TASK.add_done_callback(_trade_queue_loop_done)


@app.on_event("shutdown")
async def _shutdown_trade_queue():
    global _TRADE_QUEUE_LOOP_TASK
    task=_TRADE_QUEUE_LOOP_TASK
    if task is not None and not task.done():
        task.cancel()
        try: await task
        except _aio.CancelledError: pass
    _TRADE_QUEUE_LOOP_TASK=None


@app.get("/api/trade_queue/batch/{batch_id}", dependencies=[Depends(require_license)])
async def trade_queue_batch(batch_id:str, x_license:str=Header(default="")):
    batch=TRADE_QUEUE.batch_status(batch_id)
    if not batch:
        raise HTTPException(404,"batch not found")
    _assert_subject(batch.get("username") or "",x_license)
    return batch


@app.get("/api/trade_queue/{username}", dependencies=[Depends(require_subject)])
def trade_queue_account(username:str, symbol:str="XAUUSD", batch_ids:str=""):
    ladders=_configured_ladders(username,symbol)
    visible_slots=_trade_state_visible_slots(username,symbol,ladders)
    requested=[]
    for value in (batch_ids or "").split(","):
        value=value.strip()
        if value and len(value)<=64 and value.isalnum() and value not in requested:
            requested.append(value)
        if len(requested)>=20: break
    batches=[batch for batch in TRADE_QUEUE.batch_status_many(requested)
             if batch.get("username")==username]
    review_locks=[]
    for slot in visible_slots:
        record=_slot_review_record(username,symbol,slot)
        if record:
            review_locks.append({"slot":slot,"state":record.get("state") or "MANUAL_REVIEW",
                                 "command_id":record.get("command_id") or "",
                                 "job_id":record.get("job_id") or "",
                                 "reason":record.get("reason") or ""})
    return {"username":username,"symbol":symbol,"ladders":ladders,
            "visible_slots":visible_slots,"depths":TRADE_QUEUE.depths(username),
            "slots":TRADE_QUEUE.slot_states(username,symbol,visible_slots),
            "batches":batches,"review_locks":review_locks,"server_ts":time.time()}


class EngineCmd(BaseModel):
    username:str; license_key:str=""; running:bool
@app.post("/api/cmd/engine", dependencies=[Depends(require_admin)])
def cmd_engine(r:EngineCmd):
    R.set(RNS+"engine:running:"+r.username,"1" if r.running else "0")
    _audit(r.username,_actor(r.license_key),"engine_toggle",{"running":r.running},DEMO_MODE,"flag_set")
    return {"ok":True,"running":r.running}

# ---- UI 行为开关(进单机制/进单等待): 前端开关→Redis, 引擎侧真消费 ----
class UiSwitchesCmd(BaseModel):
    username:str; license_key:str=""
    entrymech:bool=True    # 开=「持仓时长」到时自动平仓; 关=超时平仓不触发(止盈/止损/卖点不受影响)
    entrywait:bool=True    # 开=自动进单/循环下单按「进单间隔」等待; 关=不按间隔(自动进单保留10s安全底线)
@app.post("/api/cmd/ui_switches", dependencies=[Depends(require_license)])
def cmd_ui_switches(r:UiSwitchesCmd):
    _assert_subject(r.username,r.license_key or "")
    R.set(RNS+"sw:entrymech:"+r.username, "1" if r.entrymech else "0")
    R.set(RNS+"sw:entrywait:"+r.username, "1" if r.entrywait else "0")
    return {"ok":True,"entrymech":r.entrymech,"entrywait":r.entrywait}

# ---- 全自动平仓模式开关(off/shadow/armed/full) + 急停 ----
class AutoExitCmd(BaseModel):
    username:str; license_key:str=""; mode:str="off"   # off|shadow|armed|full
    profit_first:bool=False                              # 盈利平台优先(止盈/卖点/超时仅盈利时放行; 止损不受限)
@app.post("/api/cmd/auto_exit", dependencies=[Depends(require_license)])
def cmd_auto_exit(r:AutoExitCmd):
    _assert_subject(r.username,r.license_key or "")
    if r.mode not in ("off","shadow","armed","full"):
        raise HTTPException(400,"mode 必须为 off/shadow/armed/full")
    if r.mode=="shadow": r.mode="off"
    if r.mode=="full": r.mode="armed"   # full 已废除(武装粒度下沉逐坑)
    # 自动平仓是系统默认能力; 保留全局急停这一真金安全闸。
    if r.mode in ("armed","full"):
        if R.get(RNS+"global_estop")=="1":
            raise HTTPException(409,"全局急停生效中, 无法启用自动平仓; 请先解除急停")
        _assert_user_valid(r.username)
        R.delete(_auto_validity_latch_key("exit",r.username))
    R.set(RNS+"auto_exit:"+r.username, r.mode)
    R.set(RNS+"sw:profitfirst:"+r.username, "1" if r.profit_first else "0")
    _audit(r.username,_actor(r.license_key),"auto_exit_mode",{"mode":r.mode,"profit_first":r.profit_first},DEMO_MODE,"set")
    _push_alert("warn" if r.mode in ("armed","full") else "info",
        "全自动平仓模式切换为: %s%s"%(r.mode," (真金!)" if (r.mode in ("armed","full") and not DEMO_MODE) else ""),r.username)
    return {"ok":True,"mode":r.mode,"demo":DEMO_MODE}

@app.get("/api/engine/auto_exit/{username}", dependencies=[Depends(require_subject)])
def get_auto_exit(username:str):
    return {"mode":R.get(RNS+"auto_exit:"+username) or "off",
            "decisions":json.loads(R.get(RNS+"auto_exit:decisions:"+username) or "null"),
            "last":R.get(RNS+"auto_exit:last"),"demo":DEMO_MODE}

# ---- 全自动进单模式开关(off/shadow/armed/full) + 方向 ----
class AutoEntryCmd(BaseModel):
    username:str; license_key:str=""; mode:str="off"; direction:str="reverse"
@app.post("/api/cmd/auto_entry", dependencies=[Depends(require_license)])
def cmd_auto_entry(r:AutoEntryCmd):
    _assert_subject(r.username,r.license_key or "")
    if r.mode not in ("off","shadow","armed","full"):
        raise HTTPException(400,"mode 必须为 off/shadow/armed/full")
    if r.mode=="shadow": r.mode="off"
    if r.mode=="full": r.mode="armed"   # full 已废除(武装粒度下沉逐坑, 方向=逐坑 entry_state)
    if r.direction not in ("reverse","forward"): r.direction="reverse"
    # 自动进单是系统默认能力; 保留全局急停这一真金安全闸。
    if r.mode in ("armed","full"):
        if R.get(RNS+"global_estop")=="1":
            raise HTTPException(409,"全局急停生效中, 无法启用自动进单; 请先解除急停")
        _assert_user_valid(r.username)
        R.delete(_auto_validity_latch_key("entry",r.username))
    R.set(RNS+"auto_entry:"+r.username, r.mode)
    R.set(RNS+"auto_entry_dir:"+r.username, r.direction)
    _audit(r.username,_actor(r.license_key),"auto_entry_mode",{"mode":r.mode,"direction":r.direction},DEMO_MODE,"set")
    _push_alert("warn" if r.mode in ("armed","full") else "info",
        "全自动进单模式: %s/%s%s"%(r.mode,r.direction," (真金!)" if (r.mode in ("armed","full") and not DEMO_MODE) else ""),r.username)
    return {"ok":True,"mode":r.mode,"direction":r.direction,"demo":DEMO_MODE}

@app.get("/api/engine/auto_entry/{username}", dependencies=[Depends(require_subject)])
def get_auto_entry(username:str):
    return {"mode":R.get(RNS+"auto_entry:"+username) or "off",
            "direction":R.get(RNS+"auto_entry_dir:"+username) or "reverse",
            "decisions":json.loads(R.get(RNS+"auto_entry:decisions:"+username) or "null"),
            "last":R.get(RNS+"auto_entry:last"),"demo":DEMO_MODE}


class ParamSave(BaseModel):
    username:str; license_key:str=""; symbol:str
    # P1-a: 必填字段(无默认值)保持;tp/sl 改 Optional 修复 QH-P0-007 硬编码覆盖 BUG
    entry_spread:float; ladders:conint(strict=True,ge=1,le=20); hold_secs:int; weekend_guard:bool
    tp_points:Optional[float]=None    # P1-a: None=不更新(修 QH-P0-007 前端0.30硬编码覆盖)
    sl_points:Optional[float]=None    # P1-a: None=不更新(修 QH-P0-007 前端0.50硬编码覆盖)
    # P1-a: If-Match 乐观锁(前端传当前revision,服务端校验;不传则跳过校验)
    expected_revision:Optional[int]=None
    main_lot_mult:float=1.0; hedge_lot_mult:float=1.0
    main_spread_cap:float=30.0; hedge_spread_cap:float=30.0
    slippage_tol:float=5.0; slippage_pause_min:int=2
    entry_interval_sec:int=5; max_inflight:int=3
    auto_close:bool=True; single_leg_alert:bool=True
    hedge_symbol:str=""; base_lot:float=0.01
    data_mult:float=1.0; basis_offset:float=0.0; digits:int=2
    entry_mode:str="main_first"; exit_mode:str="concurrent"; speed_mode:str="fast"; predict_budget:float=0.0
    # 批七: 数据倍数主/对冲拆分 + 进位拆分 + 数据波动 + 数据同步 + 周末双开关
    data_mult_main:float=1.0; data_mult_hedge:float=1.0
    digits_main:int=2; digits_hedge:int=2
    match_count:int=20; fluctuation_band:float=0.0
    sync_interval_sec:float=1.0; records_per_sec:int=1
    weekend_sat:bool=False; weekend_sun:bool=False
    # 批八: 保证金预留 + 每手费用
    margin_reserve_main:float=200.0; margin_reserve_hedge:float=200.0; fee_per_lot:float=0.0
    # 时间窗(北京时间 "HH:MM"; 空=全时段): 进单时段(开仓时段) + 运行时段(系统自动运行时段)
    entry_win_start:str=""; entry_win_end:str=""; run_win_start:str=""; run_win_end:str=""
@app.post("/api/params/save", dependencies=[Depends(require_license)])
def params_save(r:ParamSave):
    _assert_subject(r.username,r.license_key or "")
    if isinstance(r.ladders,bool) or not 1<=int(r.ladders)<=20:
        raise HTTPException(400,"进单量(阶梯)须为整数 1..20")
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s",(r.username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")

    # All three entry/exit modes use durable Agent ACKs; Broker terminal waiting
    # happens in the background Saga and no longer blocks the next slot.

    # 批34闸1:策略运行中禁止保存(避免运行中币种不一致)
    _active_key = RNS + "strategy_active:" + r.username + ":" + r.symbol
    if R.get(_active_key) == "1":
        c.close()
        raise HTTPException(409, "策略正在运行,请先停止策略再修改参数(避免运行中币种切换导致数据不一致)")

    # 批34闸2:hedge_symbol校验(调对冲桥检查币种存在性)
    if r.hedge_symbol and r.hedge_symbol.strip():
        _hsym = r.hedge_symbol.strip()
        _hedge_url = os.environ.get("QH_HEDGE_URL", "")
        if _hedge_url:
            try:
                import httpx
                _hedge_key = os.environ.get("QH_HEDGE_KEY", "")
                _headers = {"x-api-key": _hedge_key} if _hedge_key else {}
                _resp = httpx.get(_hedge_url + "/mt5/symbols", headers=_headers, timeout=3.0)
                if _resp.status_code == 200:
                    _syms = _resp.json().get("symbols", [])
                    if _hsym not in _syms:
                        c.close()
                        raise HTTPException(400, f"对冲币种 '{_hsym}' 在对冲桥不存在,请检查拼写(可用币种见对冲终端Market Watch)")
            except httpx.TimeoutException:
                pass  # 桥超时不阻止保存(fail-open,避免桥临时不可用时锁死配置)
            except HTTPException:
                raise  # 重新抛出400错误
            except Exception:
                pass  # 其他异常不阻止保存

    if r.records_per_sec is not None and r.records_per_sec<1: r.records_per_sec=1

    # === P1-a: PATCH 语义 — 只更新显式提交的字段 ===
    # 读取当前行(用于 revision 校验 + PATCH 合并)
    cur.execute("SELECT revision,ladders FROM param_templates WHERE user_id=%s AND symbol=%s",(u[0],r.symbol))
    _cur_row = cur.fetchone()
    _cur_revision = int(_cur_row[0] or 0) if _cur_row else 0
    _old_ladders = int(_cur_row[1] or 0) if _cur_row else 0

    # If-Match 乐观锁校验(仅当前端传了 expected_revision 时才校验)
    if r.expected_revision is not None and r.expected_revision != _cur_revision:
        c.close()
        raise HTTPException(409, f"CONFIG_REVISION_CONFLICT: 当前revision={_cur_revision},预期={r.expected_revision},请刷新后重试")

    try:
        _assert_ladder_reduction_safe(r.username,r.symbol,_old_ladders,r.ladders)
    except Exception:
        c.close()
        raise

    _new_revision = _cur_revision + 1

    # 构建 PATCH 更新集合(只含 __fields_set__ 中的字段,排除元数据字段)
    _META = {"username","license_key","symbol","expected_revision"}
    _submitted = {k for k in r.__fields_set__ if k not in _META}

    # 总是更新的字段(业务核心)
    _always = {"entry_spread","ladders","hold_secs","weekend_guard"}

    # 动态构建 SET 子句
    _field_col_map = {
        "entry_spread":"entry_spread","tp_points":"tp_points","sl_points":"sl_points",
        "ladders":"ladders","hold_secs":"hold_secs","weekend_guard":"weekend_guard",
        "main_lot_mult":"main_lot_mult","hedge_lot_mult":"hedge_lot_mult",
        "main_spread_cap":"main_spread_cap","hedge_spread_cap":"hedge_spread_cap",
        "slippage_tol":"slippage_tol","slippage_pause_min":"slippage_pause_min",
        "entry_interval_sec":"entry_interval_sec","max_inflight":"max_inflight",
        "auto_close":"auto_close","single_leg_alert":"single_leg_alert",
        "hedge_symbol":"hedge_symbol","base_lot":"base_lot","data_mult":"data_mult",
        "basis_offset":"basis_offset","digits":"digits",
        "entry_mode":"entry_mode","exit_mode":"exit_mode","speed_mode":"speed_mode",
        "predict_budget":"predict_budget",
        "data_mult_main":"data_mult_main","data_mult_hedge":"data_mult_hedge",
        "digits_main":"digits_main","digits_hedge":"digits_hedge",
        "match_count":"match_count","fluctuation_band":"fluctuation_band",
        "sync_interval_sec":"sync_interval_sec","records_per_sec":"records_per_sec",
        "weekend_sat":"weekend_sat","weekend_sun":"weekend_sun",
        "margin_reserve_main":"margin_reserve_main","margin_reserve_hedge":"margin_reserve_hedge",
        "fee_per_lot":"fee_per_lot",
        "entry_win_start":"entry_win_start","entry_win_end":"entry_win_end",
        "run_win_start":"run_win_start","run_win_end":"run_win_end",
    }
    _update_fields = _always | (_submitted & _field_col_map.keys())
    _set_parts = [f"{_field_col_map[f]}=%s" for f in sorted(_update_fields)]
    _set_parts.append("revision=%s")
    _set_parts.append("updated_at=now()")
    _set_parts.append("updated_by=%s")

    def _v(field):
        val = getattr(r, field, None)
        if field in ("entry_win_start","entry_win_end","run_win_start","run_win_end"):
            return val or ""
        return val

    _set_vals = [_v(f) for f in sorted(_update_fields)]
    _set_vals.append(_new_revision)
    _set_vals.append(r.username)

    if _cur_row:
        _sql = f"UPDATE param_templates SET {', '.join(_set_parts)} WHERE user_id=%s AND symbol=%s"
        cur.execute(_sql, _set_vals + [u[0], r.symbol])
    else:
        # INSERT 时用当前提交值 + 模型默认值补齐
        cur.execute("""INSERT INTO param_templates(user_id,symbol,entry_spread,tp_points,sl_points,ladders,hold_secs,weekend_guard,
                       main_lot_mult,hedge_lot_mult,main_spread_cap,hedge_spread_cap,slippage_tol,slippage_pause_min,entry_interval_sec,max_inflight,auto_close,single_leg_alert,
                       hedge_symbol,base_lot,data_mult,basis_offset,digits,entry_mode,exit_mode,speed_mode,predict_budget,
                       data_mult_main,data_mult_hedge,digits_main,digits_hedge,match_count,fluctuation_band,sync_interval_sec,records_per_sec,weekend_sat,weekend_sun,
                       margin_reserve_main,margin_reserve_hedge,fee_per_lot,
                       entry_win_start,entry_win_end,run_win_start,run_win_end,revision,updated_by)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (u[0],r.symbol,r.entry_spread,r.tp_points or 0.30,r.sl_points or 0.50,r.ladders,r.hold_secs,r.weekend_guard,
                     r.main_lot_mult or 1.0,r.hedge_lot_mult or 1.0,r.main_spread_cap or 30.0,r.hedge_spread_cap or 30.0,
                     r.slippage_tol or 5.0,r.slippage_pause_min or 2,r.entry_interval_sec or 5,r.max_inflight or 3,
                     r.auto_close if r.auto_close is not None else True,r.single_leg_alert if r.single_leg_alert is not None else True,
                     r.hedge_symbol or "",r.base_lot or 0.01,r.data_mult or 1.0,r.basis_offset or 0.0,r.digits or 2,
                     r.entry_mode or "main_first",r.exit_mode or "concurrent",r.speed_mode or "fast",r.predict_budget or 0.0,
                     r.data_mult_main or 1.0,r.data_mult_hedge or 1.0,r.digits_main or 2,r.digits_hedge or 2,
                     r.match_count or 20,r.fluctuation_band or 0.0,r.sync_interval_sec or 1.0,r.records_per_sec or 1,
                     r.weekend_sat or False,r.weekend_sun or False,
                     r.margin_reserve_main or 200.0,r.margin_reserve_hedge or 200.0,r.fee_per_lot or 0.0,
                     r.entry_win_start or "",r.entry_win_end or "",r.run_win_start or "",r.run_win_end or "",
                     _new_revision,r.username))

    # config_change_log(P1-a 审计轨迹)
    try:
        cur.execute("""INSERT INTO config_change_log(user_id,symbol,revision,actor,fields_updated,request_id,created_at)
                       VALUES(%s,%s,%s,%s,%s,%s,now())""",
                    (u[0],r.symbol,_new_revision,r.username,
                     ",".join(sorted(_update_fields)),
                     r.license_key[:8]+"..."))
    except Exception:
        pass  # 审计失败不阻止保存

    # 注意:原来的 tp_points/sl_points UPDATE 语句已被上面的 PATCH 替代
    # 下面跳到 audit 和 return
    c.close()
    _trade_tmpl_cache_bust(r.username,r.symbol)
    _trim_slot_overrides_above_limit(r.username,r.symbol,r.ladders)
    _recompute_auto_masters(r.username)
    _audit(r.username,_actor(r.license_key),"params_save",{"symbol":r.symbol,"revision":_new_revision,"fields":sorted(_update_fields)},DEMO_MODE,"saved_p1a")
    return {"ok":True,"revision":_new_revision,"ladders":int(r.ladders),
            "fields_updated":sorted(_update_fields),"msg":"参数已保存，引擎下轮热重载"}
    # === P1-a PATCH 结束 — 以下为旧全量 UPDATE 占位(已被上方替代) ===
    if False:  # dead code — 保留字段引用防 lint
        cur.execute("""UPDATE param_templates SET entry_spread=%s,tp_points=%s,sl_points=%s,ladders=%s,hold_secs=%s,weekend_guard=%s,
                   main_lot_mult=%s,hedge_lot_mult=%s,main_spread_cap=%s,hedge_spread_cap=%s,slippage_tol=%s,slippage_pause_min=%s,
                   entry_interval_sec=%s,max_inflight=%s,auto_close=%s,single_leg_alert=%s,
                   hedge_symbol=%s,base_lot=%s,data_mult=%s,basis_offset=%s,digits=%s,
                   entry_mode=%s,exit_mode=%s,speed_mode=%s,predict_budget=%s,
                   data_mult_main=%s,data_mult_hedge=%s,digits_main=%s,digits_hedge=%s,
                   match_count=%s,fluctuation_band=%s,sync_interval_sec=%s,records_per_sec=%s,
                   weekend_sat=%s,weekend_sun=%s,
                   margin_reserve_main=%s,margin_reserve_hedge=%s,fee_per_lot=%s,
                   entry_win_start=%s,entry_win_end=%s,run_win_start=%s,run_win_end=%s,updated_at=now()
                   WHERE user_id=%s AND symbol=%s""",
                (r.entry_spread,r.tp_points,r.sl_points,r.ladders,r.hold_secs,r.weekend_guard,
                 r.main_lot_mult,r.hedge_lot_mult,r.main_spread_cap,r.hedge_spread_cap,r.slippage_tol,r.slippage_pause_min,
                 r.entry_interval_sec,r.max_inflight,r.auto_close,r.single_leg_alert,
                 r.hedge_symbol,r.base_lot,r.data_mult,r.basis_offset,r.digits,
                 r.entry_mode,r.exit_mode,r.speed_mode,r.predict_budget,
                 r.data_mult_main,r.data_mult_hedge,r.digits_main,r.digits_hedge,
                 r.match_count,r.fluctuation_band,r.sync_interval_sec,r.records_per_sec,
                 r.weekend_sat,r.weekend_sun,
                 r.margin_reserve_main,r.margin_reserve_hedge,r.fee_per_lot,
                 (r.entry_win_start or ""),(r.entry_win_end or ""),(r.run_win_start or ""),(r.run_win_end or ""),u[0],r.symbol))
    if cur.rowcount==0:
        cur.execute("""INSERT INTO param_templates(user_id,symbol,entry_spread,tp_points,sl_points,ladders,hold_secs,weekend_guard,
                       main_lot_mult,hedge_lot_mult,main_spread_cap,hedge_spread_cap,slippage_tol,slippage_pause_min,entry_interval_sec,max_inflight,auto_close,single_leg_alert,
                       hedge_symbol,base_lot,data_mult,basis_offset,digits,entry_mode,exit_mode,speed_mode,predict_budget,
                       data_mult_main,data_mult_hedge,digits_main,digits_hedge,match_count,fluctuation_band,sync_interval_sec,records_per_sec,weekend_sat,weekend_sun,
                       margin_reserve_main,margin_reserve_hedge,fee_per_lot,
                       entry_win_start,entry_win_end,run_win_start,run_win_end)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (u[0],r.symbol,r.entry_spread,r.tp_points,r.sl_points,r.ladders,r.hold_secs,r.weekend_guard,
                     r.main_lot_mult,r.hedge_lot_mult,r.main_spread_cap,r.hedge_spread_cap,r.slippage_tol,r.slippage_pause_min,
                     r.entry_interval_sec,r.max_inflight,r.auto_close,r.single_leg_alert,
                     r.hedge_symbol,r.base_lot,r.data_mult,r.basis_offset,r.digits,
                     r.entry_mode,r.exit_mode,r.speed_mode,r.predict_budget,
                     r.data_mult_main,r.data_mult_hedge,r.digits_main,r.digits_hedge,
                     r.match_count,r.fluctuation_band,r.sync_interval_sec,r.records_per_sec,
                     r.weekend_sat,r.weekend_sun,
                     r.margin_reserve_main,r.margin_reserve_hedge,r.fee_per_lot,
                     (r.entry_win_start or ""),(r.entry_win_end or ""),(r.run_win_start or ""),(r.run_win_end or "")))
    pass  # dead code end

# ---- Params 优化: 全字段清单 + dict 版 upsert(供批量/预设套用共用) + 硬校验 ----
_PARAM_FIELDS=["entry_spread","tp_points","sl_points","ladders","hold_secs","weekend_guard",
    "main_lot_mult","hedge_lot_mult","main_spread_cap","hedge_spread_cap","slippage_tol","slippage_pause_min",
    "entry_interval_sec","max_inflight","auto_close","single_leg_alert","hedge_symbol","base_lot","data_mult",
    "basis_offset","digits","entry_mode","exit_mode","speed_mode","predict_budget","data_mult_main","data_mult_hedge",
    "digits_main","digits_hedge","match_count","fluctuation_band","sync_interval_sec","records_per_sec",
    "weekend_sat","weekend_sun","margin_reserve_main","margin_reserve_hedge","fee_per_lot",
    "entry_win_start","entry_win_end","run_win_start","run_win_end"]
def _param_validate(cfg):
    """下发前硬校验(后端保险; 前端同步校验)。返回错误列表, 空=通过。铁律见 [[testgo-ladder-advisor]]。"""
    e=[]
    def num(k):
        try: return float(cfg.get(k))
        except (TypeError,ValueError): return None
    la=cfg.get("ladders")
    if type(la) is not int:
        e.append("进单量(阶梯)须为整数 1..20")
    elif not 1<=la<=20:
        e.append("进单量(阶梯)须 1..20")
    if (num("base_lot") or 0)<=0: e.append("每U手数须 >0")
    if num("entry_spread") is None or num("entry_spread")<0: e.append("入场点差须 ≥0")
    for k,nm in (("tp_points","止盈点"),("sl_points","止损点")):
        if num(k) is None: e.append(nm+"须为数字")
    for k in ("digits","digits_main","digits_hedge"):
        v=cfg.get(k)
        try:
            if v is not None and not (0<=int(v)<=8): e.append(k+" 进位须 0..8")
        except (TypeError,ValueError): e.append(k+" 进位须整数")
    if not (cfg.get("hedge_symbol") or "").strip(): e.append("对冲品种不能为空")
    if cfg.get("entry_mode") not in ("concurrent","main_first","hedge_first"): e.append("进单模式非法")
    if cfg.get("exit_mode") not in ("concurrent","main_first","hedge_first"): e.append("出单模式非法")
    if cfg.get("speed_mode") not in ("normal","fast","turbo"): e.append("速度模式非法")
    return e
def _params_upsert(cur, user_id, symbol, cfg, actor="batch"):
    """按 _PARAM_FIELDS 全列 UPDATE→无则 INSERT(dict 驱动)。
       P1-a: 每次写入递增 revision + 记 config_change_log(否则批量覆盖击穿编辑端乐观锁)。"""
    if cfg.get("records_per_sec") is not None:
        try:
            if int(cfg["records_per_sec"])<1: cfg["records_per_sec"]=1
        except (TypeError,ValueError): cfg["records_per_sec"]=1
    for wk in ("entry_win_start","entry_win_end","run_win_start","run_win_end"):
        cfg[wk]=(cfg.get(wk) or "")
    sets=",".join("%s=%%s"%f for f in _PARAM_FIELDS)+",updated_at=now(),revision=COALESCE(revision,0)+1,updated_by=%s"
    vals=[cfg.get(f) for f in _PARAM_FIELDS]
    cur.execute("UPDATE param_templates SET "+sets+" WHERE user_id=%s AND symbol=%s RETURNING revision",
                tuple(vals)+(actor,user_id,symbol))
    _row=cur.fetchone()
    if _row is None:
        cols=",".join(["user_id","symbol"]+_PARAM_FIELDS+["revision","updated_by"])
        ph=",".join(["%s"]*(4+len(_PARAM_FIELDS)))
        cur.execute("INSERT INTO param_templates("+cols+") VALUES("+ph+")",
                    (user_id,symbol)+tuple(vals)+(1,actor))
        _rev=1
    else:
        _rev=int(_row[0])
    try:
        cur.execute("""INSERT INTO config_change_log(user_id,symbol,revision,actor,fields_updated,request_id,created_at)
                       VALUES(%s,%s,%s,%s,%s,%s,now())""",
                    (user_id,symbol,_rev,actor,"__batch_all__",""))
    except Exception:
        pass  # 审计失败不阻止保存
    return _rev

class ParamBatchReq(BaseModel):
    license_key:str=""; usernames:list=[]; symbol:str="XAUUSD"; cfg:dict={}
@app.post("/api/admin/params/batch", dependencies=[Depends(require_op("params"))])
def params_batch(r:ParamBatchReq):
    """批量下发: 同一套 cfg 写入多个用户。硬校验不过整批拒绝。"""
    errs=_param_validate(r.cfg)
    if errs: raise HTTPException(400,"参数校验未通过: "+"; ".join(errs))
    if not r.usernames: raise HTTPException(400,"未选择用户")
    done=[]; fail=[]
    c=db(); cur=c.cursor()
    for un in r.usernames:
        try:
            cur.execute("SELECT id FROM users WHERE username=%s",(un,)); u=cur.fetchone()
            if not u: fail.append({"user":un,"err":"用户不存在"}); continue
            current=_load_tmpl(un,r.symbol) or {}
            _assert_ladder_reduction_safe(
                un,r.symbol,int(current.get("ladders") or 0),int(r.cfg["ladders"]))
            _params_upsert(cur, u[0], r.symbol, dict(r.cfg), actor="batch:"+_actor(r.license_key))
            _trim_slot_overrides_above_limit(un,r.symbol,int(r.cfg["ladders"]))
            _recompute_auto_masters(un)
            done.append(un)
        except Exception as e: fail.append({"user":un,"err":str(e)[:80]})
    c.close()
    for un in done:
        _trade_tmpl_cache_bust(un,r.symbol)
    _audit("",_actor(r.license_key),"params_batch",{"symbol":r.symbol,"done":done,"fail":fail},DEMO_MODE,"batch:%d"%len(done))
    return {"ok":True,"done":done,"fail":fail,"n":len(done)}

# ---- 参数预设库(param_presets: 命名预设, 一键套用到任意用户) ----
class PresetSaveReq(BaseModel):
    license_key:str=""; id:int=0; name:str; note:str=""; symbol:str="XAUUSD"; cfg:dict={}
class PresetIdReq(BaseModel):
    license_key:str=""; id:int
@app.get("/api/admin/param_presets", dependencies=[Depends(require_op("params"))])
def param_presets_list():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,name,note,symbol,cfg,updated_at FROM param_presets ORDER BY id DESC")
    rows=[{"id":r["id"],"name":r["name"],"note":r["note"],"symbol":r["symbol"],"cfg":r["cfg"],
           "updated_at":r["updated_at"].isoformat() if r["updated_at"] else None} for r in cur.fetchall()]
    c.close(); return {"presets":rows}
@app.post("/api/admin/param_preset/save", dependencies=[Depends(require_op("params"))])
def param_preset_save(r:PresetSaveReq):
    if not (r.name or "").strip(): raise HTTPException(400,"预设名不能为空")
    errs=_param_validate(r.cfg)
    if errs: raise HTTPException(400,"参数校验未通过: "+"; ".join(errs))
    c=db(); cur=c.cursor()
    if r.id:
        cur.execute("UPDATE param_presets SET name=%s,note=%s,symbol=%s,cfg=%s,updated_at=now() WHERE id=%s",
                    (r.name.strip(),r.note,r.symbol,json.dumps(r.cfg),r.id))
    else:
        cur.execute("INSERT INTO param_presets(name,note,symbol,cfg,created_by) VALUES(%s,%s,%s,%s,%s) RETURNING id",
                    (r.name.strip(),r.note,r.symbol,json.dumps(r.cfg),_actor(r.license_key)))
        r.id=cur.fetchone()[0]
    c.close(); return {"ok":True,"id":r.id}
@app.post("/api/admin/param_preset/delete", dependencies=[Depends(require_op("params"))])
def param_preset_delete(r:PresetIdReq):
    c=db(); cur=c.cursor(); cur.execute("DELETE FROM param_presets WHERE id=%s",(r.id,)); n=cur.rowcount; c.close()
    return {"ok":True,"deleted":n}

@app.on_event("startup")
def _param_presets_boot():
    try:
        c=db(); cur=c.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS param_presets(
            id BIGSERIAL PRIMARY KEY, name TEXT NOT NULL, note TEXT, symbol TEXT DEFAULT 'XAUUSD',
            cfg JSONB NOT NULL, created_by TEXT, updated_at TIMESTAMPTZ DEFAULT now())""")
        c.close()
    except Exception as e: print("param_presets boot err",e)

@app.get("/api/audit/{username}", dependencies=[Depends(require_subject)])
def get_audit(username:str, limit:int=30):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT a.action,a.actor,a.demo_mode,a.result,a.ts FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE u.username=%s ORDER BY a.ts DESC LIMIT %s",(username,limit))
    rows=cur.fetchall(); c.close()
    return {"audit":[dict(r) for r in rows]}

@app.get("/api/quote/tick/{symbol}")
async def quote_tick(symbol:str, leg:str="main", principal: str = Depends(require_license)):
    return await _quote_tick_for_user(principal,symbol,leg)

async def _quote_tick_for_user(username, symbol, leg="main"):
    """Read and cache one quote without relying on FastAPI dependency defaults."""
    try:
        username=str(username or "").strip()
        conn=_strict_user_read_conn(username)
        if conn is None:
            raise HTTPException(404,"用户连接器未配置")
        if leg=="hedge":
            if not getattr(conn,"hedge",None): raise HTTPException(404,"无对冲腿")
            target=conn.hedge
        else:
            leg="main"; target=conn.main
        tick=await target._get("/mt5/tick/"+symbol)
        _store_bridge_tick_snapshot(_bridge_tick_cache_id(target,username,leg),symbol,tick)
        return tick
    except HTTPException: raise
    except Exception as e: raise HTTPException(502,"bridge tick err: %s"%e)

@app.get("/api/quote/config")
def quote_config():
    return {"demo_mode":DEMO_MODE}

async def _arb_bridge_symbols():
    """主桥全部品种名(A期机会雷达用; Redis 缓存 60s, 桥单线程不宜频拉)。失败返回 []。"""
    ck=RNS+"arb:mainsyms"; cached=R.get(ck)
    if cached:
        try: return json.loads(cached)
        except Exception: pass
    try:
        d=await CONN.main._get("/mt5/symbols")
        syms=[x.get("name") for x in (d.get("symbols",d) if isinstance(d,dict) else d) if x.get("name")]
        R.setex(ck, 60, json.dumps(syms)); return syms
    except Exception: return []
# 跨平台对冲符号别名(主平台 IC → 对冲 Bybit 命名不一致, 实测同标的价格量级一致):
#   金 XAUUSD→XAUUSD+ / 银 XAGUSD→XAGUSD(无+) / 布伦特 XBRUSD→UKOUSD / WTI XTIUSD→USOUSD / 天然气 XNGUSD→NG-C
# 可用 Redis 键 qh:arb:alias(JSON) 热覆盖, 无需重启。仅机会雷达用; 已配置对仍走用户自设 hedge_symbol。
_ARB_HEDGE_ALIAS={"XAUUSD":"XAUUSD+","XAGUSD":"XAGUSD","XBRUSD":"UKOUSD","XTIUSD":"USOUSD","XNGUSD":"NG-C"}
def _arb_alias_map():
    m=dict(_ARB_HEDGE_ALIAS)
    try:
        ov=R.get(RNS+"arb:alias")
        if ov: m.update(json.loads(ov))
    except Exception: pass
    return m
def _arb_hedge_for(msym, alias, suffix):
    """机会雷达: 主符号 → 对冲符号。优先别名表, 否则回落"主符号+推断后缀"。"""
    h=alias.get(msym)
    if h: return h
    return (msym+suffix) if suffix else msym
async def _arb_swap(conn, sym, tag):
    """取某腿隔夜利息 swap_long/swap_short(via /mt5/symbol_info, Redis 缓存 600s — swap 每日设定变化慢)。
       返回 (swap_long, swap_short) 或 (None,None)。tag 用于缓存键区分主/对冲桥。"""
    ck=RNS+"arb:swap:%s:%s"%(tag,sym)
    cached=R.get(ck)
    if cached:
        try: v=json.loads(cached); return v[0],v[1]
        except Exception: pass
    try:
        d=await _asyncio.wait_for(conn._get("/mt5/symbol_info/"+sym), timeout=3.0)
        sl=d.get("swap_long"); ss=d.get("swap_short")
        sl=float(sl) if sl is not None else None; ss=float(ss) if ss is not None else None
        R.setex(ck, 600, json.dumps([sl,ss])); return sl,ss
    except Exception: return None,None
def _arb_score(basis, entry):
    """基差绝对值相对入场阈值的达标度 → (score,reachable,suggest)。"""
    if basis is None or entry<=0: return 0,False,"数据不足"
    ratio=abs(basis)/entry; score=int(max(0,min(100,ratio*100))); reachable=abs(basis)>=entry
    if reachable: suggest="已达入场点差,可开仓套利"
    elif ratio>=0.8: suggest="接近入场阈值(%.0f%%),密切关注"%(ratio*100)
    elif ratio>=0.4: suggest="观望,点差偏小"
    else: suggest="点差过小,暂无套利空间"
    return score,reachable,suggest
@app.get("/api/engine/arb_scan/{username}", dependencies=[Depends(require_subject)])
async def engine_arb_scan(username:str):
    """AI 套利分析(A期: 全平台机会雷达)。两类:
       ① configured=true「我的交易对」= param_templates 已配置(可交易);
       ② configured=false「机会发现」= 主平台其余品种按推断后缀配对冲腿(仅分析, 多账户纳管落地后可一键接入)。
       桥单线程: 结果 Redis 缓存 8s + tick 受控并发(信号量), 绝不饿死交易引擎。"""
    uid=_uid(username)
    if not uid: raise HTTPException(404,"user not found")
    ck=RNS+"arb:scan:"+str(uid); cached=R.get(ck)
    if cached:
        try: return json.loads(cached)
        except Exception: pass
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT symbol,hedge_symbol,entry_spread,basis_offset,fluctuation_band
                   FROM param_templates WHERE user_id=%s ORDER BY id""",(uid,))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    # 已配置对 + 推断对冲后缀(如 XAUUSD→XAUUSD+ 得 "+") + 默认阈值(取已配置对均值, 无则0.3)
    cfg_syms=set(); suffix=""; thr_sum=0.0; thr_n=0
    for t in rows:
        cfg_syms.add(t["symbol"])
        hs=(t.get("hedge_symbol") or "").strip()
        if hs and hs.startswith(t["symbol"]) and hs!=t["symbol"]: suffix=hs[len(t["symbol"]):]
        e=float(t.get("entry_spread") or 0)
        if e>0: thr_sum+=e; thr_n+=1
    default_thr=round(thr_sum/thr_n,4) if thr_n else 0.3
    # 机会雷达候选: 主桥全品种里未配置的(≤5个, 无爆炸风险)
    radar_syms=[]
    if getattr(CONN,"hedge",None):   # 无对冲桥则不做雷达
        for s in await _arb_bridge_symbols():
            if s not in cfg_syms: radar_syms.append(s)
    # 组装任务: (msym, hsym, entry, off, fb, configured)
    tasks=[]
    for t in rows:
        tasks.append((t["symbol"], ENG.map_hedge_symbol(t["symbol"],t.get("hedge_symbol")) or t["symbol"],
                      float(t.get("entry_spread") or 0), float(t.get("basis_offset") or 0),
                      float(t.get("fluctuation_band") or 0), True))
    alias=_arb_alias_map()
    for s in radar_syms:
        tasks.append((s, _arb_hedge_for(s,alias,suffix), default_thr, 0.0, 0.0, False))
    # 受控并发拉双腿 tick(信号量=4, 限流保护单线程桥)
    sem=_asyncio.Semaphore(4)
    async def _one(ms,hs,entry,off,fb,configured):
        async def _safe(coro):
            async with sem:
                try: return await _asyncio.wait_for(coro, timeout=3.0)   # 短超时: 桥慢/死时快速降级为数据不足, 不拖垮整扫描
                except Exception: return None
        _hasH=getattr(CONN,"hedge",None)
        mt,ht,msw,hsw=await _asyncio.gather(
            _safe(CONN.main._get("/mt5/tick/"+ms)),
            _safe(CONN.hedge._get("/mt5/tick/"+hs)) if _hasH else _safe(_asyncio.sleep(0)),
            _arb_swap(CONN.main, ms, "m"),
            _arb_swap(CONN.hedge, hs, "h") if _hasH else _safe(_asyncio.sleep(0)))
        mp=(mt.get("bid",0)+mt.get("ask",0))/2 if isinstance(mt,dict) else None
        hp=(ht.get("bid",0)+ht.get("ask",0))/2 if isinstance(ht,dict) else None
        basis=round((mp-hp-off),4) if (mp is not None and hp is not None) else None
        score,reachable,suggest=_arb_score(basis,entry)
        # 隔夜利息(swap): 对冲=两腿反向锁仓, 两种锁法各算净利息, 取更优者
        #   锁法A: 主多+对冲空 = main.swap_long + hedge.swap_short
        #   锁法B: 主空+对冲多 = main.swap_short + hedge.swap_long
        # swap 单位=账户货币/手/夜(MT5 symbol_info 原值)。净为负=每夜倒扣, 会侵蚀点差利润。
        m_sl,m_ss=msw if isinstance(msw,tuple) else (None,None)
        h_sl,h_ss=hsw if isinstance(hsw,tuple) else (None,None)
        swap_net=None; swap_dir=None; swap_ok=None
        if None not in (m_sl,m_ss,h_sl,h_ss):
            netA=m_sl+h_ss; netB=m_ss+h_sl
            if netA>=netB: swap_net=round(netA,2); swap_dir="主多/对冲空"
            else:          swap_net=round(netB,2); swap_dir="主空/对冲多"
            swap_ok=swap_net>=0   # True=净收/持平(利好长持), False=净付(长持侵蚀利润)
        return {"main_symbol":ms,"hedge_symbol":hs,"main_price":mp,"hedge_price":hp,
                "basis":basis,"entry_spread":entry,"score":score,"reachable":reachable,
                "suggest":suggest,"fluctuation_band":fb,"configured":configured,
                "main_ok":isinstance(mt,dict),"hedge_ok":isinstance(ht,dict),
                "swap_net":swap_net,"swap_dir":swap_dir,"swap_ok":swap_ok,
                "main_swap_long":m_sl,"main_swap_short":m_ss,"hedge_swap_long":h_sl,"hedge_swap_short":h_ss}
    pairs=await _asyncio.gather(*[_one(*t) for t in tasks])
    # 排序: 已配置对优先, 再按评分
    pairs.sort(key=lambda p:(not p["configured"], -p["score"]))
    cfg_pairs=[p for p in pairs if p["configured"]]
    _reach=sum(1 for p in pairs if p["reachable"])
    _reach_cfg=sum(1 for p in cfg_pairs if p["reachable"])
    best=max(pairs,key=lambda p:p["score"]) if pairs else None
    summary={"pairs":len(pairs),"configured_pairs":len(cfg_pairs),"radar_pairs":len(pairs)-len(cfg_pairs),
             "reachable":_reach,"reachable_configured":_reach_cfg,
             "top_score":best["score"] if best else 0,
             "verdict": ("发现 %d 个可套利机会(%d 个在你的交易对内)"%(_reach,_reach_cfg)) if _reach>0 else "当前无达标套利机会,继续监控"}
    out={"username":username,"summary":summary,"pairs":pairs}
    R.setex(ck, 8, json.dumps(out,default=str))   # 8s 缓存: 刷新/多端不重复打桥
    # 埋点落库(仅统计已配置对的命中, 保持口径与交易一致)
    try:
        c2=db(); cur2=c2.cursor()
        cb=cfg_pairs[0] if cfg_pairs else best
        cur2.execute("""INSERT INTO ai_arb_scans(user_id,username,pairs,reachable,top_score,hit,top_symbol,top_basis)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (uid,username,len(pairs),_reach,(best["score"] if best else 0),(_reach>0),
                      (cb["main_symbol"]+"/"+cb["hedge_symbol"]) if cb else "",(cb["basis"] if cb else None)))
        c2.close()
    except Exception as _e: pass
    return out

@app.get("/api/admin/bi/arb_stats", dependencies=[Depends(require_op("bi"))])
def bi_arb_stats(days:int=30):
    """AI套利分析成功数据统计(所有用户): 扫描次数/命中次数/命中率/活跃用户/平均最高分 + 每用户明细。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT count(*) scans, COALESCE(SUM(CASE WHEN hit THEN 1 ELSE 0 END),0) hits,
                          count(DISTINCT user_id) users, COALESCE(AVG(top_score),0) avg_top,
                          COALESCE(SUM(reachable),0) total_reachable
                   FROM ai_arb_scans WHERE scanned_at>=now()-(%s||' days')::interval""",(days,))
    ov=dict(cur.fetchone() or {})
    cur.execute("""SELECT username, count(*) scans, SUM(CASE WHEN hit THEN 1 ELSE 0 END) hits,
                          COALESCE(MAX(top_score),0) best_score, COALESCE(AVG(top_score),0) avg_score,
                          MAX(scanned_at) last_scan
                   FROM ai_arb_scans WHERE scanned_at>=now()-(%s||' days')::interval
                   GROUP BY username ORDER BY hits DESC, scans DESC LIMIT 100""",(days,))
    users=[dict(x) for x in cur.fetchall()]; c.close()
    scans=int(ov.get("scans") or 0); hits=int(ov.get("hits") or 0)
    for u in users:
        u["scans"]=int(u["scans"] or 0); u["hits"]=int(u["hits"] or 0)
        u["hit_rate"]=round(u["hits"]/u["scans"]*100,1) if u["scans"] else 0
        u["best_score"]=int(u["best_score"] or 0); u["avg_score"]=round(float(u["avg_score"] or 0),1)
        u["last_scan"]=u["last_scan"].isoformat() if u["last_scan"] else None
    return {"days":days,"overview":{"scans":scans,"hits":hits,"hit_rate":round(hits/scans*100,1) if scans else 0,
            "users":int(ov.get("users") or 0),"avg_top":round(float(ov.get("avg_top") or 0),1),
            "total_reachable":int(ov.get("total_reachable") or 0)},"users":users}


@app.get("/api/naked/{username}", dependencies=[Depends(require_subject)])
def naked_alerts(username:str):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT n.leg,n.detail,n.resolved,n.ts FROM naked_alerts n LEFT JOIN users u ON u.id=n.user_id WHERE u.username=%s ORDER BY n.ts DESC LIMIT 20",(username,))
    rows=cur.fetchall(); c.close()
    return {"naked":[dict(r) for r in rows]}


# ---- 按腿直取 bridge 历史成交（主/对冲分别）----
def _history_window(days, start=None, end=None):
    now=_t_conn.time()
    days=max(1,min(int(days or 1),3650))
    try: start=float(start) if start is not None else now-days*86400
    except (TypeError,ValueError): raise HTTPException(400,"invalid history start")
    try: end=float(end) if end is not None else now
    except (TypeError,ValueError): raise HTTPException(400,"invalid history end")
    if start!=start or end!=end or end<start:
        raise HTTPException(400,"invalid history time range")
    fetch_days=max(days,min(3650,int(max(0,now-start)/86400)+2))
    return fetch_days,start,end

def _audit_history_deals(username, start, end, symbol="XAUUSD", hedge_symbol=""):
    """Rebuild confirmed QH fills when a headless MT4 has not loaded broker history."""
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT pt.symbol,pt.hedge_symbol FROM param_templates pt
                       JOIN users u ON u.id=pt.user_id WHERE u.username=%s
                       AND pt.symbol=%s LIMIT 1""",(username,symbol))
        cfg=cur.fetchone() or {}
        main_symbol=cfg.get("symbol") or symbol
        hedge_symbol=ENG.map_hedge_symbol(main_symbol,cfg.get("hedge_symbol") or hedge_symbol) or main_symbol
        cur.execute("""SELECT a.action,a.payload,a.result,a.ts FROM audit_log a
                       JOIN users u ON u.id=a.user_id WHERE u.username=%s
                       AND a.action IN ('open_pair','close_pair')
                       AND a.ts>=to_timestamp(%s)-interval '31 days' AND a.ts<=to_timestamp(%s)
                       ORDER BY a.ts""",(username,start,end))
        rows=cur.fetchall(); c.close()
    except Exception:
        try: c.close()
        except Exception: pass
        return {"main":[],"hedge":[]}
    out={"main":[],"hedge":[]}; opened_side={}
    for row in rows:
        action=row.get("action"); result=str(row.get("result") or "")
        if action=="open_pair" and not result.startswith("opened"): continue
        if action=="close_pair" and not result.startswith("closed"): continue
        payload=row.get("payload") or {}
        root=(payload.get("res") if action=="open_pair" else payload) or payload
        direction=root.get("direction") or payload.get("direction")
        event_time=int(row["ts"].timestamp()) if row.get("ts") else 0
        entry=0 if action=="open_pair" else 1
        for leg in ("main","hedge"):
            part=root.get(leg) or {}
            if not isinstance(part,dict) or part.get("success",part.get("ok",True)) is False: continue
            ticket=part.get("order") or part.get("ticket") or part.get("deal")
            if ticket in (None,""): continue
            ticket=str(ticket)
            if entry==0:
                side=1 if (direction=="reverse" and leg=="main") or (direction=="forward" and leg=="hedge") else 0
                opened_side[(leg,ticket)]=(side,direction)
            else:
                side,direction=opened_side.get((leg,ticket),(-1,direction))
            if event_time<start: continue
            out[leg].append({"ticket":ticket,"order":ticket,
                "symbol":main_symbol if leg=="main" else hedge_symbol,"type":side,"entry":entry,
                "volume":part.get("filled_volume") or part.get("volume") or 0,
                "price":part.get("price") or 0,"profit":None,"swap":None,"commission":None,
                "time":event_time,"comment":"QH-%s-%s"%((direction or "unknown"),leg),
                "history_source":"audit"})
    return out

async def _bridge_leg_deals(leg, days, username, start=None, end=None):
    if leg not in ("main","hedge"):
        raise HTTPException(400,"leg must be main or hedge")
    fetch_days,start,end=_history_window(days,start,end)
    # conn=_user_exec_conn(username) was the legacy read path; strict routing
    # below intentionally prevents its global EXEC fallback.
    conn=_strict_user_read_conn(username)
    if conn is None:
        return {"leg":leg,"deals":[],"start":start,"end":end,"error":"user connector unavailable"}
    legobj=conn.main if leg=="main" else getattr(conn,"hedge",None)
    if legobj is None: return {"leg":leg,"deals":[],"start":start,"end":end}
    try:
        data=await legobj.history_deals(fetch_days)
    except Exception as e:
        raise HTTPException(502,"bridge deals err: %s"%e)
    deals=data.get("deals",data) if isinstance(data,dict) else data
    audit_fallback=False
    if not deals:
        deals=_audit_history_deals(username,start,end).get(leg) or []
        audit_fallback=bool(deals)
    TYPE={0:"buy",1:"sell",2:"balance"}
    offset=0 if audit_fallback else await _broker_utc_offset(leg,conn,username)
    out=[]
    for d in (deals or []):
        t=int(d.get("type",-1)); event_time=_to_utc(d.get("time"),offset)
        if t not in (0,1) or not event_time or event_time<start or event_time>end: continue
        financials_known=d.get("history_source")!="audit"
        out.append({"ticket":str(d.get("ticket","")),"order":str(d.get("order","")),
                    "symbol":d.get("symbol",""),"side":TYPE.get(t,str(t)),
                    "entry":int(d.get("entry",-1)),"lots":float(d.get("volume",0) or 0),
                    "price":float(d.get("price",0) or 0),
                    "profit":float(d.get("profit",0) or 0) if financials_known else None,
                    "swap":float(d.get("swap",0) or 0) if financials_known else None,
                    "commission":float(d.get("commission",0) or 0) if financials_known else None,
                    "time":event_time,"is_trade":True,"history_source":d.get("history_source") or "broker"})
    out.sort(key=lambda x:x.get("time") or 0, reverse=True)
    return {"leg":leg,"deals":out[:1000],"start":start,"end":end}

@app.get("/api/bridge/deals/{leg}", dependencies=[Depends(require_license)])
async def bridge_leg_deals(leg:str, days:int=7, username:str="", start:float|None=None,
                           end:float|None=None, x_license:str=Header(default="")):
    principal=require_license(x_license)
    if username: _assert_subject(username,x_license)
    return await _bridge_leg_deals(leg,days,username or principal,start,end)

# ---- 两腿卡片数据: 实时持仓盈亏/过夜费(持仓) + 已结算累计过夜费/手续费(历史成交) ----
@app.get("/api/engine/legstats", dependencies=[Depends(require_optional_subject)])
async def engine_legstats(days:int=30, username:str="", x_license: str = Header(default="")):
    """每腿: live(持仓 profit/swap 合计 + 多/空手数) + settled(历史成交 swap/commission 累计) + 平均开仓点差(testgo 账本)。"""
    if not username:
        username=_LICENSE_PRINCIPAL.get() or _license_to_username(x_license) or ""
    if not username:
        raise HTTPException(403,"缺少用户主体")
    out={"main":None,"hedge":None,"days":days,"avg_spread":None}
    conn=_strict_user_read_conn(username)
    if conn is None:
        return out
    # 实时持仓(profit/swap)
    try:
        pos = await conn.both_positions() if hasattr(conn,"both_positions") else {"main":await conn.positions(),"hedge":None}
    except Exception as e:
        raise HTTPException(502,"bridge error: %s"%e)
    def _live(pl):
        items = pl.get("positions",pl) if isinstance(pl,dict) else (pl or [])
        pf=sum(float(p.get("profit",0) or 0) for p in (items or []))
        sw=sum(float(p.get("swap",0) or 0) for p in (items or []))
        # 多/空手数(MT5 type 0=buy 1=sell)
        lng=sum(float(p.get("volume",0) or 0) for p in (items or []) if str(p.get("type"))!="1" and p.get("side")!="sell")
        sht=sum(float(p.get("volume",0) or 0) for p in (items or []) if str(p.get("type"))=="1" or p.get("side")=="sell")
        return round(pf,2), round(sw,2), len(items or []), round(lng,2), round(sht,2)
    # 已结算累计(历史成交 swap/commission)
    async def _settled(leg):
        try:
            data = await (conn.hedge if leg=="hedge" else conn.main).history_deals(days) if (leg=="main" or getattr(conn,"hedge",None)) else None
        except Exception:
            data=None
        if not data: return None,None
        deals=data.get("deals",data) if isinstance(data,dict) else data
        sw=0.0; cm=0.0
        for d in (deals or []):
            t=int(d.get("type",-1))
            if t in (0,1):  # 仅真实成交计手续费/过夜费(排除 balance/出入金)
                sw+=float(d.get("swap",0) or 0); cm+=float(d.get("commission",0) or 0)
        return round(sw,2), round(cm,2)
    for leg in ("main","hedge"):
        pl = pos.get(leg)
        if leg=="hedge" and not getattr(conn,"hedge",None):
            out[leg]=None; continue
        lp,ls,n,lng,sht=_live(pl) if pl is not None else (0.0,0.0,0,0.0,0.0)
        ssw,scm=await _settled(leg)
        out[leg]={"live_profit":lp,"live_swap":ls,"pos_count":n,"long_lots":lng,"short_lots":sht,
                  "settled_swap_cum":ssw,"settled_commission_cum":scm}
    # 平均开仓点差(testgo: Σq·s/Σq, 跨两方向账本; 按持仓笔数 trim 自纠漂移)
    if username:
        try:
            mainitems=pos.get("main"); mi=mainitems.get("positions",mainitems) if isinstance(mainitems,dict) else (mainitems or [])
            n_rev=sum(1 for p in (mi or []) if str(p.get("type"))=="1" or p.get("side")=="sell")  # reverse=主sell
            n_fwd=sum(1 for p in (mi or []) if not (str(p.get("type"))=="1" or p.get("side")=="sell"))
            tot_w=0.0; tot_q=0.0
            for _dir,n_open in (("reverse",n_rev),("forward",n_fwd)):
                rows=R.lrange(RNS+"ledger:"+username+":"+_dir,0,-1) or []
                # 账本多于实际持仓→trim 最旧(自纠 QH 外平仓/手动平仓漂移)
                if len(rows)>n_open: rows=rows[len(rows)-n_open:]
                for raw in rows:
                    try: e=json.loads(raw)
                    except Exception: continue
                    q=float(e.get("q") or 0); s=float(e.get("s") or 0)
                    if q<=0: continue
                    tot_q+=q; tot_w+=q*s
            out["avg_spread"]=round(tot_w/tot_q,4) if tot_q>0 else None
        except Exception: pass
    return out

# ---- 套利配对成交历史: comment 精确配对 + 时间窗兜底(仿 testgo /trading, 但两腿同 MT5) ----
def _nearest_unclaimed_time(rows, target, claimed, max_delta=None):
    """Return the closest original row index from a sorted (time, index) list."""
    if not rows:
        return None
    try:
        target=float(target or 0)
    except (TypeError,ValueError):
        target=0.0
    pos=_bisect.bisect_left(rows,(target,-1))
    left=pos-1; right=pos
    while left>=0 or right<len(rows):
        options=[]; advanced=False
        if left>=0:
            ts=rows[left][0]
            first=_bisect.bisect_left(rows,(ts,-1),0,left+1)
            available=[idx for _stamp,idx in rows[first:left+1]
                       if idx not in claimed]
            if available:
                options.append((abs(ts-target),min(available),"left",first))
            else:
                left=first-1
                advanced=True
        if right<len(rows):
            ts=rows[right][0]
            last=_bisect.bisect_right(rows,(ts,float("inf")),right)
            available=[idx for _stamp,idx in rows[right:last]
                       if idx not in claimed]
            if available:
                options.append((abs(ts-target),min(available),"right",last))
            else:
                right=last
                advanced=True
        if advanced:
            continue
        if not options:
            continue
        delta,idx,side,boundary=min(options)
        if max_delta is not None and delta>max_delta:
            return None
        if side=="left": left=boundary-1
        else: right=boundary
        if idx not in claimed:
            return idx
    return None

def _discard_time_index(rows, timestamp, index):
    if not rows:
        return
    key=(timestamp,index)
    pos=_bisect.bisect_left(rows,key)
    if pos<len(rows) and rows[pos]==key:
        rows.pop(pos)

def _history_pair_matches(main, hedge):
    """Index history by entry/direction and preserve the legacy greedy pairing."""
    by_entry={}; by_direction={}; hedge_keys={}
    for idx,row in enumerate(hedge):
        entry=row.get("entry")
        try: ts=float(row.get("time") or 0)
        except (TypeError,ValueError): ts=0.0
        by_entry.setdefault(entry,[]).append((ts,idx))
        comment=str(row.get("comment") or "")
        directions=[]
        for direction in ("reverse","forward"):
            if direction in comment:
                directions.append(direction)
                by_direction.setdefault((entry,direction),[]).append((ts,idx))
        hedge_keys[idx]=(ts,entry,directions)
    for rows in list(by_entry.values())+list(by_direction.values()):
        rows.sort()

    claimed=set(); matches={}
    ordered=sorted(range(len(main)),key=lambda idx:main[idx].get("time") or 0)
    for pass_delta in (5,None):
        for main_idx in ordered:
            if main_idx in matches:
                continue
            row=main[main_idx]
            comment=str(row.get("comment") or "")
            direction=("reverse" if "reverse" in comment else
                       "forward" if "forward" in comment else None)
            target=row.get("time") or 0
            hedge_idx=None
            if direction:
                hedge_idx=_nearest_unclaimed_time(
                    by_direction.get((row.get("entry"),direction),()),
                    target,claimed,pass_delta)
            if hedge_idx is None:
                fallback_delta=2 if pass_delta is None else min(2,pass_delta)
                hedge_idx=_nearest_unclaimed_time(
                    by_entry.get(row.get("entry"),()),target,claimed,
                    fallback_delta)
            if hedge_idx is not None:
                matches[main_idx]=hedge_idx
                claimed.add(hedge_idx)
                ts,entry,directions=hedge_keys[hedge_idx]
                _discard_time_index(by_entry.get(entry),ts,hedge_idx)
                for direction in directions:
                    _discard_time_index(
                        by_direction.get((entry,direction)),ts,hedge_idx)
    return matches,claimed,ordered

def _history_snapshot_indices(snapshots):
    ticket_index={}; time_index={}
    for idx,snapshot in enumerate(snapshots):
        action=snapshot.get("a")
        try: ts=float(snapshot.get("ts") or 0)
        except (TypeError,ValueError): ts=0.0
        time_index.setdefault(action,[]).append((ts,idx))
        for ticket in snapshot.get("tk") or ():
            try: ticket_index.setdefault((action,ticket),[]).append(idx)
            except TypeError: continue
    for rows in time_index.values():
        rows.sort()
    return ticket_index,time_index

def _history_match_snapshot(md, deal_utc, action, snapshots, claimed,
                            ticket_index, time_index):
    tickets=[]
    for ticket in (md.get("ticket"),md.get("order")):
        if ticket not in (None,"") and ticket not in tickets:
            tickets.append(ticket)
    exact=[]
    for ticket in tickets:
        try:
            exact.extend(idx for idx in ticket_index.get((action,ticket),())
                         if idx not in claimed)
        except TypeError:
            continue
    if exact:
        idx=min(exact)
        claimed.add(idx)
        try: ts=float(snapshots[idx].get("ts") or 0)
        except (TypeError,ValueError): ts=0.0
        _discard_time_index(time_index.get(action),ts,idx)
        return snapshots[idx]
    if deal_utc is None:
        return None
    idx=_nearest_unclaimed_time(time_index.get(action,()),deal_utc,claimed)
    if idx is None:
        return None
    try: delta=abs(float(snapshots[idx].get("ts") or 0)-float(deal_utc))
    except (TypeError,ValueError): return None
    if delta>=4.5:
        return None
    claimed.add(idx)
    _discard_time_index(time_index.get(action),
                        float(snapshots[idx].get("ts") or 0),idx)
    return snapshots[idx]

async def _engine_paired_history(days:int, symbol:str, username:str, start=None, end=None):
    """主/对冲两腿历史成交按 comment(QH-{dir}-main/hedge) 精确配对; 无标签退回时间窗(±2s)。
       每配对: 双腿时间/方向/价/手数 + 开仓点差 + 双腿手续费/过夜费/盈亏 + 配对净盈亏 + 持仓时长。只读。"""
    fetch_days,start,end=_history_window(days,start,end)
    # conn=_user_exec_conn(username) was the legacy read path; strict routing
    # below intentionally prevents its global EXEC fallback.
    conn=_strict_user_read_conn(username)
    if conn is None:
        return {"symbol":symbol,"hedge_symbol":symbol,
                "threshold":None,"summary":{"pairs":0,"closed":0,
                "gross_profit":None,"net_profit":None,"fee_main":None,
                "fee_hedge":None,"swap_main":None,"swap_hedge":None,
                "win_rate":None,"financial_pairs":0},"pairs":[],
                "unmatched_hedge":0,"start":start,"end":end,
                "error":"user connector unavailable"}
    hsym=symbol
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""SELECT pt.hedge_symbol FROM param_templates pt JOIN users u ON u.id=pt.user_id
                       WHERE u.username=%s AND pt.symbol=%s LIMIT 1""",(username,symbol))
        row=cur.fetchone(); c.close()
        if row: hsym=ENG.map_hedge_symbol(symbol,row.get("hedge_symbol")) or symbol
    except Exception: pass
    async def _deals(leg):
        try:
            legobj=conn.main if leg=="main" else getattr(conn,"hedge",None)
            data=await legobj.history_deals(fetch_days) if legobj is not None else None
        except Exception: data=None
        ds=(data.get("deals",data) if isinstance(data,dict) else data) or []
        offset=await _broker_utc_offset(leg,conn,username)
        out=[]
        for d in ds:
            t_=int(d.get("type",-1)); e_=int(d.get("entry",-1))
            if t_ not in (0,1): continue   # 仅真实成交(排除 balance)
            event_time=_to_utc(d.get("time") or 0,offset)
            if not event_time or event_time<start or event_time>end: continue
            out.append({"ticket":str(d.get("ticket","")),"order":str(d.get("order","")),
                        "side":"buy" if t_==0 else "sell","entry":e_,  # entry 0=in 1=out
                        "vol":float(d.get("volume",0) or 0),"price":float(d.get("price",0) or 0),
                        "profit":float(d.get("profit",0) or 0),"swap":float(d.get("swap",0) or 0),
                        "comm":float(d.get("commission",0) or 0),"comment":d.get("comment","") or "","time":event_time,
                        "financials_known":d.get("history_source")!="audit"})
        return out
    main=await _deals("main"); hedge=await _deals("hedge")
    if not main and not hedge:
        audit=_audit_history_deals(username,start,end,symbol,hsym)
        async def _audit_rows(leg):
            out=[]
            for d in audit.get(leg) or []:
                t_=int(d.get("type",-1))
                if t_ not in (0,1): continue
                out.append({"ticket":str(d.get("ticket","")),"order":str(d.get("order","")),
                            "side":"buy" if t_==0 else "sell","entry":int(d.get("entry",-1)),
                            "vol":float(d.get("volume",0) or 0),"price":float(d.get("price",0) or 0),
                            "profit":0.0,"swap":0.0,"comm":0.0,"comment":d.get("comment","") or "",
                            "time":d.get("time") or 0,"financials_known":False})
            return out
        main=await _audit_rows("main"); hedge=await _audit_rows("hedge")
    _match_map,used,_ordered=await _aio.to_thread(
        _history_pair_matches,main,hedge)
    pairs=[]
    # 阈值(取该品种 param entry_spread, 历史单无逐单阈值→用当前配置近似)
    thr=None
    try:
        c=db(); cur=c.cursor(); cur.execute("""SELECT pt.entry_spread FROM param_templates pt JOIN users u ON u.id=pt.user_id
                                               WHERE u.username=%s AND pt.symbol=%s LIMIT 1""",(username,symbol)); rr=cur.fetchone(); c.close()
        if rr and rr[0] is not None: thr=float(rr[0])
    except Exception: pass
    # 执行滑点决策快照(全局环形): 按 action(open/close)+时间就近匹配; 滑点=实际成交捕获-决策快照(带符号)
    try: _snaps=[json.loads(x) for x in (R.lrange(RNS+"slipsnap",0,-1) or [])]
    except Exception: _snaps=[]
    _snap_used=set()
    _snap_ticket_index,_snap_time_index=await _aio.to_thread(
        _history_snapshot_indices,_snaps)
    for mi in _ordered:
        md=main[mi]
        hi=_match_map.get(mi)
        h=hedge[hi] if hi is not None else None
        spread=round(abs(md["price"]-h["price"]),4) if h else None
        # 带符号执行滑点: 优先决策快照为基准; 平仓行只认平仓侧快照(无则 None→前端'—'), 开仓行回退近似阈值(标记 approx)
        _act="open" if md["entry"]==0 else "close"
        _sn=_history_match_snapshot(
            md,md["time"],_act,_snaps,_snap_used,
            _snap_ticket_index,_snap_time_index)
        slippage=None; slip_src="none"
        if _sn is not None and h:
            _rc=_realized_cap(_sn.get("d"), _norm_price(md["price"],"main",username), _norm_price(h["price"],"hedge",username))
            if _rc is not None and _sn.get("c") is not None:
                slippage=round(_rc-float(_sn["c"]),4); slip_src="snap"
        elif _act=="open" and h and thr is not None:
            _dir="reverse" if "reverse" in md["comment"] else ("forward" if "forward" in md["comment"] else None)
            _rc=_realized_cap(_dir, _norm_price(md["price"],"main",username), _norm_price(h["price"],"hedge",username)) if _dir else None
            if _rc is not None: slippage=round(_rc-thr,4); slip_src="approx"
        # 逐行阈值(达标差用): 快照记了该单下单时真实买入点位(th)则用之, 否则回落全局近似
        row_thr = thr
        if _sn is not None and _sn.get("th") is not None:
            try: row_thr=float(_sn["th"])
            except (TypeError,ValueError): pass
        # 达标差 = 点差 − 阈值(用户口径, 与旧HED公式一致; 双列并存)
        dev = round(spread-row_thr,4) if (spread is not None and row_thr is not None) else None
        financials_known=bool(md.get("financials_known")) and bool(h and h.get("financials_known"))
        pair_profit=round(md["profit"]+md["swap"]+md["comm"]+h["profit"]+h["swap"]+h["comm"],2) if financials_known else None
        pairs.append({"time":md["time"],"entry":"开" if md["entry"]==0 else "平",
                      "main_side":md["side"],"main_price":md["price"],"main_vol":md["vol"],
                      "hedge_side":(h["side"] if h else None),"hedge_price":(h["price"] if h else None),"hedge_vol":(h["vol"] if h else None),
                      "spread":spread,"threshold":row_thr,"dev":dev,"slippage":slippage,"slip_src":slip_src,"matched":h is not None,
                      "main_fee":round(md["comm"],2) if financials_known else None,
                      "hedge_fee":round(h["comm"],2) if financials_known else None,
                      "main_swap":round(md["swap"],2) if financials_known else None,
                      "hedge_swap":round(h["swap"],2) if financials_known else None,
                      "main_profit":round(md["profit"],2) if financials_known else None,
                      "hedge_profit":round(h["profit"],2) if financials_known else None,
                      "pair_profit":pair_profit,"financials_known":financials_known,
                      "source":"QH" if md["comment"].startswith("QH") else "manual"})
    pairs.sort(key=lambda x:x["time"] or 0, reverse=True)
    # 汇总(仿 testgo 顶栏): 平仓净利润/笔数/胜率/费用合计
    closed=[p for p in pairs if p["entry"]=="平"]
    known=[p for p in pairs if p.get("financials_known")]
    known_closed=[p for p in closed if p.get("financials_known")]
    gross=round(sum(p["main_profit"]+p["hedge_profit"] for p in known),2) if known else None
    fee_main=round(sum(p["main_fee"] for p in known),2) if known else None
    fee_hedge=round(sum(p["hedge_fee"] for p in known),2) if known else None
    swap_main=round(sum(p["main_swap"] for p in known),2) if known else None
    swap_hedge=round(sum(p["hedge_swap"] for p in known),2) if known else None
    net=round(sum(p["pair_profit"] for p in known),2) if known else None
    win=len([p for p in known_closed if p["pair_profit"]>0])
    summary={"pairs":len(pairs),"closed":len(closed),"gross_profit":gross,"net_profit":net,
             "fee_main":fee_main,"fee_hedge":fee_hedge,"swap_main":swap_main,"swap_hedge":swap_hedge,
             "win_rate":round(win/len(known_closed)*100,1) if known_closed else None,
             "financial_pairs":len(known)}
    return {"symbol":symbol,"hedge_symbol":hsym,"threshold":thr,"summary":summary,
            "pairs":pairs[:1000],"unmatched_hedge":len([1 for i in range(len(hedge)) if i not in used]),
            "start":start,"end":end}

@app.get("/api/engine/paired_history", dependencies=[Depends(require_license)])
async def engine_paired_history(days:int=7, symbol:str="XAUUSD", username:str="",
                                start:float|None=None, end:float|None=None,
                                x_license:str=Header(default="")):
    principal=require_license(x_license)
    if username: _assert_subject(username,x_license)
    return await _engine_paired_history(days,symbol,username or principal,start,end)

# ---- 当日平仓利润 + 两腿过夜费/手续费/返佣(顶栏蓝框) ----
async def _engine_daypnl_for_user(username, symbol="XAUUSD"):
    """当日(北京时区)平仓净利润 + 主/对冲 过夜费/手续费/返佣。
       返佣 MT5 无原生字段→取 deal.commission 中的正值部分(部分经纪商返佣记为正佣金)；无则 0。"""
    # 北京日界 → UTC: 今天 00:00(UTC+8) 对应的 epoch
    now=_dt.datetime.now(_dt.timezone.utc); bj=now+_dt.timedelta(hours=8)
    day_start_bj=bj.replace(hour=0,minute=0,second=0,microsecond=0)
    day_start_epoch=(day_start_bj-_dt.timedelta(hours=8)).timestamp()
    conn=_strict_user_read_conn(username)
    if conn is None:
        return {"day_close_profit":0.0,"day_net_profit":0.0,
                "main":{"close_profit":0.0,"swap":0.0,"fee":0.0,"rebate":0.0},
                "hedge":{"close_profit":0.0,"swap":0.0,"fee":0.0,"rebate":0.0},
                "since":day_start_epoch,"error":"user connector unavailable"}
    async def _leg(leg):
        try:
            data=await (conn.hedge if leg=="hedge" else conn.main).history_deals(2) if (leg=="main" or getattr(conn,"hedge",None)) else None
        except Exception: data=None
        ds=(data.get("deals",data) if isinstance(data,dict) else data) or []
        close_pf=0.0; swap=0.0; fee=0.0; rebate=0.0
        for d in ds:
            t=int(d.get("type",-1)); e=int(d.get("entry",-1)); ts=d.get("time") or 0
            if t not in (0,1): continue
            if ts < day_start_epoch: continue   # 仅当日
            cm=float(d.get("commission",0) or 0); sw=float(d.get("swap",0) or 0)
            swap+=sw
            if cm<0: fee+=cm        # 手续费(负)
            elif cm>0: rebate+=cm   # 返佣(正佣金, 部分经纪商口径)
            if e==1: close_pf+=float(d.get("profit",0) or 0)  # entry=out 平仓利润
        return {"close_profit":round(close_pf,2),"swap":round(swap,2),"fee":round(fee,2),"rebate":round(rebate,2)}
    m=await _leg("main"); h=await _leg("hedge") if getattr(conn,"hedge",None) else {"close_profit":0,"swap":0,"fee":0,"rebate":0}
    day_close=round(m["close_profit"]+h["close_profit"],2)
    day_net=round(m["close_profit"]+h["close_profit"]+m["swap"]+h["swap"]+m["fee"]+h["fee"]+m["rebate"]+h["rebate"],2)
    return {"day_close_profit":day_close,"day_net_profit":day_net,"main":m,"hedge":h,"since":day_start_epoch}

@app.get("/api/engine/daypnl", dependencies=[Depends(require_license)])
async def engine_daypnl(symbol:str="XAUUSD", x_license:str=Header(default="")):
    return await _engine_daypnl_for_user(_license_to_username(x_license),symbol)

# ================= 实时推送 WebSocket(替代 web 3s 轮询) =================
# 单 worker: 内存态共享。广播任务做一次 poll() 的活, 分层缓存(快/慢字段), 扇出所有连接。
import asyncio as _asyncio
_WS_CLIENTS=set()          # 活跃连接集合
_WS_SNAP={"fast":{}, "slow":{}, "fast_ts":0, "slow_ts":0,
          "published_slow_ts":{}}
_WS_FAST_BY_USER={}
_WS_FAST_TS_BY_USER={}
_WS_SLOW_BY_USER={}
_WS_SLOW_TS_BY_USER={}
_WS_RECIPIENT_CACHE={"users":[], "at":0.0}
def _ws_resolve_symbols(state, user=""):
    """Resolve only the recipient's symbols; never borrow another user's eval."""
    hsym="XAUUSD"; msym="XAUUSD"
    try:
        ev=((state or {}).get("eval") or {})
        if not ev:
            raw=R.hgetall(RNS+"engine:eval") or {}
            ev={k:(json.loads(v) if isinstance(v,str) else (v or {})) for k,v in raw.items() if v}
        if ev and user:
            entry=ev.get(user) or {}
            hsym=entry.get("hedge_symbol") or "XAUUSD"
            msym=entry.get("symbol") or "XAUUSD"
        elif ev:
            pu=R.get(RNS+"ws:primary_user") or ""
            entry = ev.get(pu) if (pu and pu in ev) else next(iter(ev.values()),{})
            hsym=entry.get("hedge_symbol") or "XAUUSD"; msym=entry.get("symbol") or "XAUUSD"
    except Exception: pass
    return msym, hsym
async def _ws_build_fast(user):
    """Build one recipient's quote-only frame without account or position data."""
    return await _ws_build_ticks({},user)
async def _ws_build_ticks(prev, user):
    """Build a high-frequency quote frame from the recipient's own connector."""
    previous=prev if (prev or {}).get("username")==user else {}
    out={key:previous[key] for key in ("tick_main","tick_hedge","symbols")
         if key in previous}
    out["username"]=user
    msym, hsym = _ws_resolve_symbols(None,user)
    # 主+对冲报价并发拉(bridge 支持并发, 两个一起 ~50ms 而非串行 ~100ms)
    async def _safe(coro):
        try: return await coro
        except Exception: return None
    mt, ht = await _asyncio.gather(
        _safe(_quote_tick_for_user(user,msym,"main")),
        _safe(_quote_tick_for_user(user,hsym,"hedge")))
    if mt is not None:
        out["tick_main"]=mt
    if ht is not None:
        out["tick_hedge"]=ht   # 失败保留上一帧 tick, 不清零
    out["symbols"]={"main":msym,"hedge":hsym}
    return out
async def _ws_build_slow(user):
    """低频字段(~10s): 腿统计/日盈亏/配对历史。"""
    out={"username":user or ""}
    try: out["legstats"]=await engine_legstats(30,user)
    except Exception: out["legstats"]=None
    try: out["daypnl"]=await _engine_daypnl_for_user(user)
    except Exception: out["daypnl"]=None
    try: out["liq"]=await _engine_liq_for_user("XAUUSD",user)
    except Exception: out["liq"]=None
    try: out["paired"]=await _engine_paired_history(7,"XAUUSD",user)
    except Exception: out["paired"]=None
    return out
def _ws_fast_for(user):
    fast=_WS_FAST_BY_USER.get(user) if user else None
    if fast and fast.get("username")==user: return fast
    return {"username":user or ""}
def _ws_slow_for(user):
    """Return only a slow snapshot that belongs to the requested user."""
    slow=_WS_SLOW_BY_USER.get(user) if user else None
    if slow and slow.get("username")==user: return slow
    legacy=_WS_SNAP.get("slow") or {}
    if legacy.get("username")==user: return legacy
    return {"username":user or ""}
def _ws_recipient_users():
    """Return authenticated local/hub users without trusting a global primary user."""
    users={getattr(ws,"_qh_user","") for ws in _WS_CLIENTS}
    users.discard("")
    registry_seen=False
    try:
        raw=R.get(RNS+"ws:hub_users")
        registry_seen=raw is not None
        if raw:
            values=json.loads(raw)
            if isinstance(values,list):
                users.update(value for value in values
                             if isinstance(value,str) and 0<len(value)<=128)
    except Exception:
        pass
    if registry_seen:
        return sorted(users)

    # Rolling-deploy fallback for an old Hub: retain only its explicitly
    # designated primary user. Publishing every active account here would
    # make a legacy broadcast hub leak one user's frame to another user.
    try:
        if R.get(RNS+"ws:hub_alive")!="1": return sorted(users)
        primary=R.get(RNS+"ws:primary_user") or ""
        return sorted(users.union({primary} if 0<len(primary)<=128 else set()))
    except Exception:
        return sorted(users)
_WS_USER_META_CACHE={}
def _ws_default_entitlements(user):
    defaults=dict(_feat_cache.get("defaults") or _ENT_DEFAULTS_FALLBACK)
    if user:
        defaults.update(_BUILTIN_ENTITLEMENTS)
    return defaults
def _ws_load_user_entitlements(user):
    try:
        uid=_uid(user)
        return _ent_all(uid) if uid else {}
    except Exception:
        return _ws_default_entitlements(user)
async def _ws_refresh_user_meta(users):
    now=_t_conn.monotonic()
    stale=[]
    for user in dict.fromkeys(str(value or "") for value in users):
        if not user:
            continue
        cached=_WS_USER_META_CACHE.get(user)
        if not cached or now-cached[0]>=5.0:
            stale.append(user)
    if not stale:
        return
    values=await _asyncio.gather(*(
        _asyncio.to_thread(_ws_load_user_entitlements,user) for user in stale))
    refreshed=_t_conn.monotonic()
    for user,value in zip(stale,values):
        _WS_USER_META_CACHE[user]=(refreshed,value)
def _ws_user_data(user):
    """每连接便宜的 per-user Redis 读: 自动档位/DEMO/权益/告警/坑位覆盖。"""
    d={"username":user}
    d["auto_entry"]=R.get(RNS+"auto_entry:"+user) or "off"
    d["auto_exit"]=R.get(RNS+"auto_exit:"+user) or "off"
    d["force_demo"]=(R.get(RNS+"force_demo:"+user)=="1")
    cached=_WS_USER_META_CACHE.get(user)
    d["entitlements"]=(cached[1] if cached else
                       _ws_default_entitlements(user))
    d["alerts"]=_read_user_alerts(user,20)
    return d
def _ws_gate_open():
    return bool(_WS_CLIENTS) or (R.get(RNS+"ws:hub_alive")=="1")
def _ws_publish():
    """把当前 _WS_SNAP 组帧 PUBLISH 到 Redis(HUB 扇出) + 扇出本地 WS 连接。"""
    import time as _t
    try:
        published=_WS_SNAP.setdefault("published_slow_ts",{})
        for user in _ws_recipient_users():
            try:
                fast=_ws_fast_for(user)
                fast_ts=_WS_FAST_TS_BY_USER.get(user) or 0
                slow_ts=_WS_SLOW_TS_BY_USER.get(user) or 0
                include_slow=bool(slow_ts and slow_ts!=published.get(user))
                slow=_ws_slow_for(user) if include_slow else {"username":user}
                payload={"type":"snapshot","u":user,"fast":fast,
                         "slow":slow,"slow_ts":slow_ts,"user_data":_ws_user_data(user),
                         "ts":fast_ts or int(_t.time())}
                encoded=json.dumps(payload,default=str)
                R.publish(RNS+"ws:snapshot",encoded)
                cache_key=RNS+"ws:last_snapshot:"+user
                # Keep a full slow frame for new connections. The next fast
                # delta advances current prices within one publish interval.
                if include_slow or not R.expire(cache_key,30):
                    R.setex(cache_key,30,encoded)
                if include_slow: published[user]=slow_ts
            except Exception:
                continue
    except Exception: pass
async def _ws_local_fanout():
    """扇出到本地 /ws/stream 连接(HUB 架构下通常为空; 保留向后兼容)。"""
    import time as _t
    dead=[]
    for ws in list(_WS_CLIENTS):
        try:
            u=getattr(ws,"_qh_user","")
            fast=_ws_fast_for(u)
            fast_ts=_WS_FAST_TS_BY_USER.get(u) or 0
            slow_ts=_WS_SLOW_TS_BY_USER.get(u) or 0
            include_slow=bool(slow_ts and slow_ts!=getattr(ws,"_qh_slow_ts",0))
            payload={"type":"snapshot","u":u,"fast":fast,
                     "slow":(_ws_slow_for(u) if include_slow else {"username":u}),"slow_ts":slow_ts,
                     "user_data":_ws_user_data(u) if u else {},"ts":fast_ts or int(_t.time())}
            await ws.send_text(json.dumps(payload,default=str))
            if include_slow: ws._qh_slow_ts=slow_ts
        except Exception: dead.append(ws)
    for ws in dead: _WS_CLIENTS.discard(ws)

async def _ws_tick_loop():
    """~0.3s: 仅刷报价+强平(轻, 继承重字段)并 PUBLISH → 点差达 2/s+。是唯一的发布者。
       与 heavy/slow 循环并发, 桥调用皆 await I/O, 事件循环交错执行, heavy 不阻塞本循环。"""
    import time as _t
    while True:
        try:
            if _ws_gate_open():
                users=_ws_recipient_users()
                if users:
                    frames=await _asyncio.gather(*(
                        _ws_build_ticks(_ws_fast_for(user),user) for user in users))
                    fast_ts=int(_t.time())
                    for user,frame in zip(users,frames):
                        _WS_FAST_BY_USER[user]=frame
                        _WS_FAST_TS_BY_USER[user]=fast_ts
                    # Legacy diagnostics retain one frame, but fanout never reads it.
                    _WS_SNAP["fast"]=frames[0]; _WS_SNAP["fast_ts"]=fast_ts
                    await _ws_refresh_user_meta(users)
                    _ws_publish()
                    await _ws_local_fanout()
        except Exception as e: print("ws_tick err",e)
        await _asyncio.sleep(0.3)
async def _ws_heavy_loop():
    """~1s: 刷双腿状态/持仓/账户/引擎态(桥调用最贵), 只更新 _WS_SNAP 不单独发布(tick 循环发)。"""
    while True:
        try:
            if _ws_gate_open():
                users=[u for u in _ws_recipient_users() if not _WS_FAST_BY_USER.get(u)]
                if users:
                    frames=await _asyncio.gather(*(_ws_build_fast(user) for user in users))
                    fast_ts=int(_t_conn.time())
                    for user,frame in zip(users,frames):
                        _WS_FAST_BY_USER[user]=frame
                        _WS_FAST_TS_BY_USER[user]=fast_ts
        except Exception as e: print("ws_heavy err",e)
        await _asyncio.sleep(1.0)
async def _ws_slow_loop():
    """~10s: 刷腿统计/日盈亏/配对/成交。"""
    import time as _t
    while True:
        try:
            if _ws_gate_open():
                users=set(_ws_recipient_users())
                if users:
                    names=sorted(users)
                    snapshots=await _asyncio.gather(*(_ws_build_slow(u) for u in names))
                    slow_ts=int(_t.time())
                    for u,slow in zip(names,snapshots):
                        _WS_SLOW_BY_USER[u]=slow
                        _WS_SLOW_TS_BY_USER[u]=slow_ts
                    primary=names[0]
                    _WS_SNAP["slow"]=_WS_SLOW_BY_USER[primary]
                    _WS_SNAP["slow_ts"]=slow_ts
        except Exception as e: print("ws_slow err",e)
        await _asyncio.sleep(10.0)
@app.on_event("startup")
async def _startup_ws():
    # 三档并发: tick(0.3s 发布) / heavy(1s) / slow(10s), 互不阻塞
    _asyncio.create_task(_ws_heavy_loop())
    _asyncio.create_task(_ws_slow_loop())
    _asyncio.create_task(_ws_tick_loop())

@app.websocket("/ws/stream")
async def ws_stream(ws: WebSocket):
    """实时推送: 客户端连上后发 {license_key} 认证, 之后每秒收 snapshot。替代 3s 轮询。"""
    await ws.accept()
    try:
        # 首帧认证(3s 超时)
        try:
            raw=await _asyncio.wait_for(ws.receive_text(), timeout=5)
            auth=json.loads(raw)
        except Exception:
            await ws.close(code=4001); return
        lk=auth.get("license_key","")
        c=db(); cur=c.cursor()
        cur.execute("SELECT username,status FROM users WHERE license_key=%s",(lk,)); row=cur.fetchone(); c.close()
        if not row or row[1] in ("banned","disabled"):
            await ws.send_text(json.dumps({"type":"error","msg":"auth failed"})); await ws.close(code=4003); return
        ws._qh_user=row[0]
        _WS_CLIENTS.add(ws)
        # 立即回一帧当前快照(免等下一个广播周期)
        try:
            slow=_WS_SLOW_BY_USER.get(row[0])
            if not slow:
                slow=await _ws_build_slow(row[0]); _WS_SLOW_BY_USER[row[0]]=slow
            fast=_ws_fast_for(row[0])
            if not fast.get("tick_main") and not fast.get("tick_hedge"):
                fast=await _ws_build_fast(row[0]); _WS_FAST_BY_USER[row[0]]=fast
                _WS_FAST_TS_BY_USER[row[0]]=int(_t_conn.time())
            await _ws_refresh_user_meta((row[0],))
            snap={"type":"snapshot","u":row[0],
                  "fast":fast,
                  "slow":slow,
                  "slow_ts":_WS_SLOW_TS_BY_USER.get(row[0],0),
                  "user_data":_ws_user_data(row[0]),"ts":_WS_FAST_TS_BY_USER.get(row[0],0)}
            await ws.send_text(json.dumps(snap,default=str))
            ws._qh_slow_ts=_WS_SLOW_TS_BY_USER.get(row[0],0)
        except Exception: pass
        # 保活: 阻塞收(客户端可发 ping), 断开即清理
        while True:
            try:
                await _asyncio.wait_for(ws.receive_text(), timeout=120)
            except _asyncio.TimeoutError:
                try: await ws.send_text(json.dumps({"type":"ping"}))
                except Exception: break
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        _WS_CLIENTS.discard(ws)









# ================= Api2Trade 接入 (P0 只读 + 配置管理 + 用户账户管理) =================
# 参考 https://docs.api2trade.com — MT4/MT5 免终端云接入(REST GET, x-api-key / Pro Basic Auth)。
# 账户模型: api2trade_config 1行=1份订阅 : N 个已注册 MT 账户(mt_accounts.api2trade_uuid)。
# 安全铁律: ① MT 密码仅注册时在途, 绝不落库/落日志 ② 订阅到期 fail-closed ③ Key 只回掩码
#          ④ Api2Trade 为 GET 传参(query 内含密码/key), 异常信息绝不回显 query。
import time as _t33

A2T_BASE = "https://api.api2trade.com"

def _a2t_mask(k):
    k=k or ""
    return (k[:4]+"****"+k[-4:]) if len(k)>=12 else ("****" if k else "")

def _a2t_cfg(cfg_id=None, need_active=True):
    """取订阅配置行(dict)。cfg_id 为空取第一条启用行。need_active 校验 enabled+未过期(fail-closed)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    if cfg_id:
        cur.execute("SELECT * FROM api2trade_config WHERE id=%s",(cfg_id,))
    else:
        cur.execute("SELECT * FROM api2trade_config WHERE enabled ORDER BY id LIMIT 1")
    row=cur.fetchone(); c.close()
    if not row: raise HTTPException(503,"Api2Trade 未配置(后台→系统管理→Api2Trade)")
    row=dict(row)
    if need_active:
        if not row.get("enabled"): raise HTTPException(503,"Api2Trade 配置已停用")
        exp=row.get("expires_at")
        if exp and exp < datetime.date.today():
            raise HTTPException(503,"Api2Trade 订阅已到期(%s), fail-closed 拒绝调用, 请续期后再试"%exp)
    return row

def _a2t_call(cfg, path, params=None, timeout=10):
    """同步调用 Api2Trade(FastAPI sync 端点在线程池执行)。返回 (json, latency_ms)。
       日志脱敏: 任何异常/错误信息绝不携带 query string(内含密码/key)。"""
    base=(cfg.get("base_url") or "").strip().rstrip("/") or A2T_BASE
    headers={}; auth=None
    if (cfg.get("plan") or "single")=="pro" and (cfg.get("basic_user") or "").strip():
        auth=(cfg["basic_user"].strip(), cfg.get("basic_pass") or "")
    else:
        headers["x-api-key"]=(cfg.get("api_key") or "").strip()
    t0=_t33.time()
    try:
        r=_httpx.get(base+path, params=(params or {}), headers=headers, auth=auth, timeout=timeout)
    except Exception as e:
        raise HTTPException(502,"Api2Trade 连接失败: %s (%s)"%(e.__class__.__name__,path))
    ms=int((_t33.time()-t0)*1000)
    if r.status_code==401: raise HTTPException(502,"Api2Trade 鉴权失败(401): Key/凭证无效或已失效")
    if r.status_code==402: raise HTTPException(502,"Api2Trade 套餐额度不足(402): 账户数/请求量超限, 请升级套餐")
    if r.status_code>=400:
        raise HTTPException(502,"Api2Trade %s 返回 %d: %s"%(path,r.status_code,(r.text or "")[:160]))
    try: return r.json(), ms
    except Exception: return {"raw":(r.text or "")[:160]}, ms

def _a2t_acclist(j):
    """/GetAccounts 响应容错解包 → list"""
    if isinstance(j,list): return j
    return (j or {}).get("accounts") or (j or {}).get("data") or []

# ---- 执行编排下沉 FRA(架构第4项): api 模式配对开/平仓改调 FRA /pair/* 一条指令 ----
# 收益: 两腿时序(串行/并发/腿间延迟)在法兰克福本地完成(对 A2T ~50ms/调用), 东京↔法兰克福只剩 1 个来回。
# 安全铁律: FRA 明确拒绝(4xx/连接未建立)→回退逐腿; **请求已发出但结果未知(读超时等)→绝不回退重发(防双开), fail-loud**。
def _pair_uuids():
    rows=(_A2T_LEG_CACHE.get("rows") or {})
    if not rows:
        _a2t_read_legs(); rows=(_A2T_LEG_CACHE.get("rows") or {})
    return ((rows.get("main") or {}).get("api2trade_uuid") or "", (rows.get("hedge") or {}).get("api2trade_uuid") or "")
async def _fra_pair(path, payload):
    from connector import _pooled, exec_agent_cfg
    base,key,port,_hp=exec_agent_cfg()   # sg-bridge(QH_SG_*) 优先, 回落 FRA
    r=await _pooled("bridge",25).post("%s:%s%s"%(base,port,path), json=payload, headers={"X-API-Key":key}, timeout=25)
    r.raise_for_status(); return r.json()
def _fra_pair_warn(what, e, username=None):
    _push_alert("warn","FRA配对%s通道不可用(%s), 已回退逐腿执行"%(what,e.__class__.__name__),username)
def _note_exec_flags(res, ctx, username=None):
    """执行结果里的 recovered/unknown 标志 → 跑马灯留痕(V1.1 M2 可观测性)。
       recovered=UNKNOWN已核实实际成交/已平并恢复结果(防超时双开); unknown=查真相未果, 必须人工核对。"""
    try:
        for leg,cn in (("main","主"),("hedge","对冲")):
            lr=(res or {}).get(leg) or {}
            if _leg_recovered_from_unknown(lr):
                _push_alert("warn","%s: %s腿响应超时但经真相源核实已成交, 已恢复结果(src=%s, 防超时双开)"%(ctx,cn,lr.get("src")),username)
            elif lr.get("unknown"):
                _push_alert("err","%s: %s腿结果未知且真相源核对未果, 请立即人工核对持仓!"%(ctx,cn),username)
            elif lr.get("unknown_resolved")=="not_filled":
                _push_alert("info","%s: %s腿超时, 经真相源核实未成交(安全判失败, 未双开)"%(ctx,cn),username)
    except Exception: pass

async def _reconcile_pair_open(direction, rid, truth, mode, exc):
    """FRA /pair/open 结果未知(读超时等) → 双腿经真相源(内网桥)按 comment#rid 核对(V1.1 M2)。
       双腿均有确定结论→合成配对结果(上层 naked/成功逻辑照常走); 任一腿查不清→None(升级 502 交人工)。"""
    from connector import verify_leg_open
    try:
        m=await verify_leg_open(truth.main, rid)
        h=(await verify_leg_open(truth.hedge, rid)) if getattr(truth,"hedge",None) else "NOFILL"
    except Exception:
        return None
    if m is None or h is None: return None
    def _leg(v, err):
        return v if isinstance(v,dict) else {"error":err,"unknown_resolved":"not_filled"}
    out={"direction":direction,"mode":mode,"request_id":rid,"via":"fra-pair-reconciled",
         "main":_leg(m,"FRA timeout(%s), 真相源核实未成交"%exc.__class__.__name__),
         "hedge":_leg(h,"FRA timeout(%s), 真相源核实未成交"%exc.__class__.__name__),
         "main_ok":isinstance(m,dict),"hedge_ok":isinstance(h,dict)}
    return out

async def _reconcile_pair_close(main_ticket, hedge_ticket, truth, exc):
    """FRA /pair/close 结果未知 → 有票腿经真相源查 ticket 是否消失(V1.1 M2)。
       双腿均有确定结论→合成结果; 任一腿无票/查不清→None(升级 502 交人工)。"""
    from connector import (
        verify_leg_closed, CLOSE_TRUTH_TRIES, CLOSE_TRUTH_POLL_SEC,
    )
    async def _leg(leg, ticket):
        if not ticket: return None
        t_leg=getattr(truth,leg,None)
        if t_leg is None: return {"skipped":"no %s leg"%leg}
        v=await verify_leg_closed(
            t_leg, ticket, tries=CLOSE_TRUTH_TRIES,
            delay=CLOSE_TRUTH_POLL_SEC)
        if v=="CLOSED": return {"ok":True,"recovered":True,"src":"positions","closed":[ticket]}
        if v=="OPEN":   return {"error":"FRA timeout(%s), 真相源核实未平"%exc.__class__.__name__,"unknown_resolved":"still_open"}
        return None
    try:
        m=await _leg("main", main_ticket); h=await _leg("hedge", hedge_ticket)
    except Exception:
        return None
    if m is None or h is None: return None
    return {"main":m,"hedge":h,"via":"fra-pair-reconciled"}

async def _exec_open_pair(direction, main_sym, hedge_sym, mv, hv, mode, speed, username=None,
                          main_dev=None, hedge_dev=None, command_id=None, pair_rid=None,
                          async_accept=False, phase_hook=None, dispatch_only=False,
                          burst_admission=False):
    return await _exec_open_pair_unlocked(
        direction,main_sym,hedge_sym,mv,hv,mode,speed,username=username,
        main_dev=main_dev,hedge_dev=hedge_dev,command_id=command_id,
        pair_rid=pair_rid,async_accept=async_accept,phase_hook=phase_hook,
        dispatch_only=dispatch_only,burst_admission=burst_admission)

async def _exec_open_pair_unlocked(direction, main_sym, hedge_sym, mv, hv, mode, speed, username=None, main_dev=None, hedge_dev=None, command_id=None, pair_rid=None, async_accept=False, phase_hook=None, dispatch_only=False, burst_admission=False):
    from connector import _gen_rid
    rid=pair_rid or _gen_rid()        # stable Pair id; legs append m/h end-to-end
    if command_id:
        try:
            _tr=get_tracer()
            _tr.update_field(command_id,"pair_request_id",rid)
            _tr.update_field(command_id,"main_request_id",rid+"m")
            _tr.update_field(command_id,"hedge_request_id",rid+"h")
        except Exception: pass
    truth=_user_exec_conn(username)   # P4b: 真相源=用户自己的执行桥(UNKNOWN 查真相须查落单的那个桥)
    res=None
    if _active_mode()=="api":
        mu,hu=_pair_uuids_for(username)   # 多租户: 该用户的执行 UUID(缺→全局)
        _sg=bool(os.environ.get("QH_SG_AGENT_URL","").strip())   # sg-bridge=会话制, 不需要云UUID
        if _sg or (mu and hu):
            try:
                res=await _fra_pair("/pair/open",{"direction":direction,"main_symbol":main_sym,"hedge_symbol":hedge_sym,
                        "main_vol":mv,"hedge_vol":hv,"mode":mode,"speed":speed,"main_uuid":mu,"hedge_uuid":hu,
                        "comment_tag":rid})
            except (_httpx.HTTPStatusError,_httpx.ConnectError,_httpx.ConnectTimeout) as e:
                _fra_pair_warn("开仓",e,username); res=None   # 明确未执行(4xx/连接未建立)→安全回退逐腿
            except Exception as e:
                # UNKNOWN(读超时等, 指令可能已执行) → 经真相源按 comment#rid 核对双腿, 不再直接 502(V1.1 M2)
                res=await _reconcile_pair_open(direction, rid, truth, mode, e)
                if res is None:
                    _push_alert("err","FRA配对开仓结果未知(%s)且真相源核对未果, 请立即人工核对双腿持仓!"%e.__class__.__name__,username)
                    raise HTTPException(502,"FRA 配对开仓结果未知(%s)且真相源核对未果: 请人工核对持仓, 勿立即重试"%e.__class__.__name__)
    if res is None:
        # P0-A b07: Bridge发送
        if command_id:
            try:
                _tr=get_tracer()
                _tr.record_timestamp(command_id, TraceTimestamp.BRIDGE_SENT_MAIN)
                _tr.record_timestamp(command_id, TraceTimestamp.BRIDGE_SENT_HEDGE)
            except Exception: pass
        res=await _user_exec_conn(username).open_pair(
            direction, main_sym, hedge_sym, mv, hv, mode=mode, speed=speed,
            truth=truth, rid=rid, main_dev=main_dev, hedge_dev=hedge_dev,
            ordered_ack=bool(async_accept or _subsecond_user(username)),phase_hook=phase_hook,
            dispatch_only=dispatch_only,burst_admission=burst_admission,
        )
        # P0-A b08: Bridge返回
        if command_id:
            try:
                _trace_pair_execution(_tr,command_id,res,mark_ack=True)
                _tr.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_MAIN)
                _tr.record_timestamp(command_id, TraceTimestamp.BRIDGE_RECEIVED_HEDGE)
                # 记录 ticket 到 tracer
                _m=res.get('main') or {}; _h=res.get('hedge') or {}
                if _m.get('order'): _tr.update_field(command_id,'main_ticket',str(_m['order']))
                if _h.get('order'): _tr.update_field(command_id,'hedge_ticket',str(_h['order']))
            except Exception: pass
    _entry_capacity_latch_result(username,res,"broker_result")
    _note_exec_flags(res,"开仓",username)
    return res
async def _exec_close_pair(main_sym, hedge_sym, mside, hside, mv, hv, mode, speed,
                           main_ticket=None, hedge_ticket=None, username=None,
                           command_id=None, pair_rid=None, async_accept=False,
                           burst_admission=False):
    return await _exec_close_pair_unlocked(
        main_sym,hedge_sym,mside,hside,mv,hv,mode,speed,
        main_ticket=main_ticket,hedge_ticket=hedge_ticket,username=username,
        command_id=command_id,pair_rid=pair_rid,async_accept=async_accept,
        burst_admission=burst_admission)

async def _exec_close_pair_unlocked(main_sym, hedge_sym, mside, hside, mv, hv, mode, speed, main_ticket=None, hedge_ticket=None, username=None, command_id=None, pair_rid=None, async_accept=False, burst_admission=False):
    from connector import _gen_rid
    rid=pair_rid or _gen_rid()
    truth=_user_exec_conn(username)   # P4b: 真相源=用户自己的执行桥
    res=None
    if _active_mode()=="api":
        mu,hu=_pair_uuids_for(username)   # 多租户: 该用户的执行 UUID(缺→全局)
        _sg=bool(os.environ.get("QH_SG_AGENT_URL","").strip())   # sg-bridge=会话制, 不需要云UUID
        if _sg or (mu and hu):
            try:
                _pl={"main_symbol":main_sym,"hedge_symbol":hedge_sym,
                     "main_side":mside,"hedge_side":hside,"main_vol":mv,"hedge_vol":hv,
                     "mode":mode,"speed":speed,"main_ticket":main_ticket,"hedge_ticket":hedge_ticket,
                     "main_uuid":mu,"hedge_uuid":hu}
                res=await _fra_pair("/pair/close",{k:v for k,v in _pl.items() if v is not None})
            except (_httpx.HTTPStatusError,_httpx.ConnectError,_httpx.ConnectTimeout) as e:
                _fra_pair_warn("平仓",e,username); res=None
            except Exception as e:
                # UNKNOWN → 有票腿经真相源查 ticket 消失即已平(V1.1 M2), 双腿均有结论才接受
                res=await _reconcile_pair_close(main_ticket, hedge_ticket, truth, e)
                if res is None:
                    _push_alert("err","FRA配对平仓结果未知(%s)且真相源核对未果, 请立即人工核对双腿持仓!"%e.__class__.__name__,username)
                    raise HTTPException(502,"FRA 配对平仓结果未知(%s)且真相源核对未果: 请人工核对持仓, 勿立即重试"%e.__class__.__name__)
    if res is None:
        res=await _user_exec_conn(username).close_pair(main_sym, hedge_sym, mside, hside, mv, hv, mode=mode, speed=speed, main_ticket=main_ticket, hedge_ticket=hedge_ticket, truth=truth, rid=rid, ordered_ack=async_accept, burst_admission=burst_admission)
    if command_id:
        try:
            _tr=get_tracer()
            _trace_pair_execution(_tr,command_id,res,mark_ack=True)
            _tr.update_field(command_id,"pair_request_id",rid)
            _tr.update_field(command_id,"main_request_id",rid+"m")
            _tr.update_field(command_id,"hedge_request_id",rid+"h")
        except Exception: pass
    _note_exec_flags(res,"平仓",username)
    return res

def _resolved_leg_ok(res,leg):
    lr=(res or {}).get(leg) or {}
    return bool((res or {}).get(leg+"_ok") or (lr.get("ok") and not lr.get("pending") and not lr.get("unknown") and "error" not in lr))

def _open_compensation_succeeded(result):
    compensation=(result or {}).get("compensation") or {}
    durable_phase_ok=(not (result or {}).get("saga_durable") or
                      ((result or {}).get("saga_phase")=="COMPENSATION_DONE" and
                       not (result or {}).get("saga_unknown")))
    return bool(durable_phase_ok and (result or {}).get("compensated") and
                compensation.get("ok") and compensation.get("closed") and
                compensation.get("ticket"))

def _terminal_leg_reason(result, leg):
    lr=(result or {}).get(leg) or {}
    if _resolved_leg_ok(result,leg): return "confirmed"
    if lr.get("truth_unavailable") or lr.get("unknown"): return "truth_unavailable"
    return str(lr.get("error") or lr.get("detail") or lr.get("retcode") or "not_filled")[:180]

def _terminal_failure_reason(result, operation):
    failed=[]
    for leg in ("main","hedge"):
        if not _resolved_leg_ok(result,leg):
            failed.append("%s=%s"%(leg,_terminal_leg_reason(result,leg)))
    return "%s:%s"%(operation,";".join(failed) or "unconfirmed")

def _open_truth_ticket_candidates(*results):
    tickets=set()
    for result in results:
        if not isinstance(result,dict): continue
        for key in ("order","ticket","position","deal"):
            value=result.get(key)
            if value not in (None,"",0,"0"): tickets.add(str(value))
    return tickets

async def _open_leg_terminal_truth(conn, leg, initial, final):
    """Return FILLED/NOT_FILLED/UNKNOWN from the user's broker truth source."""
    import hashlib as _hashlib
    from connector import verify_leg_open
    leg_obj=getattr(conn,leg,None)
    if leg_obj is None: return "UNKNOWN",None
    initial_leg=(initial or {}).get(leg) or {}; final_leg=(final or {}).get(leg) or {}
    for leg_result in (final_leg,initial_leg):
        if (leg_result.get("truth_confirmed")=="not_filled" and
                (leg_result.get("src")=="order-status" or leg_result.get("not_sent"))):
            return "NOT_FILLED",None
    tickets=_open_truth_ticket_candidates(initial_leg,final_leg)
    rid=(final or {}).get("request_id") or (initial or {}).get("request_id")
    request_id=final_leg.get("request_id") or initial_leg.get("request_id") or ((rid or "")+leg[0])
    otoken=("Q"+_hashlib.sha1(str(request_id).encode()).hexdigest()[:9]) if request_id else None
    try:
        raw=await leg_obj.positions(); rows=_poslist(raw)
        for row in rows:
            if not isinstance(row,dict): continue
            ticket=row.get("ticket")
            comment=str(row.get("comment") or "")
            exact=ticket is not None and str(ticket) in tickets
            tagged=bool(rid) and (("#"+str(rid)) in comment or (otoken and otoken in comment))
            if exact or tagged:
                return "FILLED",{"ok":True,"success":True,"recovered":True,
                    "src":"positions-terminal-truth","order":ticket,"ticket":ticket,
                    "volume":row.get("volume"),"price":row.get("price_open") or row.get("price"),
                    "request_id":request_id,"op":"open"}
    except Exception:
        pass
    if not rid: return "UNKNOWN",None
    try:
        recovered=await verify_leg_open(leg_obj,rid,tries=2,delay=0.25,
                                        extra_tags=[otoken] if otoken else None)
    except Exception:
        recovered=None
    if isinstance(recovered,dict):
        recovered=dict(recovered); recovered.update({"request_id":request_id,"op":"open"})
        return "FILLED",recovered
    # Agent acceptance can lead the broker position/history snapshots. Empty
    # reads alone never prove that an open was rejected.
    if recovered=="NOFILL": return "UNKNOWN",None
    return "UNKNOWN",None

async def _reconcile_pending_open_truth(conn, initial, final):
    """Broker position truth overrides an Agent terminal failure for each open leg."""
    final=final if isinstance(final,dict) else dict(initial or {})
    checks=[]; legs=[]
    for leg in ("main","hedge"):
        if not _resolved_leg_ok(final,leg):
            legs.append(leg); checks.append(_open_leg_terminal_truth(conn,leg,initial,final))
    outcomes=await _aio.gather(*checks,return_exceptions=True) if checks else []
    reconciled=[]
    for leg,outcome in zip(legs,outcomes):
        state,payload=(outcome if isinstance(outcome,tuple) else ("UNKNOWN",None))
        if state=="FILLED":
            final[leg]=payload; final[leg+"_ok"]=True; reconciled.append(leg)
        elif state=="NOT_FILLED":
            lr=dict(final.get(leg) or {}); lr.pop("pending",None); lr.pop("unknown",None)
            lr["truth_confirmed"]="not_filled"; final[leg]=lr; final[leg+"_ok"]=False
        else:
            lr=dict(final.get(leg) or {}); lr.pop("pending",None); lr["unknown"]=True
            lr["truth_unavailable"]=True; final[leg]=lr; final[leg+"_ok"]=False
    final["truth_reconciled"]={"operation":"open","recovered_legs":reconciled,
                                "authoritative":not any(_terminal_leg_reason(final,x)=="truth_unavailable" for x in legs)}
    return final

async def _reconcile_pending_close_truth(conn, initial, final, tickets):
    """For closes, disappearance of each exact ticket is the terminal truth."""
    from connector import verify_leg_closed
    final=final if isinstance(final,dict) else dict(initial or {})
    checks=[]; legs=[]; agent_terminal=[]
    target_legs=[leg for leg in ("main","hedge") if (tickets or {}).get(leg) or ((initial or {}).get("tickets") or {}).get(leg)]
    for leg in target_legs:
        ticket=(tickets or {}).get(leg) or ((initial or {}).get("tickets") or {}).get(leg)
        lr=final.get(leg) if isinstance(final.get(leg),dict) else {}
        observed=lr.get("ticket") or lr.get("order") or lr.get("position")
        pair_rid=str(final.get("request_id") or
                     (initial or {}).get("request_id") or "")
        expected_rid=(pair_rid+leg[0]) if pair_rid else ""
        try:
            exact_ticket=bool(ticket and observed and int(ticket)==int(observed))
        except (TypeError,ValueError):
            exact_ticket=False
        exact_request=(not expected_rid.strip() or
                       str(lr.get("request_id") or "")==expected_rid)
        src=str(lr.get("src") or "").lower()
        exact_idempotent_replay=bool(
            src=="idempotent-terminal-replay" and
            lr.get("idempotency_hit") is True and
            bool(expected_rid.strip()) and exact_request and
            bool(lr.get("success") or lr.get("ok")) and
            not _trade_bool(lr.get("pending")) and
            not _trade_bool(lr.get("unknown")) and
            not _trade_bool(lr.get("partial")) and
            not lr.get("error") and
            str(lr.get("certainty") or "").upper()!="UNKNOWN")
        if (_resolved_leg_ok(final,leg) and
                (src=="order-status" or exact_idempotent_replay) and
                exact_ticket and exact_request):
            # Agent DONE is written only after the exact-ticket broker close
            # returns success. A second two-snapshot disappearance check adds
            # UI latency but no stronger execution identity.
            agent_terminal.append(leg)
            continue
        leg_obj=getattr(conn,leg,None)
        legs.append((leg,ticket))
        if leg_obj is None or not ticket:
            checks.append(None)
        else:
            checks.append(verify_leg_closed(leg_obj,ticket,tries=2,delay=0.10))
    async def _await(value): return await value if value is not None else None
    outcomes=await _aio.gather(*(_await(value) for value in checks),return_exceptions=True) if checks else []
    reconciled=[]
    for (leg,ticket),outcome in zip(legs,outcomes):
        if outcome=="CLOSED":
            lr=dict(final.get(leg) or {})
            lr.update({"ok":True,"success":True,"recovered":True,
                "truth_confirmed":"closed","unknown_resolved":"closed",
                "ticket":ticket,"closed":[ticket],"op":"close"})
            lr.setdefault("src","positions-terminal-truth")
            lr.pop("pending",None); lr.pop("unknown",None); lr.pop("error",None)
            final[leg]=lr
            final[leg+"_ok"]=True; reconciled.append(leg)
        elif outcome=="OPEN":
            lr=dict(final.get(leg) or {})
            accepted_pending=bool(
                (lr.get("pending") or lr.get("unknown")) and
                (_trade_bool(final.get("saga_durable")) or
                 _trade_bool(final.get("ordered_ack"))))
            lr.pop("unknown",None)
            if accepted_pending:
                lr.update({"accepted":True,"pending":True,
                           "truth_observed":"still_open",
                           "ticket":ticket,"op":"close"})
                lr.pop("error",None); lr.pop("truth_confirmed",None)
            elif _resolved_leg_ok(final,leg):
                lr.pop("pending",None)
                lr.update({"error":"Agent DONE conflicts with exact ticket still open",
                           "unknown":True,"truth_conflict":"agent_done_ticket_open",
                           "ticket":ticket,"op":"close"})
            else:
                lr.pop("pending",None)
                lr.update({"error":"exact ticket is still open","truth_confirmed":"still_open",
                           "ticket":ticket,"op":"close"})
            final[leg]=lr; final[leg+"_ok"]=False
        else:
            lr=dict(final.get(leg) or {}); lr.pop("pending",None); lr["unknown"]=True
            lr["truth_unavailable"]=True
            if ticket: lr.setdefault("ticket",ticket)
            final[leg]=lr; final[leg+"_ok"]=False
    final["truth_reconciled"]={"operation":"close","recovered_legs":reconciled,
        "agent_terminal_legs":agent_terminal,
        "authoritative":(
            len(agent_terminal)+len(outcomes)==len(target_legs) and
            all(outcome in ("CLOSED","OPEN") for outcome in outcomes) and
            not any(bool((final.get(leg) or {}).get("truth_conflict"))
                    for leg,_ in legs))}
    return final


def _close_review_finalizer_lease_key(job_id):
    return RNS+"tradeq:close-review-recovery:"+str(job_id or "")


def _claim_close_review_finalizer_lease(job_id):
    if not job_id:
        return None
    token=_TRADE_QUEUE_OWNER+":"+os.urandom(8).hex()
    try:
        claimed=bool(R.set(_close_review_finalizer_lease_key(job_id),token,
                           nx=True,ex=_CLOSE_REVIEW_FINALIZER_LEASE_TTL))
    except Exception:
        claimed=False
    return token if claimed else None


def _release_close_review_finalizer_lease(job_id, token):
    if not job_id or not token:
        return False
    try:
        return bool(R.eval("""
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
        """,1,_close_review_finalizer_lease_key(job_id),token))
    except Exception:
        return False


def _auto_single_leg_close_lease_key(username, symbol, slot, command_id, leg, ticket):
    return RNS+"tradeq:auto-single-close:%s:%s:%d:%s:%s:%s"%(
        (username or "").strip(),symbol,int(slot),str(command_id or ""),leg,str(ticket))


def _claim_auto_single_leg_close_lease(username, symbol, slot, command_id, leg, ticket):
    token=_TRADE_QUEUE_OWNER+":"+os.urandom(8).hex()
    key=_auto_single_leg_close_lease_key(
        username,symbol,slot,command_id,leg,ticket)
    try:
        claimed=bool(R.set(key,token,nx=True,ex=_AUTO_SINGLE_LEG_CLOSE_LEASE_TTL))
    except Exception:
        claimed=False
    return (key,token) if claimed else (key,None)


def _release_auto_single_leg_close_lease(key, token):
    if not key or not token:
        return False
    try:
        return bool(R.eval("""
            if redis.call('get', KEYS[1]) == ARGV[1] then
                return redis.call('del', KEYS[1])
            end
            return 0
        """,1,key,token))
    except Exception:
        return False


def _authoritative_close_pair_survivor(final, ctx):
    """Return the one exact still-open ticket that is safe to auto-close."""
    final=final if isinstance(final,dict) else {}
    ctx=ctx if isinstance(ctx,dict) else {}
    truth=final.get("truth_reconciled")
    if (not isinstance(truth,dict) or truth.get("operation")!="close" or
            truth.get("authoritative") is not True):
        return None
    resolved={leg:_resolved_leg_ok(final,leg) for leg in ("main","hedge")}
    if resolved["main"]==resolved["hedge"]:
        return None
    closed_leg="main" if resolved["main"] else "hedge"
    live_leg="hedge" if closed_leg=="main" else "main"
    live_result=final.get(live_leg) if isinstance(final.get(live_leg),dict) else {}
    if str(live_result.get("truth_confirmed") or "").lower()!="still_open":
        return None
    slot=_exact_positive_int(ctx.get("slot"))
    ticket=_exact_positive_int(ctx.get(live_leg+"_ticket"))
    closed_ticket=_exact_positive_int(ctx.get(closed_leg+"_ticket"))
    result_ticket=_exact_positive_int(live_result.get("ticket"))
    ticket_map=final.get("tickets") if isinstance(final.get("tickets"),dict) else {}
    mapped_ticket=_exact_positive_int(ticket_map.get(live_leg))
    if (slot is None or ticket is None or closed_ticket is None or
            ticket==closed_ticket or result_ticket not in (None,ticket) or
            mapped_ticket not in (None,ticket)):
        return None
    username=str(ctx.get("username") or "").strip()
    symbol=str(ctx.get("symbol") or "XAUUSD")
    if not username:
        return None
    try:
        owner=R.hgetall(_slotowner_key(live_leg,symbol,username)) or {}
        display=R.hgetall(_slotmap_key(live_leg,symbol,username)) or {}
        other_owner=R.hgetall(_slotowner_key(closed_leg,symbol,username)) or {}
        owned_here=[_exact_positive_int(raw_ticket) for raw_ticket,raw_slot in owner.items()
                    if _exact_positive_int(raw_slot)==slot]
        other_here=[raw_ticket for raw_ticket,raw_slot in other_owner.items()
                    if _exact_positive_int(raw_slot)==slot]
        if (owned_here!=[ticket] or other_here or
                _exact_positive_int(owner.get(str(ticket)))!=slot or
                _exact_positive_int(display.get(str(ticket)))!=slot):
            return None
    except Exception:
        return None
    return {"leg":live_leg,"closed_leg":closed_leg,"ticket":ticket,
            "closed_ticket":closed_ticket,"slot":slot,"username":username,
            "symbol":symbol}


def _record_auto_single_leg_close_attempt(ctx, command_id, target, reason, request_id):
    payload={"leg":target.get("leg"),"ticket":target.get("ticket"),
             "slot":target.get("slot"),"reason":str(reason or "")[:180],
             "request_id":request_id,"attempted_at":_dt.datetime.utcnow().isoformat()}
    try:
        tracer=get_tracer()
        tracer.update_field(command_id,"auto_single_leg_close",payload)
    except Exception:
        pass
    job_id=str((ctx or {}).get("queue_job_id") or "")
    if not job_id:
        return
    try:
        job=TRADE_QUEUE.get_job(job_id) or {}
        if str(job.get("state") or "").upper() in (
                "UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
            TRADE_QUEUE.update_review_job(job_id,auto_single_leg_close=payload)
    except Exception:
        pass


async def _auto_converge_close_pair_single_leg(command_id, final, ctx):
    """Close only an authoritatively confirmed surviving exact ticket."""
    target=_authoritative_close_pair_survivor(final,ctx)
    if not target:
        return final,False,"auto_close_not_authoritative"
    leg=target["leg"]; ticket=target["ticket"]
    lease_key,lease_token=_claim_auto_single_leg_close_lease(
        target["username"],target["symbol"],target["slot"],command_id,leg,ticket)
    if lease_token is None:
        return final,False,"auto_close_already_running"
    request_id="%s-a%s%s"%(
        str((ctx or {}).get("pair_rid") or command_id or "qhclose")[:40],
        "m" if leg=="main" else "h",os.urandom(4).hex())
    try:
        side=str((ctx or {}).get(leg+"_side") or "")
        if side not in ("buy","sell"):
            _record_auto_single_leg_close_attempt(
                ctx,command_id,target,"auto_close_side_missing",request_id)
            return final,False,"auto_close_side_missing"
        symbol=target["symbol"]
        if leg=="hedge":
            symbol=str((ctx or {}).get("hedge_symbol") or "")
            if not symbol:
                try:
                    template=_load_tmpl(target["username"],target["symbol"]) or {}
                    symbol=ENG.map_hedge_symbol(
                        target["symbol"],template.get("hedge_symbol")) or target["symbol"]
                except Exception:
                    symbol=target["symbol"]
        volume=(ctx or {}).get(leg+"_vol") or None
        conn=_user_exec_conn(target["username"])
        try:
            retry=await conn.close_leg(
                leg,symbol,side,volume,ticket=ticket,rid=request_id,
                ordered_ack=False)
        except Exception as ex:
            retry={"main":None,"hedge":None,"main_ok":False,"hedge_ok":False,
                   "request_id":request_id,"op":"close","tickets":{leg:ticket},
                   leg:{"error":str(ex),"unknown":True,"ticket":ticket,
                        "request_id":request_id+("m" if leg=="main" else "h"),
                        "op":"close"}}
        try:
            verified=await _aio.wait_for(
                _reconcile_pending_close_truth(conn,retry,retry,{leg:ticket}),
                timeout=_pending_finalizer_budget(ctx))
        except Exception as ex:
            _record_auto_single_leg_close_attempt(
                ctx,command_id,target,"auto_close_truth_unavailable:%s"%ex.__class__.__name__,
                request_id)
            return final,False,"auto_close_truth_unavailable"
        if not _resolved_leg_ok(verified,leg):
            reason=_terminal_leg_reason(verified,leg)
            _record_auto_single_leg_close_attempt(ctx,command_id,target,reason,request_id)
            merged=dict(final or {})
            merged[leg]=verified.get(leg); merged[leg+"_ok"]=False
            merged["auto_single_leg_close"]={"request_id":request_id,"leg":leg,
                "ticket":ticket,"closed":False,"reason":reason}
            return merged,False,reason
        merged=dict(final or {})
        merged[leg]=verified.get(leg); merged[leg+"_ok"]=True
        merged.setdefault("tickets",{})[leg]=ticket
        merged["truth_reconciled"]={"operation":"close",
            "recovered_legs":["main","hedge"],"authoritative":True}
        merged["auto_single_leg_close"]={"request_id":request_id,"leg":leg,
            "ticket":ticket,"closed":True,"reason":"exact_ticket_closed"}
        _record_auto_single_leg_close_attempt(
            ctx,command_id,target,"exact_ticket_closed",request_id)
        return merged,True,"exact_ticket_closed"
    finally:
        _release_auto_single_leg_close_lease(lease_key,lease_token)


async def _pending_finalizer_deadline_call(deadline, factory):
    """Run resolver and broker-truth reads inside one monotonic UI budget."""
    remaining=max(0.0,float(deadline)-time.monotonic())
    if remaining<=0:
        raise _aio.TimeoutError("pending finalizer truth budget exhausted")
    return await _aio.wait_for(factory(remaining),timeout=remaining)

async def _finalize_pending_open(command_id,res,ctx):
    """Serialize initial and recovery finalizers for the same durable saga."""
    queue_job_id=str((ctx or {}).get("queue_job_id") or "")
    if not queue_job_id:
        await _finalize_pending_open_locked(command_id,res,ctx)
        return True
    lease_token=_claim_open_saga_finalizer_lease(queue_job_id)
    if lease_token is None:
        # A competing finalizer owns the saga. Do not touch tracer, queue, or
        # phase snapshots; its recovery loop will retry after the lease frees.
        return False
    try:
        await _finalize_pending_open_locked(command_id,res,ctx)
        return True
    finally:
        _release_open_saga_finalizer_lease(queue_job_id,lease_token)


async def _finalize_pending_open_locked(command_id,res,ctx):
    tracer=get_tracer()
    tracer.update_field(command_id,"pending_context",ctx)
    queue_state="UNKNOWN"; final=None; terminal_reason=""
    durable_pending=False
    truth_budget=_pending_finalizer_budget(ctx)
    truth_deadline=time.monotonic()+truth_budget
    resolver_deadline=truth_deadline-_pending_open_truth_reserve(truth_budget)
    try:
        conn=_user_exec_conn(ctx["username"])
        try:
            resolver=conn.resolve_pair_pending
            hook=_trade_queue_saga_phase_hook(ctx.get("queue_job_id"),ctx)
            parameters=_inspect.signature(resolver).parameters
            kwargs={}
            if hook is not None and ("phase_hook" in parameters or any(
                    value.kind==_inspect.Parameter.VAR_KEYWORD
                    for value in parameters.values())):
                kwargs["phase_hook"]=hook
            final=await _pending_finalizer_deadline_call(
                resolver_deadline,
                lambda remaining: resolver(res,timeout=remaining,**kwargs),
            )
        except Exception:
            # The resolver is advisory.  A broker-visible fill remains the
            # terminal truth even when the Agent status probe itself fails.
            final=res
        try:
            final=await _pending_finalizer_deadline_call(
                truth_deadline,
                lambda _remaining: _reconcile_pending_open_truth(conn,res,final),
            )
        except Exception:
            final=final if isinstance(final,dict) else dict(res or {})
        _entry_capacity_latch_result(ctx["username"],final,"broker_terminal")
        mok=_resolved_leg_ok(final,"main"); hok=_resolved_leg_ok(final,"hedge")
        _trace_pair_execution(tracer,command_id,final,mark_ack=True)
        trace_fields={"final_result":final}
        for leg in ("main","hedge"):
            lr=(final.get(leg) or {})
            tk=lr.get("order") or lr.get("deal") or lr.get("ticket")
            if tk: trace_fields[leg+"_ticket"]=str(tk)
        _update_trace_fields(tracer,command_id,trace_fields)
        if _open_compensation_succeeded(final):
            terminal_reason="second_leg_failed_compensated"
            tracer.update_status(command_id,CommandStatus.FAILED)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            _audit(ctx["username"],ctx["actor"],"open_pair",final,False,
                   "FAILED_ROLLED_BACK:exact_ticket_compensation")
            queue_state="FAILED"
        elif mok and hok:
            ledger_entry={
                "q":ctx["hedge_vol"],"m":ctx["main_vol"],
                "s":ctx["entry_spread"] if ctx["entry_spread"] is not None else 0,
                "ts":_dt.datetime.utcnow().isoformat(),"ladder":ctx["slot"]}
            # Ledger truth is part of the durable open commit.  If Redis cannot
            # prove the idempotent append, stop in UNKNOWN and retain the
            # capacity hold instead of publishing ownership/completion.
            if not _open_ledger_commit_once(
                    command_id,ctx["ledger_key"],ledger_entry,tracer):
                terminal_reason="open_ledger_commit_failed"
                tracer.update_status(command_id,CommandStatus.UNKNOWN)
                tracer.update_field(command_id,"failure_reason",terminal_reason)
                tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
                queue_state="UNKNOWN"
            else:
                _slip_snap(ctx["direction"],"open",_cap_at(ctx["main_tick"],ctx["hedge_tick"],ctx["direction"],"open"),
                           ctx["slot"],_leg_tickets(final.get("main")),thr=ctx["threshold"])
                owner_saved=await _reserve_slot_with_recovery(
                    ctx["symbol"],final,ctx["slot"],ctx["username"])
                _remember_open_positions(ctx["symbol"],ctx.get("hedge_symbol"),ctx["direction"],final,
                                         ctx["slot"],ctx["username"],ctx["main_vol"],ctx["hedge_vol"])
                if owner_saved:
                    _audit(ctx["username"],ctx["actor"],"open_pair",{"res":final,"slot":ctx["slot"]},False,"opened:async")
                    _record_trace_timestamp_once(
                        tracer,command_id,TraceTimestamp.PAIR_JOIN_DONE)
                    _record_trace_timestamp_once(
                        tracer,command_id,TraceTimestamp.LEDGER_COMMITTED)
                    tracer.update_status(command_id,CommandStatus.COMPLETED)
                    queue_state="COMPLETED"
                else:
                    terminal_reason="slotowner_persist_failed_after_fill"
                    _audit(ctx["username"],ctx["actor"],"open_pair",{"res":final,"slot":ctx["slot"]},False,
                           "MANUAL_REVIEW:slotowner_persist_failed")
                    tracer.update_status(command_id,CommandStatus.MANUAL_REVIEW)
                    tracer.update_field(command_id,"failure_reason",terminal_reason)
                    queue_state="MANUAL_REVIEW"
        elif _pair_pending(final) or any(bool((final.get(x) or {}).get("unknown")) for x in ("main","hedge")):
            terminal_reason=_terminal_failure_reason(final,"open_unknown")
            tracer.update_status(command_id,CommandStatus.UNKNOWN)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
            queue_state="UNKNOWN"
        elif mok != hok:
            terminal_reason=_terminal_failure_reason(final,"open_single_leg")
            _halt_auto_entry(ctx["username"],"single_leg_exposed",{
                "slot":ctx.get("slot"),"symbol":ctx.get("symbol"),
                "command_id":command_id,"res":final})
            tracer.update_status(command_id,CommandStatus.SINGLE_LEG_EXPOSED)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            _push_alert("err","亚秒开仓异步终态出现单腿暴露, command_id=%s, 请立即人工核对"%command_id,ctx["username"])
            _audit(ctx["username"],ctx["actor"],"open_pair",final,False,"NAKED_RISK_async")
            queue_state="SINGLE_LEG_EXPOSED"
        elif _open_pair_explicit_no_fill(final):
            terminal_reason=_terminal_failure_reason(final,"open_failed")
            tracer.update_status(command_id,CommandStatus.FAILED)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            queue_state="FAILED"
        else:
            terminal_reason=_terminal_failure_reason(final,"open_unresolved")
            tracer.update_status(command_id,CommandStatus.UNKNOWN)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
            queue_state="UNKNOWN"
    except Exception as ex:
        terminal_reason="async_finalize:%s"%ex.__class__.__name__
        tracer.update_status(command_id,CommandStatus.UNKNOWN)
        tracer.update_field(command_id,"failure_reason",terminal_reason)
        tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
        queue_state="UNKNOWN"
    finally:
        # A durable burst ACK can legitimately outlive the first truth budget
        # while the account-serial MT5 worker drains prior slots. Keep the job
        # in its in-flight saga state and let the recovery loop continue; do
        # not publish a red manual-review latch for this normal pending case.
        durable_pending=bool(
            queue_state=="UNKNOWN" and
            _trade_bool((final or res or {}).get("saga_durable")) and
            _pair_pending(final or res or {}))
        if durable_pending:
            tracer.update_status(command_id,CommandStatus.SUBMITTED)
            tracer.update_field(command_id,"failure_reason","saga_pending_recovery")
        queue_job_id=ctx.get("queue_job_id")
        handled=False
        if queue_job_id:
            current=TRADE_QUEUE.get_job(queue_job_id) or {}
            current_state=str(current.get("state") or "").upper()
            if (current_state in ("SINGLE_LEG_EXPOSED","MANUAL_REVIEW") and
                    not _open_saga_job(current)):
                # Genuine terminal exposure requires operator resolution. A
                # durable saga that is still retryable may promote itself once
                # the same Agent request ids prove both fills.
                queue_state=current_state
                terminal_reason=terminal_reason or "manual_resolution_required"
                tracer.update_status(command_id,getattr(CommandStatus,queue_state))
                tracer.update_field(command_id,"failure_reason",terminal_reason)
            if queue_state in ("COMPLETED","FAILED","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                command=tracer.get_command(command_id) or {
                    "type":CommandType.OPEN_PAIR.value,"username":ctx.get("username"),
                    "symbol":ctx.get("symbol"),"slot":ctx.get("slot"),
                    "direction":ctx.get("direction"),"queue_job_id":queue_job_id,
                }
                evidence=dict(final or res or {})
                evidence["main_ok"]=_resolved_leg_ok(evidence,"main")
                evidence["hedge_ok"]=_resolved_leg_ok(evidence,"hedge")
                if terminal_reason: evidence["reason"]=terminal_reason
                handled=await _on_reconciled_open(
                    command_id,command,evidence,queue_state)
                if not handled and queue_state in ("COMPLETED","FAILED"):
                    queue_state="MANUAL_REVIEW"
                    terminal_reason="durable_open_cleanup_failed:%s"%queue_state.lower()
                    tracer.update_status(command_id,CommandStatus.MANUAL_REVIEW)
                    tracer.update_field(command_id,"failure_reason",terminal_reason)
        if not handled:
            if durable_pending:
                _clear_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],command_id)
                hold_job=TRADE_QUEUE.get_job(queue_job_id) if queue_job_id else None
                if not _ensure_entry_capacity_hold(
                        ctx["username"],ctx.get("capacity_reservation_id"),hold_job):
                    _record_entry_capacity_hold_failure(
                        ctx["username"],ctx.get("capacity_reservation_id"),
                        "async_finalize_hold_failed")
                if queue_job_id:
                    current=TRADE_QUEUE.get_job(queue_job_id) or {}
                    current_state=str(current.get("state") or "").upper()
                    fields={"result":final or res,"context":ctx,
                            "saga_durable":True,
                            "saga_phase":str((final or res or {}).get("saga_phase") or "BURST_ACK")}
                    if current_state=="DISPATCHING":
                        TRADE_QUEUE.update_job(queue_job_id,state="DISPATCHING",**fields)
                    elif current_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                        TRADE_QUEUE.update_review_job(queue_job_id,**fields)
            elif queue_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                _set_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],queue_state,
                                 command_id,queue_job_id,terminal_reason)
                hold_job=TRADE_QUEUE.get_job(queue_job_id) if queue_job_id else None
                if not _ensure_entry_capacity_hold(
                        ctx["username"],ctx.get("capacity_reservation_id"),hold_job):
                    _record_entry_capacity_hold_failure(
                        ctx["username"],ctx.get("capacity_reservation_id"),
                        "async_finalize_hold_failed")
            else:
                _clear_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],command_id)
                _release_entry_capacity_reservation(
                    ctx["username"],ctx.get("capacity_reservation_id"))
            if queue_job_id and not durable_pending:
                current=TRADE_QUEUE.get_job(queue_job_id) or {}
                current_state=str(current.get("state") or "").upper()
                if current_state in ("DISPATCHING","UNKNOWN"):
                    finisher=(TRADE_QUEUE.reconcile_finish if current_state=="UNKNOWN"
                              else TRADE_QUEUE.finish)
                    finisher(queue_job_id,queue_state,result=final or res,
                             error=({"detail":terminal_reason} if terminal_reason else None),
                             finished_at=_dt.datetime.utcnow().isoformat())
            if (queue_state=="UNKNOWN" and
                    bool((final or res or {}).get("saga_durable"))):
                _schedule_open_saga_recovery(command_id,final or res,ctx)
        if queue_job_id:
            recovery_job=TRADE_QUEUE.get_job(queue_job_id) or {}
            if _open_saga_job(recovery_job):
                _schedule_open_saga_recovery(command_id,final or res,ctx)
        if not durable_pending:
            _release_account_op(ctx["username"],ctx.get("account_token"))
        if ctx.get("slot_token") and not durable_pending:
            _clear_slot_busy(ctx["symbol"],ctx["slot"],ctx["username"])
            _release_slot_op(ctx["username"],ctx["symbol"],ctx["slot"],ctx["slot_token"])

async def _finalize_pending_close(command_id,res,ctx):
    tracer=get_tracer()
    tracer.update_field(command_id,"pending_context",ctx)
    queue_job_id=str((ctx or {}).get("queue_job_id") or "")
    if queue_job_id:
        existing_job=TRADE_QUEUE.get_job(queue_job_id) or {}
        if str(existing_job.get("state") or "").upper()=="COMPLETED":
            _clear_slot_review(
                ctx["username"],ctx["symbol"],ctx["slot"],command_id)
            return True
    close_lease_token=(_claim_close_review_finalizer_lease(queue_job_id)
                       if queue_job_id else None)
    if queue_job_id and close_lease_token is None:
        return False
    queue_state="UNKNOWN"; final=None; terminal_reason=""
    durable_pending=False
    truth_budget=_pending_finalizer_budget(ctx)
    truth_deadline=time.monotonic()+truth_budget
    resolver_deadline=truth_deadline-_pending_close_truth_reserve(truth_budget)
    try:
        conn=_user_exec_conn(ctx["username"])
        try:
            final=await _pending_finalizer_deadline_call(
                resolver_deadline,
                lambda remaining: conn.resolve_pair_pending(res,timeout=remaining),
            )
        except Exception:
            final=res
        try:
            final=await _pending_finalizer_deadline_call(
                truth_deadline,
                lambda _remaining: _reconcile_pending_close_truth(conn,res,final,
                    {"main":ctx.get("main_ticket"),"hedge":ctx.get("hedge_ticket")}),
            )
        except Exception:
            final=final if isinstance(final,dict) else dict(res or {})
        mok=_resolved_leg_ok(final,"main"); hok=_resolved_leg_ok(final,"hedge")
        _trace_pair_execution(tracer,command_id,final,mark_ack=True)
        tracer.update_field(command_id,"final_result",final)
        _finalize_closed_tickets_local(ctx["symbol"],(
            ("main",ctx.get("main_ticket") if mok else None),
            ("hedge",ctx.get("hedge_ticket") if hok else None)),ctx["username"])
        if mok != hok and not _pair_pending(final):
            final,_auto_closed,_auto_reason=await _auto_converge_close_pair_single_leg(
                command_id,final,ctx)
            mok=_resolved_leg_ok(final,"main"); hok=_resolved_leg_ok(final,"hedge")
            tracer.update_field(command_id,"final_result",final)
            if _auto_closed:
                _finalize_closed_tickets_local(ctx["symbol"],(
                    (leg,ticket if _resolved_leg_ok(final,leg) else None)
                    for leg,ticket in (("main",ctx.get("main_ticket")),
                                       ("hedge",ctx.get("hedge_ticket")))),
                    ctx["username"])
                terminal_reason=""
        if mok and hok:
            _persist_after_close()
            _audit(ctx["username"],ctx["actor"],"close_pair",final,False,"closed_pair:async")
            _slip_snap(ctx["direction"],"close",_cap_at(ctx["main_tick"],ctx["hedge_tick"],ctx["direction"],"close"),
                       None,_leg_tickets(final.get("main")))
            if _close_ledger_commit_once(
                    command_id,RNS+"ledger:"+ctx["username"]+":"+ctx["direction"],
                    ctx.get("slot")):
                queue_state="COMPLETED"
            else:
                terminal_reason="close_ledger_commit_failed"
                tracer.update_status(command_id,CommandStatus.UNKNOWN)
                tracer.update_field(command_id,"failure_reason",terminal_reason)
                tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
                queue_state="UNKNOWN"
        elif _pair_pending(final) or any(bool((final.get(x) or {}).get("unknown")) for x in ("main","hedge")):
            terminal_reason=_terminal_failure_reason(final,"close_unknown")
            tracer.update_status(command_id,CommandStatus.UNKNOWN)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
            queue_state="UNKNOWN"
        elif mok != hok:
            terminal_reason=_terminal_failure_reason(final,"close_single_leg")
            _halt_auto_entry(ctx["username"],"single_leg_exposed",{
                "slot":ctx.get("slot"),"symbol":ctx.get("symbol"),
                "command_id":command_id,"res":final,"op":"close"})
            tracer.update_status(command_id,CommandStatus.SINGLE_LEG_EXPOSED)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            _push_alert("err","亚秒平仓异步终态出现单腿暴露, command_id=%s, 请立即人工核对"%command_id,ctx["username"])
            _audit(ctx["username"],ctx["actor"],"close_pair",final,False,"NAKED_RISK_async")
            queue_state="SINGLE_LEG_EXPOSED"
        else:
            terminal_reason=_terminal_failure_reason(final,"close_failed")
            tracer.update_status(command_id,CommandStatus.FAILED)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            queue_state="FAILED"
    except Exception as ex:
        terminal_reason="async_finalize:%s"%ex.__class__.__name__
        tracer.update_status(command_id,CommandStatus.UNKNOWN)
        tracer.update_field(command_id,"failure_reason",terminal_reason)
        tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
        queue_state="UNKNOWN"
    finally:
        durable_pending=bool(
            queue_state=="UNKNOWN" and
            (_trade_bool((final or res or {}).get("saga_durable")) or
             _trade_bool((ctx or {}).get("burst_admission"))) and
            _pair_pending(final or res or {}))
        if durable_pending:
            tracer.update_status(command_id,CommandStatus.SUBMITTED)
            tracer.update_field(command_id,"failure_reason","saga_pending_recovery")
        if ctx.get("queue_job_id") and not durable_pending:
            try:
                current=TRADE_QUEUE.get_job(ctx["queue_job_id"]) or {}
                current_state=str(current.get("state") or "").upper()
                fields={"result":final or res,
                        "error":({"detail":terminal_reason} if terminal_reason else None),
                        "finished_at":_dt.datetime.utcnow().isoformat()}
                if current_state==queue_state:
                    job=(TRADE_QUEUE.update_review_job(ctx["queue_job_id"],**fields)
                         if current_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED")
                         else current)
                elif current_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
                    job=TRADE_QUEUE.reconcile_finish(
                        ctx["queue_job_id"],queue_state,**fields)
                else:
                    job=TRADE_QUEUE.finish(ctx["queue_job_id"],queue_state,**fields)
                actual_state=str((job or {}).get("state") or "").upper()
                if actual_state!=queue_state:
                    terminal_reason="queue_finalize_rejected:%s"%(actual_state or "missing")
                    queue_state=(actual_state if actual_state in (
                        "UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED") else "UNKNOWN")
                    tracer.update_status(
                        command_id,getattr(CommandStatus,queue_state,CommandStatus.UNKNOWN))
                    tracer.update_field(command_id,"failure_reason",terminal_reason)
            except Exception as ex:
                terminal_reason="queue_finalize:%s"%ex.__class__.__name__
                queue_state="UNKNOWN"
                tracer.update_status(command_id,CommandStatus.UNKNOWN)
                tracer.update_field(command_id,"failure_reason",terminal_reason)
        elif durable_pending and ctx.get("queue_job_id"):
            try:
                current=TRADE_QUEUE.get_job(ctx["queue_job_id"]) or {}
                if str(current.get("state") or "").upper() in (
                        "DISPATCHING","UNKNOWN","MANUAL_REVIEW"):
                    TRADE_QUEUE.update_job(
                        ctx["queue_job_id"],state="DISPATCHING",
                        result=final or res,context=ctx,saga_durable=True,
                        saga_phase=str((final or res or {}).get(
                            "saga_phase") or "BURST_ACK"),
                        error={"detail":"burst close still pending; automatic recovery scheduled"})
            except Exception:
                pass
        if queue_state=="COMPLETED":
            _record_trace_timestamp_once(
                tracer,command_id,TraceTimestamp.PAIR_JOIN_DONE)
            _record_trace_timestamp_once(
                tracer,command_id,TraceTimestamp.LEDGER_COMMITTED)
            tracer.update_status(command_id,CommandStatus.COMPLETED)
            _clear_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],command_id)
        elif durable_pending:
            _clear_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],command_id)
        elif queue_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
            _set_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],queue_state,
                             command_id,ctx.get("queue_job_id"),terminal_reason)
        else:
            _clear_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],command_id)
        if ctx.get("queue_job_id"):
            if durable_pending or queue_state=="SINGLE_LEG_EXPOSED":
                _schedule_close_pair_review_recovery(
                    command_id,final or res,ctx,delay=(0.25 if durable_pending else 0.5))
        if not durable_pending:
            _release_account_op(ctx["username"],ctx.get("account_token"))
        if ctx.get("slot_token") and not durable_pending:
            _clear_slot_busy(ctx["symbol"],ctx["slot"],ctx["username"])
            _release_slot_op(ctx["username"],ctx["symbol"],ctx["slot"],ctx["slot_token"])
        if close_lease_token:
            _release_close_review_finalizer_lease(queue_job_id,close_lease_token)

async def _finalize_pending_leg_close(command_id,res,ctx):
    tracer=get_tracer()
    tracer.update_field(command_id,"pending_context",ctx)
    queue_state="UNKNOWN"; final=None; terminal_reason=""
    truth_budget=_pending_finalizer_budget(ctx)
    truth_deadline=time.monotonic()+truth_budget
    resolver_deadline=truth_deadline-_pending_close_truth_reserve(truth_budget)
    try:
        conn=_user_exec_conn(ctx["username"])
        try:
            final=await _pending_finalizer_deadline_call(
                resolver_deadline,
                lambda remaining: conn.resolve_pair_pending(res,timeout=remaining),
            )
        except Exception:
            final=res
        try:
            final=await _pending_finalizer_deadline_call(
                truth_deadline,
                lambda _remaining: _reconcile_pending_close_truth(
                    conn,res,final,{ctx["leg"]:ctx["ticket"]}),
            )
        except Exception:
            final=final if isinstance(final,dict) else dict(res or {})
        tracer.update_field(command_id,"final_result",final)
        leg_result=((final or {}).get(ctx["leg"]) if isinstance(final,dict) else None)
        if not isinstance(leg_result,dict) and isinstance(final,dict):
            leg_result=final
        _trace_leg_bridge_ack(tracer,command_id,ctx["leg"],leg_result)
        _trace_leg_broker_terminal(tracer,command_id,ctx["leg"],leg_result)
        if _resolved_leg_ok(final,ctx["leg"]):
            _mark_ticket_closed(ctx["symbol"],ctx["leg"],ctx["ticket"],ctx["username"])
            _release_slot(ctx["symbol"],ctx["leg"],ctx["ticket"],ctx["username"])
            source_ok,source_reason=_resolve_source_single_leg_review_after_close(
                ctx["username"],ctx["symbol"],command_id,ctx)
            if source_ok:
                _persist_after_close()
                _audit(ctx["username"],ctx["actor"],"close_leg",final,False,"closed_leg:async")
                tracer.update_status(command_id,CommandStatus.COMPLETED)
                queue_state="COMPLETED"
            else:
                terminal_reason="local_close_finalization_failed:%s"%source_reason
                tracer.update_status(command_id,CommandStatus.MANUAL_REVIEW)
                tracer.update_field(command_id,"failure_reason",terminal_reason)
                queue_state="MANUAL_REVIEW"
        elif _pair_pending(final) or bool((final.get(ctx["leg"]) or {}).get("unknown")):
            terminal_reason=_terminal_failure_reason(final,"close_leg_unknown")
            tracer.update_status(command_id,CommandStatus.UNKNOWN)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
            queue_state="UNKNOWN"
        else:
            terminal_reason=_terminal_failure_reason(final,"close_leg_failed")
            tracer.update_status(command_id,CommandStatus.FAILED)
            tracer.update_field(command_id,"failure_reason",terminal_reason)
            _push_alert("err","单腿 ticket 平仓失败, command_id=%s, 请人工核对"%command_id,ctx["username"])
            queue_state="FAILED"
    except Exception as ex:
        terminal_reason="async_finalize:%s"%ex.__class__.__name__
        tracer.update_status(command_id,CommandStatus.UNKNOWN)
        tracer.update_field(command_id,"failure_reason",terminal_reason)
        tracer.record_timestamp(command_id,TraceTimestamp.UNKNOWN_COMMITTED)
        queue_state="UNKNOWN"
    finally:
        if queue_state in ("UNKNOWN","MANUAL_REVIEW","SINGLE_LEG_EXPOSED"):
            _set_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],queue_state,
                             command_id,ctx.get("queue_job_id"),terminal_reason)
        else:
            _clear_slot_review(ctx["username"],ctx["symbol"],ctx["slot"],command_id)
        if ctx.get("queue_job_id"):
            TRADE_QUEUE.finish(ctx["queue_job_id"],queue_state,result=final or res,
                               error=({"detail":terminal_reason} if terminal_reason else None),
                               finished_at=_dt.datetime.utcnow().isoformat())
        _release_account_op(ctx["username"],ctx.get("account_token"))
        if ctx.get("slot_token"):
            _clear_slot_busy(ctx["symbol"],ctx["slot"],ctx["username"])
            _release_slot_op(ctx["username"],ctx["symbol"],ctx["slot"],ctx["slot_token"])

def _fra_sync_uuid(role, uuid):
    """登记变更→FRA a2t-bridge 对应腿 UUID 热同步(POST /admin/account_uuid, 持久化 env)。
       best-effort: 失败仅跑马灯告警绝不阻塞注册/清除主流程。返回 (ok,msg)。
       sg-bridge(会话制)生效时跳过 —— PRO API 无 UUID 概念, FRA 退役后此同步随旧云API一起废。"""
    if os.environ.get("QH_SG_AGENT_URL","").strip():
        return True,"sg-bridge 会话制生效, 无需 UUID 同步(跳过)"
    try:
        base=os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206").rstrip("/")
        key=os.environ.get("QH_FRA_KEY","")
        port=(os.environ.get("QH_FRA_MAIN_PORT","8021") if role=="main" else os.environ.get("QH_FRA_HEDGE_PORT","8001"))
        r=_httpx.post("%s:%s/admin/account_uuid"%(base,port), json={"uuid":uuid or ""},
                      headers={"X-API-Key":key}, timeout=5)
        if r.status_code!=200: raise RuntimeError("http %d"%r.status_code)
        return True,"FRA %s 腿已同步(%s)"%(role,(uuid or "")[:8] or "清除")
    except Exception as e:
        try:
            R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn",
                    "msg":"FRA %s 腿 UUID 同步失败(%s), api 执行模式恢复前需人工核对"%(role,e.__class__.__name__)}))
            R.ltrim(RNS+"alerts",0,49)
        except Exception: pass
        return False,"FRA 同步失败: %s"%e.__class__.__name__

def _a2t_release(cfg_id, uuid):
    """注销云端托管账户: 官方 GET /DeleteAccount?id=UUID(实测语义: 缺参400/不存在403 "Trading Account not found")。
       返回 (ok,msg), 绝不抛异常。幂等: 云端已不存在视为已释放(不阻塞本地清理)。
       复用方: 重注册释放旧 UUID(reg_account) / 彻底清除(admin_acct_purge)。"""
    uuid=(uuid or "").strip()
    if not uuid: return False,"无云端UUID, 跳过云端注销"
    try:
        cfg=_a2t_cfg(cfg_id, need_active=False)
        base=(cfg.get("base_url") or "").strip().rstrip("/") or A2T_BASE
        headers={}; auth=None
        if (cfg.get("plan") or "single")=="pro" and (cfg.get("basic_user") or "").strip():
            auth=(cfg["basic_user"].strip(), cfg.get("basic_pass") or "")
        else: headers["x-api-key"]=(cfg.get("api_key") or "").strip()
        r=_httpx.get(base+"/DeleteAccount", params={"id":uuid}, headers=headers, auth=auth, timeout=10)
        if r.status_code==200: return True,"云端注销成功"
        body=(r.text or "")[:120]
        if "not found" in body.lower(): return True,"云端已不存在该账户(视为已释放)"
        if r.status_code==401: return False,"云端鉴权失败(401): Key 无效或已失效"
        if r.status_code==402: return False,"云端套餐额度受限(402)"
        return False,"云端注销未成功(HTTP %d): %s"%(r.status_code,body)
    except HTTPException as e:
        return False,"云端配置不可用: %s"%(str(getattr(e,"detail",""))[:50])
    except Exception as e:
        return False,"云端调用异常: %s"%e.__class__.__name__

# ---- 经纪商/服务器目录(供 qh 前端账户设置下拉; 从 A2T /Search 聚合) ----
# A2T 无"列全部经纪商"端点, 只能按公司名 /Search; 故用种子清单逐个查再聚合。
# 种子可用 Redis 键 qh:a2t:broker_seed(JSON 数组)热覆盖, 无需改代码/重启。
# 注意: 种子用"品牌关键词", 但 A2T 按法人名匹配 → ICMarketsSC 实为 "Raw Trading Ltd"(品牌≠法人)。
# 故显式补 Raw Trading/Infra Capital(Bybit法人) 等易漏项; 缺失平台加关键词即可(热覆盖 qh:a2t:broker_seed)。
_A2T_BROKER_SEED=["IC Markets","Raw Trading","Bybit","Infra Capital","Exness","XM","Pepperstone",
                  "FBS","Vantage","Tickmill","FXTM","OctaFX","RoboForex","Admirals","FxPro","HFM"]

def a2t_brokers(refresh:int=0):
    """经纪商→服务器名聚合列表 helper(A2T /Search 逐经纪商聚合, Redis 缓存 6h)。
       路由由 a2t_brokers_pub/_admin 承接(叠加本地 override)。
       chicken-egg: /Search 需一个有效账户 UUID 作 id → 取订阅下任一已注册账户探测。"""
    ck=RNS+"a2t:brokers"
    if not refresh:
        cached=R.get(ck)
        if cached:
            try: return json.loads(cached)
            except Exception: pass
    cfg=_a2t_cfg(need_active=False)
    j,_=_a2t_call(cfg,"/GetAccounts")
    accs=_a2t_acclist(j)
    if not accs:
        raise HTTPException(503,"A2T 无已注册账户, 无法查询经纪商服务器目录(先注册至少一个账户)")
    probe_id=str((accs[0] or {}).get("id") or "")
    try: seed=json.loads(R.get(RNS+"a2t:broker_seed") or "null") or _A2T_BROKER_SEED
    except Exception: seed=_A2T_BROKER_SEED
    companies=[]; seen=set()
    for name in seed:
        try:
            r,_=_a2t_call(cfg,"/Search",{"id":probe_id,"company":name},timeout=8)
            for co in (r if isinstance(r,list) else []):
                cn=co.get("companyName") or name
                servers=[s.get("name") for s in (co.get("results") or []) if s.get("name")]
                if servers and cn not in seen:
                    seen.add(cn); companies.append({"company":cn,"servers":sorted(set(servers))})
        except Exception: continue
    companies.sort(key=lambda x:x["company"])
    out={"companies":companies,"count":len(companies),"cached_at":_dt.datetime.utcnow().isoformat()}
    R.setex(ck, 21600, json.dumps(out))
    return out

def _apply_broker_override(base):
    """本地客户端真源覆盖(qh:a2t:broker_override, 由本机 MT5 采集器推送)。
       对 override 里的经纪商: 本地服务器排前(权威), 再并入 A2T 剩余项(不丢), 标 local=True。"""
    try: ov=json.loads(R.get(RNS+"a2t:broker_override") or "{}")
    except Exception: ov={}
    if not ov: return base
    comps={c["company"]:c for c in base.get("companies",[])}
    for company, servers in ov.items():
        loc=[s for s in (servers or []) if s]
        if not loc: continue
        if company in comps:
            a2t=[s for s in comps[company].get("servers",[]) if s not in loc]
            comps[company]={"company":company,"servers":loc+a2t,"local":True}
        else:
            comps[company]={"company":company,"servers":loc,"local":True}
    lst=sorted(comps.values(), key=lambda x:x["company"])
    return {"companies":lst,"count":len(lst),"cached_at":base.get("cached_at"),
            "override":list(ov.keys())}

# ---- 品牌终处理: 法人实体→品牌改名 + 品牌合并法人服务器 + 内网桥终端在用服务器注入(真源置顶) ----
# 背景: A2T /Search 按法人聚合 —— 用户的 IC 账户实际在 "Raw Trading Ltd"(SC 法人)服务器上,
#       Bybit 的法人名是 "Infra Capital Limited", 用户视角应显示品牌名且服务器列表补齐。
# 热覆盖 Redis qh:a2t:broker_finalize = {"rename":{},"merge":{},"bridge_map":{}}, 无需改代码。
_BROKER_FINALIZE_DEFAULT={
  "rename":{"Infra Capital Limited":"Bybit"},
  "merge":{"IC Markets Ltd":["Raw Trading Ltd"],"Bybit":["Infra Capital Limited"]},
  "bridge_map":{"main":"IC Markets Ltd","hedge":"Bybit"},
}
def _bridge_live_servers():
    """内网桥两腿终端在用 服务器/公司(由 _bridge_srv_collector 后台采集写 Redis, 桥挂保旧值)。"""
    try: return json.loads(R.get(RNS+"a2t:bridge_srv") or "{}")
    except Exception: return {}
def _broker_finalize(base):
    try:
        cfg=_BROKER_FINALIZE_DEFAULT
        try:
            ov=json.loads(R.get(RNS+"a2t:broker_finalize") or "null")
            if isinstance(ov,dict) and ov: cfg=ov
        except Exception: pass
        comps={c["company"]:dict(c) for c in base.get("companies",[])}
        ren=cfg.get("rename") or {}
        # ① 法人→品牌改名(目标已存在则并服务器)
        for old,new in ren.items():
            if old in comps:
                e=comps.pop(old)
                tgt=comps.get(new)
                if tgt:
                    tgt["servers"]=list(dict.fromkeys((tgt.get("servers") or [])+(e.get("servers") or [])))
                    tgt["local"]=tgt.get("local") or e.get("local")
                else:
                    e["company"]=new; e["legal"]=old; comps[new]=e
        # ② 品牌 ← 法人实体服务器合并(原实体条目保留, 不丢信息)
        for brand,srcs in (cfg.get("merge") or {}).items():
            for s in srcs:
                src=comps.get(s) or comps.get(ren.get(s) or "")
                if not src or src is comps.get(brand): continue
                tgt=comps.setdefault(brand,{"company":brand,"servers":[]})
                tgt["servers"]=list(dict.fromkeys((tgt.get("servers") or [])+(src.get("servers") or [])))
                if src.get("local"): tgt["local"]=True
        # ③ 内网桥终端在用服务器注入(真源, 置顶回显优先)
        live=_bridge_live_servers()
        for role,brand in (cfg.get("bridge_map") or {}).items():
            srv=((live.get(role) or {}).get("server") or "").strip()
            if not srv: continue
            tgt=comps.setdefault(brand,{"company":brand,"servers":[]})
            tgt["servers"]=[srv]+[x for x in (tgt.get("servers") or []) if x!=srv]
            tgt["local"]=True
        lst=sorted(comps.values(), key=lambda x:x["company"])
        out=dict(base); out["companies"]=lst; out["count"]=len(lst)
        return out
    except Exception:
        return base

async def _bridge_srv_collector():
    """内网桥终端在用 服务器/公司 采集(300s/轮, 每腿5s超时): 供平台目录'真源注入'。
       独立于 read_source 切换(目录补齐明确要求走桥终端); 桥挂→Redis 保旧值, 目录不抖。"""
    await _aio.sleep(20)
    while True:
        try:
            bc=_raw_bridge(); out={}
            for role in ("main","hedge"):
                leg=bc.main if role=="main" else getattr(bc,"hedge",None)
                if leg is None: continue
                try:
                    ai=await _aio.wait_for(leg.account_info(), timeout=5)
                    srv=(ai.get("server") or "").strip()
                    if srv: out[role]={"server":srv,"company":(ai.get("company") or "").strip(),
                                       "ts":_dt.datetime.utcnow().isoformat()}
                except Exception: pass
            if out:
                try: prev=json.loads(R.get(RNS+"a2t:bridge_srv") or "{}")
                except Exception: prev={}
                prev.update(out)
                R.set(RNS+"a2t:bridge_srv", json.dumps(prev))
        except Exception: pass
        await _aio.sleep(300)

@app.on_event("startup")
async def _bridge_srv_boot():
    _aio.create_task(_bridge_srv_collector())

@app.get("/api/a2t/brokers", dependencies=[Depends(require_license)])
def a2t_brokers_pub(refresh:int=0):
    return _broker_finalize(_apply_broker_override(a2t_brokers(refresh)))

@app.get("/api/admin/a2t/brokers", dependencies=[Depends(require_op("accounts"))])
def a2t_brokers_admin(refresh:int=0):
    """同 /api/a2t/brokers, 供 qhadmin 账户管理(操作员可能无用户密钥, 走 op 权限)。"""
    return _broker_finalize(_apply_broker_override(a2t_brokers(refresh)))

class BrokerOverride(BaseModel):
    override: dict = {}   # {经纪商法人名: [服务器名,...]}; 由本机 MT5 客户端采集器推送

@app.post("/api/admin/a2t/broker_override", dependencies=[Depends(require_op("accounts"))])
def set_broker_override(b:BrokerOverride):
    """接收本地 IC/Bybit 等客户端真实服务器清单, 存 Redis 供 brokers 合并(本地优先)。"""
    clean={}
    for k,v in (b.override or {}).items():
        srvs=[str(s).strip() for s in (v or []) if str(s).strip()]
        if str(k).strip() and srvs: clean[str(k).strip()]=sorted(set(srvs))
    R.set(RNS+"a2t:broker_override", json.dumps(clean))
    return {"ok":True,"companies":list(clean.keys()),"total_servers":sum(len(v) for v in clean.values())}

@app.get("/api/admin/a2t/broker_override", dependencies=[Depends(require_op("accounts"))])
def get_broker_override():
    try: ov=json.loads(R.get(RNS+"a2t:broker_override") or "{}")
    except Exception: ov={}
    return {"override":ov}

# ---- 订阅配置 CRUD (perm=datamgr, 与 SSL/数据库同权) ----
class A2TCfgSave(BaseModel):
    id:int=0; label:str=""; account:str=""; plan:str="single"; api_key:str=""
    base_url:str=""; basic_user:str=""; basic_pass:str=""
    expires_at:str=""; enabled:bool=True; note:str=""

@app.get("/api/admin/api2trade/config", dependencies=[Depends(require_op("datamgr"))])
def a2t_cfg_list():
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT * FROM api2trade_config ORDER BY id")
    rows=[dict(r) for r in cur.fetchall()]
    cur.execute("SELECT api2trade_config_id cid, COUNT(*) n FROM mt_accounts WHERE conn_mode='api' AND api2trade_uuid<>'' GROUP BY 1")
    cnt={r["cid"]:r["n"] for r in cur.fetchall()}; c.close()
    today=datetime.date.today()
    for r in rows:
        r["api_key"]=_a2t_mask(r["api_key"]); r["basic_pass"]="****" if r["basic_pass"] else ""
        r["bound_accounts"]=cnt.get(r["id"],0)
        r["days_left"]=(r["expires_at"]-today).days if r["expires_at"] else None
        r["expires_at"]=str(r["expires_at"]) if r["expires_at"] else ""
        r["created_at"]=str(r["created_at"]); r["updated_at"]=str(r["updated_at"])
    return {"configs":rows}

@app.post("/api/admin/api2trade/config/save", dependencies=[Depends(require_op("datamgr"))])
def a2t_cfg_save(b:A2TCfgSave):
    if b.plan not in ("single","pro"): raise HTTPException(400,"plan 须为 single|pro")
    exp=None
    if (b.expires_at or "").strip():
        try: exp=datetime.date.fromisoformat(b.expires_at.strip()[:10])
        except ValueError: raise HTTPException(400,"有效期格式须 YYYY-MM-DD")
    c=db(); cur=c.cursor()
    if b.id:
        # 掩码回传(含 ****)不覆盖库中真值
        sets=["label=%s","account=%s","plan=%s","base_url=%s","basic_user=%s","expires_at=%s","enabled=%s","note=%s","updated_at=now()"]
        vals=[b.label.strip(),b.account.strip(),b.plan,b.base_url.strip(),b.basic_user.strip(),exp,b.enabled,b.note]
        if b.api_key and "****" not in b.api_key: sets.append("api_key=%s"); vals.append(b.api_key.strip())
        if b.basic_pass and "****" not in b.basic_pass: sets.append("basic_pass=%s"); vals.append(b.basic_pass)
        vals.append(b.id)
        cur.execute("UPDATE api2trade_config SET "+",".join(sets)+" WHERE id=%s",vals)
        if not cur.rowcount: c.close(); raise HTTPException(404,"配置不存在")
    else:
        cur.execute("INSERT INTO api2trade_config(label,account,plan,api_key,base_url,basic_user,basic_pass,expires_at,enabled,note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (b.label.strip(),b.account.strip(),b.plan,(b.api_key or "").strip(),b.base_url.strip(),b.basic_user.strip(),b.basic_pass,exp,b.enabled,b.note))
        b.id=cur.fetchone()[0]
    c.close(); return {"ok":True,"id":b.id}

class A2TId(BaseModel):
    id:int=0

@app.post("/api/admin/api2trade/config/delete", dependencies=[Depends(require_op("datamgr"))])
def a2t_cfg_del(b:A2TId):
    c=db(); cur=c.cursor()
    cur.execute("SELECT COUNT(*) FROM mt_accounts WHERE api2trade_config_id=%s AND conn_mode='api'",(b.id,))
    n=cur.fetchone()[0]
    if n: c.close(); raise HTTPException(400,"仍有 %d 个用户账户绑定该订阅, 请先解绑/删除账户"%n)
    cur.execute("DELETE FROM api2trade_config WHERE id=%s",(b.id,)); ok=cur.rowcount; c.close()
    if not ok: raise HTTPException(404,"配置不存在")
    return {"ok":True}

@app.post("/api/admin/api2trade/test", dependencies=[Depends(require_op("datamgr"))])
def a2t_test(b:A2TId):
    """连通性测试: /GetAccounts。不校验到期(测试本身要能诊断过期前后的连通性), 但明示状态。"""
    cfg=_a2t_cfg(b.id or None, need_active=False)
    j,ms=_a2t_call(cfg,"/GetAccounts")
    exp=cfg.get("expires_at"); expired=bool(exp and exp<datetime.date.today())
    return {"ok":True,"latency_ms":ms,"accounts":len(_a2t_acclist(j)),
            "expired":expired,"enabled":bool(cfg.get("enabled"))}

@app.get("/api/admin/api2trade/accounts", dependencies=[Depends(require_op("datamgr"))])
def a2t_accounts(id:int=0):
    """Api2Trade 侧已注册账户实时列表 + 本地 mt_accounts 绑定关系"""
    cfg=_a2t_cfg(id or None, need_active=False)
    j,ms=_a2t_call(cfg,"/GetAccounts")
    lst=_a2t_acclist(j)
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT a.api2trade_uuid uuid,a.login,a.role,u.username FROM mt_accounts a JOIN users u ON u.id=a.user_id WHERE a.conn_mode='api' AND a.api2trade_uuid<>''")
    local={r["uuid"]:r for r in cur.fetchall()}; c.close()
    out=[]
    for a in lst:
        if not isinstance(a,dict): continue
        uid=str(a.get("id") or "")
        m=local.get(uid)
        out.append({"uuid":uid,"account_number":a.get("account_number") or a.get("accountNumber"),
                    "account_server":a.get("account_server") or a.get("accountServer"),
                    "type":a.get("type"),"name":a.get("name"),
                    "bound_user":(m or {}).get("username") or "","bound_role":(m or {}).get("role") or ""})
    return {"config_id":cfg["id"],"latency_ms":ms,"accounts":out}

class A2TCanary(BaseModel):
    id:int=0; uuid:str=""; n:int=10

@app.post("/api/admin/api2trade/canary", dependencies=[Depends(require_op("datamgr"))])
def a2t_canary(b:A2TCanary):
    """P1 交易腿前置证据: N 次 /AccountSummary 延迟分布。p50>300ms 建议仅只读。"""
    cfg=_a2t_cfg(b.id or None)
    uuid=(b.uuid or "").strip()
    if not uuid:
        j,_=_a2t_call(cfg,"/GetAccounts")
        lst=_a2t_acclist(j)
        if not lst: raise HTTPException(400,"该订阅下无已注册账户, 无法 canary")
        uuid=str((lst[0] or {}).get("id") or "")
    n=max(3,min(30,int(b.n or 10))); lat=[]
    for _i in range(n):
        _,ms=_a2t_call(cfg,"/AccountSummary",{"id":uuid}); lat.append(ms)
    lat.sort()
    p50=lat[n//2]; p90=lat[min(n-1,int(n*0.9))]
    return {"n":n,"uuid":uuid,"min":lat[0],"p50":p50,"p90":p90,"max":lat[-1],
            "verdict":("PASS(可评估交易腿, 设 QH_A2T_TRADING=1 武装)" if p50<=300 else "SLOW(延迟偏高, 建议仅只读)")}

# ---- 用户侧只读: 本人 api 模式账户的实时摘要(前端"测试连接"用) ----
class A2TSummaryReq(BaseModel):
    role:str="hedge"

@app.post("/api/a2t/summary", dependencies=[Depends(require_license)])
def a2t_summary(b:A2TSummaryReq, x_license: str = Header(default="")):
    role=b.role if b.role in ("main","hedge") else "hedge"
    c=db(); cur=c.cursor()
    cur.execute("SELECT a.api2trade_uuid,a.api2trade_config_id,a.login FROM mt_accounts a JOIN users u ON u.id=a.user_id WHERE u.license_key=%s AND a.role=%s AND a.conn_mode='api' AND a.api2trade_uuid<>'' AND a.enabled ORDER BY a.id DESC LIMIT 1",(x_license,role))
    row=cur.fetchone(); c.close()
    if not row: raise HTTPException(404,"该角色未注册 API 连接账户(请先保存并登录)")
    cfg=_a2t_cfg(row[1])
    j,ms=_a2t_call(cfg,"/AccountSummary",{"id":row[0]})
    j=j if isinstance(j,dict) else {}
    return {"login":row[2],"latency_ms":ms,"balance":j.get("balance"),"equity":j.get("equity"),
            "margin":j.get("margin"),"free_margin":j.get("freeMargin"),
            "margin_level":j.get("marginLevel"),"currency":j.get("currency"),"leverage":j.get("leverage")}

# ================= 用户账户管理 (admin, perm=accounts) =================
# 跨用户 mt_accounts 登记信息管理。只动登记表, 不触碰任何交易/持仓数据。
@app.get("/api/admin/accounts", dependencies=[Depends(require_op("accounts"))])
def admin_accounts(q:str=""):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    sql=("SELECT a.id,a.label,a.login,a.platform,a.broker,a.role,a.conn_mode,a.enabled,a.server,"
         "a.api2trade_uuid,a.api2trade_config_id,a.created_at,u.username,u.status user_status "
         "FROM mt_accounts a JOIN users u ON u.id=a.user_id")
    args=[]
    if (q or "").strip():
        like="%"+q.strip()+"%"
        sql+=" WHERE u.username ILIKE %s OR a.login ILIKE %s OR a.label ILIKE %s"; args=[like,like,like]
    sql+=" ORDER BY u.username,a.role,a.id"
    cur.execute(sql,args); rows=[dict(r) for r in cur.fetchall()]; c.close()
    for r in rows: r["created_at"]=str(r["created_at"])
    return {"accounts":rows}

class AdminAcctSave(BaseModel):
    id:int; label:str=""; role:str="main"; conn_mode:str="bridge"; enabled:bool=True
    platform:str="MT5"; broker:str=""; server:str=""

@app.post("/api/admin/accounts/save", dependencies=[Depends(require_op("accounts"))])
def admin_acct_save(b:AdminAcctSave):
    if b.role not in ("main","hedge"): raise HTTPException(400,"role 须为 main|hedge")
    if b.conn_mode not in ("bridge","api"): raise HTTPException(400,"conn_mode 须为 bridge|api(本地直连已停用)")
    if b.platform not in ("MT4","MT5"): raise HTTPException(400,"platform 须为 MT4|MT5")
    c=db(); cur=c.cursor()
    cur.execute("UPDATE mt_accounts SET label=%s,role=%s,conn_mode=%s,enabled=%s,platform=%s,broker=%s,server=%s WHERE id=%s",
                (b.label.strip(),b.role,b.conn_mode,b.enabled,b.platform,b.broker.strip(),b.server.strip(),b.id))
    n=cur.rowcount; c.close()
    if not n: raise HTTPException(404,"账户不存在")
    _reg_roles_bust()
    return {"ok":True}

@app.post("/api/admin/accounts/delete", dependencies=[Depends(require_op("accounts"))])
def admin_acct_del(b:A2TId):
    """仅删除登记行。api 模式账户在云端侧的托管不联动删除(需后台处理), 前端已明示。"""
    c=db(); cur=c.cursor()
    cur.execute("DELETE FROM mt_accounts WHERE id=%s",(b.id,)); n=cur.rowcount; c.close()
    if not n: raise HTTPException(404,"账户不存在")
    _reg_roles_bust()
    return {"ok":True}

@app.post("/api/admin/accounts/purge", dependencies=[Depends(require_op("accounts",danger=True))])
async def admin_acct_purge(b:A2TId):
    """彻底清除: 联动 Api2Trade 官方 /DeleteAccount 注销云端托管账户 + 删本地登记行。
       **绝不动交易记录/历史成交**: 登记行删除不级联 deals 表(按 user 键), 配对历史读桥/券商实时。
    保护闸: 自动策略运行中 或 该腿有未平持仓 → 409 禁止清除(与用户端 delete_mine 同口径)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT m.id,m.login,m.role,m.api2trade_uuid,m.api2trade_config_id,u.username
                   FROM mt_accounts m JOIN users u ON u.id=m.user_id WHERE m.id=%s""",(b.id,))
    acc=cur.fetchone(); c.close()
    if not acc: raise HTTPException(404,"账户不存在")
    if (acc.get("role") or "") in ("main","hedge"):
        _deny=await _acct_clear_guard(acc["role"],acc.get("username"))
        if _deny: raise HTTPException(409,_deny)
    acc=dict(acc); uuid=(acc.get("api2trade_uuid") or "").strip()
    a2t_ok,a2t_msg=_a2t_release(acc.get("api2trade_config_id"), uuid)
    c=db(); cur=c.cursor()
    cur.execute("DELETE FROM mt_accounts WHERE id=%s",(b.id,)); n=cur.rowcount; c.close()
    _reg_roles_bust()
    if (acc.get("role") or "") in ("main","hedge"):
        try: await _aio.to_thread(_fra_sync_uuid, acc["role"], "")
        except Exception: pass
    return {"ok":True,"local_deleted":bool(n),"a2t_ok":a2t_ok,"a2t_msg":a2t_msg,"uuid8":uuid[:8]}

# P0.1: 命令追踪查询端点
@app.get("/api/command/{command_id}")
async def get_command_status(command_id: str, principal:str=Depends(require_license)):
    tracer = get_tracer()
    cmd = tracer.get_command(command_id)
    if not cmd or str(cmd.get("username") or "")!=str(principal):
        raise HTTPException(404, "命令不存在")
    latencies = tracer.calculate_latencies(command_id)
    return {
        "command_id": command_id,
        "type": cmd.get("type"),
        "status": cmd.get("status"),
        "username": cmd.get("username"),
        "symbol": cmd.get("symbol"),
        "direction": cmd.get("direction"),
        "main_ticket": cmd.get("main_ticket"),
        "hedge_ticket": cmd.get("hedge_ticket"),
        "pair_request_id": cmd.get("pair_request_id"),
        "main_request_id": cmd.get("main_request_id"),
        "hedge_request_id": cmd.get("hedge_request_id"),
        "created_at": cmd.get("api_received"),
        "latencies": latencies,
        "failure_reason": cmd.get("failure_reason"),
        "final_result": json.loads(cmd["final_result"]) if cmd.get("final_result") else None,
    }

@app.get("/api/commands/unknown", dependencies=[Depends(require_op("recon"))])
async def list_unknown_commands():
    tracer = get_tracer()
    unknown_cmds = tracer.list_unknown_commands(limit=50)
    return {"count": len(unknown_cmds), "commands": [tracer.get_command(cmd_id) for cmd_id in unknown_cmds]}

_SUBSECOND_RECON_WORKER=None
_SUBSECOND_RECON_TASK=None

def _reconciled_open_mapping(value):
    if isinstance(value,dict):
        return dict(value)
    if isinstance(value,(str,bytes)):
        try:
            if isinstance(value,bytes): value=value.decode("utf-8","replace")
            decoded=json.loads(value)
            return dict(decoded) if isinstance(decoded,dict) else {}
        except (TypeError,ValueError):
            return {}
    return {}

async def _on_open_saga_reconcile(command_id, command):
    """Let the durable saga own UNKNOWN recovery before generic leg inference."""
    command=dict(command or {})
    job_id=str(command.get("queue_job_id") or "")
    if _trade_queue_command_task_active(command_id,command):
        # The local dispatcher still owns this exact command. Reconciliation
        # must not consume its truth budget or rewrite SUBMITTED while the
        # broker response is still arriving.
        return True
    job=TRADE_QUEUE.get_job(job_id) if job_id else None
    if not _open_saga_job(job):
        return False
    context=_trade_queue_recovery_context(job)
    result=_trade_queue_recovery_result(job,context)
    if not result:
        return False
    if not _ensure_entry_capacity_hold(command.get("username"),job_id,job):
        return False
    get_tracer().update_status(command_id,CommandStatus.UNKNOWN)
    get_tracer().update_field(command_id,"pending_context",context)
    _schedule_open_saga_recovery(command_id,result,context,delay=0.0)
    return True


def _late_open_saga_completion_allowed(command_id, command, job, evidence, slot, tickets):
    """Allow review promotion only for both fills from this exact durable saga."""
    if not _open_saga_job(job):
        return False
    username=str(command.get("username") or "").strip()
    symbol=str(command.get("symbol") or "XAUUSD")
    if (str(job.get("command_id") or "")!=str(command_id) or
            str(job.get("username") or "").strip()!=username or
            str(job.get("symbol") or "XAUUSD")!=symbol or
            _exact_positive_int(job.get("slot"))!=slot):
        return False

    raw_result=job.get("result") if isinstance(job.get("result"),dict) else {}
    stored_evidence=raw_result.get("evidence")
    stored=(stored_evidence if raw_result.get("reconciled") and
            isinstance(stored_evidence,dict) else raw_result)
    context=_reconciled_open_mapping(job.get("context"))
    context.update(_reconciled_open_mapping(command.get("pending_context")))
    pair_rid=str(job.get("pair_rid") or context.get("pair_rid") or "")
    if not pair_rid:
        return False
    pair_ids=[job.get("pair_rid"),context.get("pair_rid"),stored.get("request_id"),
              command.get("pair_request_id"),evidence.get("request_id")]
    if any(str(value)!=pair_rid for value in pair_ids if value not in (None,"")):
        return False

    agent_states=evidence.get("agent_states") if isinstance(
        evidence.get("agent_states"),dict) else {}
    for leg in ("main","hedge"):
        expected=pair_rid+leg[0]
        leg_result=evidence.get(leg) if isinstance(evidence.get(leg),dict) else {}
        stored_leg=stored.get(leg) if isinstance(stored.get(leg),dict) else {}
        declared=[command.get(leg+"_request_id"),leg_result.get("request_id"),
                  stored_leg.get("request_id")]
        if any(str(value)!=expected for value in declared if value not in (None,"")):
            return False
        if str(agent_states.get(leg) or "").upper()=="DONE":
            if str(command.get(leg+"_request_id") or "")!=expected:
                return False
        elif str(leg_result.get("request_id") or "")!=expected:
            return False
        if not _resolved_leg_ok(evidence,leg):
            return False
        evidence_ticket=_exact_positive_int(
            leg_result.get("order") or leg_result.get("ticket") or leg_result.get("deal"))
        if evidence_ticket is not None and evidence_ticket!=tickets.get(leg):
            return False

    try:
        raw_review=R.get(_slotreview_key(username,symbol,slot))
        if isinstance(raw_review,bytes):
            raw_review=raw_review.decode("utf-8","replace")
        review=json.loads(raw_review) if raw_review else None
    except Exception:
        return False
    if review is not None and (
            not isinstance(review,dict) or
            str(review.get("command_id") or "")!=str(command_id) or
            str(review.get("job_id") or "")!=str(job.get("job_id") or "") or
            _exact_positive_int(review.get("slot"))!=slot):
        return False
    return bool(tickets.get("main") and tickets.get("hedge") and
                tickets["main"]!=tickets["hedge"])


async def _on_reconciled_open(command_id, command, evidence, resolution_state):
    """Commit open ownership/capacity truth before the tracer becomes terminal."""
    command=dict(command or {}); evidence=dict(evidence or {})
    if str(command.get("type") or "").lower()!=CommandType.OPEN_PAIR.value:
        return False
    resolution_state=str(resolution_state or "").upper()
    if resolution_state not in (
            "COMPLETED","FAILED","SINGLE_LEG_EXPOSED","MANUAL_REVIEW"):
        return False
    username=str(command.get("username") or "").strip()
    symbol=str(command.get("symbol") or "XAUUSD")
    if not username:
        return False

    try:
        latest=get_tracer().get_command(command_id) or {}
        command.update(latest)
    except Exception:
        pass
    queue_job_id=str(command.get("queue_job_id") or "")
    job=TRADE_QUEUE.get_job(queue_job_id) if queue_job_id else None
    if queue_job_id and not isinstance(job,dict):
        return False
    current_queue_state=str((job or {}).get("state") or "").upper()
    confirmed_pair_failure=(
        resolution_state=="FAILED" and
        not bool(evidence.get("main_ok")) and
        not bool(evidence.get("hedge_ok")) and
        _open_pair_explicit_no_fill(evidence) and
        not any(_exact_positive_int(command.get(leg+"_ticket"))
                for leg in ("main","hedge")))
    if (queue_job_id and
            current_queue_state not in ("DISPATCHING","UNKNOWN",resolution_state)):
        # Only a still-recoverable durable saga may promote a review state.
        # Genuine terminal one-leg exposure remains operator-controlled.
        if not (confirmed_pair_failure or
                (_open_saga_job(job) and resolution_state in ("COMPLETED","FAILED"))):
            return False
    context={}
    if isinstance(job,dict):
        context.update(_reconciled_open_mapping(job.get("context")))
    context.update(_reconciled_open_mapping(command.get("pending_context")))
    payload=_reconciled_open_mapping((job or {}).get("payload"))
    slot=_exact_positive_int(command.get("slot") or (job or {}).get("slot") or context.get("slot"))
    if slot is None:
        return False
    direction=str(command.get("direction") or context.get("direction") or
                  payload.get("direction") or "")
    capacity_id=str(context.get("capacity_reservation_id") or queue_job_id or "")

    def _ticket(leg):
        ticket=_exact_positive_int(command.get(leg+"_ticket"))
        if ticket is not None:
            return ticket
        leg_result=evidence.get(leg) if isinstance(evidence.get(leg),dict) else {}
        return _exact_positive_int(
            leg_result.get("order") or leg_result.get("ticket") or leg_result.get("deal"))

    tickets={leg:_ticket(leg) for leg in ("main","hedge")}
    compensated=_open_compensation_succeeded(evidence)
    main_ok=bool(evidence.get("main_ok")); hedge_ok=bool(evidence.get("hedge_ok"))
    if resolution_state=="COMPLETED" and not (
            main_ok and hedge_ok and tickets["main"] and tickets["hedge"] and
            tickets["main"]!=tickets["hedge"]):
        return False
    if resolution_state=="FAILED" and not (confirmed_pair_failure or compensated):
        return False
    if resolution_state=="SINGLE_LEG_EXPOSED" and main_ok==hedge_ok:
        return False
    # A durable saga can reach this callback with a terminal review state
    # even though both fills are now confirmed.  Permit promotion only for
    # that exact saga; a genuine one-leg/manual outcome remains blocked.
    if (resolution_state in ("COMPLETED", "MANUAL_REVIEW") and
            main_ok and hedge_ok and tickets["main"] and tickets["hedge"] and
            tickets["main"] != tickets["hedge"] and
            _open_saga_job(job)):
        if current_queue_state in ("SINGLE_LEG_EXPOSED", "MANUAL_REVIEW"):
            late_allowed = _late_open_saga_completion_allowed(
                command_id,command,job,evidence,slot,tickets)
            if resolution_state == "COMPLETED" and not late_allowed:
                return False
            if late_allowed:
                resolution_state = "COMPLETED"
        elif current_queue_state == "DISPATCHING" and resolution_state == "MANUAL_REVIEW":
            # The first finalizer may have failed only at local owner
            # persistence.  The queue is still at its dispatch boundary, so
            # the exact durable saga itself is the promotion proof.
            resolution_state = "COMPLETED"

    normalized={}
    for leg in ("main","hedge"):
        if not compensated and tickets[leg] is not None and (
                resolution_state=="COMPLETED" or
                (resolution_state in ("SINGLE_LEG_EXPOSED","MANUAL_REVIEW") and
                 bool(evidence.get(leg+"_ok")))):
            normalized[leg]={"order":tickets[leg]}

    if resolution_state=="COMPLETED" and context.get("ledger_key"):
        ledger_key=str(context.get("ledger_key") or "").strip()
        ledger_entry={
            "q":context.get("hedge_vol"),"m":context.get("main_vol"),
            "s":context.get("entry_spread") if context.get("entry_spread") is not None else 0,
            "ts":_dt.datetime.utcnow().isoformat(),"ladder":slot,
            "command_id":command_id}
        if not ledger_key or ledger_entry["q"] is None or ledger_entry["m"] is None:
            return False
        if not _open_ledger_commit_once(
                command_id,ledger_key,ledger_entry,get_tracer()):
            return False
    repair_display = False
    if (normalized and queue_job_id and _open_saga_job(job) and
            resolution_state == "COMPLETED"):
        repair_display = _allow_provisional_display_rebind(
            symbol, [(leg, str(tickets[leg])) for leg in ("main", "hedge")
                     if tickets[leg] is not None], slot, username)
    if normalized and not await _reserve_slot_with_recovery(
            symbol,normalized,slot,username,
            allow_provisional_display_rebind=repair_display):
        return False

    reservation_keys=_entry_capacity_reservation_keys(username)
    uncertain_resolution=resolution_state in ("SINGLE_LEG_EXPOSED","MANUAL_REVIEW")
    if uncertain_resolution:
        if _entry_position_limits(username) and not capacity_id:
            return False
        if capacity_id:
            if not _ensure_entry_capacity_hold(username,capacity_id,job):
                return False
            score=R.zscore(reservation_keys[1],capacity_id)
            if _entry_position_limits(username) and (
                    score is None or float(score)<253402300799000):
                return False
        reason=str(evidence.get("reason") or resolution_state)
        _set_slot_review(username,symbol,slot,resolution_state,
                         command_id,queue_job_id,reason)
        if R.get(_slotreview_key(username,symbol,slot)) is None:
            return False

    if queue_job_id:
        result={"reconciled":True,"open_tickets":tickets,
                "command_id":command_id,"state":resolution_state,
                "evidence":evidence}
        if current_queue_state=="DISPATCHING":
            reconciled=TRADE_QUEUE.finish(queue_job_id,resolution_state,result=result,
                finished_at=_dt.datetime.utcnow().isoformat())
        else:
            reconciled=TRADE_QUEUE.reconcile_finish(
                queue_job_id,resolution_state,result=result)
        if not reconciled or str(reconciled.get("state") or "").upper()!=resolution_state:
            return False

    # Resolved capacity can be released only after owner truth and the queue
    # terminal transition both succeeded.  A callback race that leaves the
    # queue UNKNOWN therefore retains its permanent hold.
    if not uncertain_resolution:
        if capacity_id:
            _release_entry_capacity_reservation(username,capacity_id)
            if (R.hget(reservation_keys[0],capacity_id) is not None or
                    R.zscore(reservation_keys[1],capacity_id) is not None):
                return False
        _clear_slot_review(username,symbol,slot,command_id)
        if R.get(_slotreview_key(username,symbol,slot)) is not None:
            return False

    if normalized and direction in ("reverse","forward"):
        _remember_open_positions(
            symbol,context.get("hedge_symbol"),direction,normalized,slot,username,
            context.get("main_vol"),context.get("hedge_vol"))
    try:
        _audit(username,"reconciler","open_truth",{
            "command_id":command_id,"tickets":tickets,"state":resolution_state},
            False,"opened:reconciled:%s"%resolution_state.lower())
    except Exception:
        pass
    return True

async def _on_reconciled_close(command_id, command, closed, resolution_state):
    """Apply exact-ticket close truth and its matching queue terminal state."""
    command=dict(command or {})
    pending=_reconciled_open_mapping(command.get("pending_context"))
    queue_job_id=str(command.get("queue_job_id") or pending.get("queue_job_id") or "")
    queue_job=TRADE_QUEUE.get_job(queue_job_id) if queue_job_id else None
    payload=_reconciled_open_mapping((queue_job or {}).get("payload"))
    for name in ("leg","ticket","slot","single_leg_review_authorized",*_SOURCE_REVIEW_FIELDS):
        if command.get(name) in (None,""):
            candidate=pending.get(name)
            if candidate in (None,""):
                candidate=payload.get(name)
            if candidate not in (None,""):
                command[name]=candidate
    if queue_job_id:
        command["queue_job_id"]=queue_job_id
    username=str(command.get("username") or "").strip()
    symbol=str(command.get("symbol") or "XAUUSD")
    if not username or not isinstance(closed,dict) or not closed:
        return False
    resolution_state=str(resolution_state or "").upper()
    if resolution_state not in ("COMPLETED","SINGLE_LEG_EXPOSED","MANUAL_REVIEW"):
        return False

    command_type=str(command.get("type") or "").lower()
    targets={}
    if command_type==CommandType.CLOSE_LEG.value:
        leg=str(command.get("leg") or "")
        ticket=_exact_positive_int(command.get("ticket"))
        if leg not in ("main","hedge") or ticket is None:
            return False
        targets[leg]=str(ticket)
    elif command_type==CommandType.CLOSE_PAIR.value:
        main_ticket=_exact_positive_int(command.get("main_ticket"))
        hedge_ticket=_exact_positive_int(command.get("hedge_ticket"))
        if main_ticket is None or hedge_ticket is None or main_ticket==hedge_ticket:
            return False
        targets={"main":str(main_ticket),"hedge":str(hedge_ticket)}
    else:
        return False

    normalized={}
    for leg,ticket in closed.items():
        ticket=_exact_positive_int(ticket)
        if leg not in targets or ticket is None or str(ticket)!=targets[leg]:
            return False
        normalized[leg]=str(ticket)
    if resolution_state=="COMPLETED" and normalized!=targets:
        return False
    if resolution_state=="SINGLE_LEG_EXPOSED" and not (
            command_type==CommandType.CLOSE_PAIR.value and len(normalized)==1):
        return False

    if resolution_state=="SINGLE_LEG_EXPOSED":
        # The reconciler proved one exact close and one still-live ticket.  Do
        # not publish a permanent manual-review terminal before attempting the
        # only safe repair: close that surviving exact ticket.
        for leg,ticket in normalized.items():
            _mark_ticket_closed(symbol,leg,ticket,username)
            _release_slot(symbol,leg,ticket,username)
        auto_context={}
        auto_context.update(payload)
        auto_context.update(pending)
        auto_context.update(command)
        auto_context.update({"username":username,"symbol":symbol,
            "queue_job_id":queue_job_id,
            "main_ticket":int(targets["main"]),
            "hedge_ticket":int(targets["hedge"])})
        try:
            conn=_user_exec_conn(username)
            probe={"main":None,"hedge":None,"main_ok":False,"hedge_ok":False,
                   "op":"close","tickets":{
                       "main":int(targets["main"]),"hedge":int(targets["hedge"])}}
            probe=await _reconcile_pending_close_truth(
                conn,probe,probe,probe["tickets"])
        except Exception:
            probe=None
        if isinstance(probe,dict):
            broker_closed={leg:targets[leg] for leg in ("main","hedge")
                           if _resolved_leg_ok(probe,leg)}
            if broker_closed==targets:
                normalized=dict(targets)
                resolution_state="COMPLETED"
            elif len(broker_closed)==1:
                repaired,auto_closed,_auto_reason=(
                    await _auto_converge_close_pair_single_leg(
                        command_id,probe,auto_context))
                if auto_closed and all(
                        _resolved_leg_ok(repaired,leg) for leg in ("main","hedge")):
                    normalized=dict(targets)
                    resolution_state="COMPLETED"

    if resolution_state=="COMPLETED" and normalized!=targets:
        return False

    now=_dt.datetime.utcnow().timestamp()
    for leg,ticket in normalized.items():
        _mark_ticket_closed(symbol,leg,ticket,username)
        _release_slot(symbol,leg,ticket,username)
        if (R.hget(_slotowner_key(leg,symbol,username),ticket) is not None or
                R.hget(_slotmap_key(leg,symbol,username),ticket) is not None):
            return False
        tombstone=R.zscore(_closed_ticket_key(username,leg,symbol),ticket)
        if tombstone is None or float(tombstone)<=now:
            return False
    if command_type==CommandType.CLOSE_LEG.value and resolution_state=="COMPLETED":
        source_value=dict(payload)
        source_value.update(pending)
        source_value.update(command)
        source_ok,_source_reason=_resolve_source_single_leg_review_after_close(
            username,symbol,command_id,source_value)
        if not source_ok:
            return False
    slot=_exact_positive_int(command.get("slot"))
    if slot is None:
        slot=_exact_positive_int(pending.get("slot"))
    if slot is None:
        slot=_exact_positive_int(payload.get("slot"))
    if command_type==CommandType.CLOSE_PAIR.value and resolution_state=="COMPLETED":
        close_context={}
        close_context.update(payload)
        close_context.update(pending)
        close_context.update(command)
        direction=str(close_context.get("direction") or "").lower()
        if direction not in ("reverse","forward"):
            main_side=str(close_context.get("main_side") or "").lower()
            direction=("reverse" if main_side=="sell" else
                       "forward" if main_side=="buy" else "")
        if slot is None or direction not in ("reverse","forward"):
            return False
        if not _close_ledger_commit_once(
                command_id,RNS+"ledger:"+username+":"+direction,slot):
            return False
    if queue_job_id:
        job=TRADE_QUEUE.reconcile_finish(queue_job_id,resolution_state,
            result={"reconciled":True,"closed":normalized,"command_id":command_id,
                    "state":resolution_state})
        if not job or str(job.get("state") or "").upper()!=resolution_state:
            return False
    try:
        tracer=get_tracer()
        tracer.update_status(
            command_id,getattr(CommandStatus,resolution_state,CommandStatus.MANUAL_REVIEW))
        if command_type==CommandType.CLOSE_PAIR.value and resolution_state=="COMPLETED":
            _record_trace_timestamp_once(
                tracer,command_id,TraceTimestamp.LEDGER_COMMITTED)
    except Exception:
        pass
    if resolution_state=="COMPLETED" and slot is not None:
        _clear_slot_review(username,symbol,slot,command_id)
    _persist_after_close()
    try:
        _audit(username,"reconciler","close_truth",{
            "command_id":command_id,"closed":normalized,"state":resolution_state},
            False,"closed:reconciled:%s"%resolution_state.lower())
    except Exception:
        pass
    return True

@app.on_event("startup")
async def _startup_subsecond_reconciler():
    global _SUBSECOND_RECON_WORKER,_SUBSECOND_RECON_TASK
    from qh_reconciliation_worker import ReconciliationWorker
    _SUBSECOND_RECON_WORKER=ReconciliationWorker(
        redis_client=R,
        db_session=None,
        bridge_main_url=os.environ.get("QH_BRIDGE_URL","http://172.31.5.62:8041"),
        bridge_hedge_url=os.environ.get("QH_HEDGE_URL","http://172.31.5.62:8042"),
        bridge_api_key=os.environ.get("QH_BRIDGE_KEY",""),
        connection_factory=_strict_user_exec_conn,
        close_confirmed_callback=_on_reconciled_close,
        open_confirmed_callback=_on_reconciled_open,
        open_saga_callback=_on_open_saga_reconcile,
        command_active_callback=_trade_queue_command_task_active,
    )
    _SUBSECOND_RECON_TASK=_aio.create_task(_SUBSECOND_RECON_WORKER.start())

@app.on_event("shutdown")
async def _shutdown_subsecond_reconciler():
    if _SUBSECOND_RECON_WORKER is not None:
        await _SUBSECOND_RECON_WORKER.stop()
    if _SUBSECOND_RECON_TASK is not None:
        _SUBSECOND_RECON_TASK.cancel()
    saga_tasks=list(_OPEN_SAGA_RECOVERY_TASKS.values())
    for task in saga_tasks:
        task.cancel()
    if saga_tasks:
        await _aio.gather(*saga_tasks,return_exceptions=True)
    _OPEN_SAGA_RECOVERY_TASKS.clear()
    close_tasks=list(_CLOSE_REVIEW_RECOVERY_TASKS.values())
    for task in close_tasks:
        task.cancel()
    if close_tasks:
        await _aio.gather(*close_tasks,return_exceptions=True)
    _CLOSE_REVIEW_RECOVERY_TASKS.clear()

# === P1.3: tick缓存统计端点 ===
@app.get("/api/admin/tick_cache_stats", dependencies=[Depends(require_op("system"))])
def get_tick_cache_stats():
    """查询tick缓存使用统计"""
    try:
        keys = R.keys("bridge:*:tick:*")

        stats = {
            "total_cached_symbols": len(keys),
            "cached_ticks": []
        }

        for key in keys[:10]:
            data = R.hgetall(key)
            if data:
                stats["cached_ticks"].append({
                    "key": key,
                    "symbol": data.get('symbol'),
                    "pushed_at": data.get('pushed_at'),
                    "bid": data.get('bid'),
                    "ask": data.get('ask')
                })

        return stats
    except Exception as e:
        return {"error": str(e), "total_cached_symbols": 0}
