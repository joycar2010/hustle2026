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
        cur.execute("SELECT price FROM iap_products WHERE key=%s AND enabled=true",(r.product_key,)); p=cur.fetchone()
        amt=float(p["price"] or 0) if p else 0
    try:
        disc,cp=_coupon_eval(cur, r.code, u["id"], u["username"], r.kind, amt)
    except HTTPException: c.close(); raise
    c.close()
    return {"ok":True,"code":r.code,"name":cp["name"],"amount":round(amt,2),"discount":disc,"payable":round(amt-disc,2)}
@app.get("/api/coupon/mine/{username}")
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
@app.get("/api/invite/mine/{username}")
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

@app.get("/api/user/wallet/{username}")
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
    "autoloop_1d": {"name":"全自动进出场日卡",  "cost":50,  "feature_key":"auto_loop",     "value":"true", "days":1},
    "pairs3_1d":   {"name":"3对账户日权",       "cost":80,  "feature_key":"max_pairs",     "value":"3",    "days":1},
    "mobile_7d":   {"name":"移动端权限周卡",    "cost":200, "feature_key":"mobile_access", "value":"true", "days":7},
    "trial_7d":    {"name":"试用延长 7 天(演示)","cost":100, "feature_key":"_trial_ext",    "value":"7",    "days":0},
}
@app.get("/api/points/catalog")
def points_catalog():
    """兑换目录(公开只读, 用户端渲染)。"""
    return {"catalog":[{"key":k,**{x:v[x] for x in ("name","cost")}} for k,v in _REDEEM_CATALOG.items()],
            "points_per_usdt":POINTS_PER_USDT}
@app.get("/api/points/{username}")
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

# ================= 连接方式路由 (P0: Bridge / Api2Trade) =================
from connector import get_connector, build_connector
import time as _t_conn
# active_mode 持久在 Redis(qh:conn:active_mode; 默认 bridge, 重启不丢); 连接器按方式懒建+缓存
_CONN_CACHE={}                       # {mode: connector}
_CONN_MODE_CACHE={"mode":None,"ts":0.0}
def _active_mode():
    """当前生效连接方式(15s 内存缓存, 避免热路径频繁读 Redis)。默认 bridge。"""
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
async def _a2t_cached(key, ttl, fn):
    now=_t_conn.time(); e=_A2T_RC.get(key)
    if e and (now-e[0])<ttl: return e[1]
    v=await fn(); _A2T_RC[key]=(now,v)
    if len(_A2T_RC)>512: _A2T_RC.clear()
    return v

class _FallbackLeg:
    """读取腿(数据源由 _read_source() 决定):
       - 'a2t'(默认): **纯云端** —— 内网桥退出读取链路; 该腿以 mt_accounts 登记(conn_mode=api+UUID)为准,
         未登记→返回良性空形状(both_* 聚合不塌, 卡片/行情显示'--'), 登记→行情/账户/持仓/历史全走 A2T。
       - 'bridge'(回滚杆): 桥优先+连续3败熔断60s回退云端(保留旧行为, redis 热切换)。
       执行(_post/open/close)与桥专属路径(symbol_info/symbols等)不参与切换, 原样走桥。"""
    _EMPTY_POS={"positions":[],"registered":False}
    _EMPTY_HIST={"deals":[],"registered":False}
    _EMPTY_ST={"connected":False,"registered":False}
    def __init__(self, role): self.role=role; self._fail=0; self._skip_until=0.0
    def _b(self):
        bc=_raw_bridge(); return bc.main if self.role=="main" else getattr(bc,"hedge",None)
    def _fb(self): return _a2t_read_legs().get(self.role)
    async def _read(self, bridge_call, a2t_call, empty=None):
        fb=self._fb()
        if _read_source()=="a2t":
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
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("tick",self.role,sym),1.0,lambda: _a2t_tick(fb,sym)))
        if path=="/mt5/history/deals":
            d=params.get("days",1)
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("hist",self.role,d),30.0,lambda: _a2t_history(fb,d,self.role)), empty=self._EMPTY_HIST)
        if path=="/mt5/account/info":
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("acct",self.role),5.0,lambda: fb.account_info()))
        if path=="/mt5/positions":
            return await self._read(lambda b: b._get(path,**params),
                                    lambda fb: _a2t_cached(("pos",self.role),2.0,lambda: _a2t_positions(fb,self.role)), empty=self._EMPTY_POS)
        b=self._b()
        if b is None: raise RuntimeError("bridge leg missing: "+path)
        return await b._get(path, **params)                     # 桥专属路径(symbol_info/symbols等)
    async def account_info(self):
        return await self._read(lambda b: b.account_info(),
                                lambda fb: _a2t_cached(("acct",self.role),5.0,lambda: fb.account_info()))
    async def positions(self):
        return await self._read(lambda b: b.positions(),
                                lambda fb: _a2t_cached(("pos",self.role),2.0,lambda: _a2t_positions(fb,self.role)), empty=self._EMPTY_POS)
    async def history_deals(self, days=1):
        return await self._read(lambda b: b.history_deals(days),
                                lambda fb: _a2t_cached(("hist",self.role,days),30.0,lambda: _a2t_history(fb,days,self.role)), empty=self._EMPTY_HIST)
    async def status(self):
        return await self._read(lambda b: b.status(),
                                lambda fb: _a2t_cached(("st",self.role),5.0,lambda: _a2t_leg_status(self.role,fb)), empty=self._EMPTY_ST)
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
    try: _a2t_leg_bust()   # A2T 动态读取腿一并失效(重注册换 UUID 立即跟随)
    except Exception: pass

def _auto_loop_running():
    """任一用户自动进/出场处于 armed/full → 返回描述; 否则 None。(单账户上下文, 全局判定)"""
    try:
        for pfx in ("auto_entry:","auto_exit:"):
            for k in R.scan_iter(RNS+pfx+"*"):
                v=R.get(k) or "off"
                if v in ("armed","full"):
                    return "%s=%s (用户 %s)"%(pfx[:-1], v, str(k).split(":")[-1])
    except Exception: pass
    return None
async def _acct_clear_guard(role):
    """清除账户保护闸: 自动策略运行中 或 该腿有未平持仓 → 返回禁止原因(str); 放行返回 None。
       持仓查询失败(桥/云端均不可达)时 fail-open 放行 —— 策略闸(Redis 本地)是硬保障。"""
    r=_auto_loop_running()
    if r: return "系统自动策略运行中(%s), 禁止清除账户; 请先在操作台停止自动进/出场"%r
    try:
        pos=await CONN.both_positions()
        pl=(pos or {}).get(role) or {}
        items=pl.get("positions",pl) if isinstance(pl,dict) else (pl or [])
        n=len([p for p in (items or []) if float(p.get("volume",0) or 0)>0])
        if n>0: return "该账户尚有 %d 笔未平持仓, 请先平仓再清除(防止监控盲区)"%n
    except Exception: pass
    return None

def _conn_consistency():
    """主/对冲账户 conn_mode 一致性(单主+单对冲上下文)。返回 consistent/eff_mode/明细。"""
    try:
        c=db(); cur=c.cursor()
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

async def _conn_block_reason():
    """执行连接方式(active_mode)是否可执行? 不一致/不可达→返回原因串, 否则 None。读取不受此限(读桥真相)。"""
    cons=_conn_consistency()
    if not cons["consistent"]:
        return "主/对冲连接方式不一致(主%s/对冲%s)"%(cons["main_modes"] or "未设",cons["hedge_modes"] or "未设")
    ok,_st=await _conn_health()   # active_mode(执行链路)健康
    if not ok:
        return "当前连接方式(%s)双腿不可达"%_active_mode()
    return None

async def _conn_gate_exec():
    """执行前 fail-closed 闸: 连接方式不一致或执行链路不可达 → 409。返回执行连接器 EXEC。"""
    r=await _conn_block_reason()
    if r: raise HTTPException(409, r+", 已fail-closed拒绝执行, 请统一/切换连接方式后再操作")
    return EXEC

