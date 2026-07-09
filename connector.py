# Quant Hedge 连接器层 — Adapter 模式（双腿：主 ICMarkets + 对冲 Bybit）
import os, httpx, asyncio

# 速度档位 → 腿间延迟(秒)。同进同出忽略此延迟(并发); 顺序模式用它隔开两腿。
SPEED_LEG_DELAY = {"normal": 0.5, "fast": 0.2, "turbo": 0.0}
from abc import ABC, abstractmethod

class IHedgeConnector(ABC):
    @abstractmethod
    async def account_info(self): ...
    @abstractmethod
    async def positions(self): ...
    @abstractmethod
    async def history_deals(self, days: int = 1): ...
    @abstractmethod
    async def status(self): ...

# ---- 共享 HTTP 连接池(keep-alive 复用) ----
# 坑: 原每次调用 `async with httpx.AsyncClient()` 新建客户端 = 每个请求都付一次 TCP 握手,
#     跨洲链路(东京→法兰克福 FRA)实测 460ms/调用, 复用后 ~230ms(省一整个 RTT)。
#     uvicorn 单事件循环下模块级共享安全; 按用途分池, 超时按请求粒度传。
_POOL={}
def _pooled(key, timeout):
    c=_POOL.get(key)
    if c is None or c.is_closed:
        c=httpx.AsyncClient(timeout=timeout,
            limits=httpx.Limits(max_keepalive_connections=16, keepalive_expiry=90))
        _POOL[key]=c
    return c

class _BridgeLeg:
    """单条 bridge 腿（凭证留 bridge 机，QH 只发 X-API-Key）"""
    def __init__(self, url, key):
        self.base=url; self.h={"X-API-Key":key}
    async def _get(self, path, **params):
        r=await _pooled("bridge",10).get(self.base+path, headers=self.h, params=params, timeout=10)
        r.raise_for_status(); return r.json()
    async def account_info(self): return await self._get("/mt5/account/info")
    async def positions(self):    return await self._get("/mt5/positions")
    async def history_deals(self, days=1): return await self._get("/mt5/history/deals", days=days)
    async def status(self):       return await self._get("/mt5/connection/status")
    async def _post(self, path, body=None):
        r=await _pooled("bridge",15).post(self.base+path, headers=self.h, json=(body or {}), timeout=15)
        r.raise_for_status(); return r.json()
    async def close_all(self, symbol=None):
        return await self._post("/mt5/position/close-all", {"symbol": symbol})
    async def open_order(self, symbol, volume, order_type, comment="QH"):
        """市价开仓单腿。order_type: 'buy'/'sell'(桥 ORDER_TYPE_MAP, 小写)。"""
        return await self._post("/mt5/order", {"symbol": symbol, "volume": volume,
                                               "order_type": order_type, "comment": comment})
    async def close_position(self, symbol, side, volume=None, ticket=None):
        """按仓平：side 为持仓方向 'buy'/'sell'；可带 ticket 精确平某笔。"""
        body={"symbol": symbol, "side": side}
        if volume is not None: body["volume"]=volume
        if ticket is not None: body["ticket"]=ticket
        return await self._post("/mt5/position/close", body)

