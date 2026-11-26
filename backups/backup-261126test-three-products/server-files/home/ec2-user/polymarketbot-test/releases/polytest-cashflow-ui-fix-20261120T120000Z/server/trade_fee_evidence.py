"""Read actual Exchange V2 fill fees; never estimate or allocate account totals.

Amounts in OrderFilled are the contract's six-decimal units.  ``maker`` is
the order owner, not the CLOB liquidity role: the role comes from authenticated
trade records.  A fill's fee is usable even when the liquidity role is unknown.
"""
from itertools import combinations
import json
import math


ORDER_FILLED_V2 = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"
SCALE = 1_000_000


def _address(value):
    value = str(value or "").lower()
    return "0x" + value[-40:] if len(value) >= 42 else value


def _units(value):
    try:
        number = float(value)
        return round(number * SCALE) if math.isfinite(number) and number >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def receipt_fee_evidence(receipt, wallet, allowed_exchanges=None):
    """Decode confirmed own-order fills from the official V2 Exchange ABI.

    Unknown versions, failed receipts and counterparty orders return no evidence.
    Use the exchange allowlist in production to reject lookalike event emitters.
    """
    if not isinstance(receipt, dict) or receipt.get("status") not in (1, "1", "0x1", "0x01"):
        return []
    wallet = _address(wallet)
    allowed = {_address(address) for address in allowed_exchanges} if allowed_exchanges is not None else None
    events, seen = [], set()
    for log in receipt.get("logs") or []:
        try:
            topics = log.get("topics") or []
            if len(topics) != 4 or str(topics[0]).lower() != ORDER_FILLED_V2:
                continue
            emitter = _address(log.get("address"))
            if allowed is not None and emitter not in allowed:
                continue
            maker, taker = _address(topics[2]), _address(topics[3])
            if maker != wallet:
                continue
            data = str(log.get("data") or "").removeprefix("0x")
            if len(data) != 7 * 64:
                continue
            words = [int(data[index:index + 64], 16) for index in range(0, len(data), 64)]
            side, token, maker_raw, taker_raw, fee_raw = words[:5]
            if side not in (0, 1):
                continue
            shares = taker_raw if side == 0 else maker_raw
            if shares <= 0:
                continue
            order_hash = str(topics[1]).lower()
            index = log.get("logIndex")
            index = int(index, 16) if isinstance(index, str) and index.startswith("0x") else int(index)
            event_key = (emitter, index)
            if event_key in seen:
                continue
            seen.add(event_key)
            events.append({
                "transaction_hash": str(receipt.get("transactionHash") or log.get("transactionHash") or "").lower(),
                "order_hash": order_hash, "token_id": str(token), "side": "BUY" if side == 0 else "SELL",
                "size": shares / SCALE, "size_raw": shares,
                "maker_amount_raw": maker_raw, "taker_amount_raw": taker_raw,
                "fee_raw": fee_raw, "fee_usd": -fee_raw / SCALE,
                "maker": maker, "taker": taker, "exchange": emitter,
                "log_index": index, "role": None,
                "fee_source": "polygon_order_filled", "fee_status": "confirmed",
            })
        except (TypeError, ValueError, OverflowError):
            continue
    return sorted(events, key=lambda item: item["log_index"])


def _key(activity):
    return json.dumps(activity, sort_keys=True, separators=(",", ":"), default=str)


def _group(activity):
    return (
        str(activity.get("transaction_hash") or activity.get("transactionHash") or activity.get("tx") or "").lower(),
        str(activity.get("token_id") or activity.get("tokenId") or activity.get("asset_id") or activity.get("asset") or ""),
        str(activity.get("side") or "").upper(),
    )


def _order_roles(trades, wallet):
    roles = {}
    for trade in trades or []:
        if not isinstance(trade, dict) or str(trade.get("status") or "").upper() not in ("CONFIRMED", "MINED", "MATCHED"):
            continue
        tx = str(trade.get("transaction_hash") or trade.get("transactionHash") or "").lower()
        if str(trade.get("trader_side") or "").upper() == "TAKER" and trade.get("taker_order_id"):
            roles[(tx, str(trade["taker_order_id"]).lower())] = "TAKER"
        for maker in trade.get("maker_orders") or []:
            if _address(maker.get("maker_address")) == wallet and maker.get("order_id"):
                roles[(tx, str(maker["order_id"]).lower())] = "MAKER"
    return roles


