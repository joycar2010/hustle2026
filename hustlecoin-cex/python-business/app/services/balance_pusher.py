import asyncio
import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings
from app.db.session import SessionLocal
from app.db.models import SubAccount, BalanceSnapshot, GlobalRules
from app.services.fund_aggregate import aggregate_balances

logger = logging.getLogger(__name__)

BALANCE_INTERVAL = 10  # seconds
# 资金净值快照落库间隔(以 10s 周期计):60 → 每 ~10 分钟一行/用户。低频,不压 DB。
SNAPSHOT_EVERY = 60
# 无券币(-3045)重查节流:fetch_max_borrow 每 6 周期(~60s)触发一次,此值=10 → 无券币约每 10 分钟
# 才重查一次 maxBorrowable(看库存是否恢复),避免每分钟对一批无券币重查刷高 400 错误率/SAPI 消耗。
RECHECK_NOINV_EVERY = 10
# P1-5 抢券:对"有人在盯(在 targets)且当前无券"的币,按此秒数节流补一次强查(远快于 10min 常规复查),
# 一旦库存恢复立即删全局 noinv 键解冻,把"盲等到 1800s TTL 过期"缩短到秒级抢券。单币每 15s 至多多查一次,REST 可控。
GRAB_POLL_SEC = 15
# 无券标志 TTL(秒):与引擎侧 engine:noinv EX=1800 对齐。原实现为无过期的进程内存布尔,
# 清除只能靠一次成功查询,而复查又被节流/40币切片卡住 → 库存恢复后"无券"被无限期钉死。
# 加 TTL 后到期自动失效,下轮 fetch 真实重查。
NOINV_TTL_SEC = 1800

# ── 写后即时余额刷新(事件驱动)──
# 借/还币成功后,生产者(还币端点 / 引擎 execute_borrow·execute_repay)往此频道 publish user_id,
# BalancePusher 立即对该用户做一次「按范围限定」的余额重推(只查该用户账户,用缓存的 maxBorrowable),
# 让 dashboard 子账户行的现币/借币/利息秒级刷新,而非干等下一个 10s 轮询周期(问题4根因)。
REFRESH_CHANNEL = "balance:refresh"
# 突发去抖:一批信号(如引擎连续借多币)合并为一次该用户刷新,避免逐笔打爆 SAPI/REST 预算。
# 0.8→0.3:账户采集已并行化(整轮<2s),去抖是显示延迟链上纯等待,缩短以贴近"秒级"体感。
REFRESH_DEBOUNCE = 0.3  # seconds


