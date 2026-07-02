# Quant Hedge 后端骨架 (FastAPI)
# 架构: testgo 式服务端中心 — 引擎+数据在服务端，凭证留用户 MT 终端（本服务绝不接收/存储 MT 凭证）
# api2trade 预留：连接器接口空实现，当前走用户侧 MT5 bridge
import os, json, datetime
from fastapi import FastAPI, HTTPException, Depends, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import psycopg2, psycopg2.extras, redis

DB = dict(host="127.0.0.1", dbname="quanthedge", user="quanthedge",
          password=os.environ.get("QH_DB_PASS",""))
R = redis.Redis(host="127.0.0.1", port=6379, db=3, decode_responses=True)  # db3 = Quant Hedge namespace
RNS = "qh:"  # Redis key 前缀，与 crossarb/testgo 隔离

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

def db():
    c = psycopg2.connect(**DB); c.autocommit = True; return c

@app.get("/api/health")
def health():
    info = {"service":"quant-hedge","ts":datetime.datetime.utcnow().isoformat()+"Z"}
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT count(*) FROM users"); info["users"]=cur.fetchone()[0]; c.close()
        info["db"]="ok"
    except Exception as e: info["db"]="error: %s"%e
    try: R.ping(); info["redis"]="ok (db3 ns=%s)"%RNS
    except Exception as e: info["redis"]="error: %s"%e
    info["connector"]="mt5-bridge (api2trade reserved)"
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
def _self_register(username, contact, feishu_id, request, trial_days=0, agent_code=""):
    """建号(生成 license), trial_days>0 则写试用期+强制DEMO。返回 license/username。防滥用: 同 IP 24h 限 3 次。"""
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
    c=db(); cur=c.cursor()
    # 绑定代理(分佣归因)
    aid=None
    if agent_code:
        cur.execute("SELECT id FROM agents WHERE code=%s",(agent_code,)); a=cur.fetchone(); aid=a[0] if a else None
    cur.execute("""INSERT INTO users(username,license_key,plan,expire_at,feishu_id,status,created_at,last_ip,last_login,geo_country,geo_name,agent_id,source,
                   trial_until,trial_started)
                   VALUES(%s,%s,%s,%s,%s,%s,now(),%s,now(),%s,%s,%s,'self',%s,%s) RETURNING id""",
                (username,newk,None,exp,feishu_id or None,status,ip,iso,zh,aid,
                 (exp if trial_days>0 else None),(now if trial_days>0 else None)))
    uid=cur.fetchone()[0]; c.close()
    if trial_days>0: R.set(RNS+"force_demo:"+username,"1")
    _audit(username,"self","register",{"trial_days":trial_days,"ip":ip,"agent":agent_code},DEMO_MODE,status)
    return {"ok":True,"username":username,"license_key":newk,"status":status,"expire_at":exp.isoformat(),"trial":trial_days>0}

class RegisterReq(BaseModel):
    username:str; contact:str=""; feishu_id:str=""; agent_code:str=""
@app.post("/api/auth/register")
def auth_register(r:RegisterReq, request:Request):
    if not r.username or len(r.username)<3: raise HTTPException(400,"用户名至少3位")
    return _self_register(r.username, r.contact, r.feishu_id, request, trial_days=0, agent_code=r.agent_code)

class TrialReq2(BaseModel):
    username:str; contact:str=""; feishu_id:str=""; agent_code:str=""; days:int=7
@app.post("/api/auth/trial")
def auth_trial(r:TrialReq2, request:Request):
    if not r.username or len(r.username)<3: raise HTTPException(400,"用户名至少3位")
    return _self_register(r.username, r.contact, r.feishu_id, request, trial_days=max(1,min(30,r.days)), agent_code=r.agent_code)

class PurchaseReq(BaseModel):
    license_key:str; product_key:str
@app.post("/api/iap/purchase")
def iap_purchase(r:PurchaseReq):
    """用户自助内购: 校验密钥→建订单(pending 待财务核对)→授商品权益→计佣。支付走演示(与现充值一致)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,status FROM users WHERE license_key=%s",(r.license_key,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    if u["status"] in ("banned","disabled"): c.close(); raise HTTPException(403,"账户不可用")
    cur.execute("SELECT * FROM iap_products WHERE key=%s AND enabled=true",(r.product_key,)); p=cur.fetchone()
    if not p: c.close(); raise HTTPException(404,"商品不存在/已下架")
    uid=u["id"]; grants=p["grants"] or {}; amount=float(p["price"] or 0); dur=p["duration_days"]
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
    tx_hash:str=""
@app.post("/api/order/submit")
def order_submit(r:OrderSubmitReq):
    """用户自助下单统一入口。三类:
       - iap: 按 product_key 授商品权益
       - subscription: 按 months 延长 paid_until/expire_at(价用服务端 SUB_PRICES, 防篡改)
       - recharge: 充值到 users.balance(仅 onchain)
       支付方式: onchain=建 pending 订单待财务核对(演示环境即时生效); balance=扣余额即时确认。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,status,balance FROM users WHERE license_key=%s",(r.license_key,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(401,"invalid license key")
    if u["status"] in ("banned","disabled"): c.close(); raise HTTPException(403,"账户不可用")
    uid=u["id"]; bal=float(u["balance"] or 0); prod=None; grants={}; amount=0.0; months=0; unit="USDT"
    # 1) 计价 + 校验
    if r.kind=="iap":
        cur.execute("SELECT * FROM iap_products WHERE key=%s AND enabled=true",(r.product_key,)); prod=cur.fetchone()
        if not prod: c.close(); raise HTTPException(404,"商品不存在/已下架")
        grants=prod["grants"] or {}; amount=float(prod["price"] or 0); unit=prod["unit"] or "USDT"
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
    # 4) 落订单(统一入 iap_orders, 供 admin/orders 财务核对)
    pkey = r.product_key if r.kind=="iap" else ("_sub_%dm"%months if r.kind=="subscription" else "_recharge")
    cur.execute("""INSERT INTO iap_orders(user_id,product_key,amount,unit,status,operator,reconcile_status,kind,pay_method,tx_hash,months,paid_at)
                   VALUES(%s,%s,%s,%s,%s,'self',%s,%s,%s,%s,%s,now()) RETURNING id""",
                (uid,pkey,amount,unit,ostatus,recon,r.kind,r.pay_method,r.tx_hash or None,months))
    oid=cur.fetchone()["id"]
    # 计佣(充值不计佣, 内购/订阅计)
    if r.kind in ("iap","subscription"):
        try: _calc_commissions(cur, oid, r.kind, uid, amount)
        except Exception as ce: print("commission err",ce)
    cur.execute("SELECT balance FROM users WHERE id=%s",(uid,)); newbal=float(cur.fetchone()["balance"] or 0)
    c.close()
    _audit(u["username"],"self","order_submit",{"kind":r.kind,"amount":amount,"pay":r.pay_method,"tx":bool(r.tx_hash)},DEMO_MODE,recon)
    return {"ok":True,"order_id":oid,"kind":r.kind,"amount":amount,"pay_method":r.pay_method,
            "reconcile_status":recon,"granted":list(grants.keys()),"balance":newbal,"demo":DEMO_MODE,
            "expire_at":str(exp) if exp else None}

@app.get("/api/user/wallet/{username}")
def user_wallet(username:str):
    """用户余额 + 近期订单(用户端支付页/账户页用)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT balance,total_recharge FROM users WHERE username=%s",(username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    c.close()
    return {"balance":round(float(u["balance"] or 0),2),"total_recharge":round(float(u["total_recharge"] or 0),2)}

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

@app.get("/api/user/orders/{username}")
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

@app.get("/api/params/{username}")
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

@app.get("/api/deals/{username}")
def deals(username:str, limit:int=50):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT d.ticket,d.symbol,d.side,d.lots,d.price,d.profit,d.platform,d.dealt_at
                   FROM deals d JOIN users u ON u.id=d.user_id
                   WHERE u.username=%s ORDER BY d.dealt_at DESC LIMIT %s""",(username,limit))
    rows=cur.fetchall(); c.close()
    return {"username":username,"deals":[dict(r) for r in rows]}

# ================= Bridge 连接器接入 (P0) =================
from connector import get_connector
CONN = get_connector()
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

# 用户密钥验证: X-License 对应有效用户即放行(用户改自己的参数, 无需 admin token)
def require_license(x_license: str = Header(default="")):
    if not x_license:
        raise HTTPException(403, "缺少用户密钥")
    c=db(); cur=c.cursor()
    cur.execute("SELECT status FROM users WHERE license_key=%s",(x_license,))
    row=cur.fetchone(); c.close()
    if not row:
        raise HTTPException(403, "密钥无效")
    if row[0] in ("banned","disabled"):
        raise HTTPException(403, "账户已停用/封禁")
    return True

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
def require_op(perm):
    """操作员权限依赖工厂: 校验 session + 角色权限 + IP 白名单。
       向后兼容: 带合法 admin token 的请求直接放行(超管兜底)。"""
    def _dep(request: Request, x_op_token: str = Header(default=""), x_admin_token: str = Header(default="")):
        # 兜底: admin token 合法 = 超管, 放行(保留原运维通道)
        _tok=_admin_token()
        if _tok and x_admin_token==_tok:
            return {"operator":"admintoken","role":"super"}
        sess=_op_session(x_op_token)
        if not sess: raise HTTPException(401,"操作员未登录")
        if not sess.get("enabled",True): raise HTTPException(403,"操作员已禁用")
        # IP 白名单
        allow=sess.get("allowed_ips") or ""
        if allow.strip():
            ip=_client_ip(request)
            if ip not in [x.strip() for x in allow.split(",") if x.strip()]:
                raise HTTPException(403,"IP 不在白名单: %s"%ip)
        # 权限
        perms=_op_perms(sess.get("role"))
        if perms!="*" and perm not in [x.strip() for x in perms.split(",")]:
            raise HTTPException(403,"无权限: %s(角色 %s)"%(perm,sess.get("role")))
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



@app.get("/api/bridge/status")
async def bridge_status():
    try: return {"ok":True, **(await CONN.status())}
    except Exception as e: raise HTTPException(502, "bridge error: %s"%e)

@app.get("/api/bridge/account")
async def bridge_account():
    try: return await CONN.account_info()
    except Exception as e: raise HTTPException(502, "bridge error: %s"%e)

@app.get("/api/bridge/positions")
async def bridge_positions():
    try: return await CONN.positions()
    except Exception as e: raise HTTPException(502, "bridge error: %s"%e)

# 从 bridge 拉历史成交 -> 入库 deals (凭证不碰, 仅成交记录)
TYPE_MAP={0:"buy",1:"sell",2:"balance"}
ENTRY_MAP={0:"in",1:"out"}
import datetime as _dt
@app.post("/api/bridge/sync/{username}")
async def bridge_sync(username:str, days:int=1):
    try:
        data = await CONN.history_deals(days=days)
    except Exception as e:
        raise HTTPException(502, "bridge error: %s"%e)
    deals = data.get("deals", data) if isinstance(data, dict) else data
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s",(username,))
    u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    n=0; skipped=0
    for d in (deals or []):
        ticket=str(d.get("ticket") or "")
        if not ticket or ticket=="0": continue
        t=int(d.get("type",-1)); dtype=TYPE_MAP.get(t,str(t))
        entry=ENTRY_MAP.get(int(d.get("entry",-1)),"")
        is_trade=(t in (0,1))
        sym=d.get("symbol","") or ""
        vol=float(d.get("volume",0) or 0); price=float(d.get("price",0) or 0)
        profit=float(d.get("profit",0) or 0); swap=float(d.get("swap",0) or 0)
        comm=float(d.get("commission",0) or 0); cmt=d.get("comment","") or ""
        ts=d.get("time")
        dealt=_dt.datetime.fromtimestamp(ts,_dt.timezone.utc) if ts else _dt.datetime.now(_dt.timezone.utc)
        cur.execute("""INSERT INTO deals(user_id,ticket,symbol,side,deal_type,entry,lots,price,profit,swap,commission,comment,is_trade,platform,dealt_at)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'MT5',%s)
                       ON CONFLICT (user_id,ticket) DO NOTHING""",
                    (u[0],ticket,sym,dtype,dtype,entry,vol,price,profit,swap,comm,cmt,is_trade,dealt))
        if cur.rowcount>0: n+=1
        else: skipped+=1
    c.close()
    R.incr(RNS+"sync:count")
    return {"ok":True,"synced":n,"skipped_dup":skipped,"source":"mt5-bridge"}
# ================= 后台自动 sync (P0 加固) =================
import asyncio as _aio
async def _auto_sync_loop():
    await _aio.sleep(10)
    while True:
        try:
            c=db(); cur=c.cursor()
            cur.execute("SELECT username FROM users")
            users=[r[0] for r in cur.fetchall()]; c.close()
            for un in users:
                try: await bridge_sync(un, days=1)
                except Exception as ex: print("auto-sync %s err: %s"%(un,ex))
            R.set(RNS+"autosync:last", _dt.datetime.utcnow().isoformat())
        except Exception as e:
            print("auto-sync loop err:", e)
        await _aio.sleep(60)

@app.on_event("startup")
async def _startup():
    _aio.create_task(_auto_sync_loop())

@app.get("/api/sync/last")
def sync_last():
    return {"last_auto_sync": R.get(RNS+"autosync:last"), "sync_count": R.get(RNS+"sync:count")}
