#!/usr/bin/env python3
"""
Canary: measure the TWO facts that decide whether the "IOC OTOCO borrow trick" is
worth adopting, on a LIVE Binance cross-margin account, with tiny amounts.

  Q1  How much UID weight does a MARGIN_BUY-triggered borrow (order channel) cost,
      vs a direct /margin/borrow-repay (known ~1500, the 2-per-sec cap)?
        order-channel << 1500  -> it BYPASSES the borrow cap (the trick is real)
        order-channel ~= 1500   -> no bypass; the trick is just a complicated borrow
  Q2  With autoRepayAtCancel=false, does the borrowed coin STAY after the IOC cancels?

Tests (each self-cleaning — polls for settlement then repays what it borrowed):
  A  control : direct /margin/borrow-repay           -> the ~1500 reference (absolute)
  B  isolate : single MARGIN_BUY IOC limit-sell @1.5x -> Q1 (order-channel weight) + Q2
  C  faithful: full 3-leg IOC OTOCO as observed       -> confirms the real technique

CLEAN WEIGHT MEASUREMENT
  X-SAPI-USED-UID-WEIGHT-1M is a rolling-1-minute cumulative counter and only appears
  on UID-weighted calls (borrow/repay/order). We drain the window once (65s of no UID
  calls) so Test A's borrow reads its weight ABSOLUTELY; thereafter every UID call's
  header is captured and we report consecutive deltas (the IP-weighted balance polls
  in between do not touch the UID counter).

SAFETY
  * DRY-RUN by default; needs --arm to place orders.
  * Tiny fixed notional (default 8 USDT), NEVER maxBorrowable; capped by --max-notional.
  * Hard-stops --arm if maxBorrowable < needed.
  * Polls for settlement before repaying, and repays in a finally — a borrow is never
    left unpaid even on error.
  * Run via run_canary.sh so the engine is paused (clean counter) and always restarted.

USAGE
  ./run_canary.sh --account hustle-011                       # dry run
  ./run_canary.sh --arm --account hustle-011 --notional 8    # fire A+B+C
"""
import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from decimal import Decimal, ROUND_DOWN, ROUND_UP

SPOT_BASE = "https://api.binance.com"
RECV_WINDOW = 5000
DRAIN_SEC = 65  # > the 1-minute rolling window, so the UID counter resets to ~0

API_KEY = os.environ.get("BINANCE_API_KEY", "")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

_last_uid_weight = None  # refreshed from every UID-weighted SAPI response header


# ----------------------------- HTTP / signing -----------------------------

def _sign(params: dict) -> str:
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = RECV_WINDOW
    query = urllib.parse.urlencode(params)
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return query + "&signature=" + sig


def _capture_weight(headers) -> None:
    global _last_uid_weight
    u = headers.get("X-SAPI-USED-UID-WEIGHT-1M") or headers.get("x-sapi-used-uid-weight-1m")
    if u is not None:
        _last_uid_weight = int(u)


def public_get(path: str, params: dict) -> dict:
    url = f"{SPOT_BASE}{path}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=15) as r:
        return json.loads(r.read())


