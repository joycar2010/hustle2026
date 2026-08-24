# Quant Hedge 连接器层 — Adapter 模式（双腿：主 ICMarkets + 对冲 Bybit）
import os, httpx, asyncio, inspect as _inspect, uuid as _uuid, hashlib as _hashlib

# 速度档位 → 腿间延迟(秒)。同进同出忽略此延迟(并发); 顺序模式用它隔开两腿。
SPEED_LEG_DELAY = {"normal": 0.5, "fast": 0.2, "turbo": 0.0}
# 请求超时(秒, 模块级可覆写: 测试床调小以快速演练超时场景; 生产默认不变)
GET_TIMEOUT = 10
POST_TIMEOUT = 15
# Broker calls around 0.6-0.9s are normal for jj456 during quote/network
# jitter.  A 0.70s read timeout converted those successful closes into an
# async UNKNOWN path even though the Agent WAL had already accepted them.
# Keep the bound finite and configurable; request_id idempotency still guards
# every retry/replay.
POST_FAST_TIMEOUT_SEC = max(0.85, min(2.0, float(os.environ.get(
    "QH_POST_FAST_TIMEOUT_SEC", "1.10"
))))
POST_FAST_TIMEOUT = httpx.Timeout(
    POST_FAST_TIMEOUT_SEC, connect=0.5, read=POST_FAST_TIMEOUT_SEC,
    write=0.5, pool=0.5,
)
ORDERED_TERMINAL_POLL_SEC = 0.025
ORDERED_TERMINAL_TIMEOUT_SEC = float(os.environ.get("QH_ORDERED_TERMINAL_TIMEOUT_SEC","0.9"))
# Avoid hammering Agent status files every 25ms while a broker result is
# still SENDING. The caller-owned absolute deadline remains unchanged.
ORDERED_TERMINAL_MAX_POLL_SEC = max(0.05, min(0.25, float(os.environ.get(
    "QH_ORDERED_TERMINAL_MAX_POLL_SEC", "0.10"
))))
# Closing truth is already emitted by the EA immediately after OrderClose.
# Keep exact-ticket confirmation responsive when order-status is delayed or
# unavailable; verify_leg_closed still requires two consecutive snapshots.
CLOSE_TRUTH_TRIES = max(2, min(4, int(os.environ.get(
    "QH_CLOSE_TRUTH_TRIES", "3"
))))
CLOSE_TRUTH_POLL_SEC = max(0.01, min(0.25, float(os.environ.get(
    "QH_CLOSE_TRUTH_POLL_SEC", "0.05"
))))
from abc import ABC, abstractmethod

# ---- V1.1 移植(M2): request_id 幂等 + UNKNOWN 查真相 ----
# 病灶: 公网执行链(东京→FRA→A2T)超时概率高; 旧行为 超时/异常=按"该腿失败"处理,
#       但订单可能实际已成交 → 超时双开 / 裸空误判。
# 方案: 每对开仓生成 8hex rid; ①comment 带 "#rid"(实测经 A2T 全链路留存到 MT 成交史)
#       ②内网桥同时收 body.request_id(11桥幂等补丁: 同键重放只回原结果)
#       ③超时类异常=UNKNOWN → 经真相源(内网桥=MT账户直连, 实时完整)扫 持仓+成交史 comment 核对,
#         成交→恢复真结果(绝不盲判失败), 确认未成交→安全判失败, 查不清→保留 unknown 交人工。
def _gen_rid():
    return _uuid.uuid4().hex[:8]

_UNKNOWN_EXC = (httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout,
                httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError,
                asyncio.TimeoutError)
def _is_unknown_exc(ex):
    """请求可能已送达但结果未知(读超时/连接中断) → 不可当'未成交', 须查真相。
       ConnectError/ConnectTimeout=请求未发出；HTTPStatusError 仍可能发生在 Agent 落 WAL 后。"""
    return isinstance(ex, _UNKNOWN_EXC)

def _definitely_not_dispatched(ex):
    """Return True only when the HTTP request could not reach the Agent."""
    return isinstance(ex, (httpx.ConnectError, httpx.ConnectTimeout))

def _open_dispatch_exception(ex, request_id, comment):
    """Preserve dispatch certainty without inventing broker no-fill proof."""
    result = {
        "error": str(ex), "request_id": request_id, "op": "open",
        "dispatch_request_id": request_id, "dispatch_comment": comment,
    }
    if _definitely_not_dispatched(ex):
        result.update({
            "dispatch_started": False, "dispatch_durable": False,
            "not_sent": True, "not_filled": True,
            "certainty": "NOT_FILLED", "truth_confirmed": "not_filled",
            "src": "client-rejection",
        })
        return result

    # A response status (especially 409/5xx), a broken response, or an
    # unexpected client exception cannot prove that the Agent did not reserve
    # or execute this request id. Recovery must query the same id.
    result.update({
        "dispatch_started": True, "unknown": True, "certainty": "UNKNOWN",
    })
    if isinstance(ex, httpx.HTTPStatusError):
        response = getattr(ex, "response", None)
        status = getattr(response, "status_code", None)
        if status is not None:
            result["http_status"] = int(status)
        if status == 409:
            result["intent_conflict"] = True
    return result

_EXPLICIT_NOT_FILLED_RETCODES = frozenset({
    129, 130, 131, 132, 133, 134, 135, 136, 138, 140, 141,
    145, 146, 147, 148, 149, 150, 4106, 4107, 4108, 4109,
    # MT5 TRADE_RETCODE_INVALID: the request was rejected before execution.
    # Keep timeout/transport codes out of this set because they do not prove
    # that the broker never accepted the order.
    10013,
})

def _new_deadline(timeout):
    return asyncio.get_running_loop().time() + max(0.0, float(timeout))

def _deadline_remaining(deadline):
    if deadline is None:
        return None
    return max(0.0, float(deadline) - asyncio.get_running_loop().time())

async def _deadline_call(deadline, call):
    """Run one read inside a caller-owned monotonic wall-clock budget."""
    if deadline is None:
        return await call()
    remaining = _deadline_remaining(deadline)
    if remaining <= 0:
        raise asyncio.TimeoutError("broker truth deadline exceeded")
    return await asyncio.wait_for(call(), timeout=remaining)

async def _deadline_sleep(deadline, delay):
    remaining = _deadline_remaining(deadline)
    if remaining is not None and remaining <= 0:
        return False
    await asyncio.sleep(min(max(0.0, float(delay)), remaining)
                        if remaining is not None else max(0.0, float(delay)))
    return deadline is None or _deadline_remaining(deadline) > 0

def _positive_ticket(result):
    if not isinstance(result, dict):
        return False
    value = result.get("ticket") or result.get("order") or result.get("position")
    try:
        return int(value) > 0
    except (TypeError, ValueError):
        return False

def _position_items(snapshot):
    if not isinstance(snapshot, dict):
        return snapshot
    stale = snapshot.get("snapshot_stale", False)
    if isinstance(stale, str):
        stale = stale.strip().lower() in ("1", "true", "yes", "stale")
    if stale:
        raise ValueError("stale positions snapshot")
    return snapshot.get("positions")

def _explicit_not_filled(result):
    """Accept no-fill proof only when its structured fields agree."""
    if not isinstance(result, dict):
        return False
    if (result.get("not_sent") and result.get("src") == "client-rejection" and
            result.get("dispatch_durable") is False):
        return True
    if result.get("not_filled") is not True:
        return False
    if str(result.get("certainty") or "").upper() != "NOT_FILLED":
        return False
    raw = result.get("final_retcode", result.get("retcode"))
    try:
        return int(raw) in _EXPLICIT_NOT_FILLED_RETCODES
    except (TypeError, ValueError):
        return result.get("dispatch_durable") is False