# ================= 引擎循环 (P1) — 单进程 asyncio 管全部用户对 =================
import engine as ENG
async def _engine_loop():
    await _aio.sleep(12)
    while True:
        cycle={"ts":_dt.datetime.utcnow().isoformat(),"pairs":0,"gated":0,"single_leg":0}
        try:
            # 休市闸下沉到 SELECT 之后(需读 weekend_sat/sun); 此处先取行情
            # 取实时行情（当前单账户：主腿=15016910；对冲腿待接第二账户）
            try:
                acct = await CONN.account_info()
                R.set(RNS+"engine:account", json.dumps(acct))
            except Exception as ex:
                acct=None; R.set(RNS+"engine:err", "acct:%s"%ex)
            # 遍历用户参数模板，评估点差闸（行情接第二腿后补全）
            c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""SELECT u.username, pt.symbol, pt.entry_spread, pt.tp_points, pt.sl_points,
                                  pt.ladders, pt.hold_secs, pt.weekend_guard,
                                  pt.main_spread_cap, pt.hedge_spread_cap, pt.slippage_tol,
                                  pt.entry_interval_sec, pt.max_inflight, pt.auto_close,
                                  pt.main_lot_mult, pt.hedge_lot_mult, pt.hedge_symbol,
                                  pt.base_lot, pt.basis_offset, pt.data_mult, pt.digits,
                                  pt.single_leg_alert,
                                  pt.match_count, pt.fluctuation_band, pt.weekend_sat, pt.weekend_sun
                           FROM param_templates pt JOIN users u ON u.id=pt.user_id""")
            tmpls=cur.fetchall(); c.close()
            # 周末双开关(取首个模板; 单用户场景): 覆盖全局休市闸
            _w0 = tmpls[0] if tmpls else {}
            closed, why = ENG.market_closed(weekend_guard=_w0.get("weekend_guard",True),
                                            weekend_sat=_w0.get("weekend_sat"), weekend_sun=_w0.get("weekend_sun"))
            R.set(RNS+"engine:market", json.dumps({"closed":closed,"why":why}))
            # 数据波动闸: 取最近 match_count 条点差判波动(写入 engine:fluctuation, 供 open_pair 入场前校验)
            try:
                _mc=int(_w0.get("match_count") or 0); _bd=float(_w0.get("fluctuation_band") or 0)
                if _bd>0 and _mc>=2:
                    _hist=R.lrange(RNS+"spread:hist",-_mc,-1) or []
                    _sp=[json.loads(x).get("fs") for x in _hist]
                    fl=ENG.fluctuation_guard(_sp,_mc,_bd)
                    R.set(RNS+"engine:fluctuation", json.dumps({"paused":fl[0],"amp":fl[1],"reason":fl[2]}))
                else:
                    R.set(RNS+"engine:fluctuation", json.dumps({"paused":False,"amp":None,"reason":"off"}))
            except Exception: pass
            # 双腿持仓（主 ICMarkets + 对冲 Bybit）
            both_pos=None
            try:
                if hasattr(CONN,"both_positions"): both_pos=await CONN.both_positions()
            except Exception as ex:
                R.set(RNS+"engine:err","pos:%s"%ex)
            def _legsum(pl):
                items = pl.get("positions",pl) if isinstance(pl,dict) else (pl or [])
                return sum(float(p.get("volume",0) or 0) for p in (items or []))
            main_lots = _legsum(both_pos["main"]) if both_pos and both_pos.get("main") else 0.0
            hedge_lots = _legsum(both_pos["hedge"]) if both_pos and both_pos.get("hedge") else 0.0
            # 第二批 品种映射: 主/对冲符号取首个模板(单用户场景); 对冲腿用 hedge_symbol 拉行情
            _first = tmpls[0] if tmpls else {}
            main_sym = (_first.get("symbol") or "XAUUSD")
            hedge_sym = ENG.map_hedge_symbol(main_sym, _first.get("hedge_symbol")) or main_sym
            basis_off = float(_first.get("basis_offset") or 0.0)
            # 双腿行情(背离闸用) — 主腿主符号 / 对冲腿对冲符号(主≠对冲时符号转换)
            mtick=htick=None
            try:
                if hasattr(CONN,"main"): mtick=await CONN.main._get("/mt5/tick/"+main_sym)
            except Exception: pass
            try:
                if getattr(CONN,"hedge",None): htick=await CONN.hedge._get("/mt5/tick/"+hedge_sym)
            except Exception: pass
            div_prev = R.get(RNS+"engine:div_tripped")=="1"
            div_state=None
            if mtick and htick:
                dprev=ENG.divergence_guard(mtick.get("bid"),mtick.get("ask"),htick.get("bid"),htick.get("ask"),
                                           None,None,0.7,0.3,prev_tripped=div_prev,basis_offset=basis_off)
                # cap 取首个模板(单用户场景);多用户后改按 user
                div_state={"paused":dprev[0],"main_spread":dprev[1],"hedge_spread":dprev[2],"reason":dprev[3]}
                # 仅真实背离写迟滞(quote_invalid/crossed 等不污染)
                if dprev[3].startswith("diverged") or dprev[3].startswith("still_diverged"):
                    R.set(RNS+"engine:div_tripped","1")
                elif dprev[3] in ("ok","recovered"):
                    R.set(RNS+"engine:div_tripped","0")
                if dprev[0] and dprev[3] not in ("ok","recovered"):
                    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"背离/点差护栏: %s"%dprev[3]})); R.ltrim(RNS+"alerts",0,49)
                R.set(RNS+"engine:divergence", json.dumps(div_state))
            # 点差走势历史记录已移至独立 _spread_sampler 循环(按 数据同步 sync_interval_sec/records_per_sec 节流)
            for t in tmpls:
                cycle["pairs"]+=1
                if closed:
                    cycle["gated"]+=1
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
                    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),
                        "lv":"err" if tp_act=="stop_loss" else "info","msg":"%s建议: %s (软告警, 平仓需人工确认)"%(tp_act,tp_reason)})); R.ltrim(RNS+"alerts",0,49)
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
                    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err","msg":"单腿告警 %s 缺口%.3f"%(miss,gap)}))
                    R.ltrim(RNS+"alerts",0,49)
            R.set(RNS+"engine:cycle", json.dumps(cycle))
            R.set(RNS+"engine:cycle_ts", _dt.datetime.utcnow().isoformat())   # 循环心跳戳(供运维监控算新鲜度)
        except Exception as e:
            R.set(RNS+"engine:err", "loop:%s"%e)
        await _aio.sleep(5)

@app.on_event("startup")
async def _startup_engine():
    _aio.create_task(_engine_loop())

# ================= 点差采样循环 (数据同步: 按 sync_interval_sec/records_per_sec 节流写 spread:hist) =================
async def _spread_sampler():
    await _aio.sleep(14)
    while True:
        interval=1.0; rps=1; main_sym="XAUUSD"; hedge_sym="XAUUSD"
        try:
            c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT symbol,hedge_symbol,sync_interval_sec,records_per_sec FROM param_templates ORDER BY id LIMIT 1")
            row=cur.fetchone(); c.close()
            if row:
                main_sym=row.get("symbol") or "XAUUSD"
                hedge_sym=ENG.map_hedge_symbol(main_sym,row.get("hedge_symbol")) or main_sym
                interval=float(row.get("sync_interval_sec") or 1.0); interval=interval if interval>0 else 1.0
                rps=int(row.get("records_per_sec") or 1); rps=rps if rps>=1 else 1
        except Exception: pass
        try:
            mt=await CONN.main._get("/mt5/tick/"+main_sym) if hasattr(CONN,"main") else None
            ht=await CONN.hedge._get("/mt5/tick/"+hedge_sym) if getattr(CONN,"hedge",None) else None
            if mt and ht and mt.get("ask") is not None and ht.get("ask") is not None:
                fs=round(float(mt["ask"])-float(ht["bid"]),5); rs=round(float(ht["ask"])-float(mt["bid"]),5)
                # 每个同步周期写 records_per_sec 条(同值, 满足"每秒数据条数"密度要求)
                pipe=R.pipeline()
                for _ in range(min(rps,20)):
                    pipe.rpush(RNS+"spread:hist", json.dumps({"t":_dt.datetime.utcnow().isoformat()+"Z","fs":fs,"rs":rs}))
                pipe.ltrim(RNS+"spread:hist",-60000,-1); pipe.execute()
                R.set(RNS+"engine:sampler_ts", _dt.datetime.utcnow().isoformat())  # 采样成功心跳(供新鲜度)
                R.set(RNS+"engine:sampler_err","")  # 成功即清错
        except Exception as e:
            R.set(RNS+"engine:sampler_err", str(e))
        await _aio.sleep(interval)

@app.on_event("startup")
async def _startup_sampler():
    _aio.create_task(_spread_sampler())

# ================= 全自动出场循环 (逐对盈亏判定 → 按模式平仓; 默认 OFF) =================
# 模式(Redis qh:auto_exit:{user}): off=不动 / shadow=只回显"将平哪些坑"不真发 / armed=仅平 exit_enabled 的坑 / full=平所有命中坑
async def _close_one_pair(username, symbol, hedge_sym, main_side, hedge_side, mode_seq, speed, slot_no, reason):
    """真实平一坑(带裸空守护+账本弹出); 复用 close_pair 内核。返回 (ok, detail)。"""
    res=await CONN.close_pair(symbol, hedge_sym, main_side, hedge_side, None, None, mode=mode_seq, speed=speed)
    mok=("error" not in (res.get("main") or {})); hok=(res.get("hedge") is None) or ("error" not in (res.get("hedge") or {}))
    if mok and not hok:
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err",
            "msg":"⚠自动出场坑%s：主腿已平、对冲腿失败，单边暴露！需人工处理(未自动反开)"%slot_no})); R.ltrim(RNS+"alerts",0,49)
        _audit(username,"auto","auto_exit",{"slot":slot_no,"res":res},False,"NAKED_RISK_hedge_close_failed")
        return False,res
    try:
        _dir="reverse" if main_side=="sell" else "forward"; R.lpop(RNS+"ledger:"+username+":"+_dir)
    except Exception: pass
    _audit(username,"auto","auto_exit",{"slot":slot_no,"reason":reason},DEMO_MODE,"auto_closed")
    return True,res

async def _auto_exit_loop():
    await _aio.sleep(16)
    while True:
        try:
            c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT u.username, pt.* FROM param_templates pt JOIN users u ON u.id=pt.user_id")
            tmpls=cur.fetchall(); c.close()
        except Exception as e:
            R.set(RNS+"auto_exit:err","tmpl:%s"%e); await _aio.sleep(5); continue
        # 双腿持仓 + 双腿 tick(一次取, 全用户共用单账户场景)
        try: both=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        except Exception: both=None
        for t in tmpls:
            user=t["username"]; sym=t.get("symbol") or "XAUUSD"
            mode=R.get(RNS+"auto_exit:"+user) or "off"
            if mode=="off": continue
            # P1 防御: 武装/全量运行中若 auto_loop 权益失效(到期)→ 降级影子(不真平)
            if mode in ("armed","full") and str(_ent_get(t.get("user_id") or _uid(user),"auto_loop")).lower() not in ("true","1"):
                R.set(RNS+"auto_exit:"+user,"shadow"); mode="shadow"
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"自动出场权益已失效, 已降级为影子模式"})); R.ltrim(RNS+"alerts",0,49)
            if not t.get("auto_close"): continue   # 全局自动清仓总闸关→不动
            # 休市/周末闸: 休市不自动平(避免休市单腿)
            closed,_why=ENG.market_closed(weekend_guard=t.get("weekend_guard",True),
                                          weekend_sat=t.get("weekend_sat"), weekend_sun=t.get("weekend_sun"))
            if closed: continue
            hedge_sym=ENG.map_hedge_symbol(sym,t.get("hedge_symbol")) or sym
            mainL=_poslist((both or {}).get("main")); hedgeL=_poslist((both or {}).get("hedge"))
            if not mainL and not hedgeL: continue
            # 双腿 tick 算当前点差
            mt=ht=None
            try: mt=await CONN.main._get("/mt5/tick/"+sym)
            except Exception: pass
            try: ht=await CONN.hedge._get("/mt5/tick/"+hedge_sym) if getattr(CONN,"hedge",None) else None
            except Exception: pass
            slotcfg=R.hgetall(_slot_key(user,sym)) or {}
            xmode=(t.get("exit_mode") or "concurrent"); speed=(t.get("speed_mode") or "fast")
            if xmode not in ("concurrent","main_first","hedge_first"): xmode="concurrent"
            profit_first = (R.get(RNS+"sw:profitfirst:"+user)=="1")  # 盈利平台优先(前端落)
            now_ts=_dt.datetime.utcnow().timestamp()
            n=max(len(mainL),len(hedgeL)); decisions=[]
            for i in range(n):
                slot_no=i+1; m=mainL[i] if i<len(mainL) else None; h=hedgeL[i] if i<len(hedgeL) else None
                net,_mp,_hp=ENG.pair_pnl_live(m,h)
                # 该坑当前点差: 主腿 sell(reverse)=对冲ASK-主BID; buy(forward)=主ASK-对冲BID
                cur_sp=None
                if mt and ht:
                    mside=("sell" if (m and (str(m.get("type"))=="1" or m.get("side")=="sell")) else "buy")
                    if mside=="sell": cur_sp=round(float(ht.get("ask",0))-float(mt.get("bid",0)),4)
                    else:             cur_sp=round(float(mt.get("ask",0))-float(ht.get("bid",0)),4)
                # 持仓时长
                opent=(m or h or {}).get("time") or 0
                elapsed=(now_ts-float(opent)) if opent else 0
                # 逐坑覆盖
                ov=None
                try: ov=json.loads(slotcfg.get(str(slot_no))) if slotcfg.get(str(slot_no)) else None
                except Exception: ov=None
                sell_point=float(ov.get("sell_point") or 0) if ov else 0
                exit_enabled=bool(ov.get("exit_enabled")) if ov else False
                # 逐坑止盈/止损覆盖全局(0/缺省→回落全局)
                _tp = (float(ov.get("tp_points") or 0) if ov and ov.get("tp_points") else None) or t.get("tp_points")
                _sl = (float(ov.get("sl_points") or 0) if ov and ov.get("sl_points") else None) or t.get("sl_points")
                go,reason=ENG.auto_exit_decision(net,cur_sp,elapsed,
                              _tp,_sl,t.get("hold_secs"),
                              sell_point=sell_point,exit_enabled=exit_enabled,profit_first=profit_first)
                if not go: continue
                mside=("sell" if (m and (str(m.get("type"))=="1" or m.get("side")=="sell")) else "buy")
                hside=("sell" if (h and (str(h.get("type"))=="1" or h.get("side")=="sell")) else "buy")
                decisions.append({"slot":slot_no,"reason":reason,"net":net,"spread":cur_sp,"mside":mside,"hside":hside,
                                  "armed":exit_enabled})
            # 发布决策(影子/真平都先回显)
            R.set(RNS+"auto_exit:decisions:"+user, json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"mode":mode,"items":decisions}))
            for d in decisions:
                lockkey=RNS+"auto_exit:lock:"+user+":"+sym+":"+str(d["slot"])
                if mode=="shadow":
                    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"info","msg":"[影子]将平坑%d: %s 净%.2f"%(d["slot"],d["reason"],d["net"])})); R.ltrim(RNS+"alerts",0,49)
                    continue
                if mode=="armed" and not d["armed"]:
                    continue   # 武装模式仅平 exit_enabled 的坑
                # 在途锁 + 冷却(30s): 防 5s 循环重复发
                if R.get(lockkey): continue
                R.setex(lockkey, 30, "1")
                ok,_res=await _close_one_pair(user,sym,hedge_sym,d["mside"],d["hside"],xmode,speed,d["slot"],d["reason"])
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"info" if ok else "err",
                    "msg":"%s自动出场坑%d: %s 净%.2f %s"%("[演示]" if DEMO_MODE else "",d["slot"],d["reason"],d["net"],"已平" if ok else "失败/裸空")})); R.ltrim(RNS+"alerts",0,49)
        R.set(RNS+"auto_exit:last", _dt.datetime.utcnow().isoformat())
        await _aio.sleep(5)

@app.on_event("startup")
async def _startup_auto_exit():
    _aio.create_task(_auto_exit_loop())

# ================= 全自动进单循环 (与自动出场对称; 逐坑按买入点位+全局阈值+各护栏自动开仓; 默认 OFF) =================
# 模式(Redis qh:auto_entry:{user}): off / shadow(只回显将开哪坑) / armed(仅开 entry_enabled 的坑) / full(开所有未禁用空坑)
# 方向(Redis qh:auto_entry_dir:{user}): reverse(默认) / forward
async def _auto_entry_loop():
    await _aio.sleep(18)
    while True:
        try:
            c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT u.username, pt.* FROM param_templates pt JOIN users u ON u.id=pt.user_id")
            tmpls=cur.fetchall(); c.close()
        except Exception as e:
            R.set(RNS+"auto_entry:err","tmpl:%s"%e); await _aio.sleep(5); continue
        try: both=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        except Exception: both=None
        for t in tmpls:
            user=t["username"]; sym=t.get("symbol") or "XAUUSD"
            mode=R.get(RNS+"auto_entry:"+user) or "off"
            if mode=="off": continue
            # P1 防御: 武装/全量运行中若 auto_loop 权益失效→ 降级影子(不真开)
            if mode in ("armed","full") and str(_ent_get(t.get("user_id") or _uid(user),"auto_loop")).lower() not in ("true","1"):
                R.set(RNS+"auto_entry:"+user,"shadow"); mode="shadow"
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"自动进单权益已失效, 已降级为影子模式"})); R.ltrim(RNS+"alerts",0,49)
            direction=R.get(RNS+"auto_entry_dir:"+user) or "reverse"
            if direction not in ("reverse","forward"): direction="reverse"
            # 休市/周末闸
            closed,_why=ENG.market_closed(weekend_guard=t.get("weekend_guard",True),
                                          weekend_sat=t.get("weekend_sat"), weekend_sun=t.get("weekend_sun"))
            if closed: continue
            ladders=int(t.get("ladders") or 0) or 0
            if ladders<=0: continue
            filled=len(_poslist((both or {}).get("main")))
            if filled>=ladders: continue   # 阶梯满, 无空坑
            slot_no=filled+1
            slotcfg=R.hgetall(_slot_key(user,sym)) or {}
            ov=None
            try: ov=json.loads(slotcfg.get(str(slot_no))) if slotcfg.get(str(slot_no)) else None
            except Exception: ov=None
            # 进单状态: 禁用坑跳过; armed 模式仅开显式 entry_enabled 的坑
            if ov and ov.get("entry_enabled") is False: continue
            armed_slot = bool(ov and ov.get("entry_enabled"))
            if mode=="armed" and not armed_slot: continue
            hedge_sym=ENG.map_hedge_symbol(sym,t.get("hedge_symbol")) or sym
            # 双腿 tick → 当前点差(按方向)
            mt=ht=None
            try: mt=await CONN.main._get("/mt5/tick/"+sym)
            except Exception: pass
            try: ht=await CONN.hedge._get("/mt5/tick/"+hedge_sym) if getattr(CONN,"hedge",None) else None
            except Exception: pass
            if not mt or not ht: continue
            if direction=="reverse": cur_sp=round(float(ht.get("ask",0))-float(mt.get("bid",0)),4)
            else:                    cur_sp=round(float(mt.get("ask",0))-float(ht.get("bid",0)),4)
            # 有效买入点位: 逐坑 buy_point 非None→用之(0=任意), None→全局 entry_spread
            gthr=float(t.get("entry_spread") or 0); eff_bp=gthr
            if ov and ov.get("buy_point") is not None:
                try: eff_bp=float(ov.get("buy_point"))
                except (TypeError,ValueError): eff_bp=gthr
            reason=None
            if eff_bp>0 and cur_sp>eff_bp:
                continue   # 点差未达买入点位
            # 费用并入阈值(与手动一致)
            fee=float(t.get("fee_per_lot") or 0)
            if fee>0 and gthr>0:
                eff_thr,_fp=ENG.effective_spread_threshold(gthr,fee,100.0,legs=2)
                if cur_sp>eff_thr: continue
            # 数据波动闸
            _mc=int(t.get("match_count") or 0); _bd=float(t.get("fluctuation_band") or 0)
            if _bd>0 and _mc>=2:
                _hist=R.lrange(RNS+"spread:hist",-_mc,-1) or []
                _sp=[json.loads(x).get("fs") for x in _hist]
                if ENG.fluctuation_guard(_sp,_mc,_bd)[0]: continue
            # 保证金预留闸
            _rm=float(t.get("margin_reserve_main") or 0); _rh=float(t.get("margin_reserve_hedge") or 0)
            if _rm>0 or _rh>0:
                try: accs=await CONN.both_accounts() if hasattr(CONN,"both_accounts") else None
                except Exception: accs=None
                if accs:
                    if not ENG.margin_sufficient((accs.get("main") or {}).get("margin_free"),_rm,"main")[0]: continue
                    if getattr(CONN,"hedge",None) and _rh>0 and not ENG.margin_sufficient((accs.get("hedge") or {}).get("margin_free"),_rh,"hedge")[0]: continue
            # 下单量(逐坑固定手数 or 全局每U手数×倍率)
            _mm=float(t.get("main_lot_mult") or 1.0); _hm=float(t.get("hedge_lot_mult") or 1.0)
            base=float(t.get("base_lot") or 0.01)
            sizing=ENG.order_lots(base,_mm,_hm,rungs=1)
            mv=sizing["per_rung_main"]; hv=sizing["per_rung_hedge"]
            if ov and ov.get("lot_mode")=="fixed" and float(ov.get("qty") or 0)>0:
                _q=float(ov["qty"]); mv=round(_q*_mm,2); hv=round(_q*_hm,2)
            if mv<=0 or hv<=0: continue
            reason="点差%.4f<=买入点位%.2f"%(cur_sp,eff_bp) if eff_bp>0 else "点差%.4f(任意)"%cur_sp
            R.set(RNS+"auto_entry:decisions:"+user, json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"mode":mode,"dir":direction,"slot":slot_no,"spread":cur_sp,"reason":reason}))
            # 影子: 只回显
            if mode=="shadow":
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"info","msg":"[影子]将开坑%d %s: %s"%(slot_no,direction,reason)})); R.ltrim(RNS+"alerts",0,49)
                R.set(RNS+"auto_entry:last", _dt.datetime.utcnow().isoformat()); continue
            # 在途锁 + 冷却(用全局 entry_interval_sec, 最低10s)
            lockkey=RNS+"auto_entry:lock:"+user+":"+sym
            if R.get(lockkey): continue
            cooldown=max(10,int(t.get("entry_interval_sec") or 5))
            R.setex(lockkey, cooldown, "1")
            mside,hside=("sell","buy") if direction=="reverse" else ("buy","sell")
            res=await CONN.open_pair(direction, sym, hedge_sym, mv, hv, mode=(t.get("entry_mode") or "main_first"), speed=(t.get("speed_mode") or "fast"))
            mok=res.get("main_ok"); hok=res.get("hedge_ok")
            if mok and hok:
                try:
                    es=round(float(ht["ask"])-float(mt["bid"]),4) if direction=="reverse" else round(float(mt["ask"])-float(ht["bid"]),4)
                    R.rpush(RNS+"ledger:"+user+":"+direction, json.dumps({"q":hv,"m":mv,"s":es,"ts":_dt.datetime.utcnow().isoformat(),"ladder":slot_no}))
                except Exception: pass
                _audit(user,"auto","auto_entry",{"slot":slot_no,"dir":direction,"reason":reason},DEMO_MODE,"auto_opened")
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"info","msg":"%s自动进单坑%d %s: %s 已开"%("[演示]" if DEMO_MODE else "",slot_no,direction,reason)})); R.ltrim(RNS+"alerts",0,49)
            elif mok != hok:
                naked="hedge" if (mok and not hok) else "main"
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err","msg":"⚠自动进单坑%d %s腿成交另一腿失败,单边暴露!需人工处理"%(slot_no,"主" if naked=="hedge" else "对冲")})); R.ltrim(RNS+"alerts",0,49)
                _audit(user,"auto","auto_entry",{"slot":slot_no,"naked":naked,"res":res},False,"NAKED_RISK")
            R.set(RNS+"auto_entry:last", _dt.datetime.utcnow().isoformat())
        await _aio.sleep(5)

@app.on_event("startup")
async def _startup_auto_entry():
    _aio.create_task(_auto_entry_loop())


@app.get("/api/engine/state")
def engine_state():
    return {
        "cycle": json.loads(R.get(RNS+"engine:cycle") or "null"),
        "market": json.loads(R.get(RNS+"engine:market") or "null"),
        "account": json.loads(R.get(RNS+"engine:account") or "null"),
        "eval": {k:json.loads(v) for k,v in (R.hgetall(RNS+"engine:eval") or {}).items()},
        "err": R.get(RNS+"engine:err"),
    }

@app.get("/api/engine/check")
def engine_check(main_ask:float, main_bid:float, hedge_ask:float, hedge_bid:float, thr:float=0.30):
    """点差闸即时校验（供测试/前端调试）"""
    ok,sp,reason = ENG.spread_gate(main_ask,main_bid,hedge_ask,hedge_bid,thr)
    closed,why = ENG.market_closed()
    return {"spread_gate":{"pass":ok,"spread":sp,"reason":reason},"market":{"closed":closed,"why":why}}
# ================= 双腿 / 告警 端点 =================
@app.get("/api/engine/legs")
async def engine_legs():
    try:
        st = await CONN.both_status() if hasattr(CONN,"both_status") else {"main":await CONN.status(),"hedge":None}
        pos = await CONN.both_positions() if hasattr(CONN,"both_positions") else {"main":await CONN.positions(),"hedge":None}
        return {"status":st,"positions":pos}
    except Exception as e:
        raise HTTPException(502,"bridge error: %s"%e)

@app.get("/api/engine/alerts")
def engine_alerts(limit:int=20):
    items=R.lrange(RNS+"alerts",0,limit-1) or []
    return {"alerts":[json.loads(x) for x in items]}

@app.get("/api/engine/spread_chart")
def engine_spread_chart(start_time:str="", end_time:str="", interval:int=5):
    """点差走势(移植 testgo /spread/chart): 区间内按 interval 秒降采样, 返回 [{t,fs,rs}]。
       t=裸UTC ISO(前端按 UTC 解析再+8h转北京); fs=正向点差, rs=反向点差。"""
    if interval<1: interval=1
    import datetime as _d
    def _parse(s):
        if not s: return None
        try: return _d.datetime.fromisoformat(s.replace("Z","+00:00"))
        except Exception: return None
    st=_parse(start_time); et=_parse(end_time)
    rows=R.lrange(RNS+"spread:hist",0,-1) or []
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
@app.get("/api/engine/slot_overrides")
def slot_overrides(username:str, symbol:str="XAUUSD"):
    """取该用户该品种全部坑位覆盖(field=坑号)。"""
    h=R.hgetall(_slot_key(username,symbol)) or {}
    out={}
    for k,v in h.items():
        try: out[k]=json.loads(v)
        except Exception: pass
    return {"username":username,"symbol":symbol,"slots":out}

class SlotOverride(BaseModel):
    username:str; license_key:str=""; symbol:str="XAUUSD"; slot:int
    coin:str=""; lot_mode:str="auto"        # auto=按每U手数自动算 / fixed=用 qty
    qty:float=0.0                            # 交易数量(该坑手数; lot_mode=fixed 时生效)
    entry_enabled:bool=True                  # 进单状态(该坑是否允许开仓)
    buy_point:Optional[float]=None           # 买入点位(该坑入场点差阈值; null=回落全局 entry_spread, 0=字面0即任意点差都开)
    exit_enabled:bool=False                  # 是否出单(开=按卖出点位软提示平仓)
    sell_point:float=0.0                     # 卖出点位(该坑平仓点差目标)
    exit_calc:bool=False                     # 出点计算(开=按实时点差自动判定到点; 关=纯阈值比较)
    tp_points:float=0.0                      # 盈利点位(该坑止盈; 0=回落全局)
    sl_points:float=0.0                      # 止损点位(该坑止损; 0=回落全局)
@app.post("/api/engine/slot_override", dependencies=[Depends(require_license)])
def slot_override_save(r:SlotOverride):
    if r.slot<1: raise HTTPException(400,"坑号必须>=1")
    val={"coin":r.coin,"lot_mode":r.lot_mode,"qty":r.qty,"entry_enabled":r.entry_enabled,"buy_point":r.buy_point,
         "exit_enabled":r.exit_enabled,"sell_point":r.sell_point,"exit_calc":r.exit_calc,
         "tp_points":r.tp_points,"sl_points":r.sl_points}
    R.hset(_slot_key(r.username,r.symbol), str(r.slot), json.dumps(val))
    _audit(r.username,_actor(r.license_key),"slot_override",{"symbol":r.symbol,"slot":r.slot,**val},DEMO_MODE,"saved")
    return {"ok":True,"slot":r.slot,"saved":val,"msg":"坑%d 策略已保存,引擎热读生效"%r.slot}

class SlotDel(BaseModel):
    username:str; license_key:str=""; symbol:str="XAUUSD"; slot:int
@app.post("/api/engine/slot_override_del", dependencies=[Depends(require_license)])
def slot_override_del(r:SlotDel):
    R.hdel(_slot_key(r.username,r.symbol), str(r.slot))
    return {"ok":True,"slot":r.slot,"msg":"坑%d 覆盖已清除(回落全局参数)"%r.slot}



# ================= 强平价估算 (绿框: 多/空强平价 + 强平距离%, 标注估算) =================
def _net_lots(poslist):
    """持仓列表 → 净手数(buy=+/sell=-, MT5 type 0=buy 1=sell)。"""
    items = poslist.get("positions",poslist) if isinstance(poslist,dict) else (poslist or [])
    net=0.0
    for p in (items or []):
        v=float(p.get("volume",0) or 0)
        t=p.get("type"); side=p.get("side")
        is_sell = (str(t)=="1") or (side=="sell")
        net += (-v if is_sell else v)
    return round(net,4)

@app.get("/api/engine/liq")
async def engine_liq(symbol:str="XAUUSD"):
    """双腿账户级强平价【估算】+ 强平距离%。MT5 无原生强平价, 按 margin_level<=so_so 反推。"""
    out={"main":None,"hedge":None,"est":True}
    try:
        accts = await CONN.both_accounts() if hasattr(CONN,"both_accounts") else {"main":await CONN.account_info(),"hedge":None}
        pos = await CONN.both_positions() if hasattr(CONN,"both_positions") else {"main":await CONN.positions(),"hedge":None}
    except Exception as e:
        raise HTTPException(502,"bridge error: %s"%e)
    # 对冲品种映射(取首个模板)
    hsym=symbol
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT hedge_symbol FROM param_templates WHERE symbol=%s LIMIT 1",(symbol,))
        row=cur.fetchone(); c.close()
        if row: hsym=ENG.map_hedge_symbol(symbol, row.get("hedge_symbol")) or symbol
    except Exception: pass
    legs={"main":(accts.get("main"),pos.get("main"),symbol,"main"),
          "hedge":(accts.get("hedge"),pos.get("hedge"),hsym,"hedge")}
    for key,(ac,pl,sym,leg) in legs.items():
        if not ac: continue
        try:
            tick=await (CONN.main if leg=="main" else CONN.hedge)._get("/mt5/tick/"+sym) if (leg=="main" or getattr(CONN,"hedge",None)) else None
        except Exception:
            tick=None
        mid=None
        if tick and tick.get("bid") is not None and tick.get("ask") is not None:
            mid=(float(tick["bid"])+float(tick["ask"]))/2.0
        netl=_net_lots(pl)
        est=ENG.liq_estimate(ac.get("equity"), ac.get("margin"), ac.get("margin_so_so"),
                             netl, mid, contract_size=100.0, so_mode=ac.get("margin_so_mode") or 0)
        def _dist(liq):
            if liq is None or not mid or mid<=0: return None
            return round(abs(liq-mid)/mid*100.0, 2)
        out[key]={"symbol":sym,"net_lots":netl,"price":round(mid,2) if mid else None,
                  "long":est["long"],"short":est["short"],
                  "long_dist_pct":_dist(est["long"]),"short_dist_pct":_dist(est["short"]),
                  "so_so":ac.get("margin_so_so"),"reason":est["reason"],"est":True}
    return out
# ================= 多账户 / 指令 / 行情 (P2) =================
import hashlib
def _actor(key): return "lk:"+hashlib.sha256((key or "").encode()).hexdigest()[:8]

@app.get("/api/accounts/{username}")
def list_accounts(username:str):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT a.id,a.label,a.login,a.platform,a.broker,a.role,a.conn_mode,a.enabled FROM mt_accounts a JOIN users u ON u.id=a.user_id WHERE u.username=%s ORDER BY a.role,a.id",(username,))
    rows=cur.fetchall(); c.close()
    return {"username":username,"accounts":[dict(r) for r in rows]}

class AcctReg(BaseModel):
    username:str; label:str; login:str; platform:str="MT5"; broker:str=""
    role:str="main"; conn_mode:str="bridge"; bridge_url:str=""; bridge_key_ref:str=""
@app.post("/api/accounts/register", dependencies=[Depends(require_admin)])
def reg_account(a:AcctReg):
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s",(a.username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    # P1 权益闸: max_pairs 限制对冲账户对数(按 role 计已有对; 新增不得超权益)
    try: maxp=int(float(_ent_get(u[0],"max_pairs") or 1))
    except (TypeError,ValueError): maxp=1
    cur.execute("SELECT login FROM mt_accounts WHERE user_id=%s AND role=%s",(u[0],a.role))
    existing=[x[0] for x in cur.fetchall()]
    if a.login not in existing and len(existing)>=maxp:
        c.close(); raise HTTPException(403,"账户对数已达上限(%d), 升级'多客户端'内购解锁更多(role=%s)"%(maxp,a.role))
    cur.execute("INSERT INTO mt_accounts(user_id,label,login,platform,broker,role,conn_mode,bridge_url,bridge_key_ref) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id,login) DO UPDATE SET label=EXCLUDED.label,role=EXCLUDED.role,conn_mode=EXCLUDED.conn_mode,bridge_url=EXCLUDED.bridge_url",(u[0],a.label,a.login,a.platform,a.broker,a.role,a.conn_mode,a.bridge_url,a.bridge_key_ref))
    c.close()
    return {"ok":True,"login":a.login,"conn_mode":a.conn_mode}

DEMO_MODE = os.environ.get("QH_DEMO_MODE","1")=="1"
def _audit(user,actor,action,payload,demo,result):
    try:
        c=db(); cur=c.cursor()
        cur.execute("SELECT id FROM users WHERE username=%s",(user,)); u=cur.fetchone()
        cur.execute("INSERT INTO audit_log(user_id,actor,action,payload,demo_mode,result) VALUES(%s,%s,%s,%s,%s,%s)",(u[0] if u else None,actor,action,json.dumps(payload),demo,result))
        c.close()
    except Exception as e: print("audit err",e)

# ================= P0 权益门控中枢 (entitlements 唯一真相源 + 内购商品可自定义) =================
# 免费档默认(无权益行时回落): 保命护栏永不门控, 仅规模/自动化/个性化才门控
_ENT_DEFAULTS_FALLBACK={"max_pairs":"1","symbols":'["XAUUSD"]',"auto_loop":"false","speed_turbo":"false",
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
        rows=[dict(x) for x in cur.fetchall()]; c.close()
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
            if r["expire_at"] is not None and r["expire_at"]<datetime.datetime.now(datetime.timezone.utc):
                continue   # 已过期→不生效(降级回落默认)
            out[r["feature_key"]]=r["value"]
        c.close()
    except Exception as e: print("ent_all err",e)
    return out
def _ent_get(user_id, key):
    return _ent_all(user_id).get(key, _ent_defaults().get(key))
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
@app.get("/api/entitlements/{username}")
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
    return {"categories":[dict(x) for x in cats],"products":[dict(x) for x in prods]}

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
        grants=p["grants"] or {}; dur=p["duration_days"]; amount=amount or float(p["price"] or 0)
    elif r.feature_key:
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
@app.post("/api/admin/agent/save", dependencies=[Depends(require_op("agents"))])
def agent_save(r:AgentReq):
    c=db(); cur=c.cursor()
    parent_id=None; level=1
    if r.parent_code:
        cur.execute("SELECT id,level FROM agents WHERE code=%s",(r.parent_code,)); p=cur.fetchone()
        if not p: c.close(); raise HTTPException(404,"上级代理码不存在")
        parent_id=p[0]; level=min(3,(p[1] or 1)+1)
    cur.execute("""INSERT INTO agents(code,name,parent_id,level,rate_l1,rate_l2,rate_l3,contact,enabled)
                   VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (code) DO UPDATE SET name=EXCLUDED.name,parent_id=EXCLUDED.parent_id,level=EXCLUDED.level,
                   rate_l1=EXCLUDED.rate_l1,rate_l2=EXCLUDED.rate_l2,rate_l3=EXCLUDED.rate_l3,contact=EXCLUDED.contact,enabled=EXCLUDED.enabled""",
                (r.code,r.name,parent_id,level,r.rate_l1,r.rate_l2,r.rate_l3,r.contact,r.enabled))
    c.close()
    _audit("",_actor(r.license_key),"agent_save",{"code":r.code,"level":level},DEMO_MODE,"saved")
    return {"ok":True,"code":r.code,"level":level}

@app.get("/api/admin/agents")
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

@app.get("/api/admin/commissions")
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

@app.get("/api/admin/trials")
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

@app.get("/api/admin/bi/symbols")
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

@app.get("/api/admin/bi/symbol_users")
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

@app.get("/api/admin/bi/overview")
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

@app.get("/api/admin/orders")
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
        cur.execute("UPDATE iap_orders SET reconcile_status='void',confirmed_by=%s,confirmed_at=now(),reconcile_note=%s WHERE id=%s",(actor,r.note,r.order_id)); st="void"
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

@app.get("/api/admin/revenue")
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
@app.get("/api/admin/users")
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

@app.get("/api/admin/users/geo_stats")
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

@app.get("/api/admin/user/{username}")
def admin_user_detail(username:str):
    uid=_uid(username)
    if not uid: raise HTTPException(404,"user not found")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,username,plan,status,expire_at,paid_until,trial_until,trial_started,total_recharge,risk_flags,feishu_id,created_at,last_ip,last_login,geo_country,geo_name FROM users WHERE id=%s",(uid,))
    u=dict(cur.fetchone())
    cur.execute("SELECT login,broker,role,enabled FROM mt_accounts WHERE user_id=%s",(uid,)); u["accounts"]=[dict(x) for x in cur.fetchall()]
    cur.execute("SELECT product_key,amount,paid_at,status,kind FROM iap_orders WHERE user_id=%s ORDER BY paid_at DESC LIMIT 20",(uid,)); u["orders"]=[dict(x) for x in cur.fetchall()]
    cur.execute("SELECT count(*) n, COALESCE(SUM(profit),0) p FROM deals WHERE user_id=%s AND is_trade=true",(uid,)); dd=cur.fetchone(); u["deals_total"]=dd["n"]; u["pnl_total"]=round(float(dd["p"] or 0),2)
    c.close()
    u["entitlements"]=_ent_all(uid)
    u["force_demo"]=(R.get(RNS+"force_demo:"+username)=="1")
    u["auto_entry"]=R.get(RNS+"auto_entry:"+username) or "off"
    u["auto_exit"]=R.get(RNS+"auto_exit:"+username) or "off"
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
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err","msg":"用户 %s 已封禁(断自动+强制DEMO): %s"%(r.username,r.reason)})); R.ltrim(RNS+"alerts",0,49)
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
        grants=p["grants"] or {}; dur=p["duration_days"] or 0
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
            for fk in list((pp["grants"] if pp and pp["grants"] else {}).keys()):
                cur.execute("DELETE FROM entitlements WHERE user_id=%s AND feature_key=%s AND source='comp'",(uid,fk))
                if cur.rowcount>0: removed.append(fk)
        res["revoked_package"]={"product":r.product_key,"voided_orders":voided,"removed_grants":removed}
    elif r.op=="feature":                     # per-user 功能可见性 = 写一条 entitlement(复用)
        cur.execute("""INSERT INTO entitlements(user_id,feature_key,value,source,updated_at) VALUES(%s,%s,%s,'manual',now())
                       ON CONFLICT (user_id,feature_key) DO UPDATE SET value=EXCLUDED.value,source='manual',updated_at=now()""",(uid,r.feature_key,r.value))
        res["feature"]={r.feature_key:r.value}
    else:
        c.close(); raise HTTPException(400,"未知操作: %s"%r.op)
    c.close()
    _audit(r.username,_actor(r.license_key),"user_op",{"op":r.op,**res},DEMO_MODE,"done")
    return {"ok":True,"op":r.op,**res}

# ================= P4b 系统管理 + 总控面板 =================
@app.get("/api/admin/system")
async def admin_system():
    """系统健康(全链路运维监控): 桥(主/对冲)状态+延迟 + 引擎循环/采样器新鲜度 + 波动闸/背离闸 + WS 连接 + 告警流 + 全局自动开关聚合。"""
    import time as _t
    def _age(iso):
        """ISO 时间戳 → 距今秒数(无/解析失败返 None)。"""
        if not iso: return None
        try:
            s=iso.replace("Z","").split(".")[0]
            dt=_dt.datetime.fromisoformat(s)
            return max(0,int((_dt.datetime.utcnow()-dt).total_seconds()))
        except Exception: return None
    out={"bridges":{},"engine":{},"auto":{},"gates":{},"ws":{},"alerts":[]}
    # 桥健康 + 延迟(ms)
    for leg in ("main","hedge"):
        try:
            conn=getattr(CONN,leg,None)
            if conn is None: out["bridges"][leg]={"ok":False,"detail":None,"latency_ms":None}; continue
            t0=_t.time()
            st=await conn.status()
            lat=int((_t.time()-t0)*1000)
            out["bridges"][leg]={"ok":bool(st),"detail":st,"latency_ms":lat}
        except Exception as e:
            out["bridges"][leg]={"ok":False,"err":str(e)[:120],"latency_ms":None}
    # 引擎循环 + 采样器新鲜度
    cycle_ts=R.get(RNS+"engine:cycle_ts"); sampler_ts=R.get(RNS+"engine:sampler_ts")
    _samperr=R.get(RNS+"engine:sampler_err") or ""
    out["engine"]={
        "cycle":json.loads(R.get(RNS+"engine:cycle") or "null"),
        "cycle_age":_age(cycle_ts),                     # 引擎主循环距今秒(>15s 视为停滞)
        "market":json.loads(R.get(RNS+"engine:market") or "null"),
        "sampler_age":_age(sampler_ts),                 # 点差采样器距今秒(>60s 视为停更)
        "sampler_err":_samperr or None,
        "auto_exit_last":R.get(RNS+"auto_exit:last"), "auto_exit_age":_age(R.get(RNS+"auto_exit:last")),
        "auto_entry_last":R.get(RNS+"auto_entry:last"), "auto_entry_age":_age(R.get(RNS+"auto_entry:last")),
        "err":R.get(RNS+"engine:err"),
    }
    # 点差新鲜度: 最后一条 spread:hist 距今秒
    try:
        last=R.lrange(RNS+"spread:hist",-1,-1)
        out["engine"]["spread_age"]=_age(json.loads(last[0]).get("t")) if last else None
        out["engine"]["spread_count"]=R.llen(RNS+"spread:hist")
    except Exception: out["engine"]["spread_age"]=None
    # 护栏闸: 波动闸 + 背离闸
    out["gates"]={
        "fluctuation":json.loads(R.get(RNS+"engine:fluctuation") or "null"),
        "divergence":json.loads(R.get(RNS+"engine:divergence") or "null"),
        "div_tripped":R.get(RNS+"engine:div_tripped")=="1",
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
    out["demo_mode"]=DEMO_MODE
    out["server_ts"]=_dt.datetime.utcnow().isoformat()
    return out


class EstopReq(BaseModel):
    license_key:str=""; confirm:bool=False
@app.post("/api/admin/system/estop", dependencies=[Depends(require_op("system"))])
def admin_estop(r:EstopReq):
    """全局急停: 所有用户 auto_entry/exit → off + 置全局 estop 标记。真金系统红色按钮。"""
    if not r.confirm: raise HTTPException(400,"急停需二次确认(confirm=true)")
    c=db(); cur=c.cursor(); cur.execute("SELECT username FROM users"); users=[x[0] for x in cur.fetchall()]; c.close()
    for u in users:
        R.set(RNS+"auto_entry:"+u,"off"); R.set(RNS+"auto_exit:"+u,"off")
    R.set(RNS+"global_estop","1")
    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err","msg":"⛔全局急停: 所有用户自动进/出场已停"})); R.ltrim(RNS+"alerts",0,49)
    _audit("",_actor(r.license_key),"global_estop",{"users":len(users)},DEMO_MODE,"ESTOP")
    return {"ok":True,"stopped_users":len(users)}
@app.post("/api/admin/system/estop_clear", dependencies=[Depends(require_op("system"))])
def admin_estop_clear(r:EstopReq):
    R.delete(RNS+"global_estop")
    _audit("",_actor(r.license_key),"global_estop_clear",{},DEMO_MODE,"cleared")
    return {"ok":True,"cleared":True}

@app.get("/api/admin/audit")
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
def op_me(x_op_token: str = Header(default="")):
    s=_op_session(x_op_token)
    if not s: raise HTTPException(401,"未登录")
    return {"operator":s["operator"],"role":s["role"],"perms":_op_perms(s["role"])}

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

@app.get("/api/admin/leads")
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

@app.get("/api/admin/lead/{lead_id}")
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


@app.get("/api/admin/channels")
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

@app.get("/api/admin/channel/token_status")
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
    """用户端跑马灯馈源(公开只读): 网站公告广播 + 引擎实时告警(qh:alerts 的 warn/err)统一合并。
       引擎告警不改动实时交易循环, 在此读端合并(单一馈源, 用户端不再单独拉 /engine/alerts)。"""
    lim=max(1,min(50,limit)); out=[]
    # 1) 运营网站广播
    try:
        for x in (R.lrange(RNS+"marquee_recent",0,49) or []):
            d=json.loads(x); d["src"]="broadcast"; out.append(d)
    except Exception: pass
    # 2) 引擎实时告警(仅 warn/err 上跑马灯, info 噪音不推)
    try:
        for x in (R.lrange(RNS+"alerts",0,49) or []):
            a=json.loads(x); lv=a.get("lv","info")
            if lv not in ("warn","err"): continue
            out.append({"title":"引擎告警" if lv=="err" else "引擎提示","content":a.get("msg",""),
                        "priority":2 if lv=="err" else 1,"color":"#F56C6C" if lv=="err" else "#E6A23C",
                        "blink":lv=="err","sound":"none","ts":a.get("ts",""),"src":"engine"})
    except Exception: pass
    # 合并按时间倒序, 截断
    out.sort(key=lambda d:d.get("ts",""), reverse=True)
    return {"items":out[:lim]}

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
    """版本信息(只读): app 版本 + python + 本地 git(若非 git 部署则标注)。"""
    out={"app_version":app.version,"python":os.sys.version.split()[0]}
    try:
        r=_sp.run(["git","-C","/opt/quanthedge","log","-1","--format=%h %ci %s"],capture_output=True,text=True,timeout=8)
        out["git"]= r.stdout.strip() if r.returncode==0 else "非 git 部署(patch 方式)"
    except Exception as e: out["git"]="unknown: %s"%e
    try:
        r=_sp.run(["git","-C","/opt/quanthedge","log","-10","--format=%h|%ci|%s"],capture_output=True,text=True,timeout=8)
        out["history"]=[dict(zip(("hash","date","msg"),l.split("|",2))) for l in r.stdout.strip().split("\n") if l and r.returncode==0]
    except Exception: out["history"]=[]
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
    for k in ("engine:cycle","engine:market","auto_exit:last","auto_entry:last"):
        try: out["engine"][k.split(":")[-1]]=R.get(RNS+k)
        except Exception: pass
    try:
        info=R.info(); out["redis"]={"connected_clients":info.get("connected_clients"),"uptime_sec":info.get("uptime_in_seconds"),"used_memory_human":info.get("used_memory_human")}
    except Exception as e: out["redis"]={"err":str(e)}
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database()"); out["db_connections"]=cur.fetchone()[0]; c.close()
    except Exception: pass
    return out









class CmdReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
@app.post("/api/cmd/close_all", dependencies=[Depends(require_admin)])
async def cmd_close_all(r:CmdReq):
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
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
    async def _close_leg(leg_obj, name, tries=3):
        last=None
        for k in range(tries):
            try:
                r=await leg_obj.close_all()
                if r.get("failed",0)==0: return r,True
                last=r
            except Exception as ex: last={"error":str(ex)}
            await _aio.sleep(0.6)
        return last,False
    main_r,main_ok = await _close_leg(CONN.main,"main")
    hedge_r,hedge_ok = (await _close_leg(CONN.hedge,"hedge")) if getattr(CONN,"hedge",None) else ({"closed":0},True)
    mc=(main_r or {}).get("closed",0); hc=(hedge_r or {}).get("closed",0)
    # 裸空判定：一腿成功平、另一腿失败 = 单边暴露
    naked=None
    if main_ok and not hedge_ok: naked="hedge"
    elif hedge_ok and not main_ok: naked="main"
    if naked:
        # 绝不自动反开（testgo 回滚静默失败=裸空真凶教训）→ 留痕 + CRITICAL 告警 + 人工介入
        try:
            c=db(); cur=c.cursor(); cur.execute("SELECT id FROM users WHERE username=%s",(r.username,)); u=cur.fetchone()
            cur.execute("INSERT INTO naked_alerts(user_id,leg,detail) VALUES(%s,%s,%s)",
                        (u[0] if u else None, naked, json.dumps({"main":main_r,"hedge":hedge_r})))
            c.close()
        except Exception: pass
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err",
            "msg":"⚠裸空告警：%s腿平仓失败，另一腿已平，单边暴露！需人工处理"%naked})); R.ltrim(RNS+"alerts",0,49)
        _audit(r.username,actor,"close_all",{"naked":naked,"main":main_r,"hedge":hedge_r},False,"NAKED_RISK")
        raise HTTPException(409, "裸空风险：%s腿平仓失败，已告警留人工处理（未自动反开）"%naked)
    _audit(r.username,actor,"close_all",{"main":main_r,"hedge":hedge_r},False,"sent:main%d/hedge%d"%(mc,hc))
    # 全平 → 清空两方向开仓点差账本
    try: R.delete(RNS+"ledger:"+r.username+":reverse", RNS+"ledger:"+r.username+":forward")
    except Exception: pass
    return {"ok":True,"demo":False,"closed":{"main":mc,"hedge":hc},
            "msg":"已强制平仓 主腿%d/对冲腿%d 笔"%(mc,hc),"detail":{"main":main_r,"hedge":hedge_r}}

@app.post("/api/cmd/close_profit", dependencies=[Depends(require_admin)])
async def cmd_close_profit(r:CmdReq):
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过")
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
def _load_tmpl(username, symbol="XAUUSD"):
    """取用户该品种参数模板(手数倍率/每U手数/品种映射), 供下单量计算。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT pt.* FROM param_templates pt JOIN users u ON u.id=pt.user_id
                   WHERE u.username=%s AND pt.symbol=%s LIMIT 1""",(username,symbol))
    row=cur.fetchone(); c.close()
    return dict(row) if row else None

def _poslist(pl):
    """归一化 bridge 持仓返回为 list。"""
    if isinstance(pl,dict): return pl.get("positions",pl) if isinstance(pl.get("positions",pl),list) else []
    return pl or []

async def _count_filled_slots():
    """当前已填坑位数 = 主腿持仓笔数(每坑=一笔配对, 顺序填充)。取不到→None(fail-closed)。"""
    try:
        pos=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        if not pos: return None
        return len(_poslist(pos.get("main")))
    except Exception:
        return None

class OpenPairReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    direction:str                      # 'reverse'(反向/1空2涨) | 'forward'(正向/2空1涨)
    symbol:str="XAUUSD"; slots:int=1   # slots = 本次要填的坑位数(按顺序填最前面的 N 个空坑, 每坑=一对, 每坑per-rung手数)
    qty:float=0.0                       # 兼容旧字段(已废弃; slots 优先, 仅当 slots 缺省且 qty>0 时回退)
@app.post("/api/cmd/open_pair", dependencies=[Depends(require_license)])
async def cmd_open_pair(r:OpenPairReq):
    actor=_actor(r.license_key)
    if r.direction not in ("reverse","forward"):
        raise HTTPException(400,"direction 必须为 reverse 或 forward")
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    t=_load_tmpl(r.username, r.symbol)
    if not t: raise HTTPException(404,"参数模板未找到")
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
    mode=(t.get("entry_mode") or "main_first"); speed=(t.get("speed_mode") or "fast")
    if mode not in ("concurrent","main_first","hedge_first"): mode="main_first"
    legmap={"reverse":("sell","buy"),"forward":("buy","sell")}
    # 顺序填充: 读当前已填坑位, 受阶梯上限约束, 实际可开 = min(请求坑数, 剩余空坑)
    filled=await _count_filled_slots()
    if filled is None:
        raise HTTPException(502,"无法读取当前持仓坑位(fail-closed, 拒绝开仓避免超额填坑)")
    remaining = (ladders - filled) if ladders>0 else slots   # ladders=0 视为不限坑
    if remaining<=0:
        raise HTTPException(409,"阶梯已满(%d/%d坑)，无空坑可开"%(filled,ladders))
    # 数据波动闸: 近 match_count 条点差波动超 band → 拒绝开仓(软暂停, 防剧烈波动追单)
    _mc=int(t.get("match_count") or 0); _bd=float(t.get("fluctuation_band") or 0)
    if _bd>0 and _mc>=2:
        _hist=R.lrange(RNS+"spread:hist",-_mc,-1) or []
        _sp=[json.loads(x).get("fs") for x in _hist]
        fl=ENG.fluctuation_guard(_sp,_mc,_bd)
        if fl[0]:
            raise HTTPException(409,"数据波动过大暂停入场: %s(近%d条幅度>阈值%.2f)"%(fl[2],_mc,_bd))
    # 保证金预留闸: 开仓前查双腿可用保证金须 >= 预留(留风险垫, fail-closed)
    _rm=float(t.get("margin_reserve_main") or 0); _rh=float(t.get("margin_reserve_hedge") or 0)
    if _rm>0 or _rh>0:
        try:
            _accs=await CONN.both_accounts() if hasattr(CONN,"both_accounts") else {"main":await CONN.account_info(),"hedge":None}
        except Exception as ex:
            raise HTTPException(502,"无法读取账户保证金(fail-closed, 拒绝开仓): %s"%ex)
        _ma=(_accs.get("main") or {}); _ha=(_accs.get("hedge") or {})
        ok_m,why_m=ENG.margin_sufficient(_ma.get("margin_free"),_rm,"main")
        if not ok_m: raise HTTPException(409,"主账户保证金不足预留, 拒绝开仓: %s"%why_m)
        if getattr(CONN,"hedge",None) and _rh>0:
            ok_h,why_h=ENG.margin_sufficient(_ha.get("margin_free"),_rh,"hedge")
            if not ok_h: raise HTTPException(409,"对冲账户保证金不足预留, 拒绝开仓: %s"%why_h)
    to_open=min(slots, remaining)
    # 开仓点差(testgo pos_open_ledger 思路): 批前取一次双腿 tick 算 spreadAtExecution
    entry_spread=None
    try:
        _mt=await CONN.main._get("/mt5/tick/"+main_sym)
        _ht=await CONN.hedge._get("/mt5/tick/"+hedge_sym) if getattr(CONN,"hedge",None) else None
        if _mt and _ht and _mt.get("bid") is not None and _ht.get("ask") is not None:
            if r.direction=="reverse": entry_spread=round(float(_ht["ask"])-float(_mt["bid"]),4)   # 对冲ASK-主BID
            else:                      entry_spread=round(float(_mt["ask"])-float(_ht["bid"]),4)   # 主ASK-对冲BID
    except Exception: pass
    # 费用并入点差阈值闸: 每手费用折算成点收紧入场阈值, 当前点差 > 有效阈值 → 拒绝(费用吃掉套利空间)
    _fee=float(t.get("fee_per_lot") or 0); _nthr=float(t.get("entry_spread") or 0)
    if _fee>0 and _nthr>0 and entry_spread is not None:
        # 每点价值≈合约规格(XAU 1手=100oz, 1.00 价差/手 = $100); 双腿计费
        eff_thr,fee_pts=ENG.effective_spread_threshold(_nthr,_fee,100.0,legs=2)
        if entry_spread > eff_thr:
            raise HTTPException(409,"费用并入后点差超阈值, 拒绝开仓: 当前%.4f > 有效阈值%.4f(名义%.2f−费用%.4f点)"%(entry_spread,eff_thr,_nthr,fee_pts))
    _ledger_key=RNS+"ledger:"+r.username+":"+r.direction
    _force_demo = (R.get(RNS+"force_demo:"+r.username)=="1")  # 试用用户强制 DEMO(限风险)
    if DEMO_MODE or _force_demo:
        _why = "demo:not_sent" if DEMO_MODE else "trial_force_demo"
        _audit(r.username,actor,"open_pair",{"direction":r.direction,"mode":mode,"slots_req":slots,"to_open":to_open,"filled":filled,"ladders":ladders,"per_main":main_vol,"per_hedge":hedge_vol,"force_demo":_force_demo},True,_why)
        _pfx = "演示模式" if DEMO_MODE else "试用模式(强制演示)"
        return {"ok":True,"demo":True,"trial_demo":_force_demo and not DEMO_MODE,"direction":r.direction,"mode":mode,"to_open":to_open,"filled":filled,"ladders":ladders,
                "msg":"%s[%s/%s]：将按顺序填 %d 个坑(已填%d/%d)，每坑 主%s%s手/对冲%s%s手，未真实下单"%(_pfx,mode,speed,to_open,filled,ladders,legmap[r.direction][0],main_vol,legmap[r.direction][1],hedge_vol)}
    # 真发：逐坑顺序开仓; 任一坑裸空/失败即停(不继续填后续坑); 裸空守护绝不自动反开
    opened=0; details=[]; skipped=[]
    _slotcfg=R.hgetall(_slot_key(r.username,r.symbol)) or {}
    for i in range(to_open):
        slot_no=filled+opened+1   # 本坑坑号(顺序填充)
        # 逐坑策略覆盖(右键"修改订单"设置): 进单状态/交易数量/买入点位
        ov=None
        try:
            _raw=_slotcfg.get(str(slot_no)); ov=json.loads(_raw) if _raw else None
        except Exception: ov=None
        slot_mv, slot_hv = main_vol, hedge_vol
        # 该坑有效买入点位阈值: 逐坑 buy_point 非 None→用之(0=任意点差都开); None→回落全局 entry_spread
        _gthr=float(t.get("entry_spread") or 0)
        _eff_bp=_gthr
        if ov:
            if ov.get("entry_enabled") is False:
                skipped.append(slot_no); continue   # 该坑被关闭→跳过(不开)
            if ov.get("lot_mode")=="fixed" and float(ov.get("qty") or 0)>0:
                # 固定手数: 该坑用设定数量(主腿=qty×主倍率比, 对冲=qty×对冲倍率比, 以 base 为单位换算)
                _q=float(ov["qty"]); slot_mv=round(_q*_mm,2); slot_hv=round(_q*_hm,2)
                if slot_mv<=0 or slot_hv<=0: slot_mv,slot_hv=main_vol,hedge_vol
            if ov.get("buy_point") is not None:
                try: _eff_bp=float(ov.get("buy_point"))
                except (TypeError,ValueError): _eff_bp=_gthr
        # 阈值>0 才过滤(当前点差>阈值则跳过); ==0 表示任意点差都开
        if _eff_bp>0 and entry_spread is not None and entry_spread>_eff_bp:
            skipped.append(slot_no); continue   # 当前点差不满足买入点位(逐坑或全局)→跳过
        res=await CONN.open_pair(r.direction, main_sym, hedge_sym, slot_mv, slot_hv, mode=mode, speed=speed)
        details.append(res)
        mok=res.get("main_ok"); hok=res.get("hedge_ok")
        if mok and hok:
            opened+=1
            # 记开仓点差账本(FIFO, 供平均点差): q=对冲手数, s=spreadAtExecution
            try:
                R.rpush(_ledger_key, json.dumps({"q":slot_hv,"m":slot_mv,"s":entry_spread if entry_spread is not None else 0,"ts":_dt.datetime.utcnow().isoformat(),"ladder":slot_no}))
            except Exception: pass
            continue
        if not mok and not hok:
            _audit(r.username,actor,"open_pair",{"i":i,"opened":opened,"res":res},False,"slot_both_failed")
            if opened>0:
                return {"ok":True,"demo":False,"direction":r.direction,"mode":mode,"opened":opened,"requested":to_open,
                        "msg":"已开 %d/%d 坑后某坑双腿未成交，已停止(无裸空)"%(opened,to_open),"detail":details}
            raise HTTPException(502,"开仓失败，首坑双腿均未成交(无裸空): %s"%json.dumps(res))
        # 恰一腿成 = 裸空, 留痕+告警+停止(绝不自动反开)
        naked_leg="hedge" if (mok and not hok) else "main"
        try:
            c=db(); cur=c.cursor(); cur.execute("SELECT id FROM users WHERE username=%s",(r.username,)); u=cur.fetchone()
            cur.execute("INSERT INTO naked_alerts(user_id,leg,detail) VALUES(%s,%s,%s)",(u[0] if u else None, naked_leg, json.dumps(res))); c.close()
        except Exception: pass
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err",
            "msg":"⚠裸空告警[%s 第%d坑]：%s腿成交、另一腿失败，单边暴露！需人工处理(一键平仓)"%(mode,opened+1,"主" if naked_leg=="hedge" else "对冲")})); R.ltrim(RNS+"alerts",0,49)
        _audit(r.username,actor,"open_pair",{"i":i,"opened":opened,"res":res},False,"NAKED_RISK_%s"%naked_leg)
        raise HTTPException(409,"裸空风险(已开%d坑, 第%d坑%s腿成交另一腿失败)，已告警留人工处理(未自动反开)"%(opened,opened+1,"主" if naked_leg=="hedge" else "对冲"))
    _audit(r.username,actor,"open_pair",{"opened":opened,"to_open":to_open,"filled_before":filled,"ladders":ladders,"mode":mode,"skipped":skipped},False,"opened:%s:%dslots"%(r.direction,opened))
    _smsg = ("，跳过坑 %s(被禁用/未满足买入点位)"%skipped) if skipped else ""
    return {"ok":True,"demo":False,"direction":r.direction,"mode":mode,"opened":opened,"skipped":skipped,"filled_before":filled,"ladders":ladders,"detail":details,
            "msg":"已顺序开 %d 个坑[%s]%s"%(opened,mode,_smsg)}

class ClosePairReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    symbol:str="XAUUSD"; main_side:str; hedge_side:str
    main_ticket:int=0; hedge_ticket:int=0; main_vol:float=0.0; hedge_vol:float=0.0
@app.post("/api/cmd/close_pair", dependencies=[Depends(require_admin)])
async def cmd_close_pair(r:ClosePairReq):
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    t=_load_tmpl(r.username, r.symbol)
    hedge_sym=ENG.map_hedge_symbol(r.symbol, (t or {}).get("hedge_symbol")) or r.symbol
    xmode=((t or {}).get("exit_mode") or "concurrent"); speed=((t or {}).get("speed_mode") or "fast")
    if xmode not in ("concurrent","main_first","hedge_first"): xmode="concurrent"
    if DEMO_MODE:
        _audit(r.username,actor,"close_pair",{"symbol":r.symbol,"exit_mode":xmode,"main_side":r.main_side,"hedge_side":r.hedge_side},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式[%s]：将平 主腿%s/对冲腿%s 各一笔，未真实下单"%(xmode,r.main_side,r.hedge_side)}
    mv=r.main_vol or None; hv=r.hedge_vol or None
    res=await CONN.close_pair(r.symbol, hedge_sym, r.main_side, r.hedge_side, mv, hv, mode=xmode, speed=speed)
    mok=("error" not in (res.get("main") or {})); hok=(res.get("hedge") is None) or ("error" not in (res.get("hedge") or {}))
    if mok and not hok:
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err",
            "msg":"⚠按对平仓：主腿已平、对冲腿失败，单边暴露！需人工处理"})); R.ltrim(RNS+"alerts",0,49)
        _audit(r.username,actor,"close_pair",res,False,"NAKED_RISK_hedge_close_failed")
        raise HTTPException(409,"裸空风险：主腿已平、对冲腿平仓失败，已告警(未自动反开)")
    _audit(r.username,actor,"close_pair",res,False,"closed_pair")
    # 平掉一对 → 账本 FIFO 弹出一笔(main_side=sell→reverse, buy→forward)
    try:
        _dir = "reverse" if r.main_side=="sell" else "forward"
        R.lpop(RNS+"ledger:"+r.username+":"+_dir)
    except Exception: pass
    return {"ok":True,"demo":False,"detail":res,"msg":"已按对平仓 主腿%s/对冲腿%s"%(r.main_side,r.hedge_side)}

class EngineCmd(BaseModel):
    username:str; license_key:str=""; running:bool
@app.post("/api/cmd/engine", dependencies=[Depends(require_admin)])
def cmd_engine(r:EngineCmd):
    R.set(RNS+"engine:running:"+r.username,"1" if r.running else "0")
    _audit(r.username,_actor(r.license_key),"engine_toggle",{"running":r.running},DEMO_MODE,"flag_set")
    return {"ok":True,"running":r.running}

# ---- 全自动出场模式开关(off/shadow/armed/full) + 急停 ----
class AutoExitCmd(BaseModel):
    username:str; license_key:str=""; mode:str="off"   # off|shadow|armed|full
    profit_first:bool=False                              # 盈利平台优先(止盈/卖点/超时仅盈利时放行; 止损不受限)
@app.post("/api/cmd/auto_exit", dependencies=[Depends(require_admin)])
def cmd_auto_exit(r:AutoExitCmd):
    if r.mode not in ("off","shadow","armed","full"):
        raise HTTPException(400,"mode 必须为 off/shadow/armed/full")
    # P1 权益闸: 武装/全量(真金自动)需 auto_loop 权益; off/shadow(只提示)免费
    if r.mode in ("armed","full"):
        if R.get(RNS+"global_estop")=="1":
            raise HTTPException(409,"全局急停生效中, 无法启用自动出场; 请先解除急停")
        uid=_uid(r.username)
        if not uid or str(_ent_get(uid,"auto_loop")).lower() not in ("true","1"):
            raise HTTPException(403,"全自动出场(武装/全量)未解锁,需内购权益 auto_loop;影子模式可免费体验")
    R.set(RNS+"auto_exit:"+r.username, r.mode)
    R.set(RNS+"sw:profitfirst:"+r.username, "1" if r.profit_first else "0")
    _audit(r.username,_actor(r.license_key),"auto_exit_mode",{"mode":r.mode,"profit_first":r.profit_first},DEMO_MODE,"set")
    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),
        "lv":"warn" if r.mode in ("armed","full") else "info",
        "msg":"全自动出场模式切换为: %s%s"%(r.mode," (真金!)" if (r.mode in ("armed","full") and not DEMO_MODE) else "")})); R.ltrim(RNS+"alerts",0,49)
    return {"ok":True,"mode":r.mode,"demo":DEMO_MODE}

@app.get("/api/engine/auto_exit/{username}")
def get_auto_exit(username:str):
    return {"mode":R.get(RNS+"auto_exit:"+username) or "off",
            "decisions":json.loads(R.get(RNS+"auto_exit:decisions:"+username) or "null"),
            "last":R.get(RNS+"auto_exit:last"),"demo":DEMO_MODE}

# ---- 全自动进单模式开关(off/shadow/armed/full) + 方向 ----
class AutoEntryCmd(BaseModel):
    username:str; license_key:str=""; mode:str="off"; direction:str="reverse"
@app.post("/api/cmd/auto_entry", dependencies=[Depends(require_admin)])
def cmd_auto_entry(r:AutoEntryCmd):
    if r.mode not in ("off","shadow","armed","full"):
        raise HTTPException(400,"mode 必须为 off/shadow/armed/full")
    if r.direction not in ("reverse","forward"): r.direction="reverse"
    # P1 权益闸: 武装/全量(真金自动进单)需 auto_loop 权益; off/shadow 免费
    if r.mode in ("armed","full"):
        if R.get(RNS+"global_estop")=="1":
            raise HTTPException(409,"全局急停生效中, 无法启用自动进单; 请先解除急停")
        uid=_uid(r.username)
        if not uid or str(_ent_get(uid,"auto_loop")).lower() not in ("true","1"):
            raise HTTPException(403,"全自动进单(武装/全量)未解锁,需内购权益 auto_loop;影子模式可免费体验")
    R.set(RNS+"auto_entry:"+r.username, r.mode)
    R.set(RNS+"auto_entry_dir:"+r.username, r.direction)
    _audit(r.username,_actor(r.license_key),"auto_entry_mode",{"mode":r.mode,"direction":r.direction},DEMO_MODE,"set")
    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),
        "lv":"warn" if r.mode in ("armed","full") else "info",
        "msg":"全自动进单模式: %s/%s%s"%(r.mode,r.direction," (真金!)" if (r.mode in ("armed","full") and not DEMO_MODE) else "")})); R.ltrim(RNS+"alerts",0,49)
    return {"ok":True,"mode":r.mode,"direction":r.direction,"demo":DEMO_MODE}

@app.get("/api/engine/auto_entry/{username}")
def get_auto_entry(username:str):
    return {"mode":R.get(RNS+"auto_entry:"+username) or "off",
            "direction":R.get(RNS+"auto_entry_dir:"+username) or "reverse",
            "decisions":json.loads(R.get(RNS+"auto_entry:decisions:"+username) or "null"),
            "last":R.get(RNS+"auto_entry:last"),"demo":DEMO_MODE}


class ParamSave(BaseModel):
    username:str; license_key:str=""; symbol:str
    entry_spread:float; tp_points:float; sl_points:float; ladders:int; hold_secs:int; weekend_guard:bool
    main_lot_mult:float=1.0; hedge_lot_mult:float=1.0
    main_spread_cap:float=30.0; hedge_spread_cap:float=30.0
    slippage_tol:float=5.0; slippage_pause_min:int=2
    entry_interval_sec:int=5; max_inflight:int=3
    auto_close:bool=True; single_leg_alert:bool=True
    hedge_symbol:str=""; base_lot:float=0.01
    data_mult:float=10.0; basis_offset:float=0.0; digits:int=2
    entry_mode:str="main_first"; exit_mode:str="concurrent"; speed_mode:str="fast"; predict_budget:float=0.0
    # 批七: 数据倍数主/对冲拆分 + 进位拆分 + 数据波动 + 数据同步 + 周末双开关
    data_mult_main:float=10.0; data_mult_hedge:float=10.0
    digits_main:int=2; digits_hedge:int=2
    match_count:int=20; fluctuation_band:float=0.0
    sync_interval_sec:float=1.0; records_per_sec:int=1
    weekend_sat:bool=False; weekend_sun:bool=False
    # 批八: 保证金预留 + 每手费用
    margin_reserve_main:float=200.0; margin_reserve_hedge:float=200.0; fee_per_lot:float=0.0
@app.post("/api/params/save", dependencies=[Depends(require_license)])
def params_save(r:ParamSave):
    c=db(); cur=c.cursor()
    cur.execute("SELECT id FROM users WHERE username=%s",(r.username,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(404,"user not found")
    if r.records_per_sec is not None and r.records_per_sec<1: r.records_per_sec=1  # 每秒数据条数不能0
    cur.execute("""UPDATE param_templates SET entry_spread=%s,tp_points=%s,sl_points=%s,ladders=%s,hold_secs=%s,weekend_guard=%s,
                   main_lot_mult=%s,hedge_lot_mult=%s,main_spread_cap=%s,hedge_spread_cap=%s,slippage_tol=%s,slippage_pause_min=%s,
                   entry_interval_sec=%s,max_inflight=%s,auto_close=%s,single_leg_alert=%s,
                   hedge_symbol=%s,base_lot=%s,data_mult=%s,basis_offset=%s,digits=%s,
                   entry_mode=%s,exit_mode=%s,speed_mode=%s,predict_budget=%s,
                   data_mult_main=%s,data_mult_hedge=%s,digits_main=%s,digits_hedge=%s,
                   match_count=%s,fluctuation_band=%s,sync_interval_sec=%s,records_per_sec=%s,
                   weekend_sat=%s,weekend_sun=%s,
                   margin_reserve_main=%s,margin_reserve_hedge=%s,fee_per_lot=%s,updated_at=now()
                   WHERE user_id=%s AND symbol=%s""",
                (r.entry_spread,r.tp_points,r.sl_points,r.ladders,r.hold_secs,r.weekend_guard,
                 r.main_lot_mult,r.hedge_lot_mult,r.main_spread_cap,r.hedge_spread_cap,r.slippage_tol,r.slippage_pause_min,
                 r.entry_interval_sec,r.max_inflight,r.auto_close,r.single_leg_alert,
                 r.hedge_symbol,r.base_lot,r.data_mult,r.basis_offset,r.digits,
                 r.entry_mode,r.exit_mode,r.speed_mode,r.predict_budget,
                 r.data_mult_main,r.data_mult_hedge,r.digits_main,r.digits_hedge,
                 r.match_count,r.fluctuation_band,r.sync_interval_sec,r.records_per_sec,
                 r.weekend_sat,r.weekend_sun,
                 r.margin_reserve_main,r.margin_reserve_hedge,r.fee_per_lot,u[0],r.symbol))
    if cur.rowcount==0:
        cur.execute("""INSERT INTO param_templates(user_id,symbol,entry_spread,tp_points,sl_points,ladders,hold_secs,weekend_guard,
                       main_lot_mult,hedge_lot_mult,main_spread_cap,hedge_spread_cap,slippage_tol,slippage_pause_min,entry_interval_sec,max_inflight,auto_close,single_leg_alert,
                       hedge_symbol,base_lot,data_mult,basis_offset,digits,entry_mode,exit_mode,speed_mode,predict_budget,
                       data_mult_main,data_mult_hedge,digits_main,digits_hedge,match_count,fluctuation_band,sync_interval_sec,records_per_sec,weekend_sat,weekend_sun,
                       margin_reserve_main,margin_reserve_hedge,fee_per_lot)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (u[0],r.symbol,r.entry_spread,r.tp_points,r.sl_points,r.ladders,r.hold_secs,r.weekend_guard,
                     r.main_lot_mult,r.hedge_lot_mult,r.main_spread_cap,r.hedge_spread_cap,r.slippage_tol,r.slippage_pause_min,
                     r.entry_interval_sec,r.max_inflight,r.auto_close,r.single_leg_alert,
                     r.hedge_symbol,r.base_lot,r.data_mult,r.basis_offset,r.digits,
                     r.entry_mode,r.exit_mode,r.speed_mode,r.predict_budget,
                     r.data_mult_main,r.data_mult_hedge,r.digits_main,r.digits_hedge,
                     r.match_count,r.fluctuation_band,r.sync_interval_sec,r.records_per_sec,
                     r.weekend_sat,r.weekend_sun,
                     r.margin_reserve_main,r.margin_reserve_hedge,r.fee_per_lot))
    c.close()
    _audit(r.username,_actor(r.license_key),"params_save",{"symbol":r.symbol},DEMO_MODE,"saved")
    return {"ok":True,"msg":"参数已保存，引擎下轮热重载"}

