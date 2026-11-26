"""Fail-closed live execution adapter and settlement state machine.

The Paper engine is intentionally usable without this module being enabled.
Live trading requires an explicit capability manifest and a successful
preflight.  This module does not pretend that Gamma resolution is a payout or
that a CLOB order response is a chain settlement.  Those integrations are
injected behind small interfaces so they can be tested with fakes before any
real order is allowed.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Protocol

from btc5m.config import Config
from btc5m.orders import OrderResult, place_buy_fok, place_sell_fok_then_fak


class LiveExecutionNotReady(RuntimeError):
    """Raised when live execution is not explicitly enabled and ready."""


class LifecycleState(str, Enum):
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    REJECTED = "rejected"
    UNKNOWN = "unknown"
    EXIT_PENDING = "exit_pending"
    EXITED = "exited"


class SettlementState(str, Enum):
    OPEN = "open"
    RESOLUTION_PENDING = "resolution_pending"
    PAYOUT_PENDING = "payout_pending"
    REDEEM_PENDING = "redeem_pending"
    REDEEM_SUBMITTED = "redeem_submitted"
    REDEEM_CONFIRMED = "redeem_confirmed"
    RECONCILE_PENDING = "reconcile_pending"
    COMPLETE = "complete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CapabilityManifest:
    """Capabilities that must be proved before a real order is allowed.

    All fields default to False on purpose.  A manifest is data, not a secret;
    it records which independently tested integrations are available.  The
    default object therefore always fails closed.
    """

    buy_fok: bool = False
    sell_fok: bool = False
    sell_fak: bool = False
    actual_fills: bool = False
    settlement_oracle: bool = False
    redeem: bool = False
    reconcile: bool = False
    wallet: bool = False
    source: str = "disabled"

    @property
    def ready(self) -> bool:
        return all(
            (
                self.buy_fok,
                self.sell_fok,
                self.sell_fak,
                self.actual_fills,
                self.settlement_oracle,
                self.redeem,
                self.reconcile,
                self.wallet,
            )
        )

    @property
    def missing(self) -> tuple[str, ...]:
        names = (
            "buy_fok",
            "sell_fok",
            "sell_fak",
            "actual_fills",
            "settlement_oracle",
            "redeem",
            "reconcile",
            "wallet",
        )
        return tuple(name for name in names if not getattr(self, name))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], *, source: str = "mapping") -> "CapabilityManifest":
        # Capability files are an authorization boundary.  Do not coerce
        # strings such as "false" to True (Python's bool("false") is True).
        # A malformed or hand-edited manifest must fail closed.
        def strict_bool(name: str) -> bool:
            value = payload.get(name, False)
            if not isinstance(value, bool):
                raise ValueError(f"capability {name} must be a JSON boolean")
            return value

        return cls(
            buy_fok=strict_bool("buy_fok"),
            sell_fok=strict_bool("sell_fok"),
            sell_fak=strict_bool("sell_fak"),
            actual_fills=strict_bool("actual_fills"),
            settlement_oracle=strict_bool("settlement_oracle"),
            redeem=strict_bool("redeem"),
            reconcile=strict_bool("reconcile"),
            wallet=strict_bool("wallet"),
            source=source,
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "CapabilityManifest":
        p = Path(path)
        payload = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("live capability manifest must be a JSON object")
        return cls.from_mapping(payload, source=str(p))


@dataclass(frozen=True)
class ExecutionReceipt:
    order: OrderResult
    state: LifecycleState
    side: str
    requested_size: float
    filled_size: float
    avg_price: Optional[float]
    notional_usd: Optional[float]
    fee_usd: Optional[float]
    source: str = "clob_response"


@dataclass
class SettlementWorkflow:
    """Explicit settlement/redeem/reconcile state machine.

    Methods only advance after evidence from the corresponding adapter is
    supplied.  In particular, an official Gamma result alone cannot complete a
    live workflow and no local PnL should be booked at that point.
    """

    market_slug: str
    condition_id: str
    state: SettlementState = SettlementState.OPEN
    winner: Optional[str] = None
    resolution_source: Optional[str] = None
    payout_tx_hash: Optional[str] = None
    redeem_tx_hash: Optional[str] = None
    confirmed_block: Optional[int] = None
    cash_reconciled: bool = False
    positions_reconciled: bool = False
    last_error: Optional[str] = None
    updated_ts: float = field(default_factory=time.time)

    def _set(self, state: SettlementState) -> None:
        self.state = state
        self.updated_ts = time.time()

    def begin_resolution(self) -> None:
        if self.state not in {SettlementState.OPEN, SettlementState.RESOLUTION_PENDING}:
            raise LiveExecutionNotReady(f"cannot resolve from state={self.state.value}")
        self._set(SettlementState.RESOLUTION_PENDING)

    def record_resolution(self, winner: str, *, source: str, payout_tx_hash: Optional[str] = None) -> None:
        # Gamma is useful for Paper display but is not proof of a live payout.
        if self.state != SettlementState.RESOLUTION_PENDING:
            raise LiveExecutionNotReady(
                f"resolution evidence requires RESOLUTION_PENDING, got {self.state.value}"
            )
        if source not in {"chain", "ctf", "official_chain"}:
            self.block(f"untrusted resolution source: {source}")
            raise LiveExecutionNotReady("live resolution requires chain/CTF evidence")
        if not payout_tx_hash:
            self.block("chain resolution requires payout transaction hash")
            raise LiveExecutionNotReady("live resolution requires payout transaction hash")
        if winner.upper() not in {"UP", "DOWN"}:
            raise ValueError("winner must be UP or DOWN")
        self.winner = winner.upper()
        self.resolution_source = source
        self.payout_tx_hash = payout_tx_hash
        self._set(SettlementState.PAYOUT_PENDING)

    def mark_redeem_pending(self) -> None:
        if self.state != SettlementState.PAYOUT_PENDING:
            raise LiveExecutionNotReady(f"cannot redeem from state={self.state.value}")
        self._set(SettlementState.REDEEM_PENDING)

    def mark_redeem_submitted(self, tx_hash: str) -> None:
        if self.state != SettlementState.REDEEM_PENDING or not tx_hash:
            raise LiveExecutionNotReady("redeem submission requires pending state and tx hash")
        self.redeem_tx_hash = tx_hash
        self._set(SettlementState.REDEEM_SUBMITTED)

    def mark_redeem_confirmed(self, block_number: int) -> None:
        if self.state != SettlementState.REDEEM_SUBMITTED:
            raise LiveExecutionNotReady(f"cannot confirm redeem from state={self.state.value}")
        if int(block_number) <= 0:
            raise ValueError("confirmed block must be positive")
        self.confirmed_block = int(block_number)
        self._set(SettlementState.REDEEM_CONFIRMED)

    def mark_reconcile_pending(self) -> None:
        if self.state != SettlementState.REDEEM_CONFIRMED:
            raise LiveExecutionNotReady(f"cannot reconcile from state={self.state.value}")
        self._set(SettlementState.RECONCILE_PENDING)

    def mark_reconciled(self, *, cash: bool, positions: bool) -> None:
        if self.state != SettlementState.RECONCILE_PENDING:
            raise LiveExecutionNotReady(f"cannot complete from state={self.state.value}")
        self.cash_reconciled = bool(cash)
        self.positions_reconciled = bool(positions)
        if not (self.cash_reconciled and self.positions_reconciled):
            self.block("cash/position reconciliation failed")
            return
        self._set(SettlementState.COMPLETE)

    def block(self, reason: str) -> None:
        self.last_error = reason
        self._set(SettlementState.BLOCKED)


class Redeemer(Protocol):
    def submit(self, *, condition_id: str, winner: str) -> str: ...

    def receipt(self, tx_hash: str) -> Optional[int]: ...


class Reconciler(Protocol):
    def reconcile(self, *, condition_id: str, redeem_tx_hash: str) -> tuple[bool, bool]: ...


class LiveExecutionAdapter:
    """Live CLOB adapter that refuses incomplete execution capabilities."""

    def __init__(
        self,
        client: Any,
        cfg: Config,
        *,
        manifest: Optional[CapabilityManifest] = None,
        redeemer: Optional[Redeemer] = None,
        reconciler: Optional[Reconciler] = None,
        event_sink: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ) -> None:
        self.client = client
        self.cfg = cfg
        self.manifest = manifest or CapabilityManifest()
        self.redeemer = redeemer
        self.reconciler = reconciler
        self.event_sink = event_sink

    def preflight(self) -> None:
        if not self.cfg.live_trading_enabled:
            raise LiveExecutionNotReady("LIVE_TRADING_ENABLED is false")
        if not getattr(self.cfg, "live_execution_ready", False):
            raise LiveExecutionNotReady("LIVE_EXECUTION_READY is false")
        if not self.manifest.ready:
            missing = ", ".join(self.manifest.missing)
            raise LiveExecutionNotReady(f"live capability manifest incomplete: {missing}")
        if self.redeemer is None:
            raise LiveExecutionNotReady("redeemer adapter is not wired")
        if self.reconciler is None:
            raise LiveExecutionNotReady("reconciler adapter is not wired")
        if self.client is None or not all(
            callable(getattr(self.client, name, None)) for name in ("create_order", "post_order")
        ):
            raise LiveExecutionNotReady("CLOB client does not expose create_order/post_order")
        if self.redeemer is None or self.reconciler is None:
            raise LiveExecutionNotReady("chain redeem/reconcile adapters are not configured")

    def _record(self, kind: str, payload: dict[str, Any]) -> None:
        if self.event_sink:
            self.event_sink(kind, payload)

    def buy(self, *, token_id: str, price: float, size: float, tick_size: float, neg_risk: bool) -> ExecutionReceipt:
        self.preflight()
        result = place_buy_fok(
            self.client,
            token_id=token_id,
            price=price,
            size=size,
            tick_size=tick_size,
            neg_risk=neg_risk,
        )
        state = _lifecycle_from_order(result)
        receipt = ExecutionReceipt(result, state, "BUY", float(size), result.filled_size, result.avg_price, result.notional_usd, result.fee_usd)
        self._record("live_execution", {"side": "BUY", "state": state.value, "order_id": result.order_id, "filled_size": result.filled_size})
        return receipt

    def exit(
        self,
        *,
        token_id: str,
        price: float,
        size: float,
        tick_size: float,
        neg_risk: bool,
    ) -> ExecutionReceipt:
        self.preflight()
        result = place_sell_fok_then_fak(
            self.client,
            token_id=token_id,
            price=price,
            size=size,
            tick_size=tick_size,
            neg_risk=neg_risk,
        )
        state = _lifecycle_from_order(result)
        receipt = ExecutionReceipt(result, state, "SELL", float(size), result.filled_size, result.avg_price, result.notional_usd, result.fee_usd)
        self._record("live_execution", {"side": "SELL", "state": state.value, "order_id": result.order_id, "filled_size": result.filled_size})
        return receipt

    def submit_redeem(self, workflow: SettlementWorkflow) -> str:
        self.preflight()
        if not self.manifest.redeem or self.redeemer is None:
            raise LiveExecutionNotReady("redeem adapter is not configured")
        workflow.mark_redeem_pending()
        tx_hash = self.redeemer.submit(condition_id=workflow.condition_id, winner=workflow.winner or "")
        workflow.mark_redeem_submitted(tx_hash)
        return tx_hash

    def confirm_and_reconcile(self, workflow: SettlementWorkflow) -> SettlementWorkflow:
        self.preflight()
        if not self.manifest.redeem or not self.manifest.reconcile:
            raise LiveExecutionNotReady("redeem/reconcile capabilities are not configured")
        if self.redeemer is None or self.reconciler is None:
            raise LiveExecutionNotReady("redeemer and reconciler adapters are required")
        block = self.redeemer.receipt(workflow.redeem_tx_hash or "")
        if block is None:
            return workflow
        workflow.mark_redeem_confirmed(int(block))
        workflow.mark_reconcile_pending()
        cash, positions = self.reconciler.reconcile(
            condition_id=workflow.condition_id,
            redeem_tx_hash=workflow.redeem_tx_hash or "",
        )
        workflow.mark_reconciled(cash=cash, positions=positions)
        return workflow


def _lifecycle_from_order(result: OrderResult) -> LifecycleState:
    if result.status == "filled":
        return LifecycleState.FILLED
    if result.status == "partial":
        return LifecycleState.PARTIAL
    if result.status == "rejected":
        return LifecycleState.REJECTED
    if result.status == "submitted":
        return LifecycleState.SUBMITTED
    return LifecycleState.UNKNOWN