# ---- 经纪商服务器时区偏移活标定(MT5 成交/行情 time=经纪商墙钟epoch, 非UTC; ICMarkets 夏GMT+3冬GMT+2) ----
_BROKER_OFF={"sec":None,"ts":0.0}
async def _broker_utc_offset():
    """经纪商 epoch 与 UTC 偏移(秒, broker-utc; GMT+3≈10800)。桥 tick time 活标定→自动兼容夏令时。
       缓存5min; 失败回落上次值或0。成交转UTC = broker_epoch - 此偏移。
       纯云端读取(a2t)时恒 0: _a2t_norm_order 已按逐腿标定折回 UTC, 再减会二次校正。"""
    if _read_source()=="a2t": return 0
    now=_t_conn.time()
    if _BROKER_OFF["sec"] is not None and (now-_BROKER_OFF["ts"])<300:
        return _BROKER_OFF["sec"]
    try:
        tk=await _bridge_connector().main._get("/mt5/tick/XAUUSD")
        bt=tk.get("time")
        if isinstance(bt,(int,float)) and bt>0:
            off=int(round((float(bt)-_t_conn.time())/900.0))*900   # 取整到15min(时区粒度)
            if -43200<=off<=50400:                                 # 合理性 -12h..+14h
                _BROKER_OFF["sec"]=off; _BROKER_OFF["ts"]=now
                return off
    except Exception: pass
    return _BROKER_OFF["sec"] or 0
def _to_utc(broker_epoch, off):
    try: return int(broker_epoch)-int(off) if broker_epoch else broker_epoch
    except Exception: return broker_epoch

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

# ================= 全自动出场循环 (逐对盈亏判定 → 按模式平仓; 默认 OFF) =================
# 模式(Redis qh:auto_exit:{user}): off=不动 / shadow=只回显"将平哪些坑"不真发 / armed=仅平 exit_enabled 的坑 / full=平所有命中坑
async def _close_one_pair(username, symbol, hedge_sym, main_side, hedge_side, mode_seq, speed, slot_no, reason):
    """真实平一坑(带裸空守护+账本弹出); 复用 close_pair 内核。返回 (ok, detail)。"""
    res=await _exec_close_pair(symbol, hedge_sym, main_side, hedge_side, None, None, mode_seq, speed)
    _persist_after_close()   # 平仓账本即时落库(云端会话级缓存不可靠)
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
        # 执行链路闸(读取走桥不受限): 主/对冲不一致或 active 连接离线→本轮跳过+5min冷却告警
        _blk=await _conn_block_reason()
        if _blk:
            if not R.get(RNS+"conn:autoexit_warn"):
                R.setex(RNS+"conn:autoexit_warn",300,"1")
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"自动出场暂停: "+_blk})); R.ltrim(RNS+"alerts",0,49)
            await _aio.sleep(5); continue
        # 双腿持仓 + 双腿 tick(一次取, 全用户共用单账户场景)
        try: both=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        except Exception: both=None
        for t in tmpls:
            user=t["username"]; sym=t.get("symbol") or "XAUUSD"
            mode=R.get(RNS+"auto_exit:"+user) or "off"
            if mode=="shadow": R.set(RNS+"auto_exit:"+user,"off"); mode="off"   # 影子已废除, 遗留态归一为关闭
            if mode=="off": continue
            # P1 防御: 武装/全量运行中若 auto_loop 权益失效(到期)→ 自动关闭(不真平)
            if mode in ("armed","full") and str(_ent_get(t.get("user_id") or _uid(user),"auto_loop")).lower() not in ("true","1"):
                R.set(RNS+"auto_exit:"+user,"off"); mode="off"
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"自动出场权益已失效, 已自动关闭"})); R.ltrim(RNS+"alerts",0,49)
                continue
            if not t.get("auto_close"): continue   # 全局自动清仓总闸关→不动
            if not _in_window(t.get("run_win_start"), t.get("run_win_end")): continue   # 运行时段外→系统不运行(自动出场暂停; 手动平不受限)
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
            if not _CSIZE.get("_fetched"):   # 惰性取面值(供 点差净盈亏点数 换算)
                try:
                    _si=await CONN.main._get("/mt5/symbol_info/"+sym); _cs=float(_si.get("trade_contract_size") or 0)
                    if _cs>0: _CSIZE[sym]=_cs
                    _CSIZE["_fetched"]=True
                except Exception: pass
            slotcfg=R.hgetall(_slot_key(user,sym)) or {}
            xmode=(t.get("exit_mode") or "concurrent"); speed=(t.get("speed_mode") or "fast")
            if xmode not in ("concurrent","main_first","hedge_first"): xmode="concurrent"
            profit_first = (R.get(RNS+"sw:profitfirst:"+user)=="1")  # 盈利平台优先(前端落)
            now_ts=_dt.datetime.utcnow().timestamp()
            _bkoff=await _broker_utc_offset()   # 持仓 time=经纪商墙钟, 算 elapsed 前须转真UTC(否则 hold_secs 时限晚约offset)
            _hold_en=(R.get(RNS+"sw:entrymech:"+user)!="0")   # 进单机制开关: 关→持仓时长超时平仓不触发
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
                # 持仓时长(opent=经纪商墙钟epoch → 转真UTC 再与 now_ts(UTC) 相减)
                opent=(m or h or {}).get("time") or 0
                elapsed=(now_ts-(float(opent)-_bkoff)) if opent else 0
                # 逐坑覆盖
                ov=None
                try: ov=json.loads(slotcfg.get(str(slot_no))) if slotcfg.get(str(slot_no)) else None
                except Exception: ov=None
                sell_point=float(ov.get("sell_point") or 0) if ov else 0
                exit_enabled=bool(ov.get("exit_enabled")) if ov else False
                # 逐坑止盈/止损覆盖全局(0/缺省→回落全局)
                _tp = (float(ov.get("tp_points") or 0) if ov and ov.get("tp_points") else None) or t.get("tp_points")
                _sl = (float(ov.get("sl_points") or 0) if ov and ov.get("sl_points") else None) or t.get("sl_points")
                # 盈利/止损点位=点差净盈亏点数: 把$净盈亏折成点(/手数/面值)再比较
                _vol=float((m or h or {}).get("volume") or 0)
                net_pts=_pnl_to_points(net, _vol, sym)
                go,reason=ENG.auto_exit_decision(net_pts,cur_sp,elapsed,
                              _tp,_sl,(t.get("hold_secs") if _hold_en else None),
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
                _mark_slot_busy(sym, d["slot"])   # 自动出场: 该坑进度渐变
                ok,_res=await _close_one_pair(user,sym,hedge_sym,d["mside"],d["hside"],xmode,speed,d["slot"],d["reason"])
                if ok:   # 执行滑点决策快照(平仓侧, d["mside"]=持仓方向; ticket精确键取自 _res 主腿)
                    _cdir="reverse" if d["mside"]=="sell" else "forward"
                    _slip_snap(_cdir,"close",_cap_at(mt,ht,_cdir,"close"),d["slot"],_leg_tickets((_res or {}).get("main")))
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
        # 执行链路闸(读取走桥不受限): 主/对冲不一致或 active 连接离线→本轮跳过+5min冷却告警
        _blk=await _conn_block_reason()
        if _blk:
            if not R.get(RNS+"conn:autoentry_warn"):
                R.setex(RNS+"conn:autoentry_warn",300,"1")
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"自动进单暂停: "+_blk})); R.ltrim(RNS+"alerts",0,49)
            await _aio.sleep(5); continue
        try: both=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        except Exception: both=None
        for t in tmpls:
            user=t["username"]; sym=t.get("symbol") or "XAUUSD"
            mode=R.get(RNS+"auto_entry:"+user) or "off"
            if mode=="shadow": R.set(RNS+"auto_entry:"+user,"off"); mode="off"   # 影子已废除, 遗留态归一为关闭
            if mode=="off": continue
            # P1 防御: 武装/全量运行中若 auto_loop 权益失效→ 自动关闭(不真开)
            if mode in ("armed","full") and str(_ent_get(t.get("user_id") or _uid(user),"auto_loop")).lower() not in ("true","1"):
                R.set(RNS+"auto_entry:"+user,"off"); mode="off"
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"自动进单权益已失效, 已自动关闭"})); R.ltrim(RNS+"alerts",0,49)
                continue
            direction=R.get(RNS+"auto_entry_dir:"+user) or "reverse"
            if direction not in ("reverse","forward"): direction="reverse"
            # 运行时段/进单时段闸(北京): 运行时段外→系统不进单; 进单时段外→不开仓(手动/自动一致)
            if not _in_window(t.get("run_win_start"), t.get("run_win_end")): continue
            if not _in_window(t.get("entry_win_start"), t.get("entry_win_end")): continue
            # 休市/周末闸
            closed,_why=ENG.market_closed(weekend_guard=t.get("weekend_guard",True),
                                          weekend_sat=t.get("weekend_sat"), weekend_sun=t.get("weekend_sun"))
            if closed: continue
            ladders=int(t.get("ladders") or 0) or 0
            if ladders<=0: continue
            # gap-aware 下一空坑(支持坑号跳空: 定向开仓可能已占中间坑)
            _ann=_annotate_slots(both, sym)
            _occ=set()
            for _lg in ("main","hedge"):
                for _p in (_ann.get(_lg) or []):
                    _s=int(_p.get("slot") or 0)
                    if _s>0: _occ.add(_s)
            slot_no=_next_empty_slot(_occ, ladders)
            if slot_no is None: continue   # 阶梯满, 无空坑
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
            # 买入点位=入场下限(点差须≥阈值才进); 费用抬高下限(与手动一致)
            gthr=float(t.get("entry_spread") or 0)
            fee=float(t.get("fee_per_lot") or 0); _fp=0.0
            if fee>0:
                try: _,_fp=ENG.effective_spread_threshold(gthr,fee,100.0,legs=2)
                except Exception: _fp=0.0
            _pass,_lb=_entry_gate(ov,gthr,cur_sp,_fp)
            if not _pass:
                continue   # 点差未达买入点位下限
            reason="点差%.4f>=买入点位%s"%(cur_sp, ("%.2f"%_lb if _lb is not None else "任意"))
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
            R.set(RNS+"auto_entry:decisions:"+user, json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"mode":mode,"dir":direction,"slot":slot_no,"spread":cur_sp,"reason":reason}))
            # 影子: 只回显
            if mode=="shadow":
                R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"info","msg":"[影子]将开坑%d %s: %s"%(slot_no,direction,reason)})); R.ltrim(RNS+"alerts",0,49)
                R.set(RNS+"auto_entry:last", _dt.datetime.utcnow().isoformat()); continue
            # 在途锁 + 冷却: 进单等待开→按 entry_interval_sec(最低10s); 关→不按间隔(保留10s安全底线)
            lockkey=RNS+"auto_entry:lock:"+user+":"+sym
            if R.get(lockkey): continue
            _wait_en=(R.get(RNS+"sw:entrywait:"+user)!="0")
            cooldown=max(10,int(t.get("entry_interval_sec") or 5)) if _wait_en else 10
            R.setex(lockkey, cooldown, "1")
            mside,hside=("sell","buy") if direction=="reverse" else ("buy","sell")
            _mark_slot_busy(sym, slot_no)   # 自动进单: 该坑进度渐变
            res=await _exec_open_pair(direction, sym, hedge_sym, mv, hv, (t.get("entry_mode") or "main_first"), (t.get("speed_mode") or "fast"))
            mok=res.get("main_ok"); hok=res.get("hedge_ok")
            if mok and hok:
                try:
                    es=round(float(ht["ask"])-float(mt["bid"]),4) if direction=="reverse" else round(float(mt["ask"])-float(ht["bid"]),4)
                    R.rpush(RNS+"ledger:"+user+":"+direction, json.dumps({"q":hv,"m":mv,"s":es,"ts":_dt.datetime.utcnow().isoformat(),"ladder":slot_no}))
                except Exception: pass
                _slip_snap(direction,"open",_cap_at(mt,ht,direction,"open"),slot_no,_leg_tickets(res.get("main")),thr=_lb)   # 执行滑点决策快照(ticket精确键+逐单阈值)
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
    fra=os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206").rstrip("/")
    fk=os.environ.get("QH_FRA_KEY","")
    mp=os.environ.get("QH_FRA_MAIN_PORT","8021"); hp=os.environ.get("QH_FRA_HEDGE_PORT","8001")
    ic_syms=[u["ic"] for u in _PAIRSCAN_UNI if u.get("ic")]
    by_syms=[u["by"] for u in _PAIRSCAN_UNI if u.get("by")]
    bn_syms=set(u["bn"] for u in _PAIRSCAN_UNI if u.get("bn"))
    ts=int(_t_conn.time()); rows=[]
    async def fra_ticks(port,syms,plat):
        try:
            r=await _PSCAN_CX.get("%s:%s/mt5/ticks"%(fra,port),params={"symbols":",".join(syms)},headers={"X-API-Key":fk})
            tk=(r.json() or {}).get("ticks",{}) if r.status_code==200 else {}
        except Exception: tk={}
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