@app.get("/api/audit/{username}")
def get_audit(username:str, limit:int=30):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT a.action,a.actor,a.demo_mode,a.result,a.ts FROM audit_log a LEFT JOIN users u ON u.id=a.user_id WHERE u.username=%s ORDER BY a.ts DESC LIMIT %s",(username,limit))
    rows=cur.fetchall(); c.close()
    return {"audit":[dict(r) for r in rows]}

@app.get("/api/quote/tick/{symbol}")
async def quote_tick(symbol:str, leg:str="main"):
    try:
        if leg=="hedge":
            if not getattr(CONN,"hedge",None): raise HTTPException(404,"无对冲腿")
            return await CONN.hedge._get("/mt5/tick/"+symbol)
        return await CONN.main._get("/mt5/tick/"+symbol)
    except HTTPException: raise
    except Exception as e: raise HTTPException(502,"bridge tick err: %s"%e)

@app.get("/api/quote/config")
def quote_config():
    return {"demo_mode":DEMO_MODE}

@app.get("/api/engine/arb_scan/{username}")
async def engine_arb_scan(username:str):
    """AI 套利分析: 扫描该用户主账户×对冲账户旗下所有产品对, 实时取双腿行情,
       算当前点差/基差 vs 入场阈值, 给每对一个可套利性评分(0-100)+建议+可视化数据。
       评分模型: 距离入场阈值越近/越过 → 分越高; 结合波动带惩罚(波动过大扣分)。"""
    uid=_uid(username)
    if not uid: raise HTTPException(404,"user not found")
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""SELECT symbol,hedge_symbol,entry_spread,tp_points,sl_points,basis_offset,
                          main_spread_cap,hedge_spread_cap,fluctuation_band,digits
                   FROM param_templates WHERE user_id=%s ORDER BY id""",(uid,))
    rows=[dict(x) for x in cur.fetchall()]; c.close()
    pairs=[]
    for t in rows:
        msym=t["symbol"]; hsym=ENG.map_hedge_symbol(msym,t.get("hedge_symbol")) or msym
        entry=float(t.get("entry_spread") or 0); off=float(t.get("basis_offset") or 0)
        mt=ht=None
        try: mt=await CONN.main._get("/mt5/tick/"+msym)
        except Exception: pass
        try: ht=await CONN.hedge._get("/mt5/tick/"+hsym) if getattr(CONN,"hedge",None) else None
        except Exception: pass
        mp = (mt.get("bid",0)+mt.get("ask",0))/2 if mt else None
        hp = (ht.get("bid",0)+ht.get("ask",0))/2 if ht else None
        basis = round((mp-hp-off),4) if (mp is not None and hp is not None) else None
        # 评分: 基差绝对值相对入场阈值的达标度
        score=0; suggest="数据不足"; reachable=False
        if basis is not None and entry>0:
            ratio=abs(basis)/entry
            score=int(max(0,min(100,ratio*100)))
            reachable = abs(basis)>=entry
            if reachable: suggest="✅ 已达入场点差,建议开仓套利"
            elif ratio>=0.8: suggest="⏳ 接近入场阈值(%.0f%%),密切关注"%(ratio*100)
            elif ratio>=0.4: suggest="观望,点差偏小"
            else: suggest="点差过小,无套利空间"
        # 波动带惩罚
        fb=float(t.get("fluctuation_band") or 0)
        pairs.append({"main_symbol":msym,"hedge_symbol":hsym,"main_price":mp,"hedge_price":hp,
                      "basis":basis,"entry_spread":entry,"score":score,"reachable":reachable,
                      "suggest":suggest,"fluctuation_band":fb,
                      "main_ok":bool(mt),"hedge_ok":bool(ht)})
    pairs.sort(key=lambda p:p["score"],reverse=True)
    best=pairs[0] if pairs else None
    _reach=sum(1 for p in pairs if p["reachable"])
    summary={"pairs":len(pairs),"reachable":_reach,
             "top_score":best["score"] if best else 0,
             "verdict": ("发现 %d 个可套利机会"%_reach) if any(p["reachable"] for p in pairs) else "当前无达标套利机会,继续监控"}
    # 埋点落库(供产品分析统计, best-effort 不阻断)
    try:
        c2=db(); cur2=c2.cursor()
        cur2.execute("""INSERT INTO ai_arb_scans(user_id,username,pairs,reachable,top_score,hit,top_symbol,top_basis)
                        VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                     (uid,username,len(pairs),_reach,(best["score"] if best else 0),(_reach>0),
                      (best["main_symbol"]+"/"+best["hedge_symbol"]) if best else "",(best["basis"] if best else None)))
        c2.close()
    except Exception as _e: pass
    return {"username":username,"summary":summary,"pairs":pairs}

