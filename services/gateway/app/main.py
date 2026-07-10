"""DexCexMix gateway:观测面板 + API 聚合 + 总线心跳。

聚合全系统状态(Redis 总线 + 主库)成一个只读面板:服务健康、实盘权益、在场配对、
风控护栏、活跃路由、shadow 战绩。只读——不下单不改配置(那些走 decision/引擎)。
"""
import asyncio
import json
import logging
import os
import socket
import time
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from dcm_common.heartbeat import Heartbeat

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("gateway")

SERVICE = "gateway"
VERSION = "0.2.0"
REDIS_URL = os.environ.get("DCM_REDIS_URL", "redis://10.0.1.212:6379/0")
PG_DSN = os.environ.get("DCM_PG_DSN", "")
TSDB_DSN = os.environ.get("DCM_TSDB_DSN", "")
DASHBOARD_TOKEN = os.environ.get("DCM_DASHBOARD_TOKEN", "")  # 空=不设门禁(仅内网/隧道)


def _authed(request: Request) -> bool:
    if not DASHBOARD_TOKEN:
        return True
    return (request.query_params.get("token") == DASHBOARD_TOKEN
            or request.cookies.get("dcm_token") == DASHBOARD_TOKEN)

_hb = Heartbeat(REDIS_URL, SERVICE)
_redis: aioredis.Redis | None = None
_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _pool
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    if PG_DSN:
        try:
            _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=3)
        except Exception as e:
            logger.warning(f"pg pool init failed: {e!r}")
    task = asyncio.create_task(_hb.run_forever())
    logger.info(f"gateway up pid={os.getpid()} host={socket.gethostname()}")
    yield
    task.cancel()
    if _pool:
        await _pool.close()


app = FastAPI(title="DexCexMix Gateway", version=VERSION, lifespan=lifespan)


async def _get_json(key: str):
    try:
        raw = await _redis.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


@app.get("/healthz")
async def healthz():
    return {"service": SERVICE, "version": VERSION, "pid": os.getpid(),
            "host": socket.gethostname(), "ts": int(time.time())}


@app.get("/readyz")
async def readyz():
    """依赖就绪探针:总线(A机Redis)+ 主库(C机PG)+ 时序库(A机PG),逐项报告。"""
    checks: dict[str, str] = {}
    try:
        r = aioredis.from_url(REDIS_URL, decode_responses=True)
        pong = await asyncio.wait_for(r.ping(), timeout=3)
        await r.aclose()
        checks["redis_bus"] = "ok" if pong else "no pong"
    except Exception as e:
        checks["redis_bus"] = f"error: {e}"
    for name, dsn in (("pg_main", PG_DSN), ("pg_tsdb", TSDB_DSN)):
        if not dsn:
            checks[name] = "unconfigured"
            continue
        try:
            conn = await asyncio.wait_for(asyncpg.connect(dsn), timeout=5)
            await conn.execute("SELECT 1")
            await conn.close()
            checks[name] = "ok"
        except Exception as e:
            checks[name] = f"error: {e}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse(status_code=200 if ok else 503,
                        content={"service": SERVICE, "ready": ok, "checks": checks})


# 逐服务心跳最大龄(秒)——各服务周期不同(采样器小时级/顾问10min级),不能用统一阈值
EXPECTED_SVCS = {"feed-cex": 120, "funding-sync": 900, "depth-sampler": 400, "universe-sync": 7500,
                 "account-snapshot": 240, "engine-dualperp": 120, "gateway": 120, "decision": 120,
                 "risk-ledger": 120, "carry-advisor": 1900, "coin-bridge": 240, "basis-sampler": 200}