def _annotate_slots(pos, symbol="XAUUSD"):
    """给双腿持仓分配稳定坑号(Redis 持久 ticket→slot 映射: 新仓分配最小空闲坑, 平仓释放该坑)。
       每笔持仓加 slot 字段, 返回 {"main":[...],"hedge":[...]}(归一为 list)。纯显示层, 不碰下单/平仓。
       目的: 平掉几号坑→几号坑空(坑号不再随持仓增减重排)。"""
    out={}
    for leg in ("main","hedge"):
        lst=_poslist((pos or {}).get(leg))
        lst=[dict(p) for p in (lst or []) if isinstance(p,dict)]
        mapkey=RNS+"slotmap:"+leg+":"+symbol
        try: cur={k:int(v) for k,v in (R.hgetall(mapkey) or {}).items()}
        except Exception: cur={}
        live=set(str(p.get("ticket")) for p in lst if p.get("ticket") is not None)
        for tk in list(cur.keys()):        # 释放已平仓 ticket 占的坑
            if tk not in live: R.hdel(mapkey,tk); cur.pop(tk,None)
        used=set(cur.values())
        new=[p for p in lst if str(p.get("ticket")) not in cur]
        new.sort(key=lambda p: float(p.get("time") or 0))   # 早开=小坑号
        for p in new:
            s=1
            while s in used: s+=1
            used.add(s); cur[str(p.get("ticket"))]=s; R.hset(mapkey, str(p.get("ticket")), s)
        for p in lst: p["slot"]=cur.get(str(p.get("ticket")),0)
        out[leg]=lst
    return out

def _mark_slot_busy(symbol, slot, ttl=3):
    """标记某坑"正在操作中"(进/出), 供前端行进度渐变。zset member=坑号 score=过期时刻(秒)。"""
    try:
        now=_dt.datetime.utcnow().timestamp()
        R.zadd(RNS+"slotbusy:"+symbol, {str(int(slot)): now+ttl})
    except Exception: pass

def _busy_slots(symbol):
    try:
        now=_dt.datetime.utcnow().timestamp(); bk=RNS+"slotbusy:"+symbol
        R.zremrangebyscore(bk,0,now)
        return [int(x) for x in (R.zrangebyscore(bk,now,"+inf") or [])]
    except Exception: return []