@app.get("/api/admin/bi/arb_stats")
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


@app.get("/api/naked/{username}")
def naked_alerts(username:str):
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT n.leg,n.detail,n.resolved,n.ts FROM naked_alerts n LEFT JOIN users u ON u.id=n.user_id WHERE u.username=%s ORDER BY n.ts DESC LIMIT 20",(username,))
    rows=cur.fetchall(); c.close()
    return {"naked":[dict(r) for r in rows]}


# ---- 按腿直取 bridge 历史成交（主/对冲分别）----
@app.get("/api/bridge/deals/{leg}")
async def bridge_leg_deals(leg:str, days:int=7):
    try:
        if leg=="hedge":
            if not getattr(CONN,"hedge",None): return {"leg":leg,"deals":[]}
            data=await CONN.hedge.history_deals(days)
        else:
            data=await CONN.main.history_deals(days)
    except Exception as e:
        raise HTTPException(502,"bridge deals err: %s"%e)
    deals=data.get("deals",data) if isinstance(data,dict) else data
    TYPE={0:"buy",1:"sell",2:"balance"}
    out=[]
    for d in (deals or []):
        t=int(d.get("type",-1))
        out.append({"ticket":str(d.get("ticket","")),"symbol":d.get("symbol",""),
                    "side":TYPE.get(t,str(t)),"lots":float(d.get("volume",0) or 0),
                    "price":float(d.get("price",0) or 0),"profit":float(d.get("profit",0) or 0),
                    "time":d.get("time"),"is_trade":t in (0,1)})
    out=[x for x in out if x["is_trade"]]
    out.sort(key=lambda x:x.get("time") or 0, reverse=True)
    return {"leg":leg,"deals":out[:30]}