@app.get("/api/overview")
async def overview(request: Request):
    if not _authed(request):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    now = int(time.time())
    # 服务健康(dcm:hb:*)
    services = []
    for svc, max_age in EXPECTED_SVCS.items():
        hb = await _get_json(f"dcm:hb:{svc}")
        if hb is None:
            services.append({"name": svc, "state": "missing", "age": None})
        else:
            age = now - int(hb.get("ts") or 0)
            services.append({"name": svc, "state": "ok" if age < max_age else "stale",
                             "age": age, "extra": {k: hb.get(k) for k in
                             ("updates", "counts", "mode", "open_positions", "alerts") if k in hb}})
    risk = await _get_json("dcm:risk:status") or {}
    dp = await _get_json("dcm:engine:dualperp:positions") or {}
    accounts = {}
    for v in ("binance", "bybit", "okx", "gate", "bitget"):
        a = await _get_json(f"dcm:account:{v}")
        if a:
            accounts[v] = {"ok": a.get("ok"), "equity": a.get("equity_usdt"),
                           "positions": len(a.get("positions") or {})}
    try:
        routes_raw = await _redis.hgetall("dcm:route:assignments")
        routes = [json.loads(x) for x in routes_raw.values()]
    except Exception:
        routes = []
    active = [r for r in routes if r.get("state") == "active"]
    return {
        "ts": now, "mode": dp.get("mode", "?"),
        "services": services,
        "reconcile": risk.get("reconcile", {}),
        "guards": risk.get("guards", {}),
        "alerts_this_round": risk.get("alerts_this_round", 0),
        "accounts": accounts,
        "open_positions": dp.get("positions", []),
        "shadow_live": dp.get("shadow", {}),
        "routes_active": sorted(
            [{"symbol": r["symbol"], "engine": r.get("engine"),
              "venues": f"{r.get('venue_long')}/{r.get('venue_short')}",
              "target": r.get("target_notional_usdt"), "by": r.get("updated_by")}
             for r in active], key=lambda x: str(x["symbol"])),
        "routes_total": len(routes),
    }


@app.get("/api/shadow")
async def shadow_report(request: Request, hours: int = 24):
    """shadow 战绩聚合:各币 would_open 占比 / 平均 E / 平均 gap(dualperp_shadow_log)。"""
    if not _authed(request):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    if _pool is None:
        return {"configured": False, "rows": []}
    rows = await _pool.fetch(
        f"""SELECT symbol,
              count(*) AS samples,
              count(*) FILTER (WHERE decision='would_open') AS would_open,
              round(avg(gap_bps), 2) AS avg_gap,
              round(avg((detail->>'e_bps')::numeric) FILTER (WHERE (detail->>'e_bps') IS NOT NULL), 1) AS avg_e,
              round(max((detail->>'e_bps')::numeric) FILTER (WHERE (detail->>'e_bps') IS NOT NULL), 1) AS max_e
            FROM dualperp_shadow_log
            WHERE ts > now() - interval '{int(hours)} hours'
            GROUP BY symbol ORDER BY would_open DESC, samples DESC LIMIT 60""")
    return {"configured": True, "hours": hours,
            "rows": [{"symbol": r["symbol"], "samples": r["samples"], "would_open": r["would_open"],
                      "open_pct": round(100 * r["would_open"] / r["samples"], 1) if r["samples"] else 0,
                      "avg_gap": float(r["avg_gap"]) if r["avg_gap"] is not None else None,
                      "avg_e": float(r["avg_e"]) if r["avg_e"] is not None else None,
                      "max_e": float(r["max_e"]) if r["max_e"] is not None else None}
                     for r in rows]}