@app.get("/api/engine/legs")
async def engine_legs():
    try:
        st = await CONN.both_status() if hasattr(CONN,"both_status") else {"main":await CONN.status(),"hedge":None}
        pos = await CONN.both_positions() if hasattr(CONN,"both_positions") else {"main":await CONN.positions(),"hedge":None}
        try: pos=_annotate_slots(pos, "XAUUSD")   # 注入稳定坑号
        except Exception as _e: R.set(RNS+"engine:slotmap_err", str(_e)[:120])
        # 登记门控: 角色无启用登记行(如「清除云端账户」后)→该腿状态置未登记, 操作台卡片同步清空。
        # 读取虽走桥真相(与连接方式解耦), 但账户卡的展示资格以登记为准; 持仓仍如实展示(安全考量不隐藏)。
        try:
            reg=_reg_roles()
            if isinstance(st,dict):
                for _r in ("main","hedge"):
                    if _r not in reg:
                        st[_r]={"registered":False,"connected":False,"account":"--","server":"--","platform":"--"}
        except Exception: pass
        return {"status":st,"positions":pos,"busy_slots":_busy_slots("XAUUSD")}
    except Exception as e:
        raise HTTPException(502,"bridge error: %s"%e)

@app.get("/api/engine/conn_mode")
async def engine_conn_mode():
    """当前生效连接方式 + 主/对冲一致性 + 两方式健康(供顶栏切换按钮与监控)。"""
    am=_active_mode(); cons=_conn_consistency()
    bok,_=await _conn_health("bridge"); aok,_=await _conn_health("api")
    armed=None
    try:
        fra_base=os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206")
        async with _httpx.AsyncClient(timeout=2.5) as cc:
            r=await cc.get(fra_base+":8021/health")
            armed=bool((r.json() or {}).get("trading_armed")) if r.status_code==200 else None
    except Exception: armed=None
    return {"active_mode":am,"consistency":cons,"health":{"bridge":bok,"api":aok},"api_armed":armed}

class ConnSwitchReq(BaseModel):
    mode:str; license_key:str=""; confirm:bool=False
@app.post("/api/cmd/conn_switch", dependencies=[Depends(require_license)])
async def cmd_conn_switch(r:ConnSwitchReq):
    """显式切换生效连接方式(bridge/api): 校验目标连接双腿可达→写两账户 conn_mode + 持久 active_mode。"""
    if r.mode not in ("bridge","api"): raise HTTPException(400,"mode 须为 bridge|api")
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    ok,_st=await _conn_health(r.mode)
    if not ok: raise HTTPException(409,"目标连接方式(%s)双腿不可达, 拒绝切换"%r.mode)
    # 同步两账户 conn_mode=mode(配置与活跃一致), 再持久 active_mode + 清缓存
    try:
        c=db(); cur=c.cursor()
        cur.execute("UPDATE mt_accounts SET conn_mode=%s WHERE role IN ('main','hedge')",(r.mode,)); c.close()
    except Exception as e:
        raise HTTPException(500,"写账户连接方式失败: %s"%e)
    R.set(RNS+"conn:active_mode", r.mode); _conn_cache_bust()
    R.delete(RNS+"conn:autoentry_warn"); R.delete(RNS+"conn:autoexit_warn")
    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn","msg":"连接方式已切换→%s(引擎执行/取数生效)"%r.mode})); R.ltrim(RNS+"alerts",0,49)
    _audit(getattr(r,"username","") or "system",_actor(r.license_key),"conn_switch",{"mode":r.mode},DEMO_MODE,"switched")
    return {"ok":True,"active_mode":r.mode}

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
    if a.conn_mode not in ("bridge","api"):
        raise HTTPException(400,"conn_mode 须为 bridge|api(本地直连已停用)")
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
    cur.execute("INSERT INTO mt_accounts(user_id,label,login,platform,broker,role,conn_mode,bridge_url,bridge_key_ref,server,api2trade_uuid,api2trade_config_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id,login) DO UPDATE SET label=EXCLUDED.label,role=EXCLUDED.role,conn_mode=EXCLUDED.conn_mode,bridge_url=EXCLUDED.bridge_url,server=EXCLUDED.server,api2trade_uuid=CASE WHEN EXCLUDED.api2trade_uuid<>'' THEN EXCLUDED.api2trade_uuid ELSE mt_accounts.api2trade_uuid END,api2trade_config_id=COALESCE(EXCLUDED.api2trade_config_id,mt_accounts.api2trade_config_id)",(u[0],a.label,a.login,a.platform,a.broker,a.role,a.conn_mode,a.bridge_url,a.bridge_key_ref,(a.server or "").strip(),a2t_uuid,a2t_cfg_id))
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

class AcctDelMine(BaseModel):
    role:str=""; login:str=""; confirm:bool=False
@app.post("/api/accounts/delete_mine", dependencies=[Depends(require_license)])
async def del_account_mine(b:AcctDelMine, x_license: str = Header(default="")):
    """用户自删本人 MT 账户登记行(按 role 或 login), 并**联动注销云端托管**(官方 /DeleteAccount, 幂等,
       失败不阻塞本地删除、结果透明回传)。**绝不动交易记录/历史成交**
       (配对历史读桥/券商实时, DB deals 表按 user 非按 account, 无级联)。
       保护闸: 自动策略运行中 或 该腿有未平持仓 → 409 禁止清除。"""
    if not b.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    # 保护闸(角色: login 传入时反查; 都无则 400 在下方分支抛)
    _grole=b.role if b.role in ("main","hedge") else ""
    if not _grole and b.login:
        try:
            c=db(); cur=c.cursor()
            cur.execute("SELECT role FROM mt_accounts WHERE login=%s LIMIT 1",(b.login,))
            _r=cur.fetchone(); c.close()
            if _r: _grole=_r[0]
        except Exception: pass
    if _grole:
        _deny=await _acct_clear_guard(_grole)
        if _deny: raise HTTPException(409,_deny)
    c=db(); cur=c.cursor()
    cur.execute("SELECT id,username FROM users WHERE license_key=%s",(x_license,)); u=cur.fetchone()
    if not u: c.close(); raise HTTPException(403,"密钥无效")
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

@app.get("/api/admin/user/{username}")
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
    # FRA 执行代理(a2t-bridge, 贴 Api2Trade 源站): fail-soft, 代理挂了绝不拖垮本端点
    fra_base=os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206")
    if fra_base:
        async def _fra(port):
            t0=_t.time()
            try:
                async with _httpx.AsyncClient(timeout=2.5) as cc:
                    r=await cc.get("%s:%d/health"%(fra_base,port))
                return {"ok":r.status_code==200,"latency_ms":int((_t.time()-t0)*1000),
                        "health":(r.json() if r.status_code==200 else None)}
            except Exception as e:
                return {"ok":False,"latency_ms":None,"err":e.__class__.__name__}
        try:
            fm,fh=await _aio.gather(_fra(8021),_fra(8001))
            out["fra"]={"configured":True,"base":fra_base,"main":fm,"hedge":fh}
        except Exception as e:
            out["fra"]={"configured":True,"base":fra_base,"err":str(e)[:120]}
    else:
        out["fra"]={"configured":False}
    # 双腿连接器监控: 逐用户 主/对冲 连接方式 + 一致性(不一致=禁止运行) + 各方式健康
    try:
        c2=db(); cur2=c2.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur2.execute("SELECT u.username, a.role, a.conn_mode, a.enabled, a.login FROM mt_accounts a JOIN users u ON u.id=a.user_id WHERE a.role IN ('main','hedge')")
        rows=cur2.fetchall(); c2.close()
        # 各连接方式健康(全局): bridge=内网桥 out['bridges']; api=FRA 代理 out['fra']
        _bridge_ok = bool((out.get("bridges",{}).get("main") or {}).get("ok")) and bool((out.get("bridges",{}).get("hedge") or {}).get("ok"))
        _api_ok = bool(out.get("fra",{}).get("configured") and (out["fra"].get("main") or {}).get("ok") and (out["fra"].get("hedge") or {}).get("ok"))
        _mode_health={"bridge":_bridge_ok,"api":_api_ok}
        byuser={}
        for r in rows:
            u=byuser.setdefault(r["username"],{"username":r["username"],"main":None,"hedge":None})
            u[r["role"]]={"conn_mode":r["conn_mode"],"login":r["login"],"enabled":r["enabled"]}
        conns=[]
        for u in byuser.values():
            mm=(u["main"] or {}).get("conn_mode"); hm=(u["hedge"] or {}).get("conn_mode")
            consistent=(mm is not None and mm==hm)
            eff=mm if consistent else None
            conns.append({"username":u["username"],"main_mode":mm,"hedge_mode":hm,
                          "consistent":consistent,"eff_mode":eff,
                          "runnable":bool(consistent and eff and _mode_health.get(eff,False)),
                          "main_login":(u["main"] or {}).get("login"),"hedge_login":(u["hedge"] or {}).get("login")})
        out["connectors"]={"engine_connector":os.environ.get("QH_CONNECTOR","mt5bridge"),
                           "active_mode":_active_mode(),
                           "mode_health":_mode_health,
                           "inconsistent":sum(1 for x in conns if not x["consistent"]),
                           "users":sorted(conns,key=lambda x:(x["consistent"],x["username"]))}
    except Exception as e:
        out["connectors"]={"err":str(e)[:120]}
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
@app.post("/api/cmd/close_all", dependencies=[Depends(require_license)])
async def cmd_close_all(r:CmdReq):
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    await _conn_gate_exec()   # 连接方式一致+健康才执行(fail-closed)
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
    main_r,main_ok = await _close_leg(EXEC.main,"main")
    hedge_r,hedge_ok = (await _close_leg(EXEC.hedge,"hedge")) if getattr(EXEC,"hedge",None) else ({"closed":0},True)
    _persist_after_close()   # 平仓账本即时落库(云端会话级缓存不可靠)
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

