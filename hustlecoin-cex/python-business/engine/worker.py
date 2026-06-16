import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import redis.asyncio as aioredis

from app.config import settings
from app.db.models import SubAccount, Symbol, SymbolRule, AccountSymbolRule
from app.db.session import SessionLocal
from engine.models import Position, EngineState
from engine.config_loader import ConfigLoader
from engine.spread_feed import SpreadFeed, SpreadSnapshot

logger = logging.getLogger(__name__)

MAX_POSITIONS_PER_ACCOUNT = 10
MAX_PER_SYMBOL = 3
SPREAD_FRESH_MS = 10_000   # 借币门:快照 ts 超此毫秒数视为 feed 停更/陈旧,不在死数据上开仓(与 rust 新鲜度护栏对齐)


class Worker:
    def __init__(self, sub_account_id: int, config: ConfigLoader, spread_feed: SpreadFeed):
        self.sub_account_id = sub_account_id
        self.config = config
        self.spread_feed = spread_feed
        self._running = False
        self._repay_ban: dict[str, datetime] = {}
        self._last_borrow_at: dict[str, datetime] = {}
        self._cycle_count = 0
        self._trading_client = None
        self._notifier = None
        self._margin_safe = True
        self._symbol_rules: dict[str, dict] = {}
        self._symbol_statuses: dict[str, str] = {}
        self._glitch_logged: dict[str, datetime] = {}
        self._symbol_volumes: dict[str, float] = {}   # symbol -> 现货24h成交量(USDT),交易护栏用
        self._symbol_futures_volumes: dict[str, float] = {}   # symbol -> 合约24h成交量(USDT),双腿量过滤用
        self._above_since: dict[str, datetime] = {}   # symbol -> 点差首次超借币阈时间(filter_duration_ms 防抖)
        self._removed_ban: dict[str, datetime] = {}   # symbol -> 退出时间(removed_cooldown_minutes 再借冷却)
        self._user_id: int | None = None
        self._account_max_borrow: Decimal | None = None
        self._account_max_positions: int | None = None
        self._account_borrow_rate: Decimal | None = None
        self._redis: aioredis.Redis | None = None

    async def run(self):
        self._running = True
        account_info = await asyncio.to_thread(self._load_account)
        if not account_info:
            logger.error(f"Sub-account {self.sub_account_id} not found")
            return

        account_note = account_info["note"]
        self._user_id = account_info.get("user_id")
        self._account_max_borrow = account_info.get("max_borrow_amount")
        self._account_max_positions = account_info.get("max_positions")
        self._account_borrow_rate = account_info.get("borrow_rate_per_sec")
        logger.info(f"Worker started for sub-account {self.sub_account_id} ({account_note})")

        await asyncio.to_thread(self._load_symbol_rules)

        from engine.trading.binance_trading import BinanceTradingClient
        self._trading_client = BinanceTradingClient(
            account_info["api_key"], account_info["api_secret"],
            sub_account_id=self.sub_account_id,
        )

        from engine.notify.feishu_sender import FeishuSender
        self._notifier = FeishuSender()
        self._notifier.user_id = self._user_id   # 飞书机器人告警按本 user 的 feishu_open_id 路由

        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

        await self._update_state("RUNNING")

        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
        last_bnb_check = 0
        last_debt_check = 0
        last_risk_check = 0
        last_health_check = 0
        last_funding_check = 0
        last_borrow_scan = 0
        last_clock_check = 0
        last_inspection = 0
        last_futmargin_check = 0
        last_balance_check = 0
        last_debtconv_check = 0

        try:
            async with self._trading_client:
                while self._running:
                    await self._cycle(tradable_symbols, account_note)
                    self._cycle_count += 1
                    if self._cycle_count % 300 == 0:
                        tradable_symbols = await asyncio.to_thread(self._load_tradable_symbols)
                        await asyncio.to_thread(self._load_symbol_rules)

                    # periodic fund tasks
                    now = asyncio.get_event_loop().time()
                    fund_rules = self.config.fund_rules

                    if now - last_risk_check > 30:
                        from engine.fund.risk_monitor import check_margin_risk
                        self._margin_safe = await check_margin_risk(
                            self._trading_client, fund_rules, self._notifier, account_note,
                            sub_account_id=self.sub_account_id,
                        )
                        last_risk_check = now

                    if now - last_futmargin_check > 30:
                        await self._check_futures_margin(account_note)
                        last_futmargin_check = now

                    # 主→子 保证金自动平衡(仅 hedge_via_master;子账户设了单笔划才动钱)
                    if now - last_balance_check > 30 and getattr(self.config.global_rules, "hedge_via_master", False):
                        from engine.fund.margin_balancer import auto_balance_margin
                        _open = await asyncio.to_thread(self._load_open_positions)
                        await auto_balance_margin(
                            self._trading_client, self.sub_account_id, self._user_id,
                            fund_rules, self._notifier, account_note, bool(_open),
                        )
                        last_balance_check = now

                    if now - last_bnb_check > fund_rules.bnb_convert_interval_sec:
                        from engine.fund.bnb_manager import run_bnb_check
                        await run_bnb_check(
                            self._trading_client, fund_rules, self._notifier, account_note,
                            bnb_burn_enabled=getattr(self.config.global_rules, "bnb_burn_enabled", None),
                        )
                        last_bnb_check = now

                    if now - last_debt_check > fund_rules.usdt_debt_interval_sec:
                        from engine.fund.debt_repayer import run_usdt_debt_check
                        await run_usdt_debt_check(self._trading_client, fund_rules, self._notifier, account_note)
                        last_debt_check = now

                    if now - last_debtconv_check > fund_rules.debt_convert_interval_sec:
                        from engine.fund.debt_converter import run_debt_convert
                        await run_debt_convert(self._trading_client, self.sub_account_id,
                                               self.spread_feed, self._notifier, account_note)
                        last_debtconv_check = now

                    if now - last_health_check > 300:
                        from engine.fund.health_monitor import run_health_check
                        await run_health_check(self._notifier)
                        last_health_check = now

                    if now - last_clock_check > 300:
                        from engine.fund.clock_monitor import run_clock_check
                        await run_clock_check(self._notifier, self._redis)
                        last_clock_check = now

                    if now - last_inspection > 1800:   # 抗延迟巡检每 30min(redis 锁内部去重)
                        from engine.fund.inspection import run_inspection
                        await run_inspection(self._redis, self._notifier)
                        last_inspection = now

                    if now - last_funding_check > 1800:
                        from engine.fund.funding_collector import collect_funding_fees
                        await collect_funding_fees(self._trading_client, self.sub_account_id,
                                                   user_id=self._user_id)
                        last_funding_check = now

                    # C5: scan for manually borrowed assets every 60 seconds
                    if now - last_borrow_scan > 60:
                        from engine.fund.borrow_scanner import scan_manual_borrows
                        pushed = set(tradable_symbols)
                        open_positions = await asyncio.to_thread(self._load_open_positions)
                        pushed.update(p.symbol for p in open_positions)
                        new_borrows = await scan_manual_borrows(
                            self._trading_client, self.sub_account_id, self._user_id, pushed,
                        )
                        if new_borrows:
                            await asyncio.to_thread(self._load_symbol_rules)
                            logger.info(f"Borrow scan found {len(new_borrows)} new symbols: {new_borrows}")
                        last_borrow_scan = now

                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Worker {self.sub_account_id} error: {e}", exc_info=True)
            await self._update_state("ERROR", str(e))
            raise
        finally:
            await self._update_state("STOPPED")
            logger.info(f"Worker stopped for sub-account {self.sub_account_id}")

    async def stop(self):
        self._running = False

    async def _cycle(self, tradable_symbols: set[str], account_note: str):
        rules = self.config.global_rules
        blacklist = self.config.blacklist
        # Apply per-account borrow pacing: account override else global (live-updates)
        from engine.trading.binance_trading import set_borrow_rate
        eff_rate = self._account_borrow_rate if self._account_borrow_rate else getattr(rules, "borrow_rate_per_sec", 2)
        set_borrow_rate(self.sub_account_id, eff_rate)

        open_positions = await asyncio.to_thread(self._load_open_positions)
        idle_positions = await asyncio.to_thread(self._load_positions_by_status, "BORROWED_IDLE")
        pending_repay = await asyncio.to_thread(self._load_positions_by_status, "PENDING_REPAY")

        open_symbol_counts: dict[str, int] = {}
        repayable_symbols: set[str] = set()
        for p in open_positions:
            open_symbol_counts[p.symbol] = open_symbol_counts.get(p.symbol, 0) + 1
            if self._is_repay_allowed(p.symbol):
                repayable_symbols.add(p.symbol)
        # symbols already in-flight (any active state) — do not re-borrow
        active_symbols = ({p.symbol for p in open_positions} |
                          {p.symbol for p in idle_positions} |
                          {p.symbol for p in pending_repay})

        statuses: dict[str, str] = {}
        for pos in open_positions:
            sym = pos.symbol
            if sym in statuses:
                continue
            if not self._is_repay_allowed(sym):
                statuses[sym] = "借币停止"
            elif self._is_borrow_banned(sym):
                statuses[sym] = "借币红"
            else:
                sp = self.spread_feed.get_symbol(sym)
                if sp and sp.spread_short < rules.close_spread:
                    statuses[sym] = "还币中"
                else:
                    statuses[sym] = "点差不符"
        # P1: overlay in-flight execution states (排队中/待对冲/开仓中/待还币...)
        active = await asyncio.to_thread(self._load_active_statuses)
        for sym, label in active.items():
            if label:
                statuses[sym] = label
        self._symbol_statuses = statuses

        # ── UNHEDGE: OPEN → PENDING_REPAY at close_spread (or funding ratio) ──
        for pos in open_positions:
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not self._spread_sane(spread):            # 行情 glitch 护栏(PnL 也需 sane 价)
                continue
            # ── STOP-LOSS: 单仓最大亏损 — 盯市浮亏达上限即强制平仓(优先于点差/资费/冷却)──
            max_loss = getattr(rules, "max_loss_per_position", None)
            if max_loss is not None and max_loss > 0:
                upnl = self._position_unrealized_pnl(pos, spread)
                if upnl is not None and upnl <= -Decimal(str(max_loss)):
                    logger.warning(f"Stop-loss {pos.symbol}#{pos.id}: 浮亏 {upnl:.2f} <= -{max_loss} USDT, 强制平仓")
                    try:
                        await self._notifier.notify_error(
                            account_note, f"止损 {pos.symbol}",
                            f"单仓浮亏 {upnl:.2f} USDT 触及上限 -{max_loss},强制平仓(合约平+现货买回,余下按还币规则)",
                        )
                    except Exception:
                        pass
                    await self._unhedge_position(pos, spread, account_note)
                    continue
            if not self._is_repay_allowed(pos.symbol):   # C3
                continue
            if self._is_borrow_banned(pos.symbol):        # C4
                continue
            if spread.spread_short < rules.close_spread:
                await self._unhedge_position(pos, spread, account_note)
                continue
            if getattr(pos, 'funding_rate_ratio', None) is not None and \
               rules.close_funding_ratio > 0 and pos.funding_rate_ratio >= rules.close_funding_ratio:
                logger.info(f"Unhedge {pos.symbol}: funding ratio {pos.funding_rate_ratio} >= {rules.close_funding_ratio}")
                await self._unhedge_position(pos, spread, account_note)

        # ── REPAY: PENDING_REPAY → CLOSED only if an auto-repay threshold is configured & met ──
        repay_spread = getattr(rules, "repay_spread", None)
        repay_fr = getattr(rules, "repay_funding_ratio", None)
        for pos in pending_repay:
            if not self._is_repay_allowed(pos.symbol):
                continue
            spread = self.spread_feed.get_symbol(pos.symbol)
            if spread is not None and not self._spread_sane(spread):  # glitch → 本轮不还
                continue
            do_repay = False
            if repay_spread is not None and repay_spread > 0 and spread and spread.spread_short < repay_spread:
                do_repay = True
            elif repay_fr is not None and repay_fr > 0 and getattr(pos, 'funding_rate_ratio', None) is not None \
                    and pos.funding_rate_ratio >= repay_fr:
                do_repay = True
            if do_repay:
                await self._repay_position(pos, account_note)

        # C6: auto-repay for borrow-only (scan) assets with no open position
        for sym, rule in self._symbol_rules.items():
            if rule.get("source") != "scan":
                continue
            if not rule.get("allow_repay", True):
                continue
            if sym in open_symbol_counts:
                continue
            spread = self.spread_feed.get_symbol(sym)
            if not self._spread_sane(spread):
                continue
            if spread.spread_short < rules.close_spread:
                await self._borrow_only_repay(sym, account_note)

        global_max = rules.max_positions or MAX_POSITIONS_PER_ACCOUNT
        max_positions = self._account_max_positions if self._account_max_positions is not None else global_max

        # ── HEDGE: BORROWED_IDLE → OPEN at open_spread ──
        for pos in idle_positions:
            if not self._running:
                break
            if len(open_positions) >= max_positions:
                break
            spread = self.spread_feed.get_symbol(pos.symbol)
            if not self._spread_sane(spread):            # glitch → 不在坏点差上对冲开仓
                continue
            if spread.spread_short > rules.open_spread:
                await self._hedge_position(pos, spread, account_note)
                open_positions = await asyncio.to_thread(self._load_open_positions)

        # ── BORROW: pushed ∩ tradable, spread > borrow_spread → execute_borrow (idle) ──
        active_count = len(open_positions) + len(idle_positions)
        can_borrow = (self._margin_safe and active_count < max_positions and
                      not (self._account_max_borrow is not None and self._account_max_borrow == 0))
        if can_borrow:
            pushed = await asyncio.to_thread(self._load_pushed_symbols)
            borrow_spread = getattr(rules, "borrow_spread", rules.open_spread)
            # 开仓阈值缓冲: 实际要求点差 ≥ 借币点差 + buffer,吸收腿间滑点/~160ms借币延迟(0=不留,行为不变)
            eff_borrow = float(borrow_spread) + float(getattr(rules, "open_spread_buffer", 0) or 0)
            no_inventory = self._load_no_inventory()   # 无券冷却中的币(-3045),本周期跳过不重试
            for symbol in pushed:
                if not self._running or active_count >= max_positions:
                    break
                if symbol in blacklist or symbol not in tradable_symbols:
                    continue
                if symbol in active_symbols:          # already borrowed / open / pending
                    continue
                if symbol in no_inventory:            # 杠杆池无可借库存冷却(避免每周期重试打爆 SAPI)
                    continue
                if not self._volume_ok(symbol):       # 成交量护栏:薄盘币不借
                    continue
                if self._is_banned(symbol):
                    continue
                if self._is_removed_banned(symbol):   # 移除/平仓冷却:退出后短期不再借
                    continue
                sym_rule = self._symbol_rules.get(symbol, {})
                if sym_rule.get("max_borrow_amount") is not None and sym_rule["max_borrow_amount"] == 0:
                    continue
                spread = self.spread_feed.get_symbol(symbol)
                if not self._spread_sane(spread):        # glitch → 不在坏点差上借币开仓
                    continue
                if not self._spread_fresh(spread):       # feed 停更/快照陈旧 → 不在已死数据上借
                    continue
                # filter_duration_ms 防抖 + 开仓阈值缓冲:点差需持续超(借币点差+buffer)才借
                if not self._spread_persisted(symbol, float(spread.spread_short), eff_borrow):
                    continue
                await self._initiate_borrow(symbol, spread, eff_borrow, account_note)
                active_symbols.add(symbol)
                active_count += 1

        # ── Auto-push: symbols whose spread ≥ auto_push_spread join the user's pushed list ──
        if self._cycle_count % 10 == 0 and getattr(rules, "auto_push_spread", 0) and rules.auto_push_spread > 0:
            await self._auto_push(float(rules.auto_push_spread), tradable_symbols)

        if self._cycle_count % 10 == 0:
            await self._update_state("RUNNING", active_positions=len(open_positions))

    async def _initiate_borrow(self, symbol: str, spread: SpreadSnapshot, eff_borrow: float, account_note: str):
        """Phase 1: borrow at 挂单点差(含开仓缓冲), hold idle。eff_borrow=借币点差+open_spread_buffer。"""
        from engine.trading.order_executor import execute_borrow
        from decimal import Decimal as _D
        try:
            await execute_borrow(
                self.sub_account_id, symbol, spread,
                self.config.global_rules, self._trading_client,
                self._notifier, account_note,
                spread_feed=self.spread_feed,
                min_spread=_D(str(eff_borrow)),   # 二次确认按含缓冲的阈值,且 execute_borrow 内借币前会再校验新鲜度+阈值
                user_id=self._user_id,
            )
            self._last_borrow_at[symbol] = datetime.now(timezone.utc)  # C4 ban countdown
        except Exception as e:
            logger.error(f"Initiate borrow failed {symbol}: {e}")

    async def _hedge_position(self, position: Position, spread: SpreadSnapshot, account_note: str):
        """Phase 2: sell spot + futures long. BORROWED_IDLE → OPEN.
        hedge_via_master 开启时合约腿用共享主账户 client;主账户 client 不可用则
        不动现货(留 BORROWED_IDLE 重试),绝不回退到子账户 key 打合约。"""
        from engine.trading.order_executor import execute_hedge
        try:
            fc = None
            if getattr(self.config.global_rules, "hedge_via_master", False):
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(self._user_id)
                if fc is None:
                    logger.warning(f"hedge_via_master: master client unavailable; "
                                   f"{position.symbol} stays BORROWED_IDLE")
                    return
            await execute_hedge(
                position, spread, self.config.global_rules,
                self._trading_client, self._notifier, account_note,
                futures_client=fc, user_id=self._user_id,
            )
        except Exception as e:
            logger.error(f"Hedge failed {position.symbol}: {e}")

    async def _unhedge_position(self, position: Position, spread: SpreadSnapshot, account_note: str):
        """Close hedge (futures close + spot buy back), leave coin pending repay.
        合约腿按持仓归属(hedge_account)选 client,与开关当前值无关。"""
        from engine.trading.order_executor import execute_unhedge
        try:
            fc = None
            if getattr(position, "hedge_account", None) == "master":
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(self._user_id)
                # fc=None 时 execute_unhedge 内部留 OPEN 等重试
            await execute_unhedge(
                position, spread, self._trading_client, self._notifier, account_note,
                futures_client=fc,
            )
            now = datetime.now(timezone.utc)
            self._repay_ban[position.symbol] = now
            self._removed_ban[position.symbol] = now   # 退出 → 进入再借冷却窗
        except Exception as e:
            logger.error(f"Unhedge failed {position.symbol}: {e}")

    async def _repay_position(self, position: Position, account_note: str):
        """Repay margin debt → CLOSED (auto path; manual path via API)."""
        from engine.trading.order_executor import execute_repay
        try:
            await execute_repay(
                position, self._trading_client, self._notifier, account_note,
                fee_spot=getattr(self.config.global_rules, "taker_fee_spot", None),
                fee_futures=getattr(self.config.global_rules, "taker_fee_futures", None),
            )
        except Exception as e:
            logger.error(f"Repay failed {position.symbol}: {e}")

    async def _check_futures_margin(self, account_note: str):
        """合约账户距爆仓安全垫 < margin_rate_alert% 告警(纯告警,不动仓)。
        安全垫 = (totalMarginBalance − totalMaintMargin)/totalMarginBalance ×100,越低越接近强平。
        hedge_via_master 看主账户合约(全对冲腿所在),否则看子账户自身合约。
        跨子账户用 Redis 去重(每 user 每 ~25s 仅一次,避免 5 个 worker 重复查主账户)。"""
        try:
            self._notifier._ensure_config()
            thr = self._notifier.margin_rate_alert
            if thr is None or Decimal(str(thr)) <= 0:
                return
            from app.services.notifier import throttle_ok
            if not await asyncio.to_thread(throttle_ok, f"futmargin:check:{self._user_id}", 25, 1):
                return
            if getattr(self.config.global_rules, "hedge_via_master", False):
                from engine.trading.master_client import get_master_futures_client
                fc = await get_master_futures_client(self._user_id)
            else:
                fc = self._trading_client
            if fc is None:
                return
            acct = await fc.get_futures_account()
            mb = Decimal(str(acct.get("totalMarginBalance", "0")))
            mm = Decimal(str(acct.get("totalMaintMargin", "0")))
            if mb <= 0 or mm <= 0:
                return  # 无合约持仓/无维持保证金 = 无强平风险
            buffer_pct = (mb - mm) / mb * Decimal("100")
            if buffer_pct < Decimal(str(thr)):
                await self._notifier.notify_futures_margin(account_note, buffer_pct, Decimal(str(thr)))
        except Exception as e:
            logger.debug(f"futures margin check failed: {e}")

    def _position_unrealized_pnl(self, position: Position, spread: SpreadSnapshot) -> Decimal | None:
        """OPEN 仓盯市未实现 PnL(USDT,盈正亏负),供单仓止损判定。
        按平仓侧成交价估两腿:现货空腿买回=spot_ask、合约多腿平仓=fut_bid;
        加累计资金费(USDT,收正付负),减累计借币利息(币本位×现价换 USDT)。
        现货溢价走阔→两腿合计转负=亏(方向正确)。缺字段/价格异常返回 None(不触发止损,安全)。"""
        try:
            ssq = position.spot_sell_qty
            ssp = position.spot_sell_price
            flq = position.futures_long_qty
            flp = position.futures_long_price
            if not (ssq and ssp and flq and flp and spread
                    and spread.spot_ask > 0 and spread.fut_bid > 0):
                return None
            spot_leg = (Decimal(str(ssp)) - spread.spot_ask) * Decimal(str(ssq))   # 空现货: 卖价-买回价
            fut_leg = (spread.fut_bid - Decimal(str(flp))) * Decimal(str(flq))      # 多合约: 平价-开价
            funding = Decimal(str(position.cumulative_funding_fee or 0))            # USDT
            interest_usdt = Decimal(str(position.cumulative_interest or 0)) * spread.spot_ask  # 币本位→USDT
            return spot_leg + fut_leg + funding - interest_usdt
        except Exception:
            return None

    def _load_pushed_symbols(self) -> set[str]:
        """The user's actively-pushed symbols (trade gate). Synchronous Redis read."""
        try:
            import redis as _redis_sync
            r = _redis_sync.from_url(settings.redis_url, decode_responses=True)
            raw = r.get(f"engine:{self._user_id}:pushed_symbols")
            r.close()
            return set(json.loads(raw)) if raw else set()
        except Exception:
            return set()

    def _load_no_inventory(self) -> set[str]:
        """无券冷却中的币(借币 -3045 后由 order_executor 写 engine:noinv:{symbol} EX300)。
        借币前批量读,避免对稳定无券的币每周期重试打爆 SAPI(全局共享,非 per-user)。"""
        try:
            import redis as _redis_sync
            r = _redis_sync.from_url(settings.redis_url, decode_responses=True)
            keys = r.keys("engine:noinv:*")
            r.close()
            return {k.split("engine:noinv:", 1)[1] for k in keys}
        except Exception:
            return set()

    async def _auto_push(self, threshold: float, tradable_symbols: set[str]):
        """Add symbols whose spread_short ≥ auto_push_spread to the user's pushed set."""
        try:
            candidates = {
                sym for sym, sp in self.spread_feed.get_all().items()
                if sym in tradable_symbols and sym not in self.config.blacklist  # 黑名单不进推送
                and float(sp.spread_short) >= threshold
                and self._volume_ok(sym)   # 成交量护栏:低量薄盘不自动推送
                and not self._is_removed_banned(sym)   # 移除/平仓冷却内不重新推送
            }
            if not candidates:
                return
            key = f"engine:{self._user_id}:pushed_symbols"
            raw = await self._redis.get(key)
            current = set(json.loads(raw)) if raw else set()
            new = candidates - current
            if not new:
                return
            # 二次确认推送:点差≥confirm_skip_spread 直推;否则等 confirm_delay_sec 复核防抖(防瞬时跳点误推)
            rules = self.config.global_rules
            cd = int(getattr(rules, "confirm_delay_sec", 0) or 0)
            skip = float(getattr(rules, "confirm_skip_spread", 0) or 0)
            immediate, need_confirm = set(), set()
            for sym in new:
                sp = self.spread_feed.get_symbol(sym)
                s = float(sp.spread_short) if sp else 0.0
                if cd <= 0 or (skip > 0 and s >= skip):
                    immediate.add(sym)
                else:
                    need_confirm.add(sym)
            if immediate:
                current |= immediate
                await self._redis.set(key, json.dumps(sorted(current)))
                logger.info(f"Auto-pushed {len(immediate)} (spread≥{threshold}, 直推): {sorted(immediate)[:10]}")
            if need_confirm and cd > 0:
                asyncio.create_task(self._confirm_push(need_confirm, threshold, cd, key))
        except Exception as e:
            logger.debug(f"Auto-push failed: {e}")

    async def _confirm_push(self, syms: set[str], threshold: float, cd: int, key: str):
        """二次确认:等 cd 秒后复核点差仍≥阈值才推(防瞬时跳点误推)。后台执行,不阻塞主循环。"""
        try:
            await asyncio.sleep(cd)
            ok = {
                s for s in syms
                if (sp := self.spread_feed.get_symbol(s)) and float(sp.spread_short) >= threshold
                and self._volume_ok(s) and not self._is_removed_banned(s)
            }
            if not ok:
                return
            raw = await self._redis.get(key)
            current = set(json.loads(raw)) if raw else set()
            add = ok - current
            if add:
                current |= ok
                await self._redis.set(key, json.dumps(sorted(current)))
                logger.info(f"Auto-pushed {len(add)} after 2nd-confirm({cd}s): {sorted(add)[:10]}")
        except Exception as e:
            logger.debug(f"confirm_push failed: {e}")

    async def _borrow_only_repay(self, symbol: str, account_note: str):
        from engine.trading.order_executor import execute_borrow_only_repay
        try:
            await execute_borrow_only_repay(
                self.sub_account_id, symbol,
                self._trading_client, self._notifier, account_note,
                user_id=self._user_id,
            )
            logger.info(f"Auto repaid borrow-only: {symbol}")
        except Exception as e:
            logger.error(f"Auto repay failed {symbol}: {e}")

    def _is_banned(self, symbol: str) -> bool:
        ban_until = self._repay_ban.get(symbol)
        if not ban_until:
            return False
        if datetime.now(timezone.utc) - ban_until < timedelta(minutes=self.config.global_rules.repay_ban_minutes):
            return True
        del self._repay_ban[symbol]
        return False

    def _load_account(self) -> dict | None:
        db = SessionLocal()
        try:
            account = db.query(SubAccount).get(self.sub_account_id)
            if not account:
                return None
            return {
                "note": account.note,
                "api_key": account.api_key,
                "api_secret": account.api_secret,
                "user_id": account.user_id,
                "max_borrow_amount": account.max_borrow_amount,
                "max_positions": account.max_positions,
                "borrow_rate_per_sec": account.borrow_rate_per_sec,
            }
        finally:
            db.close()

    def _load_symbol_rules(self):
        db = SessionLocal()
        try:
            rules_map = {}
            q = db.query(SymbolRule)
            if self._user_id:
                q = q.filter(SymbolRule.user_id == self._user_id)
            for sr in q.all():
                rules_map[sr.symbol] = {
                    "allow_repay": sr.allow_repay,
                    "allow_remove": sr.allow_remove,
                    "remove_spread": sr.remove_spread,
                    "source": sr.source,
                }
            # account-level overrides
            for ar in db.query(AccountSymbolRule).filter(
                AccountSymbolRule.sub_account_id == self.sub_account_id,
            ).all():
                key = ar.symbol
                if key in rules_map:
                    if ar.remove_spread is not None:
                        rules_map[key]["remove_spread"] = ar.remove_spread
                    if ar.is_enabled is not None:
                        rules_map[key]["account_enabled"] = ar.is_enabled
                    if ar.max_borrow_amount is not None:
                        rules_map[key]["max_borrow_amount"] = ar.max_borrow_amount
            self._symbol_rules = rules_map
        finally:
            db.close()

    def _spread_sane(self, spread) -> bool:
        """行情 glitch 护栏: 价格非正 / 点差幅度超过 max_spread_pct 时判定为坏数据,
        跳过该币种本轮所有下单/平仓决策(canary 实测 CRV 点差瞬时 6.6% 触发误开仓)。
        max_spread_pct=0 时关闭护栏(沿用原行为)。"""
        if spread is None:
            return False
        try:
            if (spread.spot_ask <= 0 or spread.spot_bid <= 0 or
                    spread.fut_ask <= 0 or spread.fut_bid <= 0):
                self._note_glitch(spread.symbol, "non-positive price")
                return False
            ceiling = float(getattr(self.config.global_rules, "max_spread_pct", 3.0) or 0)
            if ceiling > 0 and (abs(float(spread.spread_short)) > ceiling or
                                abs(float(spread.spread_long)) > ceiling):
                self._note_glitch(spread.symbol,
                                  f"spread {spread.spread_short}/{spread.spread_long}% > {ceiling}%")
                return False
        except Exception:
            return False
        return True

    def _spread_fresh(self, spread) -> bool:
        """新鲜度护栏: 快照 ts 距今超过 SPREAD_FRESH_MS 视为 feed 停更/陈旧,不据此开仓。
        防 rust 停发/孤儿后 python 缓存残留旧值被拿来借币。注:依赖 57 与 95 时钟一致,
        偏差由 clock_monitor 监控告警。"""
        if spread is None or not getattr(spread, "ts", 0):
            return False
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return (now_ms - int(spread.ts)) <= SPREAD_FRESH_MS

    def _note_glitch(self, symbol: str, reason: str):
        """每币种每 60s 最多记一条 glitch 日志,避免刷屏。"""
        now = datetime.now(timezone.utc)
        last = self._glitch_logged.get(symbol)
        if not last or (now - last).total_seconds() > 60:
            self._glitch_logged[symbol] = now
            logger.warning(f"行情护栏: 跳过 {symbol} (坏数据: {reason})")

    def _is_repay_allowed(self, symbol: str) -> bool:
        rule = self._symbol_rules.get(symbol)
        if not rule:
            return True
        return rule.get("allow_repay", True)

    def _is_borrow_banned(self, symbol: str) -> bool:
        """C4: Check if symbol is within the post-borrow repay ban window."""
        last_borrow = self._last_borrow_at.get(symbol)
        if not last_borrow:
            return False
        elapsed = (datetime.now(timezone.utc) - last_borrow).total_seconds()
        ban_seconds = self.config.global_rules.repay_ban_minutes * 60
        return elapsed < ban_seconds

    def _is_removed_banned(self, symbol: str) -> bool:
        """移除/平仓冷却: 同币退出后 removed_cooldown_minutes 分钟内禁止再借(0=不启用)。"""
        mins = int(getattr(self.config.global_rules, "removed_cooldown_minutes", 0) or 0)
        if mins <= 0:
            return False
        ts = self._removed_ban.get(symbol)
        if not ts:
            return False
        if (datetime.now(timezone.utc) - ts).total_seconds() >= mins * 60:
            self._removed_ban.pop(symbol, None)
            return False
        return True

    def _load_tradable_symbols(self) -> set[str]:
        db = SessionLocal()
        try:
            q = db.query(Symbol.symbol, Symbol.volume_24h, Symbol.futures_volume_24h).filter(
                Symbol.is_active == True,
                Symbol.margin_tradable == True,
                Symbol.futures_tradable == True,
                Symbol.allow_open == True,        # /coins「允许开仓」硬门:禁止开仓的币不进可交易集
                Symbol.is_delisting == False,     # 下架中的币不开
            )
            if bool(getattr(self.config.global_rules, "block_risky_open", False)):
                q = q.filter(Symbol.is_risky == False)   # 可选硬拦:开启后风险币也不开
            rows = q.all()
            # 同时刷新现货/合约成交量 map(双腿量过滤:低量币不自动推送/借币)
            self._symbol_volumes = {r.symbol: float(r.volume_24h or 0) for r in rows}
            self._symbol_futures_volumes = {r.symbol: float(r.futures_volume_24h or 0) for r in rows}
            return {r.symbol for r in rows}
        finally:
            db.close()

    def _volume_ok(self, symbol: str) -> bool:
        """双腿 24h 成交量护栏:现货<min_volume_24h 或 合约<min_volume_24h_futures 的薄盘币
        不参与自动推送/借币(各自 0=该腿不启用)。"""
        min_spot = float(getattr(self.config.global_rules, "min_volume_24h", 0) or 0)
        if min_spot > 0 and self._symbol_volumes.get(symbol, 0) < min_spot:
            return False
        min_fut = float(getattr(self.config.global_rules, "min_volume_24h_futures", 0) or 0)
        if min_fut > 0 and self._symbol_futures_volumes.get(symbol, 0) < min_fut:
            return False
        return True

    def _spread_persisted(self, symbol: str, value: float, threshold: float) -> bool:
        """信号级防抖(coinmini filter_duration_ms 同款):点差需持续超阈达 N 毫秒才放行。
        - value <= threshold:清零计时并拒绝(同旧的 `spread<=borrow_spread → continue`)
        - filter_duration_ms<=0:不启用,value>threshold 即放行(完全保留旧行为)
        - 否则:首次超阈记时间戳,持续 ≥ N ms 才放行,中途跌回阈下则清零重计。"""
        if value <= threshold:
            self._above_since.pop(symbol, None)
            return False
        dur_ms = int(getattr(self.config.global_rules, "filter_duration_ms", 0) or 0)
        if dur_ms <= 0:
            return True
        now = datetime.now(timezone.utc)
        since = self._above_since.get(symbol)
        if since is None:
            self._above_since[symbol] = now
            return False
        return (now - since).total_seconds() * 1000 >= dur_ms

    def _load_open_positions(self) -> list[Position]:
        db = SessionLocal()
        try:
            return db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status == "OPEN",
            ).all()
        finally:
            db.close()

    def _load_positions_by_status(self, status: str) -> list[Position]:
        db = SessionLocal()
        try:
            return db.query(Position).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status == status,
            ).all()
        finally:
            db.close()

    # P1: transient/holding statuses -> 执行/队列 labels for the 状态 column
    _EXEC_STATUS_MAP = {
        "PENDING_BORROW": "排队中",
        "BORROWED": "借币中",
        "BORROWED_IDLE": "待对冲",
        "HEDGING": "开仓中",
        "SPOT_SOLD": "开仓中",
        "CLOSING_FUTURES": "平仓中",
        "FUTURES_CLOSED": "平仓中",
        "CLOSING_SPOT": "买回中",
        "SPOT_BOUGHT": "还币中",
        "PENDING_REPAY": "待还币",
        "REPAYING": "还币中",
    }

    def _load_active_statuses(self) -> dict[str, str]:
        """symbol -> execution label for positions currently mid-pipeline."""
        db = SessionLocal()
        try:
            rows = db.query(Position.symbol, Position.status).filter(
                Position.sub_account_id == self.sub_account_id,
                Position.status.in_(list(self._EXEC_STATUS_MAP.keys())),
            ).all()
            out: dict[str, str] = {}
            for sym, st in rows:
                out[sym] = self._EXEC_STATUS_MAP.get(st, "")
            return out
        finally:
            db.close()

    async def _update_state(self, status: str, error: str = None, active_positions: int = None):
        def _write():
            db = SessionLocal()
            try:
                scope = f"sub:{self.sub_account_id}"
                state = db.query(EngineState).filter(EngineState.scope == scope).first()
                if not state:
                    state = EngineState(scope=scope)
                    db.add(state)
                state.status = status
                state.last_heartbeat = datetime.now(timezone.utc)
                state.total_cycles = self._cycle_count
                if error:
                    state.error_message = error
                if active_positions is not None:
                    state.active_positions = active_positions
                db.commit()
            finally:
                db.close()
        await asyncio.to_thread(_write)

        # C4: publish ban countdown data to Redis
        if self._redis and status == "RUNNING":
            try:
                now_utc = datetime.now(timezone.utc)
                ban_info = {}
                ban_seconds = self.config.global_rules.repay_ban_minutes * 60
                for sym, ts in self._last_borrow_at.items():
                    remaining = ban_seconds - (now_utc - ts).total_seconds()
                    if remaining > 0:
                        ban_info[sym] = {"type": "borrow", "remaining": int(remaining), "total": ban_seconds}
                for sym, ts in self._repay_ban.items():
                    remaining = ban_seconds - (now_utc - ts).total_seconds()
                    if remaining > 0:
                        ban_info[sym] = {"type": "repay", "remaining": int(remaining), "total": ban_seconds}
                if ban_info:
                    await self._redis.publish("ban:updates", json.dumps({
                        "sub_account_id": self.sub_account_id,
                        "user_id": self._user_id,
                        "bans": ban_info,
                    }))
                if self._symbol_statuses:
                    await self._redis.publish("symbol_status:updates", json.dumps({
                        "sub_account_id": self.sub_account_id,
                        "user_id": self._user_id,
                        "statuses": self._symbol_statuses,
                    }))
                # P0: publish IP weight (read budget) + UID weight (borrow budget) for
                # the top-bar gauge and per-account throttle display.
                try:
                    from engine.metrics import global_weight_snapshot, max_uid_weight_snapshot
                    ws = global_weight_snapshot()
                    if ws["weight_time"] > 0:
                        await self._redis.set("engine:weight:latest", json.dumps(ws), ex=90)
                    us = max_uid_weight_snapshot()
                    if us["uid_weight_time"] > 0:
                        await self._redis.set("engine:uid_weight:latest", json.dumps(us), ex=90)
                except Exception:
                    pass
            except Exception as e:
                logger.debug(f"Ban/status publish failed: {e}")