class Mt5BridgeConnector(IHedgeConnector):
    """双腿连接器：main=主腿(ICMarkets 8021)  hedge=对冲腿(Bybit 8886)"""
    def __init__(self):
        self.main=_BridgeLeg(os.environ.get("QH_BRIDGE_URL","http://172.31.14.113:8021"),
                             os.environ.get("QH_BRIDGE_KEY",""))
        hurl=os.environ.get("QH_HEDGE_URL"); hkey=os.environ.get("QH_HEDGE_KEY","")
        self.hedge=_BridgeLeg(hurl,hkey) if hurl else None
    # 兼容旧接口（默认主腿）
    async def account_info(self): return await self.main.account_info()
    async def positions(self):    return await self.main.positions()
    async def history_deals(self, days=1): return await self.main.history_deals(days)
    async def status(self):       return await self.main.status()
    # 双腿接口
    # 双腿读取/紧急平仓一律并发(gather): 串行会把跨洲 RTT ×2(开仓前置检查曾因此多花 ~1s)
    async def both_accounts(self):
        if self.hedge:
            m,h=await asyncio.gather(self.main.account_info(), self.hedge.account_info())
        else:
            m=await self.main.account_info(); h=None
        return {"main":m,"hedge":h}
    async def both_positions(self):
        if self.hedge:
            m,h=await asyncio.gather(self.main.positions(), self.hedge.positions())
        else:
            m=await self.main.positions(); h=None
        return {"main":m,"hedge":h}
    async def both_status(self):
        if self.hedge:
            m,h=await asyncio.gather(self.main.status(), self.hedge.status())
        else:
            m=await self.main.status(); h=None
        return {"main":m,"hedge":h}
    async def both_close_all(self, symbol=None):
        if self.hedge:
            m,h=await asyncio.gather(self.main.close_all(symbol), self.hedge.close_all(symbol))
        else:
            m=await self.main.close_all(symbol); h=None
        return {"main":m,"hedge":h}
    async def open_pair(self, direction, main_symbol, hedge_symbol, main_vol, hedge_vol,
                        mode="main_first", speed="fast"):
        """锁仓对开仓。direction:
             'reverse'(反向/1空2涨): 主 sell + 对冲 buy
             'forward'(正向/2空1涨): 主 buy  + 对冲 sell
           mode(时序):
             'concurrent'(同进同出): 双腿并发下单
             'main_first'(1先2后):  主腿先, 对冲后(testgo 默认)
             'hedge_first'(2先1后): 对冲先, 主腿后
           顺序模式: 第一腿失败则不开第二腿(避免单边); 第一腿成功/第二腿失败=裸空, 如实返回交上层告警+人工(绝不自动反开)。
           speed: 顺序模式两腿间延迟档位(normal/fast/turbo)。"""
        if direction=="reverse":
            mside,hside="sell","buy"
        elif direction=="forward":
            mside,hside="buy","sell"
        else:
            raise ValueError("direction must be 'reverse' or 'forward'")
        out={"direction":direction,"mode":mode,"main":None,"hedge":None,"main_ok":False,"hedge_ok":False}
        def _ok(r): return bool((r or {}).get("ok", True)) and "error" not in (r or {})
        async def _main():
            try: out["main"]=await self.main.open_order(main_symbol, main_vol, mside, comment="QH-%s-main"%direction); out["main_ok"]=_ok(out["main"])
            except Exception as ex: out["main"]={"error":str(ex)}
        async def _hedge():
            if not self.hedge: out["hedge"]={"skipped":"no hedge leg"}; out["hedge_ok"]=False; return
            try: out["hedge"]=await self.hedge.open_order(hedge_symbol, hedge_vol, hside, comment="QH-%s-hedge"%direction); out["hedge_ok"]=_ok(out["hedge"])
            except Exception as ex: out["hedge"]={"error":str(ex)}
        delay=SPEED_LEG_DELAY.get(speed,0.2)
        if mode=="concurrent":
            await asyncio.gather(_main(), _hedge())          # 同进同出: 并发(无腿间延迟)
        elif mode=="hedge_first":
            await _hedge()
            if not out["hedge_ok"]: return out               # 第一腿(对冲)失败→不开主腿
            if delay>0: await asyncio.sleep(delay)
            await _main()
        else:  # main_first (默认 1先2后)
            await _main()
            if not out["main_ok"]: return out                # 第一腿(主)失败→不开对冲
            if delay>0: await asyncio.sleep(delay)
            await _hedge()
        return out
    async def close_pair(self, main_symbol, hedge_symbol, main_side, hedge_side,
                        main_vol=None, hedge_vol=None, mode="concurrent", speed="fast",
                        main_ticket=None, hedge_ticket=None):
        """按对平仓(双腿各平一笔)。side=各腿当前持仓方向; ticket=按坑精确平某笔(有票只平该笔, 无票回落按方向)。
           mode/speed 同 open_pair 语义。"""
        res={"main":None,"hedge":None}
        async def _cm(): res["main"]=await self.main.close_position(main_symbol, main_side, main_vol, ticket=main_ticket)
        async def _ch():
            if self.hedge: res["hedge"]=await self.hedge.close_position(hedge_symbol, hedge_side, hedge_vol, ticket=hedge_ticket)
        delay=SPEED_LEG_DELAY.get(speed,0.2)
        if mode=="concurrent":
            await asyncio.gather(_cm(), _ch())
        elif mode=="hedge_first":
            await _ch()
            if delay>0: await asyncio.sleep(delay)
            await _cm()
        else:  # main_first
            await _cm()
            if delay>0: await asyncio.sleep(delay)
            await _ch()
        return res