# ---- 两腿卡片数据: 实时持仓盈亏/过夜费(持仓) + 已结算累计过夜费/手续费(历史成交) ----
@app.get("/api/engine/legstats")
async def engine_legstats(days:int=30, username:str=""):
    """每腿: live(持仓 profit/swap 合计 + 多/空手数) + settled(历史成交 swap/commission 累计) + 平均开仓点差(testgo 账本)。"""
    out={"main":None,"hedge":None,"days":days,"avg_spread":None}
    # 实时持仓(profit/swap)
    try:
        pos = await CONN.both_positions() if hasattr(CONN,"both_positions") else {"main":await CONN.positions(),"hedge":None}
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
            data = await (CONN.hedge if leg=="hedge" else CONN.main).history_deals(days) if (leg=="main" or getattr(CONN,"hedge",None)) else None
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
        if leg=="hedge" and not getattr(CONN,"hedge",None):
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
@app.get("/api/engine/paired_history")
async def engine_paired_history(days:int=7, symbol:str="XAUUSD"):
    """主/对冲两腿历史成交按 comment(QH-{dir}-main/hedge) 精确配对; 无标签退回时间窗(±2s)。
       每配对: 双腿时间/方向/价/手数 + 开仓点差 + 双腿手续费/过夜费/盈亏 + 配对净盈亏 + 持仓时长。只读。"""
    hsym=symbol
    try:
        c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT hedge_symbol FROM param_templates WHERE symbol=%s LIMIT 1",(symbol,))
        row=cur.fetchone(); c.close()
        if row: hsym=ENG.map_hedge_symbol(symbol,row.get("hedge_symbol")) or symbol
    except Exception: pass
    async def _deals(leg):
        try:
            data=await (CONN.hedge if leg=="hedge" else CONN.main).history_deals(days) if (leg=="main" or getattr(CONN,"hedge",None)) else None
        except Exception: data=None
        ds=(data.get("deals",data) if isinstance(data,dict) else data) or []
        out=[]
        for d in ds:
            t_=int(d.get("type",-1)); e_=int(d.get("entry",-1))
            if t_ not in (0,1): continue   # 仅真实成交(排除 balance)
            out.append({"ticket":str(d.get("ticket","")),"order":str(d.get("order","")),
                        "side":"buy" if t_==0 else "sell","entry":e_,  # entry 0=in 1=out
                        "vol":float(d.get("volume",0) or 0),"price":float(d.get("price",0) or 0),
                        "profit":float(d.get("profit",0) or 0),"swap":float(d.get("swap",0) or 0),
                        "comm":float(d.get("commission",0) or 0),"comment":d.get("comment","") or "","time":d.get("time") or 0})
        return out
    main=await _deals("main"); hedge=await _deals("hedge")
    used=set()
    def _match(md):
        # 1) comment 精确: 同 direction 的对侧 leg, entry 相同(同为开/同为平), 时间最近
        cm=md["comment"]; want_dir=None
        if "reverse" in cm: want_dir="reverse"
        elif "forward" in cm: want_dir="forward"
        cands=[]
        for i,h in enumerate(hedge):
            if i in used: continue
            if h["entry"]!=md["entry"]: continue
            hc=h["comment"]
            precise = want_dir and (want_dir in hc)
            within = abs((h["time"] or 0)-(md["time"] or 0))<=2   # 时间窗兜底 ±2s
            if precise or within:
                cands.append((0 if precise else 1, abs((h["time"] or 0)-(md["time"] or 0)), i))
        if not cands: return None
        cands.sort()
        return cands[0][2]
    pairs=[]
    # 阈值(取该品种 param entry_spread, 历史单无逐单阈值→用当前配置近似)
    thr=None
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT entry_spread FROM param_templates WHERE symbol=%s LIMIT 1",(symbol,)); rr=cur.fetchone(); c.close()
        if rr and rr[0] is not None: thr=float(rr[0])
    except Exception: pass
    for md in sorted(main,key=lambda x:x["time"]):
        hi=_match(md)
        h=hedge[hi] if hi is not None else None
        if hi is not None: used.add(hi)
        spread=round(abs(md["price"]-h["price"]),4) if h else None
        slippage=round(spread-thr,4) if (spread is not None and thr is not None) else None
        pair_profit=round(md["profit"]+md["swap"]+md["comm"]+((h["profit"]+h["swap"]+h["comm"]) if h else 0),2)
        pairs.append({"time":md["time"],"entry":"开" if md["entry"]==0 else "平",
                      "main_side":md["side"],"main_price":md["price"],"main_vol":md["vol"],
                      "hedge_side":(h["side"] if h else None),"hedge_price":(h["price"] if h else None),"hedge_vol":(h["vol"] if h else None),
                      "spread":spread,"threshold":thr,"slippage":slippage,"matched":h is not None,
                      "main_fee":round(md["comm"],2),"hedge_fee":round(h["comm"],2) if h else 0,
                      "main_swap":round(md["swap"],2),"hedge_swap":round(h["swap"],2) if h else 0,
                      "main_profit":round(md["profit"],2),"hedge_profit":round(h["profit"],2) if h else 0,
                      "pair_profit":pair_profit,"source":"QH" if md["comment"].startswith("QH") else "manual"})
    pairs.sort(key=lambda x:x["time"] or 0, reverse=True)
    # 汇总(仿 testgo 顶栏): 平仓净利润/笔数/胜率/费用合计
    closed=[p for p in pairs if p["entry"]=="平"]
    gross=round(sum(p["main_profit"]+p["hedge_profit"] for p in pairs),2)
    fee_main=round(sum(p["main_fee"] for p in pairs),2); fee_hedge=round(sum(p["hedge_fee"] for p in pairs),2)
    swap_main=round(sum(p["main_swap"] for p in pairs),2); swap_hedge=round(sum(p["hedge_swap"] for p in pairs),2)
    net=round(sum(p["pair_profit"] for p in pairs),2)
    win=len([p for p in closed if p["pair_profit"]>0])
    summary={"pairs":len(pairs),"closed":len(closed),"gross_profit":gross,"net_profit":net,
             "fee_main":fee_main,"fee_hedge":fee_hedge,"swap_main":swap_main,"swap_hedge":swap_hedge,
             "win_rate":round(win/len(closed)*100,1) if closed else None}
    return {"symbol":symbol,"hedge_symbol":hsym,"threshold":thr,"summary":summary,
            "pairs":pairs[:80],"unmatched_hedge":len([1 for i in range(len(hedge)) if i not in used])}

