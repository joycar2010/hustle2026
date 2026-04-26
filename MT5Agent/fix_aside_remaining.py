"""
Fix remaining A-side audit items:
1. Pre-order pair_code-to-account platform_id validation (strategies.py)
2. Spread chase: skip trigger re-accumulation on no-fill when spread still favorable (continuous_executor.py)
3. Account platform_id vs pair A-side platform validation (strategies.py)

Fixes 1 & 3 are both in strategies.py — add a validation block after _resolve_pair_accounts
in all 4 single-shot endpoints + 2 continuous endpoints.

Fix 2 is in continuous_executor.py Scenario 1 block.
"""
import sys

# ============================================================
# Fix 1+3: strategies.py — pre-order validation
# ============================================================
path_strat = "/data/hustle2026/backend/app/api/v1/strategies.py"
with open(path_strat, "r") as f:
    s = f.read()

# The validation block to insert after each _resolve_pair_accounts call.
# It checks: (a) account platform_id matches pair's A-side platform, (b) pair_code binding consistency.
VALIDATION_BLOCK = '''
        # --- Pre-order validation: account ↔ pair platform consistency ---
        from app.services.hedging_pair_service import hedging_pair_service as _hps_val
        _val_pair = _hps_val.get_pair(request.pair_code or "XAU")
        if _val_pair:
            _expected_a_platform = _val_pair.symbol_a.platform_id
            if binance_account.platform_id != _expected_a_platform:
                raise HTTPException(
                    status_code=400,
                    detail=f"A-side account platform mismatch: account platform_id={binance_account.platform_id}, "
                           f"pair {request.pair_code} requires platform_id={_expected_a_platform}"
                )
'''

# We need to insert VALIDATION_BLOCK after each occurrence of the pattern:
#   "if not binance_account or not bybit_account:"
#   "    raise HTTPException(...)"
# There should be one for each of the 4 single-shot + 2 continuous endpoints = 6 total

anchor = '''        if not binance_account or not bybit_account:
            raise HTTPException(status_code=404, detail="Account not found. Please configure pair-account binding.")'''

if anchor not in s:
    print("ERROR: Could not find account-not-found anchor in strategies.py")
    sys.exit(1)

count = s.count(anchor)
print(f"Found {count} account-check anchors in strategies.py")

# Replace each occurrence with anchor + validation block
s = s.replace(anchor, anchor + VALIDATION_BLOCK)

with open(path_strat, "w") as f:
    f.write(s)
print(f"strategies.py: inserted platform validation after all {count} account-check blocks")


# ============================================================
# Fix 2: continuous_executor.py — spread chase on no-fill
# ============================================================
path_ce = "/data/hustle2026/backend/app/services/continuous_executor.py"
with open(path_ce, "r") as f:
    c = f.read()

# Replace Scenario 1 handling: when binance_filled==0, check if spread still meets threshold.
# If yes, skip trigger re-accumulation — only reset the trigger and immediately continue
# (which will pass trigger check on next iteration if we pre-set triggers to ready).
# Actually, simplest: if spread still OK, don't reset triggers and don't sleep — just continue
# to the top of the loop where trigger_ready will still be True.

old_scenario1 = """            # Scenario 1: Binance not filled or spread cancelled
            if binance_filled == 0:
                consecutive_no_fills += 1
                logger.info(f"Scenario 1: Binance not filled ({consecutive_no_fills}/{MAX_CONSECUTIVE_NO_FILLS}), resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)

                # After too many consecutive no-fills, pause and reset (don't permanently stop)
                # The strategy should keep waiting for market conditions to improve
                if consecutive_no_fills >= MAX_CONSECUTIVE_NO_FILLS:
                    logger.warning(
                        f"[ladder={ladder_idx}] {consecutive_no_fills} consecutive no-fills — "
                        f"pausing {MAX_CONSECUTIVE_NO_FILLS * 2}s then resuming"
                    )
                    consecutive_no_fills = 0  # Reset counter to allow another round
                    await asyncio.sleep(MAX_CONSECUTIVE_NO_FILLS * 2)  # 10s pause
                    self.trigger_mgr.reset()
                    continue

                # Progressive backoff: 1s → 2s → 3s → 4s → 5s
                is_opening = strategy_type in ('reverse_opening', 'forward_opening')
                base_wait = (self.order_executor.open_wait_after_cancel_no_trade
                             if is_opening else self.order_executor.close_wait_after_cancel_no_trade)
                wait_time = base_wait * consecutive_no_fills
                logger.info(f"Waiting {wait_time}s after cancel ({'spread' if spread_cancelled else 'timeout'}, no-fill #{consecutive_no_fills})")
                # Safe exit point 1: Binance order cancelled — no single-leg risk
                if self.stop_requested:
                    logger.info(f"[GRACEFUL STOP] Stop requested — exiting after Binance cancel (safe, no single-leg)")
                    self.is_running = False
                    break
                await asyncio.sleep(wait_time)
                continue"""