@app.post("/api/cmd/close_profit", dependencies=[Depends(require_license)])
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

async def _count_filled_slots(symbol="XAUUSD"):
    """当前已填坑位数 = 主腿持仓笔数(每坑=一笔配对, 顺序填充)。取不到→None(fail-closed)。
       api 模式并入 in-flight 票(A2T 读滞后期间防重复开仓)。"""
    try:
        pos=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        if not pos: return None
        return len(_poslist(pos.get("main")))
    except Exception:
        return None

async def _occupied_slots(symbol="XAUUSD"):
    """当前已占坑号 set(经稳定坑号映射; 支持跳空)。取不到→None(fail-closed)。"""
    try:
        pos=await CONN.both_positions() if hasattr(CONN,"both_positions") else None
        if pos is None: return None
        ann=_annotate_slots(pos, symbol)
        occ=set()
        for leg in ("main","hedge"):
            for p in (ann.get(leg) or []):
                s=int(p.get("slot") or 0)
                if s>0: occ.add(s)
        return occ
    except Exception:
        return None

def _next_empty_slot(occ, ladders):
    """最小空缺坑号(1..ladders; ladders<=0 视为不限)。occ=已占坑号 set。"""
    occ=occ or set()
    k=1
    while (ladders<=0 or k<=ladders):
        if k not in occ: return k
        k+=1
    return None   # 阶梯已满

_CSIZE={"XAUUSD":100.0,"_fetched":False}   # 面值缓存(XAU=100), auto_exit 惰性从 symbol_info 更新
def _pnl_to_points(pnl, vol, symbol="XAUUSD"):
    """配对净盈亏($) → 点差净盈亏点数 = pnl /(手数×面值)。盈利/止损点位按此口径比较, 跨坑手数一致。"""
    try:
        cs=float(_CSIZE.get(symbol) or 100.0); v=abs(float(vol or 0))
        return (float(pnl)/(v*cs)) if (v>0 and cs>0) else float(pnl)
    except Exception: return pnl
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

def _reserve_slot(symbol, res, slot):
    """定向开仓后写 ticket→坑号预留(供 _annotate_slots 尊重目标坑而非自动分配最小空缺)。
       票用 order(市价单 position 票); api 模式票不符时 _annotate_slots 回落最小空缺, graceful。"""
    try:
        for leg in ("main","hedge"):
            lr=(res.get(leg) or {})
            tk=lr.get("order") or lr.get("deal") or lr.get("ticket")
            if tk: R.hset(RNS+"slotmap:"+leg+":"+symbol, str(tk), int(slot))
    except Exception: pass

class OpenPairReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    direction:str                      # 'reverse'(反向/1空2涨) | 'forward'(正向/2空1涨)
    symbol:str="XAUUSD"; slots:int=1   # slots = 本次要填的坑位数(按顺序填最前面的 N 个空坑, 每坑=一对, 每坑per-rung手数)
    slot:int=0                          # >0=定向开仓该坑(允许坑号跳空); 0=顺序填充(填最小空缺坑)
    qty:float=0.0                       # 兼容旧字段(已废弃; slots 优先, 仅当 slots 缺省且 qty>0 时回退)