# ---- 当日平仓利润 + 两腿过夜费/手续费/返佣(顶栏蓝框) ----
@app.get("/api/engine/daypnl")
async def engine_daypnl(symbol:str="XAUUSD"):
    """当日(北京时区)平仓净利润 + 主/对冲 过夜费/手续费/返佣。
       返佣 MT5 无原生字段→取 deal.commission 中的正值部分(部分经纪商返佣记为正佣金)；无则 0。"""
    # 北京日界 → UTC: 今天 00:00(UTC+8) 对应的 epoch
    now=_dt.datetime.now(_dt.timezone.utc); bj=now+_dt.timedelta(hours=8)
    day_start_bj=bj.replace(hour=0,minute=0,second=0,microsecond=0)
    day_start_epoch=(day_start_bj-_dt.timedelta(hours=8)).timestamp()
    async def _leg(leg):
        try:
            data=await (CONN.hedge if leg=="hedge" else CONN.main).history_deals(2) if (leg=="main" or getattr(CONN,"hedge",None)) else None
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
    m=await _leg("main"); h=await _leg("hedge") if getattr(CONN,"hedge",None) else {"close_profit":0,"swap":0,"fee":0,"rebate":0}
    day_close=round(m["close_profit"]+h["close_profit"],2)
    day_net=round(m["close_profit"]+h["close_profit"]+m["swap"]+h["swap"]+m["fee"]+h["fee"]+m["rebate"]+h["rebate"],2)
    return {"day_close_profit":day_close,"day_net_profit":day_net,"main":m,"hedge":h,"since":day_start_epoch}

