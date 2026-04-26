"""
Fix false asset alerts caused by proxy failures returning zero balances.

Root cause: When SOCKS5 proxy fails, get_binance_balance() silently returns
net_assets=0.0 instead of raising an exception. The risk alert system then
triggers false "insufficient assets" warnings.

Fix strategy:
1. account_service.py: When ALL core Binance APIs fail (proxy down), raise
   exception instead of returning zero-value AccountBalance
2. broadcast_tasks.py: Skip risk alerts for users with failed account fetches;
   use last-known-good cached data for frontend push when current fetch fails
"""
import sys

# ============================================================
# Fix 1: account_service.py — raise when core data all failed
# ============================================================
path = "/data/hustle2026/backend/app/services/account_service.py"
with open(path, "r") as f:
    c = f.read()

# After unpacking results[0], check if ALL core APIs failed (proxy down scenario).
# Core APIs: futures_account_data[0], position_risk_data[1], spot_account_data
# If futures AND spot both failed, we have no meaningful balance data.

old_unpack = """            # Unpack results
            futures_account_data = results[0]
            position_risk_data = results[1]
            daily_pnl_data = results[2]
            funding_fee_data = results[3]
            commission_fee_data = results[4]
            margin_account_data = results[5]
            commission_rate_data = results[6]
            bnb_price_data = results[7]
            futures_balance_data = results[8]
            premium_index_data = results[9]
            funding_asset_data = results[10]"""

new_unpack = """            # Unpack results
            futures_account_data = results[0]
            position_risk_data = results[1]
            daily_pnl_data = results[2]
            funding_fee_data = results[3]
            commission_fee_data = results[4]
            margin_account_data = results[5]
            commission_rate_data = results[6]
            bnb_price_data = results[7]
            futures_balance_data = results[8]
            premium_index_data = results[9]
            funding_asset_data = results[10]

            # Guard: if BOTH futures account AND spot account failed, we have no
            # meaningful balance data (typically proxy/network down). Raise instead
            # of returning a zero-value AccountBalance that triggers false alerts.
            _futures_failed = isinstance(futures_account_data, Exception)
            _spot_failed = isinstance(spot_account_data, Exception)
            if _futures_failed and _spot_failed:
                _err_detail = str(futures_account_data)[:200]
                logger.error(f"[Binance] ALL core APIs failed (proxy down?): futures={_err_detail}")
                raise ConnectionError(f"Binance data fetch failed (proxy/network): {_err_detail}")
            if _futures_failed:
                logger.warning(f"[Binance] Futures API failed but spot OK — net_assets will be spot-only (no contract data)")"""

assert old_unpack in c, "unpack anchor not found"
c = c.replace(old_unpack, new_unpack, 1)

with open(path, "w") as f:
    f.write(c)
print("account_service.py: added core-API failure guard in get_binance_balance")


# ============================================================
# Fix 2: broadcast_tasks.py — skip risk alerts when fetch failed
# ============================================================
path2 = "/data/hustle2026/backend/app/tasks/broadcast_tasks.py"
with open(path2, "r") as f:
    b = f.read()

# 2a. In _check_risk_alerts: skip users whose aggregated data has failed_accounts
# that include the relevant platform (Binance or MT5)
old_check_binance = """                        # Check Binance net asset
                        if risk_settings.binance_net_asset:
                            # Find Binance account in the aggregated data
                            binance_account = next(
                                (acc for acc in aggregated_data.get("accounts", [])
                                 if PlatformId.from_key(acc.get("platform_id")) == PlatformId.BINANCE),
                                None
                            )
                            if binance_account:
                                binance_asset = binance_account["balance"]["net_assets"]
                                logger.info(f"[BROADCAST] Checking binance net_assets: user_id={user_id}, binance={binance_asset}, threshold={risk_settings.binance_net_asset}")
                                if binance_asset < risk_settings.binance_net_asset:
                                    await risk_alert_service.check_binance_net_asset(
                                        user_id=user_id,
                                        current_asset=binance_asset,
                                        threshold=risk_settings.binance_net_asset,
                                        is_below=True
                                    )
                            else:
                                logger.warning(f"[BROADCAST] user={user_id} binance 阈值已配置(={risk_settings.binance_net_asset}) 但聚合数据中未找到 Binance 账户,告警无法触发")"""