@app.post("/api/cmd/open_pair", dependencies=[Depends(require_license)])
async def cmd_open_pair(r:OpenPairReq):
    actor=_actor(r.license_key)
    if r.direction not in ("reverse","forward"):
        raise HTTPException(400,"direction 必须为 reverse 或 forward")
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    await _conn_gate_exec()   # 连接方式一致+健康才执行(fail-closed)
    t=_load_tmpl(r.username, r.symbol)
    if not t: raise HTTPException(404,"参数模板未找到")
    if not _in_window(t.get("entry_win_start"), t.get("entry_win_end")):   # 进单时段闸(北京)
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
    mode=(t.get("entry_mode") or "main_first"); speed=(t.get("speed_mode") or "fast")
    if mode not in ("concurrent","main_first","hedge_first"): mode="main_first"
    legmap={"reverse":("sell","buy"),"forward":("buy","sell")}
    # ── 前置读取并行化: 占坑/双腿账户/双腿tick 同时发起(原为串行冷调用, 跨洲链路累计 ~2.5s) ──
    _rm=float(t.get("margin_reserve_main") or 0); _rh=float(t.get("margin_reserve_hedge") or 0)
    async def _safe_coro(coro):
        try: return await coro
        except Exception as e: return e
    _occ_task=_aio.create_task(_occupied_slots(r.symbol))
    _accs_task=_aio.create_task(_safe_coro(CONN.both_accounts())) if ((_rm>0 or _rh>0) and hasattr(CONN,"both_accounts")) else None
    async def _tick_pair():
        async def one(leg,sym):
            try: return await leg._get("/mt5/tick/"+sym)
            except Exception: return None
        _h=getattr(CONN,"hedge",None)
        if _h is not None:
            return await _aio.gather(one(CONN.main,main_sym), one(_h,hedge_sym))
        return (await one(CONN.main,main_sym), None)
    _tick_task=_aio.create_task(_tick_pair())
    # 已占坑号(gap-aware): 支持坑号跳空
    occ=await _occ_task
    if occ is None:
        raise HTTPException(502,"无法读取当前持仓坑位(fail-closed, 拒绝开仓避免超额填坑)")
    filled=len(occ)
    target=int(r.slot or 0)
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
    # 数据波动闸: 近 match_count 条点差波动超 band → 拒绝开仓(软暂停, 防剧烈波动追单)
    _mc=int(t.get("match_count") or 0); _bd=float(t.get("fluctuation_band") or 0)
    if _bd>0 and _mc>=2:
        _hist=R.lrange(RNS+"spread:hist",-_mc,-1) or []
        _sp=[json.loads(x).get("fs") for x in _hist]
        fl=ENG.fluctuation_guard(_sp,_mc,_bd)
        if fl[0]:
            raise HTTPException(409,"数据波动过大暂停入场: %s(近%d条幅度>阈值%.2f)"%(fl[2],_mc,_bd))
    # 保证金预留闸: 开仓前查双腿可用保证金须 >= 预留(留风险垫, fail-closed; 读取已在前置并行任务发起)
    if _rm>0 or _rh>0:
        _accs=(await _accs_task) if _accs_task is not None else None
        if _accs is None or isinstance(_accs,Exception):
            raise HTTPException(502,"无法读取账户保证金(fail-closed, 拒绝开仓): %s"%(_accs if _accs is not None else "no both_accounts"))
        _ma=(_accs.get("main") or {}); _ha=(_accs.get("hedge") or {})
        ok_m,why_m=ENG.margin_sufficient(_ma.get("margin_free"),_rm,"main")
        if not ok_m: raise HTTPException(409,"主账户保证金不足预留, 拒绝开仓: %s"%why_m)
        if getattr(CONN,"hedge",None) and _rh>0:
            ok_h,why_h=ENG.margin_sufficient(_ha.get("margin_free"),_rh,"hedge")
            if not ok_h: raise HTTPException(409,"对冲账户保证金不足预留, 拒绝开仓: %s"%why_h)
    # 开仓点差(testgo pos_open_ledger 思路): 批前取一次双腿 tick 算 spreadAtExecution(前置并行任务取回)
    entry_spread=None
    try:
        _mt,_ht=await _tick_task
        if _mt and _ht and _mt.get("bid") is not None and _ht.get("ask") is not None:
            if r.direction=="reverse": entry_spread=round(float(_ht["ask"])-float(_mt["bid"]),4)   # 对冲ASK-主BID
            else:                      entry_spread=round(float(_mt["ask"])-float(_ht["bid"]),4)   # 主ASK-对冲BID
    except Exception: pass
    # 费用折算成点(抬高逐坑买入点位下限, 在下方逐坑闸并入)
    _fee=float(t.get("fee_per_lot") or 0); _nthr=float(t.get("entry_spread") or 0); _fee_pts=0.0
    if _fee>0:
        try: _,_fee_pts=ENG.effective_spread_threshold(_nthr,_fee,100.0,legs=2)
        except Exception: _fee_pts=0.0
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
                skipped.append(slot_no); continue   # 该坑被关闭→跳过(不开)
            if ov.get("lot_mode")=="fixed" and float(ov.get("qty") or 0)>0:
                # 固定手数: 该坑用设定数量(主腿=qty×主倍率比, 对冲=qty×对冲倍率比, 以 base 为单位换算)
                _q=float(ov["qty"]); slot_mv=round(_q*_mm,2); slot_hv=round(_q*_hm,2)
                if slot_mv<=0 or slot_hv<=0: slot_mv,slot_hv=main_vol,hedge_vol
        # 买入点位=入场下限: 当前点差 >= 下限 才开(费用抬高下限); null=任意都开, 0=数字0(须≥0), 无覆盖=全局
        _pass,_lb=_entry_gate(ov,_gthr,entry_spread,_fee_pts)
        if not _pass:
            skipped.append(slot_no); continue   # 当前点差未达买入点位下限→跳过
        res=await _exec_open_pair(r.direction, main_sym, hedge_sym, slot_mv, slot_hv, mode, speed)
        details.append(res)
        mok=res.get("main_ok"); hok=res.get("hedge_ok")
        if mok and hok:
            opened+=1
            # 记开仓点差账本(FIFO, 供平均点差): q=对冲手数, s=spreadAtExecution
            try:
                R.rpush(_ledger_key, json.dumps({"q":slot_hv,"m":slot_mv,"s":entry_spread if entry_spread is not None else 0,"ts":_dt.datetime.utcnow().isoformat(),"ladder":slot_no}))
            except Exception: pass
            _slip_snap(r.direction,"open",_cap_at(_mt,_ht,r.direction,"open"),slot_no,_leg_tickets(res.get("main")),thr=_lb)   # 执行滑点决策快照(ticket精确键+逐单阈值)
            if target>0: _reserve_slot(r.symbol,res,slot_no)   # 定向开仓: 预留坑号(防 _annotate 自动分配最小空缺)
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
@app.post("/api/cmd/repair_leg", dependencies=[Depends(require_license)])
async def cmd_repair_leg(r:RepairLegReq):
    """单腿修复: 一键补开缺失腿(人工确认的市价补开, 点差漂移成本由用户判断)。
       只开缺失的那条腿, 绝不动已有腿; 方向按持仓对方向映射(reverse=主sell/对冲buy, forward=主buy/对冲sell)。"""
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    if r.leg not in ("main","hedge"): raise HTTPException(400,"leg 须为 main|hedge")
    if r.direction not in ("reverse","forward"): raise HTTPException(400,"direction 须为 reverse|forward")
    if not (r.volume and r.volume>0): raise HTTPException(400,"volume 须>0")
    await _conn_gate_exec()
    t=_load_tmpl(r.username, r.symbol)
    hedge_sym=ENG.map_hedge_symbol(r.symbol,(t or {}).get("hedge_symbol")) or r.symbol
    legmap={"reverse":("sell","buy"),"forward":("buy","sell")}
    side=legmap[r.direction][0 if r.leg=="main" else 1]
    sym=r.symbol if r.leg=="main" else hedge_sym
    _force_demo=(R.get(RNS+"force_demo:"+r.username)=="1")
    if DEMO_MODE or _force_demo:
        _audit(r.username,actor,"repair_leg",{"leg":r.leg,"side":side,"sym":sym,"vol":r.volume,"slot":r.slot},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式: 将补开%s腿 %s %s %.2f手, 未真实下单"%("主" if r.leg=="main" else "对冲",sym,side,r.volume)}
    leg_obj=EXEC.main if r.leg=="main" else getattr(EXEC,"hedge",None)
    if leg_obj is None: raise HTTPException(502,"缺失腿执行连接不可用")
    try:
        res=await leg_obj.open_order(sym, r.volume, side, comment="QH-%s-%s"%(r.direction,r.leg))
    except Exception as e:
        raise HTTPException(502,"补腿下单失败: %s"%str(e)[:150])
    ok=bool((res or {}).get("ok",True)) and "error" not in (res or {})
    _audit(r.username,actor,"repair_leg",{"leg":r.leg,"side":side,"sym":sym,"vol":r.volume,"slot":r.slot,"res":res},False,"ok" if ok else "fail")
    R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn" if ok else "err",
        "msg":"单腿修复: 补开%s腿 %s %s %.2f手 %s"%("主" if r.leg=="main" else "对冲",sym,side,r.volume,"成功" if ok else "失败")})); R.ltrim(RNS+"alerts",0,49)
    if not ok: raise HTTPException(502,"补腿未成交: %s"%json.dumps(res)[:180])
    return {"ok":True,"demo":False,"leg":r.leg,"side":side,"symbol":sym,"volume":r.volume,
            "ticket":(res or {}).get("ticket") or (res or {}).get("order"),
            "msg":"已补开%s腿 %s %s %.2f手"%("主" if r.leg=="main" else "对冲",sym,side,r.volume)}

class ClosePairReq(BaseModel):
    username:str; license_key:str=""; confirm:bool=False
    symbol:str="XAUUSD"; main_side:str; hedge_side:str
    main_ticket:int=0; hedge_ticket:int=0; main_vol:float=0.0; hedge_vol:float=0.0