async def order_status_probe(exec_leg, request_id, tries=1, delay=1.0, deadline=None,
                             expected_ticket=None):
    """幂等桥快路径: GET /mt5/order-status/{rid}(内网桥有此端点; FRA/A2T 404→None 走 comment 扫描)。
       tries>1: EA 落盘有延迟(跨洲 RTT), SENDING 态轮询到终态再判——根治 SENDING 超时留孤儿。
       返回: dict(ok/recovered)=已成交结果 | {"failed":True}=桥已确定失败 | None=查不到/不支持。"""
    if deadline is None:
        requested_budget = max(1, int(tries)) * max(0.0, float(delay))
        deadline = _new_deadline(max(ORDERED_TERMINAL_TIMEOUT_SEC, requested_budget))
    for _i in range(max(1, int(tries))):
        try:
            status_get=getattr(exec_leg,"_get_trade_status",None)
            st = await _deadline_call(
                deadline,
                (lambda: status_get(request_id)) if callable(status_get) else
                (lambda: exec_leg._get("/mt5/order-status/" + request_id)),
            )
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None                      # 404/不支持(FRA/A2T) → 立即回退, 不空耗轮询
        if isinstance(st, dict):
            state = st.get("state")
            if state == "ABSENT":
                failure = dict(st.get("result") or {})
                failure.update({
                    "success": False,
                    "failed": True,
                    "not_sent": True,
                    "not_filled": True,
                    "dispatch_durable": False,
                    "certainty": "NOT_FILLED",
                    "truth_confirmed": "not_filled",
                    "unknown_resolved": "not_filled",
                    "request_id": request_id,
                    "src": "order-status",
                })
                failure.setdefault("error", "request was not admitted to the bridge WAL")
                return failure
            if state == "DONE":
                r = dict(st.get("result") or {})
                positive = bool(r.get("success") or r.get("ok"))
                history_only = (r.get("history_only") or
                                str(r.get("src") or "").lower() == "history")
                if expected_ticket is not None:
                    try:
                        exact_ticket = int(expected_ticket)
                    except (TypeError, ValueError):
                        exact_ticket = 0
                    if exact_ticket <= 0:
                        return None
                    returned = next((r.get(key) for key in ("ticket", "order", "position")
                                     if r.get(key) not in (None, "", 0, "0")), None)
                    if returned is not None:
                        try:
                            if int(returned) != exact_ticket:
                                return None
                        except (TypeError, ValueError):
                            return None
                    else:
                        # Exact-ticket close results from older bridges may
                        # omit the ticket even though Agent DONE is durable.
                        r["ticket"] = exact_ticket
                if (positive and _positive_ticket(r) and not r.get("unknown") and
                        str(r.get("certainty") or "").upper() != "UNKNOWN" and
                        not history_only):
                    # A normal async Agent ACK also reaches its terminal state
                    # through this endpoint. Keep that distinct from recovery
                    # after an actual timeout/UNKNOWN classification.
                    r["ok"] = True; r["recovered"] = True
                    r["terminal_via_status"] = True; r["src"] = "order-status"
                    return r
                return None
            if state == "FAILED":
                failure = dict(st.get("result") or {})
                if not failure.get("error") and st.get("detail"):
                    failure["error"] = st.get("detail")
                raw_retcode = failure.get("final_retcode", failure.get("retcode"))
                try:
                    retcode = int(raw_retcode)
                except (TypeError, ValueError):
                    retcode = None
                if retcode in _EXPLICIT_NOT_FILLED_RETCODES:
                    # Older MT5 Agent builds only persisted FAILED + retcode.
                    # Normalize the structured no-fill proof here so every
                    # caller follows the same safe terminal path.
                    failure.update({
                        "not_filled": True,
                        "certainty": "NOT_FILLED",
                        "truth_confirmed": "not_filled",
                        "unknown_resolved": "not_filled",
                    })
                failure["failed"] = True
                failure["src"] = "order-status"
                return failure
            if state == "UNKNOWN":
                # The Agent has frozen publication until broker truth resolves.
                # Repeated status polling cannot improve that truth, so fall
                # through immediately to the exact token/ticket scan.
                return None
        else:
            return None
        # SENDING/pending: EA 尚未落盘, 等待重试(内网桥 order-status 惰性读 EA 结果文件)
        poll_delay=max(0.0,float(delay))
        if poll_delay:
            poll_delay=min(poll_delay*(2 ** min(_i,4)),ORDERED_TERMINAL_MAX_POLL_SEC)
        if _i < tries - 1 and not await _deadline_sleep(deadline, poll_delay):
            return None
    return None

async def verify_leg_open(truth_leg, rid, tries=4, delay=1.5, extra_tags=None,
                          deadline=None):
    """UNKNOWN 查真相(开仓): 经真相源腿扫 持仓+当日成交史 的 comment。
       MT4 桥 OrderSend 用 otoken=("Q"+sha1(request_id)[:9]) 覆写 comment(非 '#rid'),
       故须传 extra_tags=[otoken] 才扫得到——否则 comment 恒不匹配→假 NOFILL→孤儿仓。
       返回: dict=当前持仓中存在该腿 | "HISTORY_ONLY"=仅历史命中(不可继续第二腿)
             | "NO_VISIBLE_FILL"=完整快照暂未看见 | None=真相源不可达/扫描不完整。
       后三种均不是未成交证明, 上层必须保持 UNKNOWN。"""
    tags = ["#" + rid] + [t for t in (extra_tags or []) if t]
    def _hit(cmt):
        s = str(cmt or "")
        return any(t in s for t in tags)
    saw_history_only = False
    confirmed_empty = False
    for i in range(max(1, int(tries))):
        clean = True
        try:
            pos = await _deadline_call(deadline, truth_leg.positions)
            items = _position_items(pos)
            for p in (items or []):
                if _hit(p.get("comment")) and _positive_ticket(p):
                    return {"ok": True, "recovered": True, "src": "positions",
                            "order": p.get("ticket"), "ticket": p.get("ticket"),
                            "volume": p.get("volume"), "price": p.get("price_open"),
                            "request_id": rid}
        except Exception:
            clean = False
            if deadline is not None and _deadline_remaining(deadline) <= 0:
                return "HISTORY_ONLY" if saw_history_only else None
        try:
            hd = await _deadline_call(deadline, lambda: truth_leg.history_deals(1))
            deals = (hd or {}).get("deals") if isinstance(hd, dict) else hd
            for d in (deals or []):
                if _hit(d.get("comment")):
                    saw_history_only = True
        except Exception:
            clean = False
            if deadline is not None and _deadline_remaining(deadline) <= 0:
                return "HISTORY_ONLY" if saw_history_only else None
        if clean: confirmed_empty = True
        if i < tries - 1:
            poll_delay=max(0.0,float(delay))
            remaining=_deadline_remaining(deadline)
            if remaining is not None:
                # Keep part of the caller-owned budget for the next truth
                # query instead of spending the whole remainder sleeping.
                poll_delay=min(poll_delay,remaining/2.0)
            if not await _deadline_sleep(deadline,poll_delay):
                break
    if saw_history_only:
        return "HISTORY_ONLY"
    # Snapshot absence can lag an accepted command and is never rejection proof.
    return "NO_VISIBLE_FILL" if confirmed_empty else None

async def _mt5_authoritative_open_truth(exec_leg, expected_comment, deadline=None,
                                        expected_ticket=None):
    """Return a filled MT5 position only from an explicitly authoritative read.

    MT5 bridge v3 implements ``authoritative=true`` as a broker read taken after
    the terminal trade gate is quiet.  MT4 ignores the query parameter and does
    not return ``snapshot_authoritative``; treating that response as unsupported
    keeps its existing status-then-file-snapshot recovery behavior unchanged.
    """
    if not expected_comment:
        return None
    if getattr(exec_leg,"_qh_authoritative_positions",None) is False:
        return None
    try:
        snapshot=await _deadline_call(
            deadline,
            lambda: exec_leg._get("/mt5/positions",authoritative=True),
        )
    except Exception:
        return None
    if (not isinstance(snapshot,dict) or
            snapshot.get("snapshot_authoritative") is not True or
            snapshot.get("snapshot_source")!="broker"):
        try:
            exec_leg._qh_authoritative_positions=False
        except Exception:
            pass
        return None
    # Keep stale rejection in the authoritative qualification itself as
    # defense in depth.  Do not cache this as an unsupported endpoint: a
    # subsequent MT5 broker snapshot may be fresh and eligible for the race.
    if snapshot.get("snapshot_stale") is True:
        return None
    try:
        exec_leg._qh_authoritative_positions=True
    except Exception:
        pass
    try:
        items=_position_items(snapshot)
        if not isinstance(items,list) or any(not isinstance(p,dict) for p in items):
            raise ValueError("invalid positions payload")
    except Exception:
        return None

    wanted_ticket=None
    if expected_ticket not in (None,"",0,"0"):
        try:
            wanted_ticket=int(expected_ticket)
            if wanted_ticket<=0:
                return None
        except (TypeError,ValueError):
            return None
    for position in items:
        if str(position.get("comment") or "")!=str(expected_comment):
            continue
        raw_ticket=next((position.get(key) for key in ("ticket","position","order")
                         if position.get(key) not in (None,"",0,"0")),None)
        try:
            ticket=int(raw_ticket)
        except (TypeError,ValueError):
            continue
        if ticket<=0 or (wanted_ticket is not None and ticket!=wanted_ticket):
            continue
        return {
            "success":True,"ok":True,"recovered":True,
            "src":"positions-authoritative","truth_confirmed":"open",
            "order":ticket,"ticket":ticket,
            "volume":position.get("volume"),
            "price":position.get("price_open"),
        }
    # Even an authoritative empty/mismatched snapshot is not no-fill proof.
    return None

async def _race_open_terminal(exec_leg, request_id, expected_comment, attempts,
                              deadline, expected_ticket=None, poll_delay=0.05):
    """Race Agent terminal state with MT5 broker-confirmed open-position truth."""
    status_task=asyncio.create_task(order_status_probe(
        exec_leg,request_id,tries=attempts,delay=poll_delay,deadline=deadline))
    truth_task=None
    try:
        # Preserve the no-extra-read fast path for an already durable Agent
        # result.  The nested deadline call needs a few scheduler turns.
        for _i in range(4):
            if status_task.done():
                break
            remaining=_deadline_remaining(deadline)
            if remaining is not None and remaining<=0:
                break
            await asyncio.sleep(0)
        if status_task.done():
            probe=status_task.result()
            if probe is not None:
                return probe

        truth_task=asyncio.create_task(_mt5_authoritative_open_truth(
            exec_leg,expected_comment,deadline=deadline,
            expected_ticket=expected_ticket))
        active={task for task in (status_task,truth_task) if not task.done()}
        while active:
            done,_=await asyncio.wait(active,return_when=asyncio.FIRST_COMPLETED)
            # Durable Agent terminal state retains precedence when both reads
            # finish in the same event-loop turn.
            if status_task in done:
                active.discard(status_task)
                probe=status_task.result()
                if probe is not None:
                    return probe
            if truth_task in done:
                active.discard(truth_task)
                recovered=truth_task.result()
                if recovered is not None:
                    return recovered
        return None
    finally:
        tasks=[task for task in (status_task,truth_task)
               if task is not None and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)