@app.get("/api/shadow_trend")
async def shadow_trend(request: Request, hours: int = 48):
    """shadow 机会趋势:逐小时 would_open 决策数 + 涉及币种数(单序列随时间变化)。"""
    if not _authed(request):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    if _pool is None:
        return {"configured": False, "points": []}
    rows = await _pool.fetch(
        f"""SELECT date_trunc('hour', ts) AS h,
              count(*) FILTER (WHERE decision='would_open') AS opps,
              count(DISTINCT symbol) FILTER (WHERE decision='would_open') AS symbols
            FROM dualperp_shadow_log WHERE ts > now() - interval '{int(hours)} hours'
            GROUP BY h ORDER BY h""")
    return {"configured": True,
            "points": [{"t": r["h"].isoformat(), "opps": r["opps"], "symbols": r["symbols"]} for r in rows]}


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    if not _authed(request):
        return HTMLResponse(status_code=401,
                            content="<h3 style='font-family:sans-serif'>需要 token:在 URL 加 ?token=你的令牌</h3>")
    resp = HTMLResponse(content=_DASHBOARD_HTML)
    if DASHBOARD_TOKEN and request.query_params.get("token") == DASHBOARD_TOKEN:
        resp.set_cookie("dcm_token", DASHBOARD_TOKEN, max_age=86400 * 7, httponly=True, samesite="lax")
    return resp