def signed(method: str, path: str, params: dict | None = None) -> dict:
    params = dict(params or {})
    query = _sign(params)
    url = f"{SPOT_BASE}{path}?{query}"
    req = urllib.request.Request(url, method=method, headers={"X-MBX-APIKEY": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            _capture_weight(r.headers)
            body = r.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        _capture_weight(e.headers)
        err = e.read().decode(errors="replace")
        raise RuntimeError(f"HTTP {e.code} {method} {path} -> {err}") from None


def load_account_from_db(identifier: str) -> dict:
    """Load a sub-account's api_key/api_secret from the project DB by note OR email.
    SubAccount.api_key/api_secret are plaintext String columns (engine reads them
    directly), so no decryption / CEX_ENCRYPTION_KEY is needed."""
    here = os.path.dirname(os.path.abspath(__file__))
    proj_root = os.path.dirname(here)
    if proj_root not in sys.path:
        sys.path.insert(0, proj_root)
    from app.db.session import SessionLocal
    from app.db.models import SubAccount
    db = SessionLocal()
    try:
        acc = (db.query(SubAccount)
               .filter((SubAccount.note == identifier) | (SubAccount.email == identifier))
               .first())
        if not acc:
            raise SystemExit(f"ERROR: sub-account '{identifier}' not found by note or email.")
        return {"id": acc.id, "note": acc.note, "email": acc.email,
                "api_key": acc.api_key, "api_secret": acc.api_secret,
                "margin_enabled": acc.margin_enabled, "is_enabled": acc.is_enabled}
    finally:
        db.close()


# ----------------------------- filters / rounding -----------------------------

def round_step(v: Decimal, step: Decimal, up: bool = False) -> Decimal:
    """Round v DOWN (or up) to a MULTIPLE of step. (Decimal.quantize is wrong here:
    a tickSize string like '0.00100000' has exponent -8, so quantize rounds to 8 dp
    instead of to 0.001 multiples — which is what caused the PRICE_FILTER reject.)"""
    if step <= 0:
        return v
    n = (v / step).to_integral_value(rounding=ROUND_UP if up else ROUND_DOWN)
    return n * step


def get_filters(symbol: str) -> dict:
    info = public_get("/api/v3/exchangeInfo", {"symbol": symbol})
    s = info["symbols"][0]
    f = {flt["filterType"]: flt for flt in s["filters"]}
    pct = f.get("PERCENT_PRICE_BY_SIDE", {})
    notf = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
    return {
        "tick": Decimal(f["PRICE_FILTER"]["tickSize"]),
        "max_price": Decimal(f["PRICE_FILTER"]["maxPrice"]),
        "step": Decimal(f["LOT_SIZE"]["stepSize"]),
        "min_qty": Decimal(f["LOT_SIZE"]["minQty"]),
        "min_notional": Decimal(notf.get("minNotional", notf.get("notional", "5"))),
        "ask_mult_up": Decimal(pct["askMultiplierUp"]) if pct.get("askMultiplierUp") else None,
        "base": s["baseAsset"], "quote": s["quoteAsset"],
    }


def compute_sell_px(bid: Decimal, last: Decimal, f: dict) -> Decimal:
    """A sell price ~1.5x that PASSES the filters and is strictly above the bid so the
    IOC limit-sell never fills (it only exists to carry the MARGIN_BUY borrow)."""
    cap = bid * Decimal("1.5")
    if f["ask_mult_up"]:
        cap = min(cap, last * f["ask_mult_up"])
    cap = min(cap, f["max_price"])
    px = round_step(cap, f["tick"], up=False)
    if px <= bid:  # keep it un-fillable
        px = round_step(bid + f["tick"], f["tick"], up=True) + f["tick"]
    return px


# ----------------------------- account helpers -----------------------------

def margin_fil(asset: str) -> dict:
    m = signed("GET", "/sapi/v1/margin/account")  # IP-weighted: does NOT move UID counter
    for a in m.get("userAssets", []):
        if a["asset"] == asset:
            return {"free": Decimal(a["free"]), "locked": Decimal(a["locked"]),
                    "borrowed": Decimal(a["borrowed"]), "interest": Decimal(a.get("interest", "0"))}
    return {"free": Decimal(0), "locked": Decimal(0), "borrowed": Decimal(0), "interest": Decimal(0)}


def poll_free(asset: str, want: Decimal, timeout: float = 8.0) -> dict:
    """Wait for the margin wallet to reflect a just-borrowed amount (settlement lag)."""
    deadline = time.monotonic() + timeout
    a = margin_fil(asset)
    while a["free"] < want and time.monotonic() < deadline:
        time.sleep(0.8)
        a = margin_fil(asset)
    return a


def cancel_open(symbol: str) -> None:
    try:
        oo = signed("GET", "/sapi/v1/margin/openOrders", {"symbol": symbol, "isIsolated": "FALSE"})
        if oo:
            print(f"  [cleanup] cancelling {len(oo)} open order(s)")
            signed("DELETE", "/sapi/v1/margin/openOrders", {"symbol": symbol, "isIsolated": "FALSE"})
    except Exception as e:
        print(f"  [cleanup] cancel warning: {e}")


def repay_debt(asset: str) -> None:
    """Poll for settlement, then repay the full outstanding debt (capped by holdings).
    Never raises — dust interest (no coin to pay it) is left for the engine's sweeper."""
    try:
        a = margin_fil(asset)
        debt = a["borrowed"] + a["interest"]
        if debt <= 0:
            print(f"  [cleanup] no {asset} debt")
            return
        if debt < Decimal("0.001"):  # dust interest, not worth (or possible) to repay
            print(f"  [cleanup] {asset} debt {debt} is dust — leaving for engine sweep")
            return
        a = poll_free(asset, debt)  # wait for borrowed coin to land before repaying
        amount = min(debt, a["free"])
        if amount <= 0:
            print(f"  [cleanup] !! {asset} debt={debt} but free={a['free']} after wait — REPAY MANUALLY")
            return
        print(f"  [cleanup] repaying {amount} {asset} (debt={debt})")
        signed("POST", "/sapi/v1/margin/borrow-repay",
               {"asset": asset, "amount": str(amount), "type": "REPAY", "isIsolated": "FALSE"})
        res = margin_fil(asset)
        print(f"  [cleanup] residual {asset} debt={res['borrowed'] + res['interest']} (dust ok)")
    except Exception as e:
        print(f"  [cleanup] repay warning: {e}")


def drain(label: str) -> None:
    print(f"  [drain] sleeping {DRAIN_SEC}s so the UID-weight window resets ({label})...")
    time.sleep(DRAIN_SEC)


# ----------------------------- tests -----------------------------

def test_A(asset: str, qty: Decimal) -> None:
    print("\n=== TEST A — control: direct /margin/borrow-repay (the ~1500 reference) ===")
    try:
        signed("POST", "/sapi/v1/margin/borrow-repay",
               {"asset": asset, "amount": str(qty), "type": "BORROW", "isIsolated": "FALSE"})
        # window was drained → this header IS the absolute weight of one direct borrow
        print(f"  >>> DIRECT BORROW weight (absolute, window drained) = {_last_uid_weight}")
        a = poll_free(asset, qty)
        print(f"  {asset}: free={a['free']} borrowed={a['borrowed']}")
    finally:
        repay_debt(asset)


def test_B(symbol: str, asset: str, qty: Decimal, sell_px: Decimal) -> None:
    print("\n=== TEST B — single MARGIN_BUY IOC limit-sell @1.5x (Q1 weight + Q2 stays) ===")
    try:
        resp = signed("POST", "/sapi/v1/margin/order", {
            "symbol": symbol, "side": "SELL", "type": "LIMIT", "timeInForce": "IOC",
            "quantity": str(qty), "price": str(sell_px),
            "sideEffectType": "MARGIN_BUY", "autoRepayAtCancel": "false",
            "isIsolated": "FALSE", "newOrderRespType": "FULL",
        })
        print(f"  order status={resp.get('status')} executedQty={resp.get('executedQty')} @ {sell_px}")
        print(f"  >>> MARGIN_BUY ORDER weight (absolute, window drained) = {_last_uid_weight}")
        print(f"      (compare to DIRECT BORROW=1500: if ~6 ⇒ borrow via order channel bypasses the 2/s cap)")
        a = margin_fil(asset)
        stayed = a["borrowed"] > 0
        print(f"  >>> {asset} after IOC-cancel: free={a['free']} borrowed={a['borrowed']}")
        print(f"      Q2: coin {'STAYED borrowed (trick works)' if stayed else 'was AUTO-REPAID (needs autoRepayAtCancel handling)'}")
    finally:
        cancel_open(symbol)
        repay_debt(asset)


def test_C(symbol: str, asset: str, qty: Decimal, sell_px: Decimal, f: dict) -> None:
    print("\n=== TEST C — faithful IOC OTOCO (3-leg; total weight + Q2) ===")
    sl = round_step(sell_px * Decimal("1.05"), f["tick"])    # STOP_LOSS_LIMIT buy: stop=limit
    tp = round_step(sell_px * Decimal("0.933"), f["tick"])   # LIMIT_MAKER buy
    print(f"  legs: SELL@{sell_px}  STOP_LOSS@{sl}  LIMIT_MAKER@{tp}  qty={qty}")
    try:
        resp = signed("POST", "/sapi/v1/margin/order/otoco", {
            "symbol": symbol, "isIsolated": "FALSE",
            "sideEffectType": "MARGIN_BUY", "autoRepayAtCancel": "false",
            "workingType": "LIMIT", "workingSide": "SELL",
            "workingPrice": str(sell_px), "workingQuantity": str(qty), "workingTimeInForce": "IOC",
            "pendingSide": "BUY", "pendingQuantity": str(qty),
            "pendingAboveType": "STOP_LOSS_LIMIT", "pendingAboveStopPrice": str(sl),
            "pendingAbovePrice": str(sl), "pendingAboveTimeInForce": "GTC",
            "pendingBelowType": "LIMIT_MAKER", "pendingBelowPrice": str(tp),
            "newOrderRespType": "FULL",
        })
        st = [o.get("status") for o in resp.get("orderReports", resp.get("orders", []))]
        print(f"  order-list statuses: {st}")
        print(f"  >>> OTOCO total weight (absolute, window drained) = {_last_uid_weight}")
        a = margin_fil(asset)
        print(f"  >>> {asset} after OTOCO-cancel: free={a['free']} borrowed={a['borrowed']}")
        print(f"      coin {'STAYED borrowed' if a['borrowed'] > 0 else 'was AUTO-REPAID'}")
    except RuntimeError as e:
        print(f"  OTOCO REJECTED: {e}")
    finally:
        cancel_open(symbol)
        repay_debt(asset)


# ----------------------------- main -----------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default=None, help="DB sub-account note or email (e.g. hustle-011)")
    ap.add_argument("--arm", action="store_true", help="actually place orders (default: dry run)")
    ap.add_argument("--symbol", default="FILUSDT")
    ap.add_argument("--notional", type=Decimal, default=Decimal("8"))
    ap.add_argument("--max-notional", type=Decimal, default=Decimal("50"))
    ap.add_argument("--tests", default="A,B,C")
    args = ap.parse_args()

    global API_KEY, API_SECRET
    if args.account:
        info = load_account_from_db(args.account)
        API_KEY, API_SECRET = info["api_key"], info["api_secret"]
        print(f"[db] sub-account id={info['id']} note={info['note']} email={info['email']} "
              f"margin_enabled={info['margin_enabled']} is_enabled={info['is_enabled']}")
        if not info["margin_enabled"]:
            print("WARNING: margin_enabled=False — borrow will likely be rejected.")
    if not API_KEY or not API_SECRET:
        print("ERROR: pass --account <note|email>, or set BINANCE_API_KEY and BINANCE_API_SECRET.")
        return 2
    if args.notional > args.max_notional:
        print(f"ERROR: notional {args.notional} exceeds cap {args.max_notional}.")
        return 2

    symbol = args.symbol.upper()
    f = get_filters(symbol)
    asset = f["base"]
    book = public_get("/api/v3/ticker/bookTicker", {"symbol": symbol})
    last = Decimal(public_get("/api/v3/ticker/price", {"symbol": symbol})["price"])
    bid = Decimal(book["bidPrice"])
    sell_px = compute_sell_px(bid, last, f)

    qty = round_step(args.notional / sell_px, f["step"])
    if qty < f["min_qty"]:
        qty = round_step(f["min_qty"], f["step"], up=True)
    if qty * sell_px < f["min_notional"]:
        qty = round_step(f["min_notional"] / sell_px, f["step"], up=True)

    print("=" * 72)
    print(f"symbol={symbol} asset={asset} bid={bid} last={last} tick={f['tick']} step={f['step']}")
    print(f"sell_px(~1.5x, filter-valid)={sell_px}  qty={qty}  ~notional={qty * sell_px}")
    print(f"mode={'ARMED — REAL ORDERS' if args.arm else 'DRY RUN'}  tests={args.tests}")
    print("=" * 72)

    max_borrowable = Decimal(0)
    try:
        mb = signed("GET", "/sapi/v1/margin/maxBorrowable", {"asset": asset})
        max_borrowable = Decimal(str(mb.get("amount", "0")))
    except Exception as e:
        print(f"preflight warning (maxBorrowable): {e}")
    a0 = margin_fil(asset)
    print(f"maxBorrowable {asset}={max_borrowable} (need {qty})   current free={a0['free']} borrowed={a0['borrowed']}")

    if qty <= 0:
        print("ERROR: computed qty <= 0.")
        return 2
    capacity_ok = max_borrowable >= qty
    if not capacity_ok:
        print(f"\n!! maxBorrowable {asset}={max_borrowable} < {qty}: no borrow capacity — fund cross-margin first.")

    if not args.arm:
        print("\nDRY RUN — re-run with --arm to fire. (No orders placed.)")
        return 0
    if not capacity_ok:
        print("ABORT: refusing to --arm without borrow capacity.")
        return 2

    tests = [t.strip().upper() for t in args.tests.split(",") if t.strip()]
    try:
        if "A" in tests:
            drain("before Test A")
            test_A(asset, qty)
        if "B" in tests:
            drain("before Test B")
            test_B(symbol, asset, qty, sell_px)
        if "C" in tests:
            drain("before Test C")
            test_C(symbol, asset, qty, sell_px, f)
    finally:
        print("\n=== FINAL SWEEP ===")
        cancel_open(symbol)
        repay_debt(asset)
        fin = margin_fil(asset)
        print(f"final {asset}: free={fin['free']} borrowed={fin['borrowed']} interest={fin['interest']}")

    print("\nDONE. Compare:  DIRECT BORROW weight (Test A)  vs  MARGIN_BUY ORDER weight (Test B).")
    print("  Test B << Test A  => the OTOCO borrow trick beats the 2/s cap (worth porting).")
    print("  Test B ~= Test A  => no bypass; keep plain borrow-repay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