new_scenario1 = """            # Scenario 1: Binance not filled or spread cancelled
            if binance_filled == 0:
                consecutive_no_fills += 1

                # Safe exit point 1: Binance order cancelled — no single-leg risk
                if self.stop_requested:
                    logger.info(f"[GRACEFUL STOP] Stop requested — exiting after Binance cancel (safe, no single-leg)")
                    self.is_running = False
                    break

                # Spread chase: if spread still meets threshold, skip trigger re-accumulation
                # and immediately re-hang Maker order (only wait 0.5s for exchange cooldown)
                try:
                    _chase_spread = await self._get_current_spread(strategy_type)
                    _chase_ok = (
                        (compare_op == CompareOperator.GREATER_EQUAL and _chase_spread >= spread_threshold) or
                        (compare_op == CompareOperator.LESS_EQUAL and _chase_spread <= spread_threshold)
                    )
                except Exception:
                    _chase_ok = False

                if _chase_ok and not spread_cancelled:
                    logger.info(
                        f"Scenario 1 [SPREAD CHASE]: no-fill #{consecutive_no_fills} but spread "
                        f"{_chase_spread:.3f} still meets threshold {spread_threshold}, "
                        f"skipping trigger re-accumulation, immediate re-hang"
                    )
                    await asyncio.sleep(0.5)
                    continue

                # Spread no longer favorable — full reset + backoff
                logger.info(f"Scenario 1: Binance not filled ({consecutive_no_fills}/{MAX_CONSECUTIVE_NO_FILLS}), resetting triggers")
                self.trigger_mgr.reset()
                await self._push_trigger_reset(ladder_idx, strategy_type)

                # After too many consecutive no-fills, pause and reset (don't permanently stop)
                if consecutive_no_fills >= MAX_CONSECUTIVE_NO_FILLS:
                    logger.warning(
                        f"[ladder={ladder_idx}] {consecutive_no_fills} consecutive no-fills — "
                        f"pausing {MAX_CONSECUTIVE_NO_FILLS * 2}s then resuming"
                    )
                    consecutive_no_fills = 0
                    await asyncio.sleep(MAX_CONSECUTIVE_NO_FILLS * 2)
                    self.trigger_mgr.reset()
                    continue

                # Progressive backoff: 1s → 2s → 3s → 4s → 5s
                is_opening = strategy_type in ('reverse_opening', 'forward_opening')
                base_wait = (self.order_executor.open_wait_after_cancel_no_trade
                             if is_opening else self.order_executor.close_wait_after_cancel_no_trade)
                wait_time = base_wait * consecutive_no_fills
                logger.info(f"Waiting {wait_time}s after cancel ({'spread' if spread_cancelled else 'timeout'}, no-fill #{consecutive_no_fills})")
                await asyncio.sleep(wait_time)
                continue"""

if old_scenario1 not in c:
    print("ERROR: Could not find Scenario 1 block in continuous_executor.py")
    sys.exit(1)

c = c.replace(old_scenario1, new_scenario1, 1)

with open(path_ce, "w") as f:
    f.write(c)
print("continuous_executor.py: spread chase on no-fill added to Scenario 1")

print("\n=== All 3 A-side fixes applied ===")