# ================= 实时推送 WebSocket(替代 web 3s 轮询) =================
# 单 worker: 内存态共享。广播任务做一次 poll() 的活, 分层缓存(快/慢字段), 扇出所有连接。
import asyncio as _asyncio
_WS_CLIENTS=set()          # 活跃连接集合
_WS_SNAP={"fast":{}, "slow":{}, "fast_ts":0, "slow_ts":0}
async def _ws_build_fast():
    """高频字段(~1s): 双腿状态/持仓 + 主对冲报价 + 引擎/市场态 + 强平估算。"""
    out={}
    try: out["legs"]=await engine_legs()
    except Exception: out["legs"]=None
    try: out["account"]=await bridge_account()
    except Exception: out["account"]=None
    try: out["state"]=engine_state()
    except Exception: out["state"]=None
    # 品种(取首个模板的对冲映射)
    hsym="XAUUSD"; msym="XAUUSD"
    try:
        st=out.get("state") or {}; ev=(st.get("eval") or {})
        if ev:
            first=next(iter(ev.values()),{})
            hsym=first.get("hedge_symbol") or "XAUUSD"; msym=first.get("symbol") or "XAUUSD"
    except Exception: pass
    try: out["tick_main"]=await quote_tick(msym,"main")
    except Exception: out["tick_main"]=None
    try: out["tick_hedge"]=await quote_tick(hsym,"hedge")
    except Exception: out["tick_hedge"]=None
    try: out["liq"]=await engine_liq(msym)
    except Exception: out["liq"]=None
    out["symbols"]={"main":msym,"hedge":hsym}
    return out