new_check_binance = """                        # Detect failed accounts — skip alerts for platforms with fetch failures
                        _failed_platforms = set()
                        for _fa in aggregated_data.get("failed_accounts", []):
                            _fa_pid = _fa.get("platform_id")
                            if _fa_pid:
                                _failed_platforms.add(_fa_pid)
                        if _failed_platforms:
                            logger.warning(f"[BROADCAST] user={user_id} has failed account fetches on platforms={_failed_platforms}, skipping those alerts")

                        # Check Binance net asset
                        if risk_settings.binance_net_asset:
                            if 1 in _failed_platforms:
                                logger.info(f"[BROADCAST] user={user_id} skipping binance_net_asset alert — Binance data fetch failed (proxy/network)")
                            else:
                                # Find Binance account in the aggregated data
                                binance_account = next(
                                    (acc for acc in aggregated_data.get("accounts", [])
                                     if PlatformId.from_key(acc.get("platform_id")) == PlatformId.BINANCE),
                                    None
                                )
                                if binance_account:
                                    binance_asset = binance_account["balance"]["net_assets"]
                                    logger.info(f"[BROADCAST] Checking binance net_assets: user_id={user_id}, binance={binance_asset}, threshold={risk_settings.binance_net_asset}")
                                    if binance_asset < risk_settings.binance_net_asset:
                                        await risk_alert_service.check_binance_net_asset(
                                            user_id=user_id,
                                            current_asset=binance_asset,
                                            threshold=risk_settings.binance_net_asset,
                                            is_below=True
                                        )
                                else:
                                    logger.warning(f"[BROADCAST] user={user_id} binance 阈值已配置(={risk_settings.binance_net_asset}) 但聚合数据中未找到 Binance 账户,告警无法触发")"""

assert old_check_binance in b, "check_binance anchor not found"
b = b.replace(old_check_binance, new_check_binance, 1)

# 2b. Also skip bybit/mt5 alert when hedge-side platform fetch failed
old_check_bybit = """                        # Check Bybit net asset
                        if risk_settings.bybit_mt5_net_asset:
                            # Find Bybit/MT5-hedge account in the aggregated data
                            bybit_account = next(
                                (acc for acc in aggregated_data.get("accounts", [])
                                 if (PlatformId.from_key(acc.get("platform_id")) or 0) in HEDGE_SIDE_IDS),
                                None
                            )
                            if bybit_account:
                                bybit_asset = bybit_account["balance"]["net_assets"]
                                logger.info(f"[BROADCAST] Checking bybit/mt5 net_assets: user_id={user_id}, bybit={bybit_asset}, threshold={risk_settings.bybit_mt5_net_asset}")
                                if bybit_asset < risk_settings.bybit_mt5_net_asset:
                                    await risk_alert_service.check_bybit_net_asset(
                                        user_id=user_id,
                                        current_asset=bybit_asset,
                                        threshold=risk_settings.bybit_mt5_net_asset,
                                        is_below=True
                                    )
                            else:
                                logger.warning(f"[BROADCAST] user={user_id} bybit/mt5 阈值已配置(={risk_settings.bybit_mt5_net_asset}) 但聚合数据中未找到对冲账户,告警无法触发")"""