async def verify_leg_closed(truth_leg, ticket, tries=4, delay=1.5, deadline=None):
    """UNKNOWN 查真相(平仓, 须有 ticket): 真相源持仓里 ticket 消失=已平(平仓成交 comment 为空, 不能用 rid)。
       返回: "CLOSED" | "OPEN"(重试到底仍在=未平) | None=查不清。"""
    if not ticket: return None
    saw_any = False
    saw_open = False
    consecutive_absent = 0
    for i in range(max(1, int(tries))):
        try:
            pos = await _deadline_call(deadline, truth_leg.positions)
            items = _position_items(pos)
            if not isinstance(items,list) or any(not isinstance(p,dict) for p in items):
                raise ValueError("invalid positions payload")
            saw_any = True
            present=any(str(p.get("ticket") or p.get("order")) == str(ticket)
                        for p in items)
            if present:
                saw_open=True
                consecutive_absent=0
            else:
                consecutive_absent+=1
        except Exception:
            consecutive_absent=0
        if consecutive_absent>=2:
            return "CLOSED"
        if i < tries - 1:
            poll_delay=max(0.0,float(delay))
            remaining=_deadline_remaining(deadline)
            if remaining is not None:
                # Preserve part of the caller's wall-clock budget for the
                # next snapshot; otherwise a short finalizer budget is spent
                # entirely sleeping and can never prove two observations.
                poll_delay=min(poll_delay,remaining/2.0)
            if not await _deadline_sleep(deadline,poll_delay):
                break
    return "OPEN" if saw_open else (None if not saw_any or consecutive_absent<2 else "CLOSED")