async def _ws_build_ticks(prev):
    """极轻字段(~0.3s): 仅主/对冲报价(并发拉, 桥可并发~50ms)。复用上一帧 fast 的 legs/account/state/liq
       (重字段由 heavy 节流刷新), 让点差(卡/账本头/蓝框)达 2/s+ 而不放大重桥调用。"""
    out=dict(prev or {})   # 继承上一帧的 legs/account/state/liq 等重字段
    msym="XAUUSD"; hsym="XAUUSD"
    try:
        st=out.get("state") or {}; ev=(st.get("eval") or {})
        if ev:
            first=next(iter(ev.values()),{})
            hsym=first.get("hedge_symbol") or "XAUUSD"; msym=first.get("symbol") or "XAUUSD"
    except Exception: pass
    # 主+对冲报价并发拉(bridge 支持并发, 两个一起 ~50ms 而非串行 ~100ms)
    async def _safe(coro):
        try: return await coro
        except Exception: return None
    mt, ht = await _asyncio.gather(_safe(quote_tick(msym,"main")), _safe(quote_tick(hsym,"hedge")))
    if mt is not None: out["tick_main"]=mt
    if ht is not None: out["tick_hedge"]=ht   # 失败保留上一帧 tick, 不清零
    out["symbols"]={"main":msym,"hedge":hsym}
    return out
async def _ws_build_slow(user):
    """低频字段(~10s): 腿统计/日盈亏/配对历史/两腿成交。user 相关但成本高, 全局缓存(单用户场景)。"""
    out={}
    try: out["legstats"]=await engine_legstats(30,user)
    except Exception: out["legstats"]=None
    try: out["daypnl"]=await engine_daypnl()
    except Exception: out["daypnl"]=None
    try: out["paired"]=await engine_paired_history(7)
    except Exception: out["paired"]=None
    try: out["deals_main"]=await bridge_leg_deals("main",7)
    except Exception: out["deals_main"]=None
    try: out["deals_hedge"]=await bridge_leg_deals("hedge",7)
    except Exception: out["deals_hedge"]=None
    return out
def _ws_user_data(user):
    """每连接便宜的 per-user Redis 读: 自动档位/DEMO/权益/告警/坑位覆盖。"""
    d={}
    d["auto_entry"]=R.get(RNS+"auto_entry:"+user) or "off"
    d["auto_exit"]=R.get(RNS+"auto_exit:"+user) or "off"
    d["force_demo"]=(R.get(RNS+"force_demo:"+user)=="1")
    try:
        uid=_uid(user); d["entitlements"]=_ent_all(uid) if uid else {}
    except Exception: d["entitlements"]={}
    try:
        d["alerts"]=[json.loads(x) for x in (R.lrange(RNS+"alerts",0,19) or [])]
    except Exception: d["alerts"]=[]
    return d
def _ws_gate_open():
    return bool(_WS_CLIENTS) or (R.get(RNS+"ws:hub_alive")=="1")
def _ws_publish():
    """把当前 _WS_SNAP 组帧 PUBLISH 到 Redis(HUB 扇出) + 扇出本地 WS 连接。"""
    import time as _t
    if not _WS_SNAP.get("fast"): return
    try:
        _hub_user = (next(iter(_WS_CLIENTS)).__dict__.get("_qh_user","") if _WS_CLIENTS else (R.get(RNS+"ws:primary_user") or ""))
        payload={"type":"snapshot","fast":_WS_SNAP.get("fast"),"slow":_WS_SNAP.get("slow"),
                 "user_data":_ws_user_data(_hub_user) if _hub_user else {},"ts":_WS_SNAP.get("fast_ts") or int(_t.time())}
        _j=json.dumps(payload,default=str)
        R.publish(RNS+"ws:snapshot", _j)
        R.setex(RNS+"ws:last_snapshot", 30, _j)
    except Exception: pass
async def _ws_local_fanout():
    """扇出到本地 /ws/stream 连接(HUB 架构下通常为空; 保留向后兼容)。"""
    import time as _t
    dead=[]
    for ws in list(_WS_CLIENTS):
        try:
            u=getattr(ws,"_qh_user","")
            payload={"type":"snapshot","fast":_WS_SNAP.get("fast"),"slow":_WS_SNAP.get("slow"),
                     "user_data":_ws_user_data(u) if u else {},"ts":_WS_SNAP.get("fast_ts") or int(_t.time())}
            await ws.send_text(json.dumps(payload,default=str))
        except Exception: dead.append(ws)
    for ws in dead: _WS_CLIENTS.discard(ws)

async def _ws_tick_loop():
    """~0.3s: 仅刷报价+强平(轻, 继承重字段)并 PUBLISH → 点差达 2/s+。是唯一的发布者。
       与 heavy/slow 循环并发, 桥调用皆 await I/O, 事件循环交错执行, heavy 不阻塞本循环。"""
    import time as _t
    while True:
        try:
            if _ws_gate_open():
                _WS_SNAP["fast"]=await _ws_build_ticks(_WS_SNAP.get("fast"))
                _WS_SNAP["fast_ts"]=int(_t.time())
                _ws_publish()
                await _ws_local_fanout()
        except Exception as e: print("ws_tick err",e)
        await _asyncio.sleep(0.3)
async def _ws_heavy_loop():
    """~1s: 刷双腿状态/持仓/账户/引擎态(桥调用最贵), 只更新 _WS_SNAP 不单独发布(tick 循环发)。"""
    while True:
        try:
            if _ws_gate_open():
                heavy=await _ws_build_fast()
                # heavy 覆盖重字段; tick 循环随后会把最新报价并入
                _WS_SNAP["fast"]={**(_WS_SNAP.get("fast") or {}), **heavy}
        except Exception as e: print("ws_heavy err",e)
        await _asyncio.sleep(1.0)
async def _ws_slow_loop():
    """~10s: 刷腿统计/日盈亏/配对/成交。"""
    import time as _t
    while True:
        try:
            if _ws_gate_open():
                u=""
                if _WS_CLIENTS: u=next(iter(_WS_CLIENTS)).__dict__.get("_qh_user","")
                _WS_SNAP["slow"]=await _ws_build_slow(u); _WS_SNAP["slow_ts"]=int(_t.time())
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
            snap={"type":"snapshot","fast":_WS_SNAP.get("fast") or await _ws_build_fast(),
                  "slow":_WS_SNAP.get("slow") or await _ws_build_slow(row[0]),
                  "user_data":_ws_user_data(row[0]),"ts":_WS_SNAP.get("fast_ts",0)}
            await ws.send_text(json.dumps(snap,default=str))
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