@app.post("/api/cmd/close_pair", dependencies=[Depends(require_license)])
async def cmd_close_pair(r:ClosePairReq):
    actor=_actor(r.license_key)
    if not r.confirm: raise HTTPException(400,"二次确认未通过(confirm=true)")
    await _conn_gate_exec()   # 连接方式一致+健康才执行(fail-closed)
    t=_load_tmpl(r.username, r.symbol)
    hedge_sym=ENG.map_hedge_symbol(r.symbol, (t or {}).get("hedge_symbol")) or r.symbol
    xmode=((t or {}).get("exit_mode") or "concurrent"); speed=((t or {}).get("speed_mode") or "fast")
    if xmode not in ("concurrent","main_first","hedge_first"): xmode="concurrent"
    if DEMO_MODE:
        _audit(r.username,actor,"close_pair",{"symbol":r.symbol,"exit_mode":xmode,"main_side":r.main_side,"hedge_side":r.hedge_side},True,"demo:not_sent")
        return {"ok":True,"demo":True,"msg":"演示模式[%s]：将平 主腿%s/对冲腿%s 各一笔，未真实下单"%(xmode,r.main_side,r.hedge_side)}
    mv=r.main_vol or None; hv=r.hedge_vol or None
    mt=r.main_ticket or None; ht=r.hedge_ticket or None   # 按坑精确平(有票→只平该笔, 无票→回落按方向平)
    _slip_dir="reverse" if r.main_side=="sell" else "forward"   # 持仓方向(平仓侧决策快照)
    # 双腿 tick 并行取(平仓滑点快照用; 原串行 2×跨洲 RTT)
    async def _tk(leg,sym):
        try: return await leg._get("/mt5/tick/"+sym)
        except Exception: return None
    _hleg=getattr(CONN,"hedge",None)
    if _hleg is not None:
        _mtk,_htk=await _aio.gather(_tk(CONN.main,r.symbol), _tk(_hleg,hedge_sym))
    else:
        _mtk=await _tk(CONN.main,r.symbol); _htk=None
    res=await _exec_close_pair(r.symbol, hedge_sym, r.main_side, r.hedge_side, mv, hv, xmode, speed, main_ticket=mt, hedge_ticket=ht)
    _persist_after_close()   # 平仓账本即时落库(云端会话级缓存不可靠)
    mok=("error" not in (res.get("main") or {})); hok=(res.get("hedge") is None) or ("error" not in (res.get("hedge") or {}))
    if mok and not hok:
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"err",
            "msg":"⚠按对平仓：主腿已平、对冲腿失败，单边暴露！需人工处理"})); R.ltrim(RNS+"alerts",0,49)
        _audit(r.username,actor,"close_pair",res,False,"NAKED_RISK_hedge_close_failed")
        raise HTTPException(409,"裸空风险：主腿已平、对冲腿平仓失败，已告警(未自动反开)")
    _audit(r.username,actor,"close_pair",res,False,"closed_pair")
    _slip_snap(_slip_dir,"close",_cap_at(_mtk,_htk,_slip_dir,"close"),None,_leg_tickets((res or {}).get("main")))   # 执行滑点决策快照(平仓侧, ticket精确键)
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

# ---- UI 行为开关(进单机制/进单等待): 前端开关→Redis, 引擎侧真消费 ----
class UiSwitchesCmd(BaseModel):
    username:str; license_key:str=""
    entrymech:bool=True    # 开=「持仓时长」到时自动平仓; 关=超时平仓不触发(止盈/止损/卖点不受影响)
    entrywait:bool=True    # 开=自动进单/循环下单按「进单间隔」等待; 关=不按间隔(自动进单保留10s安全底线)
@app.post("/api/cmd/ui_switches", dependencies=[Depends(require_license)])
def cmd_ui_switches(r:UiSwitchesCmd):
    R.set(RNS+"sw:entrymech:"+r.username, "1" if r.entrymech else "0")
    R.set(RNS+"sw:entrywait:"+r.username, "1" if r.entrywait else "0")
    return {"ok":True,"entrymech":r.entrymech,"entrywait":r.entrywait}

# ---- 全自动出场模式开关(off/shadow/armed/full) + 急停 ----
class AutoExitCmd(BaseModel):
    username:str; license_key:str=""; mode:str="off"   # off|shadow|armed|full
    profit_first:bool=False                              # 盈利平台优先(止盈/卖点/超时仅盈利时放行; 止损不受限)
@app.post("/api/cmd/auto_exit", dependencies=[Depends(require_license)])
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
@app.post("/api/cmd/auto_entry", dependencies=[Depends(require_license)])
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
    # 时间窗(北京时间 "HH:MM"; 空=全时段): 进单时段(开仓时段) + 运行时段(系统自动运行时段)
    entry_win_start:str=""; entry_win_end:str=""; run_win_start:str=""; run_win_end:str=""
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
@app.get("/api/engine/arb_scan/{username}")
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
    _off=await _broker_utc_offset()   # 经纪商墙钟→真UTC(前端再+8h显北京)
    for x in out: x["time"]=_to_utc(x.get("time"), _off)
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
    def _match(md, max_dt=None):
        # comment 精确: 同 direction 的对侧 leg, entry 相同(同为开/同为平), 时间最近; 无标签退时间窗 ±2s
        cm=md["comment"]; want_dir=None
        if "reverse" in cm: want_dir="reverse"
        elif "forward" in cm: want_dir="forward"
        cands=[]
        for i,h in enumerate(hedge):
            if i in used: continue
            if h["entry"]!=md["entry"]: continue
            hc=h["comment"]
            dt=abs((h["time"] or 0)-(md["time"] or 0))
            precise = want_dir and (want_dir in hc)
            within = dt<=2
            if not (precise or within): continue
            if max_dt is not None and dt>max_dt: continue
            cands.append((0 if precise else 1, dt, i))
        if not cands: return None
        cands.sort()
        return cands[0][2]
    # 两轮配对(防贪心就近抢错搭档: 先把 ±5s 内的精确对锁定, 剩余再放宽时间)
    _ordered=sorted(range(len(main)), key=lambda i: main[i]["time"])
    _match_map={}
    for _pass_dt in (5, None):
        for mi in _ordered:
            if mi in _match_map: continue
            hi=_match(main[mi], max_dt=_pass_dt)
            if hi is not None:
                _match_map[mi]=hi; used.add(hi)
    pairs=[]
    # 阈值(取该品种 param entry_spread, 历史单无逐单阈值→用当前配置近似)
    thr=None
    try:
        c=db(); cur=c.cursor(); cur.execute("SELECT entry_spread FROM param_templates WHERE symbol=%s LIMIT 1",(symbol,)); rr=cur.fetchone(); c.close()
        if rr and rr[0] is not None: thr=float(rr[0])
    except Exception: pass
    # 执行滑点决策快照(全局环形): 按 action(open/close)+时间就近匹配; 滑点=实际成交捕获-决策快照(带符号)
    _off=await _broker_utc_offset()
    try: _snaps=[json.loads(x) for x in (R.lrange(RNS+"slipsnap",0,-1) or [])]
    except Exception: _snaps=[]
    _snap_used=set()
    def _match_snap(md, deal_utc, action):
        # 1) ticket 精确键: 主deal票↔history.ticket 或 order票↔history.order(唯一, 首选)
        _mtk={md.get("ticket"), md.get("order")}; _mtk.discard(None); _mtk.discard("")
        if _mtk:
            for i,s in enumerate(_snaps):
                if i in _snap_used or s.get("a")!=action: continue
                if _mtk & set(s.get("tk") or []):
                    _snap_used.add(i); return _snaps[i]
        # 2) 兜底: 时间就近(±4.5s; api票非MT或历史老单无票时)
        if deal_utc is None: return None
        best=None; bestd=4.5
        for i,s in enumerate(_snaps):
            if i in _snap_used or s.get("a")!=action: continue
            dt=abs((s.get("ts") or 0)-deal_utc)
            if dt<bestd: bestd=dt; best=i
        if best is not None: _snap_used.add(best); return _snaps[best]
        return None
    for mi in _ordered:
        md=main[mi]
        hi=_match_map.get(mi)
        h=hedge[hi] if hi is not None else None
        spread=round(abs(md["price"]-h["price"]),4) if h else None
        # 带符号执行滑点: 优先决策快照为基准; 平仓行只认平仓侧快照(无则 None→前端'—'), 开仓行回退近似阈值(标记 approx)
        _act="open" if md["entry"]==0 else "close"
        _sn=_match_snap(md, _to_utc(md["time"], _off), _act)
        slippage=None; slip_src="none"
        if _sn is not None and h:
            _rc=_realized_cap(_sn.get("d"), md["price"], h["price"])
            if _rc is not None and _sn.get("c") is not None:
                slippage=round(_rc-float(_sn["c"]),4); slip_src="snap"
        elif _act=="open" and h and thr is not None:
            _dir="reverse" if "reverse" in md["comment"] else ("forward" if "forward" in md["comment"] else None)
            _rc=_realized_cap(_dir, md["price"], h["price"]) if _dir else None
            if _rc is not None: slippage=round(_rc-thr,4); slip_src="approx"
        # 逐行阈值(达标差用): 快照记了该单下单时真实买入点位(th)则用之, 否则回落全局近似
        row_thr = thr
        if _sn is not None and _sn.get("th") is not None:
            try: row_thr=float(_sn["th"])
            except (TypeError,ValueError): pass
        # 达标差 = 点差 − 阈值(用户口径, 与旧HED公式一致; 双列并存)
        dev = round(spread-row_thr,4) if (spread is not None and row_thr is not None) else None
        pair_profit=round(md["profit"]+md["swap"]+md["comm"]+((h["profit"]+h["swap"]+h["comm"]) if h else 0),2)
        pairs.append({"time":md["time"],"entry":"开" if md["entry"]==0 else "平",
                      "main_side":md["side"],"main_price":md["price"],"main_vol":md["vol"],
                      "hedge_side":(h["side"] if h else None),"hedge_price":(h["price"] if h else None),"hedge_vol":(h["vol"] if h else None),
                      "spread":spread,"threshold":row_thr,"dev":dev,"slippage":slippage,"slip_src":slip_src,"matched":h is not None,
                      "main_fee":round(md["comm"],2),"hedge_fee":round(h["comm"],2) if h else 0,
                      "main_swap":round(md["swap"],2),"hedge_swap":round(h["swap"],2) if h else 0,
                      "main_profit":round(md["profit"],2),"hedge_profit":round(h["profit"],2) if h else 0,
                      "pair_profit":pair_profit,"source":"QH" if md["comment"].startswith("QH") else "manual"})
    for p in pairs: p["time"]=_to_utc(p.get("time"), _off)   # 经纪商墙钟→真UTC(前端再+8h显北京; _off 上面已取)
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
def _ws_resolve_symbols(state):
    """从引擎态解析主/对冲品种。命门: 多用户模板同存时不能取 next(iter(ev)) 任意一个
       (否则别的用户配的非法对冲符号如 XAUUSD.m 会污染全局快照, 致对冲行情 404 无数据)。
       优先取 primary_user(仪表盘归属用户)的 eval 条目; 无则回落首个; 全无回落 XAUUSD。"""
    hsym="XAUUSD"; msym="XAUUSD"
    try:
        ev=((state or {}).get("eval") or {})
        if ev:
            pu=R.get(RNS+"ws:primary_user") or ""
            entry = ev.get(pu) if (pu and pu in ev) else next(iter(ev.values()),{})
            hsym=entry.get("hedge_symbol") or "XAUUSD"; msym=entry.get("symbol") or "XAUUSD"
    except Exception: pass
    return msym, hsym