new_check_bybit = """                        # Check Bybit net asset
                        if risk_settings.bybit_mt5_net_asset:
                            _hedge_failed = any(pid in _failed_platforms for pid in HEDGE_SIDE_IDS)
                            if _hedge_failed:
                                logger.info(f"[BROADCAST] user={user_id} skipping bybit_net_asset alert — hedge-side data fetch failed")
                            else:
                                # Find Bybit/MT5-hedge account in the aggregated data
                                bybit_account = next(
                                    (acc for acc in aggregated_data.get("accounts", [])
                                     if (PlatformId.from_key(acc.get("platform_id")) or 0) in HEDGE_SIDE_IDS),
                                    None
                                )
                                if bybit_account:
                                    bybit_asset = bybit_account["balance"]["net_assets"]
                                    logger.info(f"[BROADCAST] Checking bybit/mt5 net_assets: user_id={user_id}, bybit={bybit_asset}, threshold={risk_settings.bybit_mt5_net_asset}")
                                    if bybit_asset < risk_settings.bybit_mt5_net_asset:
                                        await risk_alert_service.check_bybit_net_asset(
                                            user_id=user_id,
                                            current_asset=bybit_asset,
                                            threshold=risk_settings.bybit_mt5_net_asset,
                                            is_below=True
                                        )
                                else:
                                    logger.warning(f"[BROADCAST] user={user_id} bybit/mt5 阈值已配置(={risk_settings.bybit_mt5_net_asset}) 但聚合数据中未找到对冲账户,告警无法触发")"""

assert old_check_bybit in b, "check_bybit anchor not found"
b = b.replace(old_check_bybit, new_check_bybit, 1)

# 2c. Skip total_net_asset alert when ANY platform failed (total would be understated)
old_check_total = """                        # Check total net asset
                        if risk_settings.total_net_asset:
                            # Use net_assets from summary (this is the correct key)
                            total_asset = summary.get("net_assets", 0)
                            logger.info(f"[BROADCAST] Checking total net_assets: user_id={user_id}, total={total_asset}, threshold={risk_settings.total_net_asset}")
                            if total_asset < risk_settings.total_net_asset:
                                logger.info(f"[BROADCAST] Total asset below threshold, triggering alert")
                                await risk_alert_service.check_total_net_asset(
                                    user_id=user_id,
                                    current_asset=total_asset,
                                    threshold=risk_settings.total_net_asset,
                                    is_below=True
                                )"""

new_check_total = """                        # Check total net asset
                        if risk_settings.total_net_asset:
                            if _failed_platforms:
                                logger.info(f"[BROADCAST] user={user_id} skipping total_net_asset alert — partial data (failed platforms={_failed_platforms})")
                            else:
                                # Use net_assets from summary (this is the correct key)
                                total_asset = summary.get("net_assets", 0)
                                logger.info(f"[BROADCAST] Checking total net_assets: user_id={user_id}, total={total_asset}, threshold={risk_settings.total_net_asset}")
                                if total_asset < risk_settings.total_net_asset:
                                    logger.info(f"[BROADCAST] Total asset below threshold, triggering alert")
                                    await risk_alert_service.check_total_net_asset(
                                        user_id=user_id,
                                        current_asset=total_asset,
                                        threshold=risk_settings.total_net_asset,
                                        is_below=True
                                    )"""

assert old_check_total in b, "check_total anchor not found"
b = b.replace(old_check_total, new_check_total, 1)

with open(path2, "w") as f:
    f.write(b)
print("broadcast_tasks.py: risk alerts now skip failed-platform accounts")


# ============================================================
# Fix 3: account_service.py — extend cache TTL for last-known-good
# When get_account_data fails, return stale cache instead of propagating
# the error to the frontend (which shows 0.00)
# ============================================================
with open(path, "r") as f:
    c = f.read()

old_get_account_data_cache = """    async def get_account_data(
        self,
        account: Account,
    ) -> Dict[str, Any]:
        \"\"\"Get comprehensive account data for a single account with caching\"\"\"
        platform_id = account.platform_id
        account_id_str = str(account.account_id)

        # Check cache first
        cache_key = self._get_cache_key(account_id_str, "account_data")
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            logger.debug(f"Returning cached account data for {account_id_str}")
            return cached_data"""