class BalancePusher:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._max_borrow_tick = 0
        self._max_borrow_cache: dict[int, dict[str, float]] = {}  # account_id -> {asset: amount}
        self._no_inventory: dict[str, float] = {}  # asset -> 最近一次 -3045 的 monotonic 时刻(TTL 见 NOINV_TTL_SEC)
        self._mb_cursor: dict[int, int] = {}  # account_id -> maxBorrowable 轮转游标(targets 超单轮预算时轮转窗口)
        # 推送即查:pushed:updates 到达时把该用户推送资产加入强查集,下一次(即时)fetch 无视节流立即查
        self._force_mb_assets: set[str] = set()
        self._grab_last: dict[str, float] = {}   # P1-5 抢券:asset -> 最近一次抢券强查的 monotonic 时刻(GRAB_POLL_SEC 节流)
        # VIP 档借贷上限缓存: asset -> (borrowLimit, monotonic取数时刻)。与库存无关、按VIP恒定,6h 缓存;
        # 取数失败负缓存 10min 防连环重试。是无券币(-3045 连 borrowLimit 都拿不到)额度显示的唯一来源。
        self._vip_limit_cache: dict[str, tuple[float, float]] = {}
        self._interest_rate_cache: dict[str, float] = {}  # asset -> daily_interest_rate (global)
        # 即时刷新(immediate)时不重查主账户合约持仓(省 REST);沿用上一次整轮采集的缓存,
        # 避免即时推送把「现-期/爆率」列清空闪烁。整轮 _fetch_and_push 会刷新这两个缓存。
        self._last_master_pos: dict[int, dict] = {}   # uid -> {symbol: positionAmt}
        self._last_master_liq: dict[int, float] = {}  # uid -> 维持保证金率%
        # 写后即时刷新:待处理用户集合 + 唤醒事件(去抖合并突发信号)
        self._refresh_pending: set[int] = set()
        self._refresh_event: Optional[asyncio.Event] = None

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True
        self._refresh_event = asyncio.Event()
        asyncio.create_task(self._loop())
        asyncio.create_task(self._refresh_listener())  # 订阅 balance:refresh
        asyncio.create_task(self._refresh_worker())     # 去抖后按用户即时重推
        logger.info("BalancePusher started")

    async def stop(self):
        self._running = False

    async def _loop(self):
        while self._running:
            try:
                await self._fetch_and_push()
            except Exception as e:
                logger.warning(f"BalancePusher error: {e}")
            await asyncio.sleep(BALANCE_INTERVAL)

    async def _refresh_listener(self):
        """订阅 balance:refresh:借/还币成功后生产者 publish user_id,这里收集到待处理集合并唤醒 worker。
        独立连接(pubsub 自带),收集后立即返回,真正的拉取/推送交给 _refresh_worker(去抖一次)。"""
        try:
            pubsub = self._redis.pubsub()
            # pushed:updates: 推送列表变化(手动/自动推送)→ 对该用户所有推送资产立即强查
            # maxBorrowable/VIP额度,做到"推送进来马上显示最大可借",不等 60s 轮询节拍。
            await pubsub.subscribe(REFRESH_CHANNEL, "pushed:updates")
            async for msg in pubsub.listen():
                if not self._running:
                    break
                if msg.get("type") != "message":
                    continue
                if msg.get("channel") == "pushed:updates":
                    try:
                        payload = json.loads(msg["data"])
                        uid = int(payload.get("user_id"))
                        assets = {s.replace("USDT", "") for s in payload.get("pushed_symbols", [])}
                        self._force_mb_assets |= assets
                        self._refresh_pending.add(uid)
                        if self._refresh_event:
                            self._refresh_event.set()
                    except Exception:
                        pass
                    continue
                try:
                    uid = int(msg["data"])
                except (ValueError, TypeError):
                    continue
                self._refresh_pending.add(uid)
                if self._refresh_event:
                    self._refresh_event.set()
        except Exception as e:
            logger.warning(f"balance refresh listener stopped: {e}")

    async def _refresh_worker(self):
        """去抖处理即时刷新:被唤醒后等 REFRESH_DEBOUNCE 合并突发信号,再对每个待处理用户各做一次
        范围限定的即时重推(immediate=True:只查该用户账户,maxBorrowable/主账户合约走缓存,最省 REST)。"""
        while self._running:
            try:
                if self._refresh_event:
                    await self._refresh_event.wait()
                    self._refresh_event.clear()
                await asyncio.sleep(REFRESH_DEBOUNCE)  # 合并 0.8s 内的突发信号
                pending = list(self._refresh_pending)
                self._refresh_pending.clear()
                for uid in pending:
                    try:
                        await self._fetch_and_push(only_user_id=uid, immediate=True)
                    except Exception as e:
                        logger.warning(f"immediate balance refresh failed (user {uid}): {e}")
            except Exception as e:
                logger.warning(f"balance refresh worker error: {e}")
                await asyncio.sleep(1)

    async def _btc_price(self) -> float:
        """Read BTCUSDT futures bid from the Redis spreads hash to convert
        margin equity (denominated in BTC by Binance) into USDT."""
        try:
            raw = await self._redis.hget("spreads", "BTCUSDT")
            if raw:
                parsed = json.loads(raw)
                return float(parsed.get("fut_bid") or parsed.get("spot_bid") or 0)
        except Exception:
            pass
        return 0.0

    async def _spot_bids(self) -> dict[str, float]:
        """All symbols' spot_bid from the Redis spreads hash, for converting
        coin quantities to USDT and computing per-symbol borrow caps.
        借币封顶口径用 spot_bid(与 order_executor 借币侧 price 取数一致)。"""
        out: dict[str, float] = {}
        try:
            allp = await self._redis.hgetall("spreads")
            for sym, raw in (allp or {}).items():
                try:
                    out[sym] = float(json.loads(raw).get("spot_bid") or 0)
                except Exception:
                    continue
        except Exception:
            pass
        return out

    async def _pushed_assets(self, user_id: int) -> set[str]:
        """Base assets the user is actively monitoring (pushed list), so the
        dashboard shows 现币/借币/最大可借 for monitored coins, not only positioned ones."""
        try:
            raw = await self._redis.get(f"engine:{user_id}:pushed_symbols")
            if raw:
                return {s.replace("USDT", "") for s in json.loads(raw)}
        except Exception:
            pass
        return set()

    def _load_borrow_policy(self, db) -> dict:
        """读引擎借币封顶口径所需的规则,口径与 order_executor.execute_borrow 完全一致:
        - borrow_via_otoco / collateral_ratio 是系统级字段(user_id IS NULL 行,全用户统一,
          见 config_loader._SYSTEM_FIELDS),故只取一次系统行。
        - order_amount(OTOCO 关闭时的固定单笔)按 per-user GlobalRules,回退系统行/默认 500。
        返回 {otoco, ratio(float), sys_order_amount, order_amount_by_user{uid:amt}}。"""
        sysrow = (db.query(GlobalRules)
                  .filter(GlobalRules.user_id.is_(None))
                  .order_by(GlobalRules.id).first())
        # 借币方式: 新枚举 borrow_mode 优先,回退旧 bool(与引擎 config_loader/order_executor 同口径)。
        # otoco/single/multi 三种均走「金额限制∩maxBorrowable×抵押率」封顶 → "有效可借"按此算。
        _mode = (getattr(sysrow, "borrow_mode", None) if sysrow else None) or \
                ("otoco" if (sysrow and getattr(sysrow, "borrow_via_otoco", False)) else "repay")
        otoco = _mode in ("otoco", "single", "multi")
        ratio_raw = getattr(sysrow, "collateral_ratio", None) if sysrow else None
        try:
            ratio = float(ratio_raw) if ratio_raw is not None else 1.0
        except Exception:
            ratio = 1.0
        if ratio <= 0 or ratio > 1:
            ratio = 1.0  # 与引擎一致:越界视为借满
        sys_order_amount = None
        if sysrow and getattr(sysrow, "order_amount", None) is not None:
            try:
                sys_order_amount = float(sysrow.order_amount)
            except Exception:
                sys_order_amount = None
        order_amount_by_user: dict[int, float] = {}
        for r in db.query(GlobalRules).filter(GlobalRules.user_id.isnot(None)).all():
            if r.order_amount is not None:
                try:
                    order_amount_by_user[r.user_id] = float(r.order_amount)
                except Exception:
                    pass
        return {
            "otoco": otoco,
            "ratio": ratio,
            "sys_order_amount": sys_order_amount,
            "order_amount_by_user": order_amount_by_user,
        }

    def _resolve_amount_cap(self, db, sub_account_id: int, user_id: int, symbol: str,
                            base_asset: str) -> Optional[float]:
        """「金额限制」(USDT 借币上限)解析,严格复用引擎优先级:
        账户单币(AccountSymbolRule) → 单币通用(SymbolRule) → 子账户(SubAccount).max_borrow_amount。
        null=不封顶(跟随 maxBorrowable)。"""
        from app.db.models import SymbolRule, AccountSymbolRule
        syms = [symbol, base_asset]
        asr = (db.query(AccountSymbolRule)
               .filter(AccountSymbolRule.sub_account_id == sub_account_id,
                       AccountSymbolRule.symbol.in_(syms)).first())
        if asr and asr.max_borrow_amount is not None:
            return float(asr.max_borrow_amount)
        if user_id is not None:
            sr = (db.query(SymbolRule)
                  .filter(SymbolRule.user_id == user_id,
                          SymbolRule.symbol.in_(syms)).first())
            if sr and sr.max_borrow_amount is not None:
                return float(sr.max_borrow_amount)
        sa = db.query(SubAccount).get(sub_account_id)
        if sa and sa.max_borrow_amount is not None:
            return float(sa.max_borrow_amount)
        return None

    def _resolve_order_amount(self, db, acc, user_id: int, symbol: str,
                              base_asset: str, policy: dict) -> Optional[float]:
        """非 OTOCO 模式单笔借币金额(USDT),复用引擎 else 分支优先级:
        全局 order_amount → 子账户 single_order_amount → 单币 SymbolRule.order_amount(最高)。"""
        from app.db.models import SymbolRule
        eff = policy["order_amount_by_user"].get(user_id, policy["sys_order_amount"])
        sa_single = getattr(acc, "single_order_amount", None)
        if sa_single is not None:
            try:
                eff = float(sa_single)
            except Exception:
                pass
        if user_id is not None:
            sr = (db.query(SymbolRule)
                  .filter(SymbolRule.user_id == user_id,
                          SymbolRule.symbol.in_([symbol, base_asset])).first())
            if sr and sr.order_amount is not None:
                try:
                    eff = float(sr.order_amount)
                except Exception:
                    pass
        return eff

    def _noinv_active(self, asset: str) -> bool:
        """无券标志是否仍有效:超过 NOINV_TTL_SEC 自动过期(顺手清 key),
        到期后下轮 fetch 会真实重查 maxBorrowable,库存恢复不再被永久钉成"无券"。"""
        ts = self._no_inventory.get(asset)
        if ts is None:
            return False
        if time.monotonic() - ts >= NOINV_TTL_SEC:
            self._no_inventory.pop(asset, None)
            return False
        return True

    async def _noinv_remaining(self, assets: set[str]) -> dict[str, int]:
        """逐资产合并两处无券冷却的剩余秒数,取大者:
        ① 引擎借币 -3045 写的 engine:noinv:{sym} 键(EX=1800,借币真正被闸住的时长);
        ② 本进程 maxBorrowable 查询 -3045 标志(NOINV_TTL_SEC)。
        供前端「无券(剩N分)」倒计时;不在冷却中的资产不出现在结果里。"""
        out: dict[str, int] = {}
        now = time.monotonic()
        for a in assets:
            rem = 0
            ts = self._no_inventory.get(a)
            if ts is not None:
                rem = max(0, int(NOINV_TTL_SEC - (now - ts)))
            try:
                t = await self._redis.ttl(f"engine:noinv:{a}USDT")
                if t and t > 0:
                    rem = max(rem, int(t))
            except Exception:
                pass
            if rem > 0:
                out[a] = rem
        return out

    async def _check_borrow_heartbeats(self, db):
        """P1-8 借币子路径停摆检测。worker 每周期借币评估跑完写 engine:{uid}:borrow_hb:{sid}
        (300s TTL)。这里对 EngineState=RUNNING 的子账户核对该戳:缺失或停更 > STALE 秒 = 借币
        子路径卡死(进程还活/systemd 看着正常,但事件循环停摆或借币循环抛错那类,主心跳按10周期
        可能才发现)。命中 → 飞书 + 跑马灯,单账户 600s 冷却防刷。"""
        from app.db.models import EngineState, SubAccount
        from datetime import datetime, timezone
        STALE = 180          # 借币戳每 ~1s 更新,>180s 未更新即异常
        COOLDOWN = 600       # 单账户告警冷却
        try:
            rows = db.query(EngineState).filter(
                EngineState.status == "RUNNING", EngineState.scope.like("sub:%")).all()
        except Exception:
            return
        now = datetime.now(timezone.utc)
        for st in rows:
            try:
                sid = int(str(st.scope).split(":")[1])
            except Exception:
                continue
            # 刚启动宽限:主心跳 last_heartbeat 距今 < STALE 说明刚起,借币戳可能还没写第一次
            try:
                lhb = st.last_heartbeat
                if lhb is not None:
                    if lhb.tzinfo is None:
                        lhb = lhb.replace(tzinfo=timezone.utc)
                    if (now - lhb).total_seconds() > 600:
                        continue  # 主心跳自己都停了>10min:那是引擎整体停/停用,交由既有引擎存活告警,不在此重复报
            except Exception:
                pass
            sa = db.query(SubAccount).filter(SubAccount.id == sid).first()
            if not sa:
                continue
            uid = sa.user_id
            name = sa.note or f"sub#{sid}"   # SubAccount 字段是 note,非 account_name(原误致心跳检测每轮抛错跳过)
            try:
                raw = await self._redis.get(f"engine:{uid}:borrow_hb:{sid}")
            except Exception:
                continue
            reason = None
            if not raw:
                reason = "借币心跳缺失(>300s 未写)"
            else:
                try:
                    ts = datetime.fromisoformat(raw)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    age = (now - ts).total_seconds()
                    if age > STALE:
                        reason = f"借币心跳停更 {int(age)}s"
                except Exception:
                    reason = "借币心跳戳无法解析"
            if not reason:
                continue
            # 冷却:命中才占位,避免每周期刷
            try:
                ck = f"alert:borrow_hb_stale:{sid}"
                if await self._redis.get(ck):
                    continue
                await self._redis.setex(ck, COOLDOWN, "1")
            except Exception:
                pass
            msg = f"⚠️ 借币子路径停摆 | 账户 {name}(sub#{sid}) | {reason} | 引擎进程或事件循环可能卡死,请检查"
            logger.error(msg)
            try:
                if self._redis:
                    await self._redis.publish("notification:broadcast", json.dumps({
                        "type": "engine_alert", "level": "critical",
                        "title": "借币子路径停摆", "message": msg,
                        "marquee": True, "user_id": uid,
                    }))
            except Exception:
                pass
            # 飞书(复用引擎告警发送器 async send,自带令牌桶节流;失败静默)
            try:
                from engine.notify.feishu_sender import FeishuSender
                await FeishuSender().send(
                    "借币子路径停摆", msg, marquee=True, priority=1,
                    color="#ef4444", blink=True,
                    throttle_key=f"borrow_hb_stale:{sid}", alert_type="engine_health")
            except Exception:
                pass

    async def _auto_converge_hedge(self, db, tasks: list[dict]):
        """P1-7 净敞口自动收敛:对裸多(master实仓>在管对冲)reduceOnly 市价卖出对齐。
        开关 hedge_auto_converge 用户行优先(规则页可自助开),用户行 NULL 回退系统行
        (user_id IS NULL,admin 管;默认关=只告警不动仓)。用主账户 key 下单,
        reduceOnly 保证只减不反向开仓(绝对安全)。量向下取整到合约步长,不超卖。收敛后飞书+跑马灯报告。"""
        from app.db.models import MasterAccount, GlobalRules
        try:
            sys_enabled = db.query(GlobalRules.hedge_auto_converge).filter(
                GlobalRules.user_id.is_(None)).order_by(GlobalRules.id).scalar()
        except Exception:
            sys_enabled = None
        from engine.trading.binance_trading import BinanceTradingClient
        by_uid: dict[int, list] = {}
        for t in tasks:
            by_uid.setdefault(t["uid"], []).append(t)
        for uid, uid_tasks in by_uid.items():
            try:
                user_enabled = db.query(GlobalRules.hedge_auto_converge).filter(
                    GlobalRules.user_id == uid).scalar()
            except Exception:
                user_enabled = None
            if not (user_enabled if user_enabled is not None else sys_enabled):
                continue   # 该用户未开(系统行也未开):只告警(上游已发),不自动动仓
            master = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
            if not master or not master.api_key:
                continue
            try:
                async with BinanceTradingClient(master.api_key, master.api_secret) as mc:
                    info = await mc._request("GET", "https://fapi.binance.com/fapi/v1/exchangeInfo", {}, signed=False)
                    steps = {}
                    for s in info.get("symbols", []):
                        lot = next((f for f in s.get("filters", []) if f["filterType"] == "LOT_SIZE"), None)
                        if lot:
                            steps[s["symbol"]] = float(lot.get("stepSize", "0.001") or "0.001")
                    for t in uid_tasks:
                        sym = t["symbol"]; excess = float(t["excess_qty"])
                        step = steps.get(sym, 0.001)
                        import math as _m
                        qty = _m.floor(excess / step) * step if step > 0 else 0.0
                        if qty <= 0:
                            continue
                        try:
                            await mc._request("POST", "https://fapi.binance.com/fapi/v1/order", {
                                "symbol": sym, "side": "SELL", "type": "MARKET",
                                "quantity": f"{qty:.8f}".rstrip("0").rstrip("."), "reduceOnly": "true",
                            }, signed=True)
                            logger.info(f"[auto-converge] u{uid} {sym} reduceOnly SELL {qty} (裸多{excess:.4f}→对齐)")
                            try:
                                self._redis and await self._redis.publish("notification:broadcast", json.dumps({
                                    "title": "净敞口自动收敛", "priority": "high", "color": "#f59e0b", "blink": False,
                                    "content": f"{sym} 裸多 {excess:.4f} 已 reduceOnly 卖出 {qty} 对齐对冲量 {t['managed']:.4f}",
                                }))
                            except Exception:
                                pass
                        except Exception as _oe:
                            logger.warning(f"[auto-converge] u{uid} {sym} reduceOnly failed: {_oe}")
            except Exception as e:
                logger.warning(f"[auto-converge] u{uid} master client failed: {e}")

    async def _vip_borrow_limit(self, client, asset: str) -> float:
        """VIP 档借贷上限(与库存/持U无关,同VIP各账户相同),进程内 6h 缓存;失败负缓存 10min。"""
        VIP_TTL, NEG_TTL = 21600.0, 600.0
        hit = self._vip_limit_cache.get(asset)
        now = time.monotonic()
        if hit and now - hit[1] < (VIP_TTL if hit[0] > 0 else NEG_TTL):
            return hit[0]
        limit = 0.0
        try:
            d = await client.get_cross_margin_data(asset)
            limit = float(d.get("borrowLimit", 0) or 0)
        except Exception:
            limit = 0.0
        self._vip_limit_cache[asset] = (limit, now)
        return limit

    def _compute_effective_borrowable(self, db, acc, sym_key: str, mb: float,
                                      policy: dict, spot_bids: dict) -> tuple[float, str]:
        """有效可借(币数量)+ 受限原因,口径与 order_executor.execute_borrow 完全一致。
        OTOCO 开 & 有金额限制: min(金额限制/价, maxBorrowable×抵押率)。
        否则(OTOCO 关 或 无金额限制): 单笔 order_amount/价(引擎此模式不看 maxBorrowable)。"""
        base_asset = sym_key.replace("USDT", "")
        uid = acc.user_id
        price = float(spot_bids.get(sym_key, 0) or 0)
        if mb is None:
            mb = 0.0
        if mb <= 0:
            # 只有确认过 -3045 才叫"无券";还没查到(刚推送/排在本轮预算外/查询失败)如实标"待查询",
            # 不再把"未查询"混标成无券误导用户。
            return 0.0, ("无券" if self._noinv_active(base_asset) else "待查询")
        cap_usdt = self._resolve_amount_cap(db, acc.id, uid, sym_key, base_asset)
        if policy["otoco"] and cap_usdt is not None and cap_usdt > 0:
            cap_qty = (cap_usdt / price) if price > 0 else 0.0
            eff_max = mb * policy["ratio"]
            if eff_max <= 0:
                return cap_qty, "金额限制"
            if cap_qty <= eff_max:
                return cap_qty, "金额限制"
            # maxBorrowable×抵押率 更紧
            return eff_max, ("抵押率" if policy["ratio"] < 1 else "可借上限")
        # 非 OTOCO(或未设金额限制)→ 单笔金额封顶
        amt = self._resolve_order_amount(db, acc, uid, sym_key, base_asset, policy)
        if amt is None or price <= 0:
            # 拿不到单笔金额/价格 → 退回理论上限,不误导为 0
            return mb, "可借上限"
        eff = amt / price
        return (min(eff, mb), "单笔金额") if eff <= mb else (mb, "可借上限")

    async def _fetch_and_push(self, only_user_id: Optional[int] = None, immediate: bool = False):
        """only_user_id 非空 → 只采集该用户的账户(写后即时刷新用)。
        immediate=True → 不推进周期计数器、不重查 maxBorrowable/主账户合约(走缓存)、不落快照/告警,
        仅以最新 get_margin_account/get_futures_account 真值重推该用户余额,最省 REST 又秒级刷新。"""
        if not immediate:
            self._max_borrow_tick += 1
        fetch_max_borrow = (not immediate) and (self._max_borrow_tick % 6 == 0)
        btc_price = await self._btc_price()
        spot_bids = await self._spot_bids()
        # Cap maxBorrowable calls per account per cycle to protect the SAPI weight budget.
        MAX_BORROW_PER_CYCLE = 40

        db = SessionLocal()
        try:
            acct_q = db.query(SubAccount).filter(SubAccount.is_enabled == True)
            if only_user_id is not None:
                acct_q = acct_q.filter(SubAccount.user_id == only_user_id)
            accounts = acct_q.all()
            if not accounts:
                return

            # 借币封顶口径(与 order_executor.execute_borrow 同源),整周期取一次。
            borrow_policy = self._load_borrow_policy(db)

            from engine.trading.binance_trading import BinanceTradingClient
            from engine.models import Position

            # Per-user pushed assets, then per-account target = positioned ∪ pushed.
            pushed_by_user: dict[int, set[str]] = {}
            target_assets: dict[int, set[str]] = {}
            for acc in accounts:
                uid = acc.user_id or 0
                if uid not in pushed_by_user:
                    pushed_by_user[uid] = await self._pushed_assets(uid)
                positions = db.query(Position.symbol).filter(
                    Position.sub_account_id == acc.id, Position.status == "OPEN",
                ).all()
                positioned = {p.symbol.replace("USDT", "") for p in positions}
                target_assets[acc.id] = positioned | pushed_by_user[uid]

            # 无券冷却剩余秒数(全用户 targets 并集,每周期一次;供前端「无券(剩N分)」倒计时)
            all_assets: set[str] = set()
            for s in target_assets.values():
                all_assets |= s
            noinv_rem = await self._noinv_remaining(all_assets)

            # 还币暂停剩余秒数(engine:{uid}:repayhold:{SYM},用户勾选/在途静默):供状态列倒计时+点击解除
            hold_rem: dict[tuple[int, str], int] = {}
            for uid2, assets2 in pushed_by_user.items():
                for a2 in assets2:
                    try:
                        t2 = await self._redis.ttl(f"engine:{uid2}:repayhold:{a2}USDT")
                        if t2 and t2 > 0:
                            hold_rem[(uid2, a2)] = int(t2)
                    except Exception:
                        pass

            interest_fetched: set[str] = set()
            force_consumed: set[str] = set()   # 本轮已消费的"推送即查"强查资产,轮末从全局集扣除

            user_balances: dict[int, list] = {}
            # 逐账户采集并行化(信号量4):原串行 for 循环 12 账户×~0.4s ≈ 5s,是"借币/开仓后
            # 显示延迟约5秒"的主瓶颈(即时刷新也走这里)。各账户写各自 key(user_balances 按uid append/
            # _max_borrow_cache 按acc.id),单线程事件循环下无竞态;并发额外突发 REST 权重可忽略(总量不变)。
            async def _fetch_acc(acc):
                try:
                    targets = target_assets.get(acc.id, set())
                    async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
                        margin, futures = await asyncio.gather(
                            client.get_margin_account(),
                            client.get_futures_account(),
                        )

                        # P1-5 抢券:对 targets 中当前无券的币,按 GRAB_POLL_SEC 节流补进强查集,
                        # 使其绕过 10min 常规复查节流、下面立即查一次 maxBorrowable(库存恢复即秒级解冻)。
                        _gnow = time.monotonic()
                        for _a in targets:
                            if self._noinv_active(_a) and (_gnow - self._grab_last.get(_a, 0.0)) >= GRAB_POLL_SEC:
                                self._force_mb_assets.add(_a)
                                self._grab_last[_a] = _gnow
                        force_assets = self._force_mb_assets & targets  # 推送即查/抢券:无视节流/无券缓存
                        force_consumed.update(force_assets)   # 闭包内不可 |= 重绑定外层变量
                        if (fetch_max_borrow or force_assets) and targets:
                            mb_results = dict(self._max_borrow_cache.get(acc.id, {}))
                            # _limits 是嵌套 dict,浅拷贝后与缓存共享同一内层对象 → 重新复制一份再写
                            mb_results["_limits"] = dict(mb_results.get("_limits", {}))
                            # 已知无券的币(-3045)不必每轮重查 maxBorrowable(每次都 400 刷错误率/耗 SAPI);
                            # 仅每 RECHECK_NOINV_EVERY 次 fetch(fetch 自身每 6 周期一次)重试一次看库存是否恢复。
                            recheck_noinv = self._max_borrow_tick % (6 * RECHECK_NOINV_EVERY) == 0
                            # 轮转游标:targets 超过单轮预算(40)时按排序轮转取窗,保证所有币最终都轮得到。
                            # 原固定切片 list(targets)[:40] 让 40 名以外的币在进程生命周期内永远查不到,
                            # 其 max_borrowable 恒 0/无券标志永不复查。
                            tlist = sorted(targets)
                            if not fetch_max_borrow:
                                batch = []   # 即时(推送触发)模式只查强查资产,不跑整轮
                            elif len(tlist) > MAX_BORROW_PER_CYCLE:
                                start = self._mb_cursor.get(acc.id, 0) % len(tlist)
                                batch = (tlist + tlist)[start:start + MAX_BORROW_PER_CYCLE]
                                self._mb_cursor[acc.id] = (start + MAX_BORROW_PER_CYCLE) % len(tlist)
                            else:
                                batch = tlist
                            batch = list(dict.fromkeys(list(batch) + sorted(force_assets)))
                            for asset in batch:
                                forced = asset in force_assets
                                if (not forced) and self._noinv_active(asset) and not recheck_noinv:
                                    mb_results[asset] = 0.0   # 沿用无券缓存,跳过查询(TTL 过期自动失效)
                                else:
                                    try:
                                        mb_data = await client.get_max_borrowable(asset)
                                        _amt = float(mb_data["amount"])
                                        mb_results[asset] = _amt
                                        # 缓存 borrowLimit(VIP档借贷上限,与持U无关)。
                                        # 原判断误写为 `if "borrowLimit" not in mb_results` 恒真,
                                        # 每次成功查询都把 _limits 清空、只剩最后一个币 —— 已修。
                                        mb_results["_limits"][asset] = float(mb_data["borrowLimit"])
                                        self._no_inventory.pop(asset, None)  # 查询成功 = 有券,清除无券标志
                                        # P1-5 抢券:查到库存恢复(amount>0)且该币此前被引擎标记全局无券
                                        # (engine:noinv:{sym},-3045 冷却 1800s)→ 立即删全局键解冻,worker 下一周期(≤3s)
                                        # 即可重新借该币。原来只清本进程 local 标志、全局键一直钉到 TTL 过期 → worker 盲等30min。
                                        # delete 返回删除数>0 = 真发生"无券→有券"跃迁,只在跃迁时记日志/播报(天然去重)。
                                        # 解冻门槛:恢复量名义 ≥15U 才解冻。零星补货(几粒币)时 maxBorrowable>0
                                        # 但引擎按整口借必再 -3045 → 解冻/冻结互搏,1s级重试刷 FAILED 行
                                        # (实测囤券模式下 2min 93 次)。无价格数据时保守要求 ≥5 个币。
                                        _px = spot_bids.get(f"{asset}USDT", 0) or 0
                                        _meaningful = (_amt * _px >= 15.0) if _px > 0 else (_amt >= 5.0)
                                        if _amt > 0 and _meaningful:
                                            try:
                                                if await self._redis.delete(f"engine:noinv:{asset}USDT"):
                                                    logger.info(f"抢券:{asset} 库存恢复(可借{_amt:.4f}),已解冻全局无券标志,worker 下周期可借")
                                                    self._grab_last.pop(asset, None)
                                                    await self._redis.publish("notification:broadcast", json.dumps({
                                                        "type": "inventory_grab", "level": "info",
                                                        "title": "库存恢复", "message": f"🎯 {asset} 券已恢复,解冻可借",
                                                        "marquee": True,
                                                    }))
                                            except Exception:
                                                pass
                                    except Exception as e:
                                        # -3045 = 币安杠杆池该币无可借库存(真实市场状态,非故障)→ 明确置 0 + 标记池空
                                        if "-3045" in str(e):
                                            mb_results[asset] = 0.0
                                            self._no_inventory[asset] = time.monotonic()
                                        else:
                                            mb_results[asset] = mb_results.get(asset, 0)
                                # 无券/查询失败拿不到 borrowLimit → 回退 VIP 档额度(crossMarginData,
                                # 与库存无关):推送进来就能显示"账户最大能借多少",无券只是角标。
                                if not mb_results["_limits"].get(asset):
                                    vl = await self._vip_borrow_limit(client, asset)
                                    if vl > 0:
                                        mb_results["_limits"][asset] = vl
                                if asset not in interest_fetched:
                                    try:
                                        rate = await client.get_margin_interest_rate(asset)
                                        self._interest_rate_cache[asset] = float(rate)
                                    except Exception:
                                        pass
                                    interest_fetched.add(asset)
                            self._max_borrow_cache[acc.id] = mb_results

                    margin_free = "0"
                    margin_borrowed = "0"
                    bnb_free = "0"
                    bnb_interest = "0"
                    symbol_margin: dict[str, dict] = {}
                    for a in margin.get("userAssets", []):
                        asset_name = a["asset"]
                        if asset_name == "USDT":
                            margin_free = a.get("free", "0")
                            margin_borrowed = a.get("borrowed", "0")
                        elif asset_name == "BNB":
                            bnb_free = a.get("free", "0")
                            bnb_interest = a.get("interest", "0")
                        if asset_name not in targets and asset_name not in ("USDT", "BNB") and (
                            float(a.get("free", "0") or 0) > 1e-8
                            or float(a.get("borrowed", "0") or 0) > 1e-8
                            or float(a.get("interest", "0") or 0) > 1e-8
                        ):
                            # 非推送/持仓币但账户里有残留(历史零债残留如 PLUME 610个≈24U,不推送就完全
                            # 不可见,用户以为"钱没恢复")→ 也入 payload,让「持币汇总」可见并提供卖回入口。
                            # 不进 targets(不参与 maxBorrowable 查询,零 REST 开销);USDT/BNB 另有专列不掺和。
                            symbol_margin[f"{asset_name}USDT"] = {
                                "free": float(a.get("free", "0")),
                                "borrowed": float(a.get("borrowed", "0")),
                                "interest": float(a.get("interest", "0")),
                                "max_borrowable": 0, "borrow_limit": 0,
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                "no_inventory": False, "noinv_remaining_sec": 0,
                                "residual_only": True,   # 前端据此归入"残留区",不当作可交易行
                            }
                        if asset_name in targets:
                            sym_key = f"{asset_name}USDT"
                            mb_cache = self._max_borrow_cache.get(acc.id, {})
                            symbol_margin[sym_key] = {
                                "free": float(a.get("free", "0")),
                                "borrowed": float(a.get("borrowed", "0")),      # 该子账户已借该币本金(持币)
                                "interest": float(a.get("interest", "0")),      # 已计利息(还币需本金+利息)
                                "max_borrowable": mb_cache.get(asset_name, 0),
                                "borrow_limit": mb_cache.get("_limits", {}).get(asset_name, 0),  # VIP档借贷上限(与持U无关)
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                # 无券=本进程 -3045 标志 或 引擎借币冷却键仍在(引擎真正被闸住的口径)
                                "no_inventory": self._noinv_active(asset_name) or noinv_rem.get(asset_name, 0) > 0,
                                "noinv_remaining_sec": noinv_rem.get(asset_name, 0),
                                "repayhold_remaining_sec": hold_rem.get((acc.user_id or 0, asset_name), 0),
                            }

                    # Pushed-but-not-held assets aren't in userAssets — still surface
                    # 最大可借/日息 so monitored coins show data before any position.
                    for asset_name in targets:
                        sym_key = f"{asset_name}USDT"
                        if sym_key not in symbol_margin:
                            mb_cache = self._max_borrow_cache.get(acc.id, {})
                            symbol_margin[sym_key] = {
                                "free": 0.0,
                                "borrowed": 0.0,
                                "interest": 0.0,
                                "max_borrowable": mb_cache.get(asset_name, 0),
                                "borrow_limit": mb_cache.get("_limits", {}).get(asset_name, 0),
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                "no_inventory": self._noinv_active(asset_name) or noinv_rem.get(asset_name, 0) > 0,
                                "noinv_remaining_sec": noinv_rem.get(asset_name, 0),
                                "repayhold_remaining_sec": hold_rem.get((acc.user_id or 0, asset_name), 0),
                            }

                    # 有效可借: 在理论上限(max_borrowable)基础上,套引擎同一封顶口径
                    # (金额限制/抵押率/单笔金额),给前端展示「实际会借到的量」。
                    for sym_key, sm in symbol_margin.items():
                        if sm.get("residual_only"):
                            continue   # 残留展示行,无借币语义,不算有效可借
                        try:
                            eff, reason = self._compute_effective_borrowable(
                                db, acc, sym_key, sm.get("max_borrowable", 0),
                                borrow_policy, spot_bids,
                            )
                        except Exception:
                            eff, reason = sm.get("max_borrowable", 0), "可借上限"
                        sm["effective_borrowable"] = eff
                        sm["borrow_cap_reason"] = reason

                    spot_free = "0"
                    for a in margin.get("userAssets", []):
                        if a["asset"] == "USDT":
                            spot_free = a.get("free", "0")
                            break

                    # 保证金总权益 (USDT) = 杠杆账户净资产(BTC) × BTC价格
                    margin_net_btc = float(margin.get("totalNetAssetOfBtc", "0") or "0")
                    margin_net_usdt = margin_net_btc * btc_price if btc_price > 0 else 0.0

                    uid = acc.user_id or 0
                    user_balances.setdefault(uid, []).append({
                        "account_id": acc.id,
                        "note": acc.note or f"#{acc.id}",
                        "spot_usdt_free": float(spot_free),
                        "margin_usdt_free": float(margin_free),
                        "margin_usdt_borrowed": float(margin_borrowed),
                        "margin_net_usdt": margin_net_usdt,
                        "margin_level": float(margin.get("marginLevel", "0") or "0"),
                        "futures_total": float(futures.get("totalWalletBalance", "0")),
                        "futures_available": float(futures.get("availableBalance", "0")),
                        "futures_unrealized_pnl": float(futures.get("totalUnrealizedProfit", "0")),
                        "bnb_free": float(bnb_free),
                        "bnb_interest": float(bnb_interest),
                        "symbol_margin": symbol_margin,
                    })
                except Exception as e:
                    logger.debug(f"Balance fetch failed for account {acc.id}: {e}")

            _acc_sem = asyncio.Semaphore(4)

            async def _fetch_acc_guarded(acc):
                async with _acc_sem:
                    await _fetch_acc(acc)

            await asyncio.gather(*[_fetch_acc_guarded(a) for a in accounts])

            # 主账户合约持仓采集(hedge_via_master 模式下合约腿在主账户,前端"现-期"列需要)。
            # immediate 即时刷新也采集:它由借/还币/开平仓事件触发且范围限定单用户(去抖 0.8s),
            # 正是「现-期」列必须立刻反映合约腿变化的时刻 —— 原先跳过导致对冲成交后合约列
            # 仍等 10s 整轮才更新。采集失败时 payload 仍回退上一轮缓存,不闪空。
            master_futures_positions = {}  # {uid: {symbol: positionAmt}}
            master_futures_liq = {}        # {uid: 维持保证金率%} 主账户合约户爆仓率(币安标准:totalMaintMargin/totalMarginBalance×100,越接近100越接近强平)
            for uid in user_balances.keys():
                from app.db.models import MasterAccount
                master = db.query(MasterAccount).filter(MasterAccount.user_id == uid).first()
                if not master or not master.api_key:
                    continue
                try:
                    from engine.trading.binance_trading import BinanceTradingClient
                    async with BinanceTradingClient(master.api_key, master.api_secret) as mc:
                        # 主账户合约户维持保证金率(爆仓率口径,前端「爆率」列)。与 pushed 无关,先采集。
                        try:
                            facc = await mc.get_futures_account()
                            tmm = float(facc.get("totalMaintMargin", "0") or 0)
                            tmb = float(facc.get("totalMarginBalance", "0") or 0)
                            if tmb > 0:
                                master_futures_liq[uid] = tmm / tmb * 100
                        except Exception:
                            pass
                        # 只采集 pushed_symbols 里的币(避免全市场遍历)。
                        # pushed_symbols 在 Redis 里是 JSON 字符串(非 set),self._redis 为 aioredis →
                        # 必须 await get + json.loads。原 `self._redis.smembers(...)` 既漏 await、又对字符串键
                        # 误用集合操作,coroutine 从未 await(现-期列采集静默失败)。对齐 _pushed_assets 读法。
                        raw_ps = await self._redis.get(f"engine:{uid}:pushed_symbols")
                        pushed = json.loads(raw_ps) if raw_ps else []
                        if not pushed:
                            # pushed 已清空也要写空 dict:否则缓存永远留着最后一次的旧仓位,
                            # 全部下架后「现-期」列仍显示残留数字
                            master_futures_positions[uid] = {}
                            continue
                        positions = {}
                        _pr_sem = asyncio.Semaphore(5)

                        async def _one_pos(sym_bytes):
                            # futures_position_risk 返回【单个 dict】(或 None),不是 list ——
                            # 原代码按 list 取 pos_data[0] → dict 取键 0 → KeyError 被逐币
                            # except 吞掉 → master_futures_positions 恒 {}。已修为 dict 直取。
                            # 逐币并行(sem5):原串行 N 币×~0.3s 拖慢即时刷新的「现-期」列更新。
                            try:
                                sym = sym_bytes.decode() if isinstance(sym_bytes, bytes) else sym_bytes
                                async with _pr_sem:
                                    pos_data = await mc.futures_position_risk(sym)
                                if pos_data:
                                    positions[sym] = float(pos_data.get("positionAmt", "0") or 0)
                            except Exception:
                                pass  # 某币查不到持仓不影响其他币
                        await asyncio.gather(*[_one_pos(s) for s in pushed])
                        master_futures_positions[uid] = positions
                except Exception as e:
                    logger.debug(f"Master futures position fetch failed for user {uid}: {e}")

            # 采集成功即刷新缓存(uid 级全量替换),供采集失败的轮次兜底(避免清空闪烁)。
            # 孤儿/净敞口对账由下方 run_hedge_reconcile_checks 统一负责(裸多可自动收敛)。
            self._last_master_pos.update(master_futures_positions)
            self._last_master_liq.update(master_futures_liq)
            self._force_mb_assets -= force_consumed   # 强查已完成,防同资产反复无视节流

            for uid, balances in user_balances.items():
                position_count = db.query(Position).filter(
                    Position.status == "OPEN", Position.user_id == uid,
                ).count()
                total_contracts = db.query(Position).filter(
                    Position.user_id == uid,
                ).count()

                payload = {
                    "user_id": uid,
                    "balances": balances,
                    "position_count": position_count,
                    "total_contracts": total_contracts,
                    # immediate 时本轮未采集主账户合约 → 回退上一轮缓存,避免「现-期/爆率」列闪空
                    "master_futures_positions": master_futures_positions.get(
                        uid, self._last_master_pos.get(uid, {})),  # {symbol: positionAmt}
                    "master_futures_liq_pct": master_futures_liq.get(
                        uid, self._last_master_liq.get(uid)),  # 主账户合约户维持保证金率%(爆率列),无主账户/无合约权益则 None
                }

                await self._redis.publish("balance:updates", json.dumps(payload))
                await self._redis.set(f"balance:latest:{uid}", json.dumps(payload), ex=30)

            # 资金净值快照落库(每 ~10min 一次,每用户一行)→ 资金曲线/日终对账/回撤监控。
            # 复用 aggregate_balances 同一净值口径(与 admin 实时总览一致)。落库失败不影响推送。
            # immediate 即时刷新不落快照/不跑资金告警(这两者绑定周期节拍,避免离散触发刷错告警/脏行)。
            if not immediate and self._max_borrow_tick % SNAPSHOT_EVERY == 0:
                agg_by_user: dict[int, dict] = {}
                try:
                    for uid, balances in user_balances.items():
                        agg = aggregate_balances(balances)
                        agg_by_user[uid] = agg
                        db.add(BalanceSnapshot(
                            user_id=uid,
                            equity=agg["equity"],
                            available=agg["available"],
                            borrowed=agg["borrowed"],
                            unrealized_pnl=agg["unrealized_pnl"],
                            margin_level_min=agg["margin_level_min"],
                            bnb=agg["bnb"],
                            account_count=agg["account_count"],
                        ))
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logger.warning(f"balance_snapshot persist failed: {e}")
                # 资金风险告警(回撤/保证金/日亏)→ 跑马灯,节流自管,失败不影响主流程
                converge_tasks = []
                try:
                    from app.services.fund_alerts import run_fund_alert_checks, run_hedge_reconcile_checks
                    run_fund_alert_checks(db, agg_by_user)
                    # 净敞口对账:主账户合约净仓 vs DB 在管对冲量(本轮已采集的 master_futures_positions
                    # + spot_bids,零额外 REST),裸多/裸空差额名义超阈值 → 告警;返回裸多收敛任务
                    converge_tasks = run_hedge_reconcile_checks(db, master_futures_positions, spot_bids) or []
                except Exception as e:
                    db.rollback()
                    logger.warning(f"fund alert checks failed: {e}")
                # P1-7 净敞口自动收敛:开关开启时,对裸多(实仓>对冲)reduceOnly 市价卖出对齐 + 飞书报告。
                # 只裸多(reduceOnly 不开新敞口最安全);节流靠对账阈值+币安 reduceOnly 幂等。失败不影响主流程。
                if converge_tasks:
                    await self._auto_converge_hedge(db, converge_tasks)

                # P1-8 借币子路径心跳检测:RUNNING 子账户借币戳停更/缺失 → 借币停摆告警
                try:
                    await self._check_borrow_heartbeats(db)
                except Exception as e:
                    db.rollback()
                    logger.warning(f"borrow heartbeat check failed: {e}")

            # P0: publish IP-wide used weight (this process makes frequent SAPI calls)
            try:
                from engine.metrics import global_weight_snapshot
                ws = global_weight_snapshot()
                if ws["weight_time"] > 0:
                    await self._redis.set("engine:weight:latest", json.dumps(ws), ex=90)
            except Exception:
                pass

        finally:
            db.close()


balance_pusher = BalancePusher()
