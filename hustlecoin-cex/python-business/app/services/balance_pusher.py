import asyncio
import json
import logging
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


class BalancePusher:
    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._running = False
        self._max_borrow_tick = 0
        self._max_borrow_cache: dict[int, dict[str, float]] = {}  # account_id -> {asset: amount}
        self._no_inventory: dict[str, bool] = {}  # asset -> True 表示币安杠杆池无可借库存(-3045)
        self._interest_rate_cache: dict[str, float] = {}  # asset -> daily_interest_rate (global)

    async def start(self):
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True
        asyncio.create_task(self._loop())
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
        otoco = bool(getattr(sysrow, "borrow_via_otoco", False)) if sysrow else False
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
            return 0.0, "无券"
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

    async def _fetch_and_push(self):
        self._max_borrow_tick += 1
        fetch_max_borrow = self._max_borrow_tick % 6 == 0
        btc_price = await self._btc_price()
        spot_bids = await self._spot_bids()
        # Cap maxBorrowable calls per account per cycle to protect the SAPI weight budget.
        MAX_BORROW_PER_CYCLE = 40

        db = SessionLocal()
        try:
            accounts = db.query(SubAccount).filter(SubAccount.is_enabled == True).all()
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

            interest_fetched: set[str] = set()

            user_balances: dict[int, list] = {}
            for acc in accounts:
                try:
                    targets = target_assets.get(acc.id, set())
                    async with BinanceTradingClient(acc.api_key, acc.api_secret) as client:
                        margin, futures = await asyncio.gather(
                            client.get_margin_account(),
                            client.get_futures_account(),
                        )

                        if fetch_max_borrow and targets:
                            mb_results = dict(self._max_borrow_cache.get(acc.id, {}))
                            # 已知无券的币(-3045)不必每轮重查 maxBorrowable(每次都 400 刷错误率/耗 SAPI);
                            # 仅每 RECHECK_NOINV_EVERY 次 fetch(fetch 自身每 6 周期一次)重试一次看库存是否恢复。
                            recheck_noinv = self._max_borrow_tick % (6 * RECHECK_NOINV_EVERY) == 0
                            for asset in list(targets)[:MAX_BORROW_PER_CYCLE]:
                                if self._no_inventory.get(asset) and not recheck_noinv:
                                    mb_results[asset] = 0.0   # 沿用无券缓存,跳过查询
                                else:
                                    try:
                                        amt = await client.get_max_borrowable(asset)
                                        mb_results[asset] = float(amt)
                                        self._no_inventory[asset] = False
                                    except Exception as e:
                                        # -3045 = 币安杠杆池该币无可借库存(真实市场状态,非故障)→ 明确置 0 + 标记池空
                                        if "-3045" in str(e):
                                            mb_results[asset] = 0.0
                                            self._no_inventory[asset] = True
                                        else:
                                            mb_results[asset] = mb_results.get(asset, 0)
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
                        if asset_name in targets:
                            sym_key = f"{asset_name}USDT"
                            symbol_margin[sym_key] = {
                                "free": float(a.get("free", "0")),
                                "max_borrowable": self._max_borrow_cache.get(acc.id, {}).get(asset_name, 0),
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                "no_inventory": self._no_inventory.get(asset_name, False),
                            }

                    # Pushed-but-not-held assets aren't in userAssets — still surface
                    # 最大可借/日息 so monitored coins show data before any position.
                    for asset_name in targets:
                        sym_key = f"{asset_name}USDT"
                        if sym_key not in symbol_margin:
                            symbol_margin[sym_key] = {
                                "free": 0.0,
                                "max_borrowable": self._max_borrow_cache.get(acc.id, {}).get(asset_name, 0),
                                "daily_interest_rate": self._interest_rate_cache.get(asset_name, 0),
                                "no_inventory": self._no_inventory.get(asset_name, False),
                            }

                    # 有效可借: 在理论上限(max_borrowable)基础上,套引擎同一封顶口径
                    # (金额限制/抵押率/单笔金额),给前端展示「实际会借到的量」。
                    for sym_key, sm in symbol_margin.items():
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
                }

                await self._redis.publish("balance:updates", json.dumps(payload))
                await self._redis.set(f"balance:latest:{uid}", json.dumps(payload), ex=30)

            # 资金净值快照落库(每 ~10min 一次,每用户一行)→ 资金曲线/日终对账/回撤监控。
            # 复用 aggregate_balances 同一净值口径(与 admin 实时总览一致)。落库失败不影响推送。
            if self._max_borrow_tick % SNAPSHOT_EVERY == 0:
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
                try:
                    from app.services.fund_alerts import run_fund_alert_checks
                    run_fund_alert_checks(db, agg_by_user)
                except Exception as e:
                    db.rollback()
                    logger.warning(f"fund alert checks failed: {e}")

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