new_get_account_data_cache = """    async def get_account_data(
        self,
        account: Account,
    ) -> Dict[str, Any]:
        \"\"\"Get comprehensive account data for a single account with caching\"\"\"
        platform_id = account.platform_id
        account_id_str = str(account.account_id)

        # Check cache first
        cache_key = self._get_cache_key(account_id_str, "account_data")
        cached_data = self._get_cached_data(cache_key)
        if cached_data:
            logger.debug(f"Returning cached account data for {account_id_str}")
            return cached_data"""

# Now we need to add stale-cache fallback at the end of get_account_data's except block.
# Find the cache-set + return pattern and the outer except, and add stale fallback.
# The pattern we need is in the outer try/except of get_account_data.
# Let me find it differently — wrap the raise in the except with stale cache check.

# Actually, the better approach: in get_aggregated_account_data, when an account
# fetch fails, try to use stale cached data instead of putting it in failed_accounts.

old_failed_append = """        for i, data in enumerate(account_data_list):
            if isinstance(data, Exception):
                error_msg = str(data)
                # Check if it's a rate limit ban with timestamp
                if error_msg.startswith("RATE_LIMIT_BAN:"):
                    ban_until_ms = error_msg.split(":")[1]
                    error_msg = f"RATE_LIMIT:{ban_until_ms}"

                failed_accounts.append({
                    "account_id": str(unique_accounts[i].account_id),
                    "account_name": unique_accounts[i].account_name,
                    "platform_id": unique_accounts[i].platform_id,
                    "is_mt5_account": unique_accounts[i].is_mt5_account,
                    "is_active": unique_accounts[i].is_active,  # Include is_active status
                    "account_role": getattr(unique_accounts[i], 'account_role', None),
                    "proxy_config": unique_accounts[i].proxy_config,
                    "error": error_msg,
                })
            else:
                successful_accounts.append(data)"""

new_failed_append = """        for i, data in enumerate(account_data_list):
            if isinstance(data, Exception):
                error_msg = str(data)
                # Check if it's a rate limit ban with timestamp
                if error_msg.startswith("RATE_LIMIT_BAN:"):
                    ban_until_ms = error_msg.split(":")[1]
                    error_msg = f"RATE_LIMIT:{ban_until_ms}"

                # Stale-cache fallback: if we have a previous good result for this
                # account (even if TTL expired), use it instead of reporting failure.
                # This prevents proxy flickers from pushing zero-value data to
                # the frontend and triggering false risk alerts.
                _stale_key = self._get_cache_key(str(unique_accounts[i].account_id), "account_data")
                _stale = self._cache.get(_stale_key)
                if _stale and not error_msg.startswith("RATE_LIMIT"):
                    _stale_data, _stale_ts = _stale
                    _stale_age = (datetime.utcnow() - _stale_ts).total_seconds()
                    if _stale_age < 300:  # accept stale data up to 5 minutes
                        logger.warning(
                            f"[STALE_CACHE] Account {unique_accounts[i].account_name} fetch failed "
                            f"({error_msg[:80]}), using {_stale_age:.0f}s stale cache"
                        )
                        _stale_data["_stale"] = True
                        _stale_data["_stale_age_s"] = round(_stale_age)
                        successful_accounts.append(_stale_data)
                        continue

                failed_accounts.append({
                    "account_id": str(unique_accounts[i].account_id),
                    "account_name": unique_accounts[i].account_name,
                    "platform_id": unique_accounts[i].platform_id,
                    "is_mt5_account": unique_accounts[i].is_mt5_account,
                    "is_active": unique_accounts[i].is_active,  # Include is_active status
                    "account_role": getattr(unique_accounts[i], 'account_role', None),
                    "proxy_config": unique_accounts[i].proxy_config,
                    "error": error_msg,
                })
            else:
                successful_accounts.append(data)"""

assert old_failed_append in c, "failed_append anchor not found in account_service.py"
c = c.replace(old_failed_append, new_failed_append, 1)

with open(path, "w") as f:
    f.write(c)
print("account_service.py: added stale-cache fallback (5min) for failed fetches")

print("\n=== All fixes applied ===")