_DASHBOARD_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DexCexMix 观测面板</title>
<style>
:root{--bg:#0d1117;--panel:#161b22;--border:#30363d;--fg:#e6edf3;--dim:#8b949e;
--ok:#3fb950;--warn:#d29922;--bad:#f85149;--accent:#58a6ff}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:13px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-size:16px;margin:0}h2{font-size:12px;color:var(--dim);text-transform:uppercase;
letter-spacing:.5px;margin:0 0 8px}.wrap{max-width:1280px;margin:0 auto;padding:16px}
header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;margin-bottom:16px}
.kpi{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:8px 14px}
.kpi b{font-size:18px;display:block}.kpi span{color:var(--dim);font-size:11px}
.grid{display:grid;gap:12px}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}
@media(max-width:820px){.g2,.g3{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:12px}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:var(--dim);font-weight:500;padding:4px 8px;border-bottom:1px solid var(--border)}
td{padding:4px 8px;border-bottom:1px solid #21262d}tr:last-child td{border:0}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.s-ok{background:var(--ok)}.s-stale{background:var(--warn)}.s-missing{background:var(--bad)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
.pos{color:var(--ok)}.neg{color:var(--bad)}.dim{color:var(--dim)}
.pill{padding:1px 7px;border-radius:10px;font-size:11px;background:#21262d}
.pill.armed{background:#3d1e1e;color:var(--bad)}.pill.shadow{background:#1c2733;color:var(--accent)}
#upd{color:var(--dim);font-size:11px}
</style></head><body><div class="wrap">
<header><h1>⚡ DexCexMix</h1><span id="mode" class="pill"></span>
<div class="kpi"><b id="equity">–</b><span>实盘权益 USDT</span></div>
<div class="kpi"><b id="posn">–</b><span>在场配对</span></div>
<div class="kpi"><b id="alerts">–</b><span>本轮告警</span></div>
<div class="kpi"><b id="svcok">–</b><span>服务在线</span></div>
<span id="upd" style="margin-left:auto"></span></header>

<div class="grid g2">
<div class="panel"><h2>服务健康</h2><table id="svc"></table></div>
<div class="panel"><h2>各所权益/持仓</h2><table id="acct"></table></div>
</div>

<div class="panel"><h2>在场配对 + 风控护栏</h2><table id="guards"></table></div>
<div class="panel"><h2>机会趋势（48h · would_open 决策数 / 小时）</h2>
<div id="trend" style="position:relative"><svg id="tsvg" width="100%" height="140" preserveAspectRatio="none"></svg>
<div id="ttip" style="position:absolute;display:none;pointer-events:none;background:#0d1117;
border:1px solid var(--border);border-radius:6px;padding:4px 8px;font-size:11px;white-space:nowrap"></div></div></div>
<div class="panel"><h2>活跃路由</h2><table id="routes"></table></div>
<div class="panel"><h2>Shadow 战绩（24h：would_open 占比 / 平均净期望E / 平均价差）</h2><table id="shadow"></table></div>
</div>

<script>
const $=s=>document.querySelector(s), fmt=(v,d=2)=>v==null?'–':(+v).toFixed(d);
function cls(v){return v==null?'':(v>=0?'pos':'neg')}
async function j(u){try{return await(await fetch(u)).json()}catch(e){return null}}
function row(cells){return '<tr>'+cells.map(c=>'<td>'+c+'</td>').join('')+'</tr>'}
async function tick(){
 const o=await j('/api/overview'); if(!o)return;
 $('#mode').textContent=o.mode; $('#mode').className='pill '+(o.mode==='armed'?'armed':'shadow');
 $('#equity').textContent=fmt(o.reconcile.total_equity_usdt);
 $('#posn').textContent=(o.open_positions||[]).length;
 $('#alerts').textContent=o.alerts_this_round;
 const ok=o.services.filter(s=>s.state==='ok').length;
 $('#svcok').textContent=ok+'/'+o.services.length;
 $('#upd').textContent='更新 '+new Date(o.ts*1000).toLocaleTimeString();
 $('#svc').innerHTML='<tr><th>服务</th><th>状态</th><th>心跳(s)</th></tr>'+
  o.services.map(s=>row(['<span class="dot s-'+s.state+'"></span>'+s.name,s.state,s.age==null?'–':s.age])).join('');
 const A=o.accounts||{};
 $('#acct').innerHTML='<tr><th>所</th><th>认证</th><th class="mono">权益</th><th>持仓</th></tr>'+
  Object.keys(A).map(v=>row([v,A[v].ok?'<span class="dot s-ok"></span>':'<span class="dot s-missing"></span>',
   '<span class="mono">'+fmt(A[v].equity)+'</span>',A[v].positions])).join('');
 const g=(o.guards&&o.guards.pairs)||[];
 $('#guards').innerHTML='<tr><th>币</th><th>venue</th><th>多腿距强平%</th><th>空腿距强平%</th><th>ADL</th><th class="mono">配对浮亏</th></tr>'+
  (g.length?g.map(p=>{const u=p.upnl?(+p.upnl.long+ +p.upnl.short):null;
   const st=p.single_leg?'<span class="neg">单腿!</span>':(p.verifying?'<span class="dim">待验证</span>':'');
   return row([p.symbol+' '+st,p.venue_long+'/'+p.venue_short,
    p.dist_liq?fmt(p.dist_liq.long,1):'–',p.dist_liq?fmt(p.dist_liq.short,1):'–',
    p.adl?(p.adl.long+'/'+p.adl.short):'–',
    '<span class="mono '+cls(u)+'">'+fmt(u,4)+'</span>'])}).join('')
   :'<tr><td class="dim" colspan=6>无在场配对</td></tr>');
 $('#routes').innerHTML='<tr><th>币</th><th>引擎</th><th>venue</th><th class="mono">目标U</th><th>来源</th></tr>'+
  (o.routes_active.length?o.routes_active.map(r=>row([r.symbol,r.engine,r.venues,
   '<span class="mono">'+r.target+'</span>',r.by])).join('')
   :'<tr><td class="dim" colspan=5>无活跃路由</td></tr>');
 const s=await j('/api/shadow'); if(s&&s.rows){
  $('#shadow').innerHTML='<tr><th>币</th><th>样本</th><th>would_open</th><th>占比%</th><th class="mono">平均E(bps)</th><th class="mono">峰值E</th><th class="mono">平均gap</th></tr>'+
   s.rows.slice(0,30).map(r=>row([r.symbol,r.samples,r.would_open,fmt(r.open_pct,1),
    '<span class="mono '+cls(r.avg_e)+'">'+fmt(r.avg_e,1)+'</span>',
    '<span class="mono">'+fmt(r.max_e,1)+'</span>',
    '<span class="mono">'+fmt(r.avg_gap,1)+'</span>'])).join('');
 }
 drawTrend(await j('/api/shadow_trend'));
}
// 机会趋势:单序列面积图(基线锚定/2px线/隐性网格/hover十字准星)——形随"随时间变化"
let _pts=[];
function drawTrend(d){
 const svg=$('#tsvg'); if(!d||!d.points||!d.points.length){svg.innerHTML='';return}
 _pts=d.points; const W=svg.clientWidth||900,H=140,PL=32,PR=8,PT=10,PB=18;
 const xs=_pts.map(p=>new Date(p.t).getTime()), ys=_pts.map(p=>p.opps);
 const x0=Math.min(...xs),x1=Math.max(...xs)||x0+1,ymax=Math.max(4,...ys);
 const X=t=>PL+(W-PL-PR)*(x1===x0?0.5:(t-x0)/(x1-x0)), Y=v=>PT+(H-PT-PB)*(1-v/ymax);
 let g='';for(let i=0;i<=3;i++){const v=Math.round(ymax*i/3),y=Y(v);
  g+='<line x1="'+PL+'" y1="'+y+'" x2="'+(W-PR)+'" y2="'+y+'" stroke="#21262d" stroke-width="1"/>'
   +'<text x="'+(PL-4)+'" y="'+(y+3)+'" fill="#8b949e" font-size="10" text-anchor="end">'+v+'</text>'}
 const lp=_pts.map((p,i)=>(i?'L':'M')+X(xs[i]).toFixed(1)+' '+Y(ys[i]).toFixed(1)).join(' ');
 const ap=lp+' L'+X(x1).toFixed(1)+' '+Y(0)+' L'+X(x0).toFixed(1)+' '+Y(0)+' Z';
 const t0=new Date(x0),t1=new Date(x1);
 const xl='<text x="'+PL+'" y="'+(H-4)+'" fill="#8b949e" font-size="10">'+t0.toLocaleString([],{month:'numeric',day:'numeric',hour:'2-digit'})+'</text>'
  +'<text x="'+(W-PR)+'" y="'+(H-4)+'" fill="#8b949e" font-size="10" text-anchor="end">'+t1.toLocaleString([],{month:'numeric',day:'numeric',hour:'2-digit'})+'</text>';
 svg.innerHTML=g+'<path d="'+ap+'" fill="#58a6ff" fill-opacity="0.12"/>'
  +'<path d="'+lp+'" fill="none" stroke="#58a6ff" stroke-width="2"/>'
  +'<line id="cx" x1="0" y1="'+PT+'" x2="0" y2="'+(H-PB)+'" stroke="#58a6ff" stroke-width="1" style="display:none"/>'+xl;
 svg._m={W,PL,PR,PT,PB,x0,x1,X,Y,xs,ys};
}
$('#tsvg').addEventListener('mousemove',e=>{
 const svg=$('#tsvg'),m=svg._m; if(!m||!_pts.length)return;
 const rx=e.offsetX/svg.clientWidth*m.W, i=_pts.reduce((b,p,k)=>Math.abs(m.xs[k]-invX(m,rx))<Math.abs(m.xs[b]-invX(m,rx))?k:b,0);
 const cx=$('#cx');cx.style.display='';cx.setAttribute('x1',m.X(m.xs[i]));cx.setAttribute('x2',m.X(m.xs[i]));
 const tt=$('#ttip');tt.style.display='';tt.style.left=Math.min(e.offsetX+10,svg.clientWidth-120)+'px';tt.style.top='6px';
 tt.innerHTML=new Date(_pts[i].t).toLocaleString([],{month:'numeric',day:'numeric',hour:'2-digit'})+'<br><b>'+_pts[i].opps+'</b> 机会 · '+_pts[i].symbols+' 币';
});
$('#tsvg').addEventListener('mouseleave',()=>{const c=$('#cx');if(c)c.style.display='none';$('#ttip').style.display='none'});
function invX(m,px){return m.x0+(m.x1-m.x0)*(px-m.PL)/(m.W-m.PL-m.PR)}
tick(); setInterval(tick,5000);
</script></body></html>"""