async def _race_close_terminal(exec_leg, request_id, ticket, attempts, deadline):
    """Race a pending close's Agent result against exact-ticket broker truth.

    Give an immediately available Agent terminal result a brief event-loop
    head start. This preserves the fast path (and avoids an unnecessary
    positions read), while a still-pending status poll can no longer consume
    the whole caller deadline before exact-ticket truth starts.
    """
    status_task=asyncio.create_task(order_status_probe(
        exec_leg,request_id,tries=attempts,delay=0.05,deadline=deadline,
        expected_ticket=ticket))
    truth_task=None
    probe=None
    closed=None
    try:
        # Most Agent DONE replies need no broker snapshot. Let that coroutine
        # complete before starting the more expensive positions read.
        # ``_deadline_call`` adds an inner task, so allow enough zero-delay
        # turns for an already-available response to travel through both task
        # layers. This adds no timer latency before the actual race.
        for _i in range(4):
            if status_task.done():
                break
            remaining=_deadline_remaining(deadline)
            if remaining is not None and remaining<=0:
                break
            await asyncio.sleep(0)
        if status_task.done():
            probe=status_task.result()
            if probe is not None:
                return probe,None

        truth_task=asyncio.create_task(verify_leg_closed(
            exec_leg,ticket,tries=CLOSE_TRUTH_TRIES,
            delay=CLOSE_TRUTH_POLL_SEC,deadline=deadline))
        active={task for task in (status_task,truth_task) if not task.done()}
        while active:
            done,_=await asyncio.wait(
                active,return_when=asyncio.FIRST_COMPLETED)

            # Agent terminal truth retains precedence when both reads finish
            # in the same event-loop turn. OPEN/unknown position truth is not
            # terminal: a later broker-success ACK must still win.
            if status_task in done:
                active.discard(status_task)
                probe=status_task.result()
                if probe is not None:
                    return probe,closed
            if truth_task in done:
                active.discard(truth_task)
                closed=truth_task.result()
                if closed=="CLOSED":
                    return probe,closed
        return probe,closed
    finally:
        tasks=[task for task in (status_task,truth_task)
               if task is not None and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)

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
        # 读取路径 503/短暂错误兜底重试一次(Exness 桥间歇 5xx/读超时→保证金闸/持仓查询不因单次抖动失败=单腿/卡顿减少)。
        # 仅读取(_get)重试, 下单(_post)不盲重试(有 request_id 幂等另行保护)。
        for _att in range(2):
            try:
                r=await _pooled("bridge",GET_TIMEOUT).get(self.base+path, headers=self.h, params=params, timeout=GET_TIMEOUT)
                r.raise_for_status(); return r.json()
            except httpx.HTTPStatusError as e:
                if _att==0 and e.response is not None and e.response.status_code in (502,503,504):
                    await asyncio.sleep(0.3); continue
                raise
            except (httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ReadError) as e:
                if _att==0: await asyncio.sleep(0.3); continue
                raise
    async def _get_trade_status(self, request_id):
        """Read a trade status without the generic 300 ms GET backoff."""
        path="/mt5/order-status/"+str(request_id)
        for attempt in range(2):
            try:
                r=await _pooled("bridge",GET_TIMEOUT).get(
                    self.base+path,headers=self.h,timeout=GET_TIMEOUT)
                r.raise_for_status(); return r.json()
            except httpx.HTTPStatusError as exc:
                if (attempt==0 and exc.response is not None and
                        exc.response.status_code in (502,503,504)):
                    await asyncio.sleep(0.02); continue
                raise
            except (httpx.ReadTimeout,httpx.RemoteProtocolError,httpx.ReadError):
                if attempt==0:
                    await asyncio.sleep(0.02); continue
                raise
    async def account_info(self): return await self._get("/mt5/account/info")
    async def positions(self):    return await self._get("/mt5/positions")
    async def history_deals(self, days=1): return await self._get("/mt5/history/deals", days=days)
    async def status(self):       return await self._get("/mt5/connection/status")
    async def _post(self, path, body=None):
        r=await _pooled("bridge-fast",POST_FAST_TIMEOUT).post(
            self.base+path, headers=self.h, json=(body or {}), timeout=POST_FAST_TIMEOUT)
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as ex:
            detail = None
            try:
                payload = r.json()
                detail = payload.get("detail") if isinstance(payload, dict) else payload
            except Exception:
                detail = (r.text or "").strip()
            message = "HTTP %s" % r.status_code
            if detail:
                message += ": %s" % detail
            raise httpx.HTTPStatusError(message, request=r.request, response=r) from ex
        return r.json()
    async def close_all(self, symbol=None):
        return await self._post("/mt5/position/close-all", {"symbol": symbol})
    async def open_order(self, symbol, volume, order_type, comment="QH", request_id=None,
                         deviation=None, ack_only=False):
        """市价开仓单腿。order_type: 'buy'/'sell'(桥 ORDER_TYPE_MAP, 小写)。
           request_id: 内网桥幂等键(同键重放只回原结果); FRA/A2T 忽略此字段无害。
           deviation: 成交容差(point); 按经纪商小数位折算使实际 USD 容差对齐(缺省=桥默认10, 对3位小数经纪商仅0.01USD易REQUOTE)。"""
        body={"symbol": symbol, "volume": volume, "order_type": order_type, "comment": comment}
        if request_id: body["request_id"]=request_id
        if deviation is not None: body["deviation"]=int(deviation)
        if ack_only: body["ack_only"]=True
        return await self._post("/mt5/order", body)
    async def close_position(self, symbol, side, volume=None, ticket=None, request_id=None,
                             ack_only=False):
        """按仓平：side 为持仓方向 'buy'/'sell'；可带 ticket 精确平某笔。"""
        body={"symbol": symbol, "side": side}
        if volume is not None: body["volume"]=volume
        if ticket is not None: body["ticket"]=ticket
        if request_id: body["request_id"]=request_id
        if ack_only: body["ack_only"]=True
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
                        mode="main_first", speed="fast", truth=None, rid=None, main_dev=None,
                        hedge_dev=None, ordered_ack=False, phase_hook=None,
                        dispatch_only=False, burst_admission=False,
                        eager_ordered_ack=False):
        """锁仓对开仓。direction:
             'reverse'(反向/1空2涨): 主 sell + 对冲 buy
             'forward'(正向/2空1涨): 主 buy  + 对冲 sell
           mode(时序):
             'concurrent'(同进同出): 双腿并发下单
             'main_first'(1先2后):  主腿先, 对冲后(testgo 默认)
             'hedge_first'(2先1后): 对冲先, 主腿后
           顺序模式: 第一腿失败则不开第二腿(避免单边); 第一腿成功/第二腿失败=裸空, 如实返回交上层告警+人工(绝不自动反开)。
           speed: 顺序模式两腿间延迟档位(normal/fast/turbo)。
           ordered_ack: 用 Agent WAL ACK 快速提交每条腿，但顺序模式仍以首腿 Broker 终态成功
           作为第二腿派发屏障。第二腿明确失败时按首腿 exact ticket 执行幂等补偿平仓。
           V1.1(M2): rid=幂等键(缺省自动生成), comment 带 #rid + 内网桥 request_id 幂等;
           超时类异常=UNKNOWN → 经 truth(真相源连接器, 缺省=self) 查真相: 实际成交→恢复结果继续时序,
           确认未成交→安全判失败, 查不清→保留 unknown 标志交上层告警(绝不当'未成交'盲判)。"""
        if direction=="reverse":
            mside,hside="sell","buy"
        elif direction=="forward":
            mside,hside="buy","sell"
        else:
            raise ValueError("direction must be 'reverse' or 'forward'")
        rid=rid or _gen_rid()
        main_request_id=rid+"m"; hedge_request_id=rid+"h"
        main_comment="QH-%s-main#%s"%(direction,rid)
        hedge_comment="QH-%s-hedge#%s"%(direction,rid)
        out={"direction":direction,"mode":mode,"main":None,"hedge":None,"main_ok":False,"hedge_ok":False,
             "request_id":rid,"op":"open","ordered_ack":bool(ordered_ack),
             "dispatch_only":bool(dispatch_only),"burst_admission":bool(burst_admission),
             "eager_ordered_ack":bool(eager_ordered_ack),
             "saga_durable":bool(phase_hook),"saga_phase":"PAIR_INTENT",
             "leg_contexts":{
                 "main":{"symbol":main_symbol,"volume":main_vol,"side":mside,"deviation":main_dev,
                         "request_id":main_request_id,"comment":main_comment,
                         "dispatch_request_id":main_request_id,"dispatch_comment":main_comment,
                         "dispatch_started":False},
                 "hedge":{"symbol":hedge_symbol,"volume":hedge_vol,"side":hside,"deviation":hedge_dev,
                          "request_id":hedge_request_id,"comment":hedge_comment,
                          "dispatch_request_id":hedge_request_id,"dispatch_comment":hedge_comment,
                          "dispatch_started":False},
             }}
        async def _phase(name):
            """Persist a complete pair snapshot before crossing a write boundary."""
            out["saga_phase"]=name
            if phase_hook is None:
                return True
            try:
                saved=phase_hook(name,out)
                if _inspect.isawaitable(saved):
                    saved=await saved
                if saved is False:
                    raise RuntimeError("phase hook rejected snapshot")
                return True
            except Exception as ex:
                out["saga_persist_error"]="%s:%s"%(name,ex.__class__.__name__)
                return False
        def _ok(r):
            r=r or {}
            return bool(r.get("success", r.get("ok", True))) and not r.get("pending") and not r.get("unknown") and "error" not in r
        def _record_dispatch(leg,result):
            ctx=out["leg_contexts"][leg]
            if not isinstance(result,dict):
                result={"result":result}
            result.setdefault("request_id",ctx["request_id"])
            result.setdefault("op","open")
            result.setdefault("dispatch_request_id",ctx["request_id"])
            result.setdefault("dispatch_comment",ctx["comment"])
            result.setdefault("dispatch_started",True)
            if (result.get("accepted") or result.get("pending") or
                    result.get("success") or result.get("ok")):
                result.setdefault("dispatch_durable",True)
            ctx["dispatch_started"]=bool(result.get("dispatch_started"))
            if "dispatch_durable" in result:
                ctx["dispatch_durable"]=result.get("dispatch_durable")
            return result
        async def _main(ack_only=False):
            ctx=out["leg_contexts"]["main"]
            ctx["dispatch_started"]=True
            try:
                out["main"]=await self.main.open_order(main_symbol, main_vol, mside,
                              comment=ctx["comment"], request_id=ctx["request_id"],
                              deviation=main_dev, ack_only=ack_only)
                out["main"]=_record_dispatch("main",out["main"])
                out["main_ok"]=_ok(out["main"])
            except Exception as ex:
                out["main"]=_open_dispatch_exception(
                    ex,ctx["request_id"],ctx["comment"])
                ctx["dispatch_started"]=bool(out["main"].get("dispatch_started"))
                if "dispatch_durable" in out["main"]:
                    ctx["dispatch_durable"]=out["main"]["dispatch_durable"]
        async def _hedge(ack_only=False):
            if not self.hedge: out["hedge"]={"skipped":"no hedge leg"}; out["hedge_ok"]=False; return
            ctx=out["leg_contexts"]["hedge"]
            ctx["dispatch_started"]=True
            try:
                out["hedge"]=await self.hedge.open_order(hedge_symbol, hedge_vol, hside,
                               comment=ctx["comment"], request_id=ctx["request_id"],
                               deviation=hedge_dev, ack_only=ack_only)
                out["hedge"]=_record_dispatch("hedge",out["hedge"])
                out["hedge_ok"]=_ok(out["hedge"])
            except Exception as ex:
                out["hedge"]=_open_dispatch_exception(
                    ex,ctx["request_id"],ctx["comment"])
                ctx["dispatch_started"]=bool(out["hedge"].get("dispatch_started"))
                if "dispatch_durable" in out["hedge"]:
                    ctx["dispatch_durable"]=out["hedge"]["dispatch_durable"]
        async def _rec(leg, wait_for_terminal=False):
            """UNKNOWN 腿 → 幂等桥 order-status 快路径 → comment#rid 真相扫描 → 恢复/判失败/保留unknown。"""
            lr=out.get(leg) or {}
            recovered_from_unknown=bool(
                lr.get("unknown") or
                str(lr.get("certainty") or "").upper()=="UNKNOWN")
            if lr.get("pending") and not wait_for_terminal:
                return
            if lr.get("not_sent") and lr.get("dispatch_durable") is False:
                lr["truth_confirmed"]="not_filled"
                lr["not_filled"]=True
                lr["certainty"]="NOT_FILLED"
                lr.setdefault("src","client-rejection")
                out[leg+"_ok"]=False
                return
            if lr.get("not_sent"):
                lr["unknown"]=True
                lr["certainty"]="UNKNOWN"
                lr.setdefault("error","client could not prove the request was not dispatched")
            needs_ordered_truth=(wait_for_terminal and ordered_ack and not _ok(lr))
            if not (lr.get("unknown") or lr.get("pending") or needs_ordered_truth): return
            exec_leg=self.main if leg=="main" else self.hedge
            t_leg=(getattr(truth,leg,None) if truth is not None else None) or exec_leg
            leg_ctx=(out.get("leg_contexts") or {}).get(leg) or {}
            full_rid=rid+leg[0]
            otoken="Q"+_hashlib.sha1(full_rid.encode()).hexdigest()[:9]        # 与 agent _otoken 同式, 供真相扫描
            truth_deadline=_new_deadline(ORDERED_TERMINAL_TIMEOUT_SEC)
            terminal_attempts=(max(1,int(ORDERED_TERMINAL_TIMEOUT_SEC /
                                         ORDERED_TERMINAL_POLL_SEC))
                               if wait_for_terminal else 1)
            if wait_for_terminal:
                probe=await _race_open_terminal(
                    exec_leg,full_rid,leg_ctx.get("comment"),terminal_attempts,
                    truth_deadline,expected_ticket=lr.get("ticket"),
                    poll_delay=ORDERED_TERMINAL_POLL_SEC)
            else:
                probe=await order_status_probe(
                    exec_leg,full_rid,tries=terminal_attempts,
                    delay=ORDERED_TERMINAL_POLL_SEC,deadline=truth_deadline)
            if probe is not None and probe.get("failed"):
                if _explicit_not_filled(probe):
                    failure=dict(probe)
                    failure.pop("failed",None)
                    failure.setdefault("error",lr.get("error","timeout"))
                    failure["unknown_resolved"]="not_filled"
                    failure["truth_confirmed"]="not_filled"
                    failure["src"]="order-status"
                    out[leg]=failure
                    out[leg+"_ok"]=False; return
                unresolved=dict(lr)
                unresolved.update({
                    "unknown":True, "certainty":"UNKNOWN", "src":"order-status",
                    "request_id":full_rid, "op":"open",
                })
                unresolved.setdefault("error",probe.get("error") or
                                      "terminal failure lacks explicit no-fill proof")
                out[leg]=unresolved; out[leg+"_ok"]=False; return
            if not wait_for_terminal and not probe:
                return
            rec=(probe if (probe and probe.get("ok")) else
                 await verify_leg_open(t_leg,rid,
                                       tries=1 if wait_for_terminal else 4,
                                       delay=0.0 if wait_for_terminal else 1.5,
                                       extra_tags=[otoken],deadline=truth_deadline))
            if isinstance(rec,dict):
                if recovered_from_unknown:
                    rec["recovered_from_unknown"]=True
                rec["request_id"]=full_rid; rec["op"]="open"
                out[leg]=rec; out[leg+"_ok"]=True
            elif rec in ("NO_VISIBLE_FILL","HISTORY_ONLY","NOFILL"):
                # An empty position/history snapshot can lag a command already
                # accepted by the Agent. Only Agent terminal FAILED proves that
                # an ordered leg was not filled; temporary absence stays UNKNOWN.
                unresolved=dict(lr)
                unresolved["unknown"]=True
                unresolved["certainty"]="UNKNOWN"
                unresolved["truth_snapshot"]=("history_only" if rec=="HISTORY_ONLY"
                                                else "no_visible_fill")
                unresolved.setdefault("error","ordered leg outcome is not authoritative")
                unresolved.setdefault("request_id",full_rid)
                unresolved.setdefault("op","open")
                out[leg]=unresolved; out[leg+"_ok"]=False
            elif wait_for_terminal:
                unresolved=dict(lr)
                unresolved["unknown"]=True
                unresolved.setdefault("error","ordered leg outcome is not authoritative")
                unresolved.setdefault("request_id",full_rid)
                unresolved.setdefault("op","open")
                out[leg]=unresolved; out[leg+"_ok"]=False
            # None=查不清: 保留 unknown=True 交上层(绝不盲判成/败)
        async def _ordered_leg(stage,leg,send):
            request_id=rid+leg[0]
            ctx=out["leg_contexts"][leg]
            out[leg]={"request_id":request_id,"op":"open",
                      "dispatch_request_id":ctx["request_id"],
                      "dispatch_comment":ctx["comment"],"dispatch_started":False}
            if not await _phase(stage+"_INTENT"):
                out[leg]={"error":"SAGA_%s_INTENT_PERSIST_FAILED"%stage,
                          "request_id":request_id,"op":"open",
                          "dispatch_request_id":ctx["request_id"],
                          "dispatch_comment":ctx["comment"],
                          "dispatch_started":False,"dispatch_durable":False}
                out[leg+"_ok"]=False
                if stage=="SECOND":
                    out["saga_unknown"]=True
                return False
            await send(ack_only=ordered_ack)
            current=dict(out.get(leg) or {})
            if current.get("unknown"):
                # A lost HTTP response may hide a broker fill.  Persist the
                # ambiguity and return control to the background reconciler;
                # the second ordered leg must not cross this barrier inline.
                current.setdefault("certainty","UNKNOWN")
                current.setdefault("request_id",request_id); current.setdefault("op","open")
                out[leg]=current; out[leg+"_ok"]=False
                if not await _phase(stage+"_UNKNOWN"):
                    out["saga_unknown"]=True
                return False
            if not await _phase(stage+"_ACK"):
                current=dict(out.get(leg) or {})
                current["unknown"]=True
                current.setdefault("error","saga ACK snapshot was not durable")
                current.setdefault("request_id",request_id); current.setdefault("op","open")
                out[leg]=current; out[leg+"_ok"]=False; out["saga_unknown"]=True
                return False
            # For a multi-slot burst, hand control back after the durable
            # first-leg ACK. The finalizer resumes the second leg with the same
            # idempotent request id, so independent slots do not each hold a
            # QH worker while waiting on the account-serial broker.
            if dispatch_only:
                current=dict(out.get(leg) or {})
                durable_ack=bool(
                    current.get("dispatch_durable") and
                    (current.get("pending") or current.get("accepted") or
                     current.get("success") or current.get("ok") or
                     str(current.get("state") or "").upper() in
                     ("PENDING", "SENDING", "DISPATCHING", "DONE")))
                if durable_ack:
                    current.setdefault("pending", True)
                    current.setdefault("state", "DISPATCHING")
                    out[leg]=current
                    out[leg+"_ok"]=False
                    return bool(eager_ordered_ack)
                current.setdefault("error","Agent did not durably accept ordered open")
                out[leg]=current; out[leg+"_ok"]=False
                await _phase(stage+"_FAILED")
                return False
            await _rec(leg,wait_for_terminal=True)
            current=out.get(leg) or {}
            terminal=(stage+"_DONE" if out.get(leg+"_ok") else
                      stage+"_UNKNOWN" if current.get("pending") or current.get("unknown") else
                      stage+"_FAILED")
            if not await _phase(terminal):
                current=dict(current); current["unknown"]=True
                current.setdefault("error","saga terminal snapshot was not durable")
                out[leg]=current; out[leg+"_ok"]=False; out["saga_unknown"]=True
                return False
            return bool(out.get(leg+"_ok"))

        if not await _phase("PAIR_INTENT"):
            out["main"]={"error":"SAGA_PAIR_INTENT_PERSIST_FAILED",
                         "request_id":rid+"m","op":"open"}
            out["hedge"]={"error":"SAGA_PAIR_INTENT_PERSIST_FAILED",
                          "request_id":rid+"h","op":"open"}
            return out

        if burst_admission:
            # Multi-slot QH batches own independent slot locks and capacity
            # reservations. Admit both leg request ids after the durable pair
            # intent instead of waiting for the first broker terminal result.
            # The MT5 bridge still serializes native calls per terminal; this
            # only removes the QH first-leg barrier between independent slots.
            for leg in ("main", "hedge"):
                ctx=out["leg_contexts"][leg]
                out[leg]={"request_id":ctx["request_id"],"op":"open",
                          "dispatch_request_id":ctx["request_id"],
                          "dispatch_comment":ctx["comment"],
                          "dispatch_started":False}
            if not await _phase("BURST_INTENT"):
                out["saga_unknown"]=True
                for leg in ("main", "hedge"):
                    out[leg].update({"unknown":True,"certainty":"UNKNOWN",
                                     "error":"saga burst intent snapshot was not durable"})
                return out
            await asyncio.gather(_main(ack_only=True), _hedge(ack_only=True))
            if not await _phase("BURST_ACK"):
                out["saga_unknown"]=True
            await self._compensate_ordered_open(out, timeout=30.0,
                                                phase_hook=phase_hook)
            return out

        delay=SPEED_LEG_DELAY.get(speed,0.2)
        if mode=="concurrent":
            await asyncio.gather(_main(ack_only=ordered_ack), _hedge(ack_only=ordered_ack))
            if dispatch_only:
                await _phase("PAIR_ACK")
                return out
            await asyncio.gather(_rec("main"), _rec("hedge"))
        elif mode=="hedge_first":
            if not await _ordered_leg("FIRST","hedge",_hedge):
                return out                                      # 第一腿未终态成功→不开第二腿
            if delay>0: await asyncio.sleep(delay)
            await _ordered_leg("SECOND","main",_main)
        else:  # main_first (默认 1先2后)
            if not await _ordered_leg("FIRST","main",_main):
                return out                                      # 第一腿未终态成功→不开第二腿
            if delay>0: await asyncio.sleep(delay)
            await _ordered_leg("SECOND","hedge",_hedge)
        if dispatch_only and eager_ordered_ack:
            return out
        await self._compensate_ordered_open(out, timeout=30.0, phase_hook=phase_hook)
        return out

    async def _compensate_ordered_open(self, res, timeout=30.0, phase_hook=None):
        """Close the filled first leg when the ordered second leg definitively failed.

        The compensation request id is derived from the pair id, so an Agent/QH
        restart can safely resume the same exact-ticket close without duplicating it.
        """
        if not isinstance(res,dict) or res.get("op")!="open":
            return res
        async def _persist(name):
            res["saga_phase"]=name
            if phase_hook is None:
                return True
            try:
                saved=phase_hook(name,res)
                if _inspect.isawaitable(saved):
                    saved=await saved
                if saved is False:
                    raise RuntimeError("phase hook rejected snapshot")
                return True
            except Exception as ex:
                res["saga_persist_error"]="%s:%s"%(name,ex.__class__.__name__)
                return False
        mode=res.get("mode")
        burst=bool(res.get("burst_admission"))
        if burst:
            # A burst admits both legs independently.  The bridge still
            # serializes native MT5 calls, but either leg may be the one that
            # receives an authoritative NOT_FILLED result first.  Select the
            # filled peer deterministically and never infer a no-fill from a
            # timeout, an empty snapshot, or a pending/unknown peer.
            candidates=[]
            for filled, failed in (("main","hedge"),("hedge","main")):
                filled_result=res.get(filled) or {}
                failed_result=res.get(failed) or {}
                if (bool(res.get(filled+"_ok")) and failed_result and
                        not failed_result.get("pending") and
                        not failed_result.get("unknown") and
                        not bool(res.get(failed+"_ok")) and
                        _explicit_not_filled(failed_result)):
                    candidates.append((filled,failed))
            if len(candidates)!=1:
                return res
            first,second=candidates[0]
            first_result=res.get(first) or {}; second_result=res.get(second) or {}
        else:
            if mode not in ("main_first","hedge_first"):
                return res
            first,second=(("main","hedge") if mode=="main_first" else ("hedge","main"))
            first_result=res.get(first) or {}; second_result=res.get(second) or {}
            first_ok=bool(res.get(first+"_ok"))
            second_pending=bool(second_result.get("pending") or second_result.get("unknown"))
            second_ok=bool(res.get(second+"_ok"))
            second_nofill=_explicit_not_filled(second_result)
            if (not first_ok or second_ok or second_pending or not second_result or
                    not second_nofill):
                return res
        existing=res.get("compensation") or {}
        if existing.get("ok") and existing.get("closed"):
            res["compensated"]=True
            return res

        ticket=(first_result.get("ticket") or first_result.get("order") or
                first_result.get("position"))
        try: ticket=int(ticket)
        except (TypeError,ValueError): ticket=0
        ctx=(res.get("leg_contexts") or {}).get(first) or {}
        leg_obj=self.main if first=="main" else self.hedge
        pair_rid=str(res.get("request_id") or "")
        # Keep the established ``<pair>c`` ID for ordered requests.  Burst
        # requests include the successful leg so a main-side and hedge-side
        # compensation can never collide after a restart or retry.
        request_id=(pair_rid+"c"+first[0]) if burst else (pair_rid+"c")
        compensation={"leg":first,"ticket":ticket,"request_id":request_id,
                      "op":"close","reason":(
                          "burst_peer_not_filled" if burst else
                          "ordered_second_leg_failed")}
        res["compensation"]=compensation
        if leg_obj is None or ticket<=0 or not request_id or not ctx.get("symbol") or not ctx.get("side"):
            compensation["error"]="exact first-leg compensation context unavailable"
            return res

        if not await _persist("COMPENSATION_INTENT"):
            compensation.update({"pending":True,"unknown":True,
                                 "error":"compensation intent was not durable"})
            res["saga_unknown"]=True
            return res

        try:
            submitted=await leg_obj.close_position(
                ctx["symbol"],ctx["side"],ctx.get("volume"),ticket=ticket,
                request_id=request_id,ack_only=True)
            if not isinstance(submitted,dict): submitted={"result":submitted}
            compensation.update(submitted)
            compensation.update({"leg":first,"ticket":ticket,"request_id":request_id,"op":"close"})
        except Exception as ex:
            compensation["error"]=str(ex)
            if _is_unknown_exc(ex): compensation["unknown"]=True

        if not await _persist("COMPENSATION_ACK"):
            compensation["unknown"]=True
            compensation.setdefault("error","compensation ACK snapshot was not durable")
            res["saga_unknown"]=True

        deadline=_new_deadline(timeout)
        agent_done=(bool(compensation.get("ok") or compensation.get("success")) and
                    not compensation.get("pending") and not compensation.get("unknown") and
                    "error" not in compensation)
        if not (compensation.get("ok") or compensation.get("success")) or compensation.get("pending") or compensation.get("unknown"):
            attempts=max(1,int(float(timeout)/0.05))
            probe=await order_status_probe(leg_obj,request_id,tries=attempts,delay=0.05,
                                           deadline=deadline)
            if probe and probe.get("ok"):
                compensation.update(probe)
                compensation.pop("pending",None); compensation.pop("unknown",None)
                agent_done=True
            elif probe and probe.get("failed"):
                compensation.update(probe)
                compensation.pop("pending",None)
                agent_done=False

        truth_delay=min(0.10,max(0.005,float(timeout)/4.0))
        closed=await verify_leg_closed(leg_obj,ticket,tries=3,delay=truth_delay,
                                       deadline=deadline)
        if closed=="CLOSED" and agent_done:
            compensation.update({"ok":True,"success":True,"closed":True,
                                 "recovered":True,"src":"agent-done+positions-exact-ticket"})
            compensation.pop("pending",None); compensation.pop("unknown",None)
            compensation.pop("failed",None); compensation.pop("error",None)
            res["compensated"]=True
            res["compensated_leg"]=first
        elif closed=="CLOSED":
            # One empty snapshot may lag or be incomplete. Without Agent DONE,
            # retain UNKNOWN and let the durable saga retry the same close id.
            compensation.update({"ok":False,"closed":False,"unknown":True,
                                 "position_truth":"ticket_absent_unconfirmed"})
            compensation.setdefault("error","compensation Agent terminal unavailable")
            res["saga_unknown"]=True
        elif closed=="OPEN":
            compensation.update({"ok":False,"closed":False,
                                 "error":compensation.get("error") or "compensation ticket remains open"})
        else:
            compensation["unknown"]=True
            compensation.setdefault("error","compensation truth unavailable")
        terminal=("COMPENSATION_DONE" if compensation.get("ok") and compensation.get("closed") else
                  "COMPENSATION_UNKNOWN" if compensation.get("pending") or compensation.get("unknown") else
                  "COMPENSATION_FAILED")
        if not await _persist(terminal):
            compensation["unknown"]=True
            compensation.setdefault("error","compensation terminal snapshot was not durable")
            res["saga_unknown"]=True
        elif terminal in ("COMPENSATION_DONE","COMPENSATION_FAILED"):
            res.pop("saga_unknown",None)
        return res
    async def close_pair(self, main_symbol, hedge_symbol, main_side, hedge_side,
                         main_vol=None, hedge_vol=None, mode="concurrent", speed="fast",
                         main_ticket=None, hedge_ticket=None, truth=None, rid=None,
                         ordered_ack=False, burst_admission=False):
        """按对平仓(双腿各平一笔)。side=各腿当前持仓方向; ticket=按坑精确平某笔(有票只平该笔, 无票回落按方向)。
           mode/speed 同 open_pair 语义。
           V1.1(M2): 平仓异常不再向上抛(原 gather 直接炸500); 超时类=UNKNOWN 且有 ticket →
           经 truth 查持仓: ticket 消失=实际已平(恢复成功, 防重复平仓), 仍在=确认未平, 查不清/无票=保留 unknown。"""
        if not main_ticket or not hedge_ticket:
            raise ValueError("EXACT_TICKET_REQUIRED")
        rid=rid or _gen_rid()
        res={"main":None,"hedge":None,"request_id":rid,"main_ok":False,"hedge_ok":False,
             "op":"close","ordered_ack":bool(ordered_ack),
             "burst_admission":bool(burst_admission),
             "saga_durable":bool(ordered_ack),
             "tickets":{"main":main_ticket,"hedge":hedge_ticket},
             "leg_contexts":{
                 "main":{"symbol":main_symbol,"side":main_side,
                         "volume":main_vol,"ticket":main_ticket},
                 "hedge":{"symbol":hedge_symbol,"side":hedge_side,
                          "volume":hedge_vol,"ticket":hedge_ticket},
             }}
        async def _one(leg, sym, side, vol, ticket):
            leg_obj=self.main if leg=="main" else self.hedge
            try:
                kwargs={"ticket":ticket,"request_id":rid+leg[0]}
                if ordered_ack: kwargs["ack_only"]=True
                res[leg]=await leg_obj.close_position(sym,side,vol,**kwargs)
                lr=res[leg] or {}
                if isinstance(lr,dict):
                    lr.setdefault("request_id",rid+leg[0]); lr.setdefault("op","close"); lr.setdefault("ticket",ticket)
                res[leg+"_ok"]=bool(lr.get("success",lr.get("ok",True))) and not lr.get("pending") and not lr.get("unknown") and "error" not in lr
            except Exception as ex:
                res[leg]={"error":str(ex),"request_id":rid+leg[0],"op":"close","ticket":ticket}
                if not _is_unknown_exc(ex): return
                res[leg]["unknown"]=True
        async def _cm(): await _one("main", main_symbol, main_side, main_vol, main_ticket)
        async def _ch():
            if self.hedge: await _one("hedge", hedge_symbol, hedge_side, hedge_vol, hedge_ticket)
        delay=SPEED_LEG_DELAY.get(speed,0.2)
        if burst_admission:
            # Exact tickets make both legs independently idempotent. In a
            # multi-slot close burst, admit both legs together and let the
            # finalizer verify each ticket without a configured leg delay.
            await asyncio.gather(_cm(), _ch())
        elif mode=="concurrent":
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

    async def close_leg(self, leg, symbol, side, volume=None, ticket=None, rid=None,
                        ordered_ack=False):
        """Close exactly one ticket on one leg without requiring a synthetic pair."""
        if leg not in ("main", "hedge"):
            raise ValueError("leg must be main or hedge")
        if not ticket:
            raise ValueError("EXACT_TICKET_REQUIRED")
        leg_obj = self.main if leg == "main" else self.hedge
        if leg_obj is None:
            raise ValueError("LEG_CONNECTOR_UNAVAILABLE")
        rid = rid or _gen_rid()
        request_id = rid + ("m" if leg == "main" else "h")
        res = {"main": None, "hedge": None, "request_id": rid,
               "main_ok": False, "hedge_ok": False, "op": "close",
               "tickets": {leg: ticket}}
        try:
            kwargs={"ticket":ticket,"request_id":request_id}
            if ordered_ack: kwargs["ack_only"]=True
            res[leg] = await leg_obj.close_position(symbol,side,volume,**kwargs)
            lr = res[leg] or {}
            if isinstance(lr, dict):
                lr.setdefault("request_id", request_id)
                lr.setdefault("op", "close")
                lr.setdefault("ticket", ticket)
            res[leg + "_ok"] = (
                bool(lr.get("success", lr.get("ok", True)))
                and not lr.get("pending")
                and not lr.get("unknown")
                and "error" not in lr
            )
        except Exception as ex:
            res[leg] = {"error": str(ex), "request_id": request_id,
                        "op": "close", "ticket": ticket}
            if _is_unknown_exc(ex):
                res[leg]["unknown"] = True
        return res

    async def resolve_pair_pending(self, res, timeout=60.0, phase_hook=None):
        """Resolve Agent responses from status first, then broker truth without duplicate writes."""
        attempts=max(1, int(float(timeout) / 0.05))
        truth_deadline=_new_deadline(timeout)
        async def _phase(name):
            res["saga_phase"]=name
            if phase_hook is None:
                return True
            try:
                saved=phase_hook(name,res)
                if _inspect.isawaitable(saved):
                    saved=await saved
                if saved is False:
                    raise RuntimeError("phase hook rejected snapshot")
                return True
            except Exception as ex:
                res["saga_persist_error"]="%s:%s"%(name,ex.__class__.__name__)
                res["saga_unknown"]=True
                return False
        async def _resume_burst_intent(leg):
            """Replay a crash-persisted burst intent with the same Agent id."""
            if (res.get("op")!="open" or not res.get("burst_admission") or
                    str(res.get("saga_phase") or "") not in
                    ("PAIR_INTENT","BURST_INTENT")):
                return False
            current=res.get(leg) if isinstance(res.get(leg),dict) else {}
            if (current.get("pending") or current.get("unknown") or
                    current.get("dispatch_started") is True or
                    _explicit_not_filled(current)):
                return False
            ctx=(res.get("leg_contexts") or {}).get(leg) or {}
            expected=(res.get("request_id") or "")+leg[0]
            observed=[value for value in (
                current.get("request_id"),current.get("dispatch_request_id"),
                ctx.get("request_id"),ctx.get("dispatch_request_id"),
            ) if value]
            if not expected or any(str(value)!=expected for value in observed):
                res[leg]={"error":"SAGA_REQUEST_ID_MISMATCH","unknown":True,
                          "certainty":"UNKNOWN","request_id":expected,
                          "observed_request_ids":observed,"op":"open"}
                res[leg+"_ok"]=False
                return False
            comment=(ctx.get("comment") or ctx.get("dispatch_comment") or
                     current.get("dispatch_comment"))
            leg_obj=self.main if leg=="main" else self.hedge
            if (leg_obj is None or not ctx.get("symbol") or
                    ctx.get("volume") is None or not ctx.get("side") or
                    not comment):
                unresolved=dict(current)
                unresolved.update({"unknown":True,"certainty":"UNKNOWN",
                                   "request_id":expected,"op":"open",
                                   "error":"SAGA_BURST_RECOVERY_CONTEXT_UNAVAILABLE"})
                res[leg]=unresolved; res[leg+"_ok"]=False
                return False
            try:
                reply=await _deadline_call(
                    truth_deadline,
                    lambda: leg_obj.open_order(
                        ctx["symbol"],ctx["volume"],ctx["side"],
                        comment=comment,request_id=expected,
                        deviation=ctx.get("deviation"),ack_only=True),
                )
                reply=dict(reply or {})
                reply.setdefault("request_id",expected); reply.setdefault("op","open")
                reply.setdefault("dispatch_request_id",expected)
                reply.setdefault("dispatch_comment",comment)
                reply.setdefault("dispatch_started",True)
                if (reply.get("accepted") or reply.get("pending") or
                        reply.get("success") or reply.get("ok")):
                    reply.setdefault("dispatch_durable",True)
                res[leg]=reply
                res[leg+"_ok"]=(bool(reply.get("success",reply.get("ok",True))) and
                                  not reply.get("pending") and
                                  not reply.get("unknown") and
                                  "error" not in reply)
            except Exception as ex:
                res[leg]=_open_dispatch_exception(ex,expected,comment)
                res[leg+"_ok"]=False
            ctx["dispatch_started"]=bool((res.get(leg) or {}).get("dispatch_started"))
            if "dispatch_durable" in (res.get(leg) or {}):
                ctx["dispatch_durable"]=res[leg]["dispatch_durable"]
            return True
        async def _one(leg):
            current=res.get(leg) or {}
            if not (current.get("pending") or current.get("unknown")):
                return
            leg_obj=self.main if leg=="main" else self.hedge
            if leg_obj is None:
                return
            request_id=current.get("request_id") or ((res.get("request_id") or "") + leg[0])
            operation=current.get("op") or res.get("op")
            recovered_from_unknown=bool(
                current.get("unknown") or
                str(current.get("certainty") or "").upper()=="UNKNOWN")
            if (operation=="open" and res.get("ordered_ack") and
                    res.get("mode") in ("main_first","hedge_first")):
                expected_request_id=(res.get("request_id") or "")+leg[0]
                if not expected_request_id or request_id!=expected_request_id:
                    res[leg]={
                        "error":"SAGA_REQUEST_ID_MISMATCH", "unknown":True,
                        "certainty":"UNKNOWN", "request_id":expected_request_id,
                        "observed_request_id":request_id, "op":"open",
                    }
                    res[leg+"_ok"]=False
                    return
            ticket=current.get("ticket") or (res.get("tickets") or {}).get(leg)
            closed=None
            if operation=="close" and ticket is not None:
                probe,closed=await _race_close_terminal(
                    leg_obj,request_id,ticket,attempts,truth_deadline)
            elif operation=="open":
                ctx=(res.get("leg_contexts") or {}).get(leg) or {}
                expected_comment=(ctx.get("comment") or
                                  ctx.get("dispatch_comment") or
                                  current.get("dispatch_comment"))
                probe=await _race_open_terminal(
                    leg_obj,request_id,expected_comment,attempts,truth_deadline,
                    expected_ticket=(current.get("ticket") or
                                     current.get("position")))
            else:
                probe=await order_status_probe(
                    leg_obj,request_id,tries=attempts,delay=0.05,
                    deadline=truth_deadline)
            if probe and probe.get("ok"):
                if recovered_from_unknown:
                    probe["recovered_from_unknown"]=True
                probe["request_id"]=request_id
                if operation: probe["op"]=operation
                if ticket is not None: probe.setdefault("ticket",ticket)
                res[leg]=probe
                res[leg+"_ok"]=True
            elif probe and probe.get("failed"):
                if operation!="open" or _explicit_not_filled(probe):
                    failure=dict(probe)
                    failure.pop("failed",None)
                    failure.setdefault("error","Agent reported terminal failure")
                    failure["src"]="order-status"
                    if operation=="open":
                        failure["unknown_resolved"]="not_filled"
                        failure["truth_confirmed"]="not_filled"
                    failure["request_id"]=request_id
                    if operation: failure["op"]=operation
                    if ticket is not None: failure.setdefault("ticket",ticket)
                    res[leg]=failure
                    res[leg+"_ok"]=False
                else:
                    unresolved=dict(current)
                    unresolved.update({"unknown":True,"certainty":"UNKNOWN",
                                       "src":"order-status","request_id":request_id,
                                       "op":"open"})
                    unresolved.setdefault("error",probe.get("error") or
                                          "terminal failure lacks explicit no-fill proof")
                    res[leg]=unresolved; res[leg+"_ok"]=False
            elif operation=="close" and ticket is not None:
                if closed=="CLOSED":
                    res[leg]={"success":True,"ok":True,"recovered":True,"src":"positions",
                              "unknown_resolved":"closed","closed":[ticket],"ticket":ticket,
                              "request_id":request_id,"op":"close"}
                    if recovered_from_unknown:
                        res[leg]["recovered_from_unknown"]=True
                    res[leg+"_ok"]=True
                elif closed=="OPEN":
                    res[leg]={"error":"close result unknown; exact ticket is still open",
                              "unknown_resolved":"still_open","ticket":ticket,
                              "request_id":request_id,"op":"close"}
                    res[leg+"_ok"]=False
            elif operation=="open":
                pair_rid=res.get("request_id") or request_id[:-1]
                otoken="Q"+_hashlib.sha1(request_id.encode()).hexdigest()[:9]
                recovered=await verify_leg_open(leg_obj,pair_rid,extra_tags=[otoken],
                                                deadline=truth_deadline)
                if isinstance(recovered,dict):
                    if recovered_from_unknown:
                        recovered["recovered_from_unknown"]=True
                    recovered["request_id"]=request_id; recovered["op"]="open"
                    res[leg]=recovered; res[leg+"_ok"]=True
                elif recovered in ("NO_VISIBLE_FILL","HISTORY_ONLY","NOFILL"):
                    unresolved=dict(current)
                    unresolved.update({"unknown":True,"certainty":"UNKNOWN",
                                       "truth_snapshot":("history_only" if recovered=="HISTORY_ONLY"
                                                         else "no_visible_fill"),
                                       "request_id":request_id,"op":"open"})
                    unresolved.setdefault("error","open result remains unknown; fill is not visible yet")
                    res[leg]=unresolved
                    res[leg+"_ok"]=False
        resumed=await asyncio.gather(
            _resume_burst_intent("main"),_resume_burst_intent("hedge"))
        if any(resumed):
            await _phase("BURST_ACK")
        await asyncio.gather(_one("main"), _one("hedge"))

        if res.get("op")=="close" and res.get("ordered_ack"):
            # A durable close ACK may still be waiting behind earlier native
            # MT5 calls.  If the exact ticket remains open, replay the same
            # request id: Agent WAL/tombstones make this a status recovery,
            # while the immutable ticket prevents closing another position.
            async def _resume_close(leg):
                current=res.get(leg) if isinstance(res.get(leg),dict) else {}
                if (bool(current.get("success") or current.get("ok")) and
                        not current.get("pending") and not current.get("unknown") and
                        not current.get("error")):
                    return
                if (current.get("src")=="order-status" and current.get("error") and
                        not current.get("pending") and not current.get("unknown")):
                    return
                unresolved=bool(
                    current.get("pending") or current.get("unknown") or
                    current.get("truth_unavailable") or
                    current.get("unknown_resolved")=="still_open" or
                    current.get("truth_observed")=="still_open" or
                    current.get("truth_confirmed")=="still_open")
                if not unresolved:
                    return
                leg_obj=self.main if leg=="main" else self.hedge
                ctx=(res.get("leg_contexts") or {}).get(leg) or {}
                request_id=(res.get("request_id") or "")+leg[0]
                ticket=(res.get("tickets") or {}).get(leg) or ctx.get("ticket")
                observed_id=current.get("request_id")
                if observed_id and str(observed_id)!=str(request_id):
                    res[leg]={"error":"SAGA_REQUEST_ID_MISMATCH","unknown":True,
                              "certainty":"UNKNOWN","request_id":request_id,
                              "observed_request_id":observed_id,"op":"close",
                              "ticket":ticket}
                    res[leg+"_ok"]=False
                    return
                try:
                    context_ticket=ctx.get("ticket")
                    ticket_matches=(context_ticket in (None,"") or
                                    int(context_ticket)==int(ticket))
                except (TypeError,ValueError):
                    ticket_matches=False
                if (leg_obj is None or not request_id or not ticket or
                        not ticket_matches or not ctx.get("symbol") or
                        ctx.get("side") not in ("buy","sell")):
                    pending=dict(current)
                    pending.update({"accepted":True,"pending":True,
                                    "request_id":request_id,"ticket":ticket,
                                    "op":"close"})
                    pending.pop("error",None); pending.pop("truth_confirmed",None)
                    res[leg]=pending; res[leg+"_ok"]=False
                    return
                try:
                    reply=await _deadline_call(
                        truth_deadline,
                        lambda: leg_obj.close_position(
                            ctx["symbol"],ctx["side"],ctx.get("volume"),
                            ticket=ticket,request_id=request_id,ack_only=True),
                    )
                except Exception as ex:
                    pending=dict(current)
                    pending.update({"accepted":True,"pending":True,
                                    "request_id":request_id,"ticket":ticket,
                                    "op":"close","resume_error":ex.__class__.__name__})
                    pending.pop("error",None); pending.pop("truth_confirmed",None)
                    res[leg]=pending; res[leg+"_ok"]=False
                    return
                reply=dict(reply or {})
                reported_request_id=reply.get("request_id")
                reported_ticket=reply.get("ticket")
                try:
                    replay_identity_exact=bool(
                        reported_request_id not in (None,"") and
                        str(reported_request_id)==str(request_id) and
                        reported_ticket not in (None,"",0,"0") and
                        int(reported_ticket)==int(ticket))
                except (TypeError,ValueError):
                    replay_identity_exact=False
                reply.setdefault("request_id",request_id)
                reply.setdefault("ticket",ticket)
                reply.setdefault("op","close")
                positive=bool(reply.get("success") or reply.get("ok"))
                terminal_success=bool(
                    positive and not reply.get("pending") and
                    not reply.get("unknown") and not reply.get("error") and
                    not reply.get("partial") and
                    str(reply.get("certainty") or "").upper()!="UNKNOWN")
                trusted_replay=bool(
                    terminal_success and reply.get("idempotency_hit") is True and
                    replay_identity_exact)
                if trusted_replay:
                    # The Agent returned its durable DONE tombstone for this
                    # exact request and position ticket. A pending position
                    # cache refresh does not weaken that broker terminal fact.
                    reply["src"]="idempotent-terminal-replay"
                if terminal_success:
                    res[leg]=reply; res[leg+"_ok"]=True
                elif reply.get("error") and not reply.get("accepted"):
                    res[leg]=reply; res[leg+"_ok"]=False
                else:
                    reply["accepted"]=True; reply["pending"]=True
                    reply.pop("error",None); reply.pop("truth_confirmed",None)
                    res[leg]=reply; res[leg+"_ok"]=False

            await asyncio.gather(_resume_close("main"), _resume_close("hedge"))

        # Resume a crash at either write boundary with the same Agent request id.
        # The Agent tombstone/WAL turns this into status recovery, never a second
        # broker operation, even if QH died immediately after its HTTP write.
        if (res.get("op")=="open" and res.get("ordered_ack") and
                res.get("mode") in ("main_first","hedge_first") and
                not res.get("burst_admission")):
            first,second=(("main","hedge") if res.get("mode")=="main_first" else ("hedge","main"))

            async def _resume(stage,leg):
                leg_obj=self.main if leg=="main" else self.hedge
                ctx=(res.get("leg_contexts") or {}).get(leg) or {}
                current=res.get(leg) or {}
                request_id=(res.get("request_id") or "")+leg[0]
                stored_ids=[value for value in (
                    ctx.get("request_id"),ctx.get("dispatch_request_id"),
                    current.get("request_id"),current.get("dispatch_request_id"),
                ) if value]
                if any(str(value)!=request_id for value in stored_ids):
                    res[leg]={"error":"SAGA_REQUEST_ID_MISMATCH","unknown":True,
                              "certainty":"UNKNOWN","request_id":request_id,
                              "observed_request_ids":stored_ids,"op":"open"}
                    res[leg+"_ok"]=False
                    await _phase(stage+"_UNKNOWN")
                    return False
                comment=(ctx.get("comment") or ctx.get("dispatch_comment") or
                         current.get("dispatch_comment"))
                if not comment and res.get("direction"):
                    comment="QH-%s-%s#%s"%(res["direction"],leg,res.get("request_id") or "")
                if (leg_obj is None or not request_id or not ctx.get("symbol") or
                        not ctx.get("side") or ctx.get("volume") is None or not comment):
                    return False
                if (current.get("pending") or current.get("unknown") or
                        current.get("dispatch_started") is True):
                    return False
                ctx["request_id"]=request_id; ctx["comment"]=comment
                ctx["dispatch_request_id"]=request_id; ctx["dispatch_comment"]=comment
                ctx["dispatch_started"]=False
                res[leg]={"request_id":request_id,"op":"open",
                          "dispatch_request_id":request_id,
                          "dispatch_comment":comment,"dispatch_started":False}
                if not await _phase(stage+"_INTENT"):
                    return False
                ctx["dispatch_started"]=True
                try:
                    resumed=await leg_obj.open_order(
                        ctx["symbol"],ctx["volume"],ctx["side"],
                        comment=comment,
                        request_id=request_id,deviation=ctx.get("deviation"),ack_only=True)
                    if not isinstance(resumed,dict): resumed={"result":resumed}
                    resumed.setdefault("request_id",request_id); resumed.setdefault("op","open")
                    resumed.setdefault("dispatch_request_id",request_id)
                    resumed.setdefault("dispatch_comment",comment)
                    resumed.setdefault("dispatch_started",True)
                    if (resumed.get("accepted") or resumed.get("pending") or
                            resumed.get("success") or resumed.get("ok")):
                        resumed.setdefault("dispatch_durable",True)
                    res[leg]=resumed
                    ctx["dispatch_started"]=bool(resumed.get("dispatch_started"))
                    if "dispatch_durable" in resumed:
                        ctx["dispatch_durable"]=resumed.get("dispatch_durable")
                    res[leg+"_ok"]=(bool(resumed.get("success",resumed.get("ok",True)))
                                      and not resumed.get("pending") and not resumed.get("unknown")
                                      and "error" not in resumed)
                except Exception as ex:
                    res[leg]=_open_dispatch_exception(ex,request_id,comment)
                    ctx["dispatch_started"]=bool(res[leg].get("dispatch_started"))
                    if "dispatch_durable" in res[leg]:
                        ctx["dispatch_durable"]=res[leg]["dispatch_durable"]
                if not await _phase(stage+"_ACK"):
                    return False
                await _one(leg)
                current=res.get(leg) or {}
                terminal=(stage+"_DONE" if res.get(leg+"_ok") else
                          stage+"_UNKNOWN" if current.get("pending") or current.get("unknown") else
                          stage+"_FAILED")
                return await _phase(terminal)

            saga_phase=str(res.get("saga_phase") or "")
            first_current=res.get(first) or {}
            first_unsent=(res.get(first) is None or
                          first_current.get("dispatch_started") is False)
            if (not res.get(first+"_ok") and first_unsent and
                    saga_phase in ("PAIR_INTENT","FIRST_INTENT") and
                    not first_current.get("pending") and
                    not first_current.get("unknown")):
                await _resume("FIRST",first)

            if res.get(first+"_ok"):
                current_phase=str(res.get("saga_phase") or "")
                if not current_phase.startswith(("SECOND_","COMPENSATION_")):
                    await _phase("FIRST_DONE")
                if not current_phase.startswith("COMPENSATION_"):
                    second_current=res.get(second) or {}
                    second_phase=str(res.get("saga_phase") or "")
                    retryable_intent_error=str(second_current.get("error") or "").startswith(
                        "SAGA_SECOND_INTENT_PERSIST_FAILED")
                    second_unsent=(res.get(second) is None or
                                   second_current.get("dispatch_started") is False or
                                   retryable_intent_error)
                    can_start_second=(second_phase in ("FIRST_DONE","SECOND_INTENT") and
                                      not second_current.get("pending") and
                                      not second_current.get("unknown"))
                    if second_unsent and can_start_second:
                        await _resume("SECOND",second)
                    elif res.get(second+"_ok"):
                        await _phase("SECOND_DONE")
                    elif second_current.get("pending") or second_current.get("unknown"):
                        await _phase("SECOND_UNKNOWN")
                    elif second_current:
                        await _phase("SECOND_FAILED")
        await self._compensate_ordered_open(res,timeout=timeout,phase_hook=phase_hook)
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
    async def open_order(self, symbol, volume, order_type, comment="QH", request_id=None,
                         deviation=None, ack_only=False):
        self._guard()
        op="Buy" if str(order_type).lower()=="buy" else "Sell"
        j=await self._get("/OrderSend", symbol=symbol, operation=op, volume=volume, comment=comment)
        return {"ok":bool((j or {}).get("ticket")),"ticket":(j or {}).get("ticket"),"_raw":j}
    async def close_position(self, symbol, side, volume=None, ticket=None,
                             request_id=None, ack_only=False):
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

