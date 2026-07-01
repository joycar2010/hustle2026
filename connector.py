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

class _BridgeLeg:
    """单条 bridge 腿（凭证留 bridge 机，QH 只发 X-API-Key）"""
    def __init__(self, url, key):
        self.base=url; self.h={"X-API-Key":key}
    async def _get(self, path, **params):
        async with httpx.AsyncClient(timeout=10) as c:
            r=await c.get(self.base+path, headers=self.h, params=params); r.raise_for_status(); return r.json()
    async def account_info(self): return await self._get("/mt5/account/info")
    async def positions(self):    return await self._get("/mt5/positions")
    async def history_deals(self, days=1): return await self._get("/mt5/history/deals", days=days)
    async def status(self):       return await self._get("/mt5/connection/status")
    async def _post(self, path, body=None):
        async with httpx.AsyncClient(timeout=15) as c:
            r=await c.post(self.base+path, headers=self.h, json=(body or {})); r.raise_for_status(); return r.json()
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
    async def both_accounts(self):
        m=await self.main.account_info()
        h=await self.hedge.account_info() if self.hedge else None
        return {"main":m,"hedge":h}
    async def both_positions(self):
        m=await self.main.positions()
        h=await self.hedge.positions() if self.hedge else None
        return {"main":m,"hedge":h}
    async def both_status(self):
        m=await self.main.status()
        h=await self.hedge.status() if self.hedge else None
        return {"main":m,"hedge":h}
    async def both_close_all(self, symbol=None):
        m=await self.main.close_all(symbol)
        h=await self.hedge.close_all(symbol) if self.hedge else None
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
                        main_vol=None, hedge_vol=None, mode="concurrent", speed="fast"):
        """按对平仓(双腿各平一笔)。side=各腿当前持仓方向。mode/speed 同 open_pair 语义。"""
        res={"main":None,"hedge":None}
        async def _cm(): res["main"]=await self.main.close_position(main_symbol, main_side, main_vol)
        async def _ch():
            if self.hedge: res["hedge"]=await self.hedge.close_position(hedge_symbol, hedge_side, hedge_vol)
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

class Api2TradeConnector(IHedgeConnector):
    async def account_info(self): raise NotImplementedError("api2trade reserved")
    async def positions(self):    raise NotImplementedError("api2trade reserved")
    async def history_deals(self, days=1): raise NotImplementedError("api2trade reserved")
    async def status(self):       raise NotImplementedError("api2trade reserved")

def get_connector() -> IHedgeConnector:
    mode=os.environ.get("QH_CONNECTOR","mt5bridge")
    return Api2TradeConnector() if mode=="api2trade" else Mt5BridgeConnector()