def activity_fee_evidence(activity, events, clob_trades, wallet, peer_activity=None):
    """Attach only a uniquely determined actual fee to this Activity record.

    Activity can aggregate fills, or contain several records in one transaction.
    Exact share-unit subsets are used, never cashflow/price arithmetic or a
    proportional allocation. Peers must be the complete same-transaction feed,
    not just the current UI page. Ambiguous partitions remain pending.
    """
    kind = str(activity.get("type") or activity.get("activity_type") or "").upper()
    if kind != "TRADE":
        if kind in ("REDEEM", "MERGE", "SPLIT"):
            return {"fee_usd": 0.0, "fee_raw": 0, "fee_status": "not_applicable", "fee_source": "non_trade_activity", "liquidity_role": None}
        return {"fee_status": "unavailable", "fee_source": None}
    group = _group(activity)
    fills = [event for event in events or [] if (
        str(event.get("transaction_hash") or "").lower(), str(event.get("token_id") or ""), str(event.get("side") or "").upper()
    ) == group]
    if not fills:
        return {"fee_status": "pending", "fee_source": None}
    peers = [peer for peer in (peer_activity if peer_activity is not None else [activity])
             if str(peer.get("type") or peer.get("activity_type") or "").upper() == "TRADE" and _group(peer) == group]
    # Discard exact cursor duplicates, preserving distinct same-tx fills.
    peers = list({_key(peer): peer for peer in peers}.values())
    target = next((index for index, peer in enumerate(peers) if _key(peer) == _key(activity)), None)
    if target is None:
        return {"fee_status": "pending", "fee_source": None}
    targets = [_units(peer.get("size")) for peer in peers]
    if any(value is None for value in targets) or len(fills) > 16 or len(peers) > 12:
        return {"fee_status": "ambiguous", "fee_source": None}
    # Require all fills/peers to reconcile; otherwise an unseen row could get
    # charged twice. A single-microshare tolerance handles decimal serialization.
    if abs(sum(targets) - sum(fill["size_raw"] for fill in fills)) > 1:
        return {"fee_status": "ambiguous", "fee_source": None}
    candidates = []
    for size in targets:
        options = []
        for count in range(1, len(fills) + 1):
            for indices in combinations(range(len(fills)), count):
                if abs(sum(fills[index]["size_raw"] for index in indices) - size) <= 1:
                    options.append(sum(1 << index for index in indices))
        if not options:
            return {"fee_status": "ambiguous", "fee_source": None}
        candidates.append(options)
    solutions, explored = [], [0]
    def search(index, used, choices):
        explored[0] += 1
        if explored[0] > 20000 or len(solutions) > 256:
            return
        if index == len(peers):
            if used == (1 << len(fills)) - 1:
                solutions.append(choices[target])
            return
        for option in candidates[index]:
            if option & used == 0:
                search(index + 1, used | option, choices + [option])
    search(0, 0, [])
    if not solutions or explored[0] > 20000 or len(solutions) > 256:
        return {"fee_status": "ambiguous", "fee_source": None}
    roles = _order_roles(clob_trades, _address(wallet))
    actual_fees, actual_roles, orders = set(), set(), set()
    for mask in set(solutions):
        selected = [fill for index, fill in enumerate(fills) if mask & (1 << index)]
        actual_fees.add(sum(fill["fee_raw"] for fill in selected))
        selected_roles = {roles.get((group[0], fill["order_hash"])) for fill in selected}
        actual_roles.add(next(iter(selected_roles)) if len(selected_roles) == 1 else None)
        orders.update(fill["order_hash"] for fill in selected)
    if len(actual_fees) != 1:
        return {"fee_status": "ambiguous", "fee_source": None}
    fee_raw = next(iter(actual_fees))
    role = next(iter(actual_roles)) if len(actual_roles) == 1 else None
    return {"fee_raw": fee_raw, "fee_usd": -fee_raw / SCALE,
            "fee_source": "polygon_order_filled", "fee_status": "confirmed",
            "liquidity_role": role, "fee_order_hashes": sorted(orders)}