def exec_agent_cfg():
    """api 模式执行代理端点: sg-bridge(A2T PRO 会话制/新加坡, QH_SG_*)优先, 未配置回落 FRA(旧云API)。
       只影响执行链路; pairscan/system健康卡/UUID同步仍显式走 QH_FRA_* env。返回 (base,key,main_port,hedge_port)。"""
    sg=os.environ.get("QH_SG_AGENT_URL","").rstrip("/")
    if sg:
        return (sg, os.environ.get("QH_SG_KEY",""),
                os.environ.get("QH_SG_MAIN_PORT","8021"), os.environ.get("QH_SG_HEDGE_PORT","8001"))
    return (os.environ.get("QH_FRA_AGENT_URL","http://3.77.161.206").rstrip("/"),
            os.environ.get("QH_FRA_KEY",""),
            os.environ.get("QH_FRA_MAIN_PORT","8021"), os.environ.get("QH_FRA_HEDGE_PORT","8001"))

def build_connector(mode) -> IHedgeConnector:
    """连接方式路由工厂(P0): 'bridge'=内网桥(env), 'api'=执行代理(sg-bridge 优先/FRA 回落, 同 mt5-bridge 协议)。
       代理复刻桥协议→api 只是换一组腿 URL/key, 复用同一个 Mt5BridgeConnector。"""
    if mode=="api":
        base,key,mp,hp=exec_agent_cfg()
        return _bridge_from_urls("%s:%s"%(base,mp), key, "%s:%s"%(base,hp), key)
    return Mt5BridgeConnector()   # bridge: env 内网桥