# ================= Api2Trade 腿 (P1, 免终端云接入) =================
# 参考 https://docs.api2trade.com。REST GET, header x-api-key(single) 或 Basic Auth(pro)。
# 账户级 id=UUID。读方法(account_info/positions/history/status)随时可用;
# 交易方法(open_order/close_position/close_all)受 QH_A2T_TRADING=1 门控, 默认不武装(fail-closed)。
class Api2TradeLeg:
    """单条 Api2Trade 腿。凭证经 header 传, 账户以 uuid 定位。方法面对齐 _BridgeLeg 供引擎复用。"""
    def __init__(self, uuid, api_key="", base_url="https://api.api2trade.com",
                 basic_user="", basic_pass=""):
        self.uuid=uuid; self.base=(base_url or "https://api.api2trade.com").rstrip("/")
        self.h={}; self.auth=None
        if basic_user:
            self.auth=(basic_user, basic_pass or "")
        else:
            self.h={"x-api-key": api_key or ""}
        self.armed = os.environ.get("QH_A2T_TRADING","0")=="1"
    async def _get(self, path, **params):
        params.setdefault("id", self.uuid)
        r=await _pooled("a2t",10).get(self.base+path, params=params, headers=self.h, auth=self.auth, timeout=10)
        r.raise_for_status(); return r.json()
    # ---- 读(P0 就绪) ---- 归一化为与 bridge 相近的键, 供上层复用
    async def account_info(self):
        j=await self._get("/AccountSummary")
        return {"balance":j.get("balance"),"equity":j.get("equity"),"margin":j.get("margin"),
                "margin_free":j.get("freeMargin"),"margin_level":j.get("marginLevel"),
                "currency":j.get("currency"),"leverage":j.get("leverage"),"_raw":j}
    async def positions(self):
        j=await self._get("/OpenedOrders")
        return j if isinstance(j,(list,dict)) else []
    async def history_deals(self, days=1):
        return await self._get("/ClosedOrders")
    async def status(self):
        try:
            await self._get("/AccountSummary"); return {"connected":True}
        except Exception as ex:
            return {"connected":False,"error":str(ex.__class__.__name__)}
    # ---- 交易(P1, 门控) ---- Api2Trade 交易走 GET query(含参数), 上层调用点须避免记录 query
    def _guard(self):
        if not self.armed:
            raise RuntimeError("QH_A2T_TRADING 未武装: Api2Trade 交易腿默认 fail-closed, 需 canary 达标后显式开启")
    async def open_order(self, symbol, volume, order_type, comment="QH"):
        self._guard()
        op="Buy" if str(order_type).lower()=="buy" else "Sell"
        j=await self._get("/OrderSend", symbol=symbol, operation=op, volume=volume, comment=comment)
        return {"ok":bool((j or {}).get("ticket")),"ticket":(j or {}).get("ticket"),"_raw":j}
    async def close_position(self, symbol, side, volume=None, ticket=None):
        self._guard()
        if ticket is None:
            raise RuntimeError("Api2Trade 平仓需 ticket(先经 /OpenedOrders 定位), 拒绝无票平仓防误伤")
        params={"ticket":ticket}
        if volume is not None: params["lots"]=volume
        j=await self._get("/OrderClose", **params)
        return {"ok":True,"_raw":j}
    async def close_all(self, symbol=None):
        self._guard()
        raise RuntimeError("Api2Trade 无批量平仓端点: 须逐票 /OrderClose(上层遍历 /OpenedOrders)")

class Api2TradeConnector(IHedgeConnector):
    """全 Api2Trade 双腿连接器(env 配置 main/hedge 的 UUID + 凭证)。当前为 P1 预留完整实现,
       引擎默认仍用 Mt5BridgeConnector; 切换需 QH_CONNECTOR=api2trade 且 QH_A2T_TRADING=1。"""
    def __init__(self):
        ak=os.environ.get("QH_A2T_KEY",""); bu=os.environ.get("QH_A2T_BASE","https://api.api2trade.com")
        buser=os.environ.get("QH_A2T_BASIC_USER",""); bpass=os.environ.get("QH_A2T_BASIC_PASS","")
        mu=os.environ.get("QH_A2T_MAIN_UUID",""); hu=os.environ.get("QH_A2T_HEDGE_UUID","")
        self.main=Api2TradeLeg(mu, ak, bu, buser, bpass) if mu else None
        self.hedge=Api2TradeLeg(hu, ak, bu, buser, bpass) if hu else None
    async def account_info(self):
        if not self.main: raise NotImplementedError("QH_A2T_MAIN_UUID 未配置")
        return await self.main.account_info()
    async def positions(self):
        if not self.main: raise NotImplementedError("QH_A2T_MAIN_UUID 未配置")
        return await self.main.positions()
    async def history_deals(self, days=1):
        if not self.main: raise NotImplementedError("QH_A2T_MAIN_UUID 未配置")
        return await self.main.history_deals(days)
    async def status(self):
        return await self.main.status() if self.main else {"connected":False,"error":"no_main_uuid"}

def get_connector() -> IHedgeConnector:
    mode=os.environ.get("QH_CONNECTOR","mt5bridge")
    return Api2TradeConnector() if mode=="api2trade" else Mt5BridgeConnector()

def _bridge_from_urls(main_url, main_key, hedge_url, hedge_key):
    """构造一个 Mt5BridgeConnector, 两腿指向给定 URL(用于按连接方式换端点; 不走 __init__ 的 env)。"""
    c=Mt5BridgeConnector.__new__(Mt5BridgeConnector)
    c.main=_BridgeLeg(main_url, main_key)
    c.hedge=_BridgeLeg(hedge_url, hedge_key) if hedge_url else None
    return c

def build_connector(mode) -> IHedgeConnector:
    """连接方式路由工厂(P0): 'bridge'=内网桥(env), 'api'=FRA 代理(a2t-bridge, 同 mt5-bridge 协议)。
       FRA 复刻桥协议→api 只是换一组腿 URL/key, 复用同一个 Mt5BridgeConnector。"""
    if mode=="api":
        base=os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206").rstrip("/")
        key=os.environ.get("QH_FRA_KEY","")
        mp=os.environ.get("QH_FRA_MAIN_PORT","8021"); hp=os.environ.get("QH_FRA_HEDGE_PORT","8001")
        return _bridge_from_urls("%s:%s"%(base,mp), key, "%s:%s"%(base,hp), key)
    return Mt5BridgeConnector()   # bridge: env 内网桥