async def _ws_build_fast():
    """高频字段(~1s): 双腿状态/持仓 + 主对冲报价 + 引擎/市场态 + 强平估算。"""
    out={}
    try: out["legs"]=await engine_legs()
    except Exception: out["legs"]=None
    try: out["account"]=await bridge_account()
    except Exception: out["account"]=None
    # 主账户未登记(卡片已清空)→不播账户利润, 防前端 m-pnl 字段被 account 块复活
    try:
        _lm=(((out.get("legs") or {}).get("status") or {}).get("main") or {})
        if _lm.get("registered") is False: out["account"]=None
    except Exception: pass
    try: out["state"]=engine_state()
    except Exception: out["state"]=None
    # 品种: 取 primary_user 模板的对冲映射(防他人非法符号污染全局)
    msym, hsym = _ws_resolve_symbols(out.get("state"))
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
    msym, hsym = _ws_resolve_symbols(out.get("state"))
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
    from connector import _pooled
    base=os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206").rstrip("/")
    port=os.environ.get("QH_FRA_MAIN_PORT","8021")
    key=os.environ.get("QH_FRA_KEY","")
    r=await _pooled("bridge",25).post("%s:%s%s"%(base,port,path), json=payload, headers={"X-API-Key":key}, timeout=25)
    r.raise_for_status(); return r.json()
def _fra_pair_warn(what, e):
    try:
        R.lpush(RNS+"alerts", json.dumps({"ts":_dt.datetime.utcnow().isoformat(),"lv":"warn",
                "msg":"FRA配对%s通道不可用(%s), 已回退逐腿执行"%(what,e.__class__.__name__)})); R.ltrim(RNS+"alerts",0,49)
    except Exception: pass
async def _exec_open_pair(direction, main_sym, hedge_sym, mv, hv, mode, speed):
    if _active_mode()=="api":
        mu,hu=_pair_uuids()
        if mu and hu:
            try:
                return await _fra_pair("/pair/open",{"direction":direction,"main_symbol":main_sym,"hedge_symbol":hedge_sym,
                        "main_vol":mv,"hedge_vol":hv,"mode":mode,"speed":speed,"main_uuid":mu,"hedge_uuid":hu})
            except (_httpx.HTTPStatusError,_httpx.ConnectError,_httpx.ConnectTimeout) as e:
                _fra_pair_warn("开仓",e)   # 明确未执行(4xx/连接未建立)→安全回退逐腿
            except Exception as e:
                raise HTTPException(502,"FRA 配对开仓结果未知(%s): 指令可能已执行, 请核对持仓后再操作, 勿立即重试"%e.__class__.__name__)
    return await EXEC.open_pair(direction, main_sym, hedge_sym, mv, hv, mode=mode, speed=speed)
async def _exec_close_pair(main_sym, hedge_sym, mside, hside, mv, hv, mode, speed, main_ticket=None, hedge_ticket=None):
    if _active_mode()=="api":
        mu,hu=_pair_uuids()
        if mu and hu:
            try:
                _pl={"main_symbol":main_sym,"hedge_symbol":hedge_sym,
                     "main_side":mside,"hedge_side":hside,"main_vol":mv,"hedge_vol":hv,
                     "mode":mode,"speed":speed,"main_ticket":main_ticket,"hedge_ticket":hedge_ticket,
                     "main_uuid":mu,"hedge_uuid":hu}
                return await _fra_pair("/pair/close",{k:v for k,v in _pl.items() if v is not None})
            except (_httpx.HTTPStatusError,_httpx.ConnectError,_httpx.ConnectTimeout) as e:
                _fra_pair_warn("平仓",e)
            except Exception as e:
                raise HTTPException(502,"FRA 配对平仓结果未知(%s): 指令可能已执行, 请核对持仓后再操作, 勿立即重试"%e.__class__.__name__)
    return await EXEC.close_pair(main_sym, hedge_sym, mside, hside, mv, hv, mode=mode, speed=speed, main_ticket=main_ticket, hedge_ticket=hedge_ticket)

def _fra_sync_uuid(role, uuid):
    """登记变更→FRA a2t-bridge 对应腿 UUID 热同步(POST /admin/account_uuid, 持久化 env)。
       best-effort: 失败仅跑马灯告警绝不阻塞注册/清除主流程。返回 (ok,msg)。"""
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
    return {"ok":True}

@app.post("/api/admin/accounts/delete", dependencies=[Depends(require_op("accounts"))])
def admin_acct_del(b:A2TId):
    """仅删除登记行。api 模式账户在云端侧的托管不联动删除(需后台处理), 前端已明示。"""
    c=db(); cur=c.cursor()
    cur.execute("DELETE FROM mt_accounts WHERE id=%s",(b.id,)); n=cur.rowcount; c.close()
    if not n: raise HTTPException(404,"账户不存在")
    _reg_roles_bust()
    return {"ok":True}

@app.post("/api/admin/accounts/purge", dependencies=[Depends(require_op("accounts"))])
async def admin_acct_purge(b:A2TId):
    """彻底清除: 联动 Api2Trade 官方 /DeleteAccount 注销云端托管账户 + 删本地登记行。
       **绝不动交易记录/历史成交**: 登记行删除不级联 deals 表(按 user 键), 配对历史读桥/券商实时。
       保护闸: 自动策略运行中 或 该腿有未平持仓 → 409 禁止清除(与用户端 delete_mine 同口径)。"""
    c=db(); cur=c.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT id,login,role,api2trade_uuid,api2trade_config_id FROM mt_accounts WHERE id=%s",(b.id,))
    acc=cur.fetchone(); c.close()
    if not acc: raise HTTPException(404,"账户不存在")
    if (acc.get("role") or "") in ("main","hedge"):
        _deny=await _acct_clear_guard(acc["role"])
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
