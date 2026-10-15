"""V3.87 first-Testnet-order safety boundary.

The first real Testnet mutation must be demonstrably non-marketable at the time
of submission. The policy therefore requires:

- TESTNET-only operator session already READY;
- LIMIT + GTC only;
- fresh bid/ask quote;
- side-aware non-marketable price proof;
- minimum price distance from the touch;
- hard notional ceiling;
- exactly one dispatch through the already-protected V3.86 boundary.

Observation/reconciliation is deliberately explicit. An acknowledgement alone is
not a completed Testnet run.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v35.binance_execution import RuntimeCredentialValues
from trading_platform.v386 import GateResultV386, OperatorSessionAuthorityV386, OperatorSessionStateV386
from trading_platform.v385.controlled_testnet_submit import ControlledSubmitResultV385


class FirstTestnetRunStateV387(str, Enum):
    PRECHECK = "PRECHECK"
    ARMED = "ARMED"
    SUBMITTED = "SUBMITTED"
    OBSERVING = "OBSERVING"
    RECONCILING = "RECONCILING"
    COMPLETE = "COMPLETE"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    HALTED = "HALTED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class QuoteSnapshotV387:
    symbol: str
    bid: Decimal
    ask: Decimal
    event_time: datetime
    source: str = "MARKET"

    def validate(self, *, now: datetime, max_age_s: float) -> None:
        if not self.symbol or self.symbol.upper() != self.symbol:
            raise PermissionError("QUOTE_SYMBOL_INVALID")
        if self.bid <= 0 or self.ask <= 0:
            raise PermissionError("QUOTE_NON_POSITIVE")
        if self.bid > self.ask:
            raise PermissionError("QUOTE_CROSS_INVARIANT_BROKEN")
        age = (now - self.event_time).total_seconds()
        if age < 0:
            raise PermissionError("QUOTE_FROM_FUTURE")
        if age > max_age_s:
            raise PermissionError("QUOTE_STALE")


@dataclass(frozen=True)
class FirstTestnetOrderPolicyV387:
    symbol: str = "BTCUSDT"
    max_notional: Decimal = Decimal("25")
    min_distance_bps: Decimal = Decimal("10")
    max_quote_age_s: float = 2.0
    environment: str = "TESTNET"

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise PermissionError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if self.max_notional <= 0:
            raise ValueError("MAX_NOTIONAL_REQUIRED")
        if self.min_distance_bps <= 0:
            raise ValueError("MIN_DISTANCE_BPS_REQUIRED")
        if self.max_quote_age_s <= 0:
            raise ValueError("MAX_QUOTE_AGE_REQUIRED")
        if not self.symbol or self.symbol.upper() != self.symbol:
            raise ValueError("SYMBOL_CANONICALIZATION_REQUIRED")


@dataclass(frozen=True)
class V387PreparationResult:
    allowed: bool
    reason: str
    checks: tuple[tuple[str, bool], ...]
    quote_age_s: float | None


@dataclass(frozen=True)
class OrderEventObservationV387:
    client_order_id: str
    status: str
    event_time: datetime
    transaction_time: datetime | None = None
    execution_type: str | None = None
    event_type: str = "ORDER_TRADE_UPDATE"
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReconciliationResultV387:
    green: bool
    client_order_id: str
    exchange_order_id: str | None
    position_reconciled: bool
    accounting_reconciled: bool
    reason: str


class FirstTestnetOrderRunnerV387:
    """Single-order runner above the V3.86 operator session boundary."""

    __test__ = False

    def __init__(
        self,
        *,
        session: OperatorSessionAuthorityV386,
        policy: FirstTestnetOrderPolicyV387 | None = None,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.session = session
        self.policy = policy or FirstTestnetOrderPolicyV387()
        self.policy.validate()
        self.clock = clock
        self.state = FirstTestnetRunStateV387.PRECHECK
        self._intent_id: str | None = None
        self._client_order_id: str | None = None
        self._submitted_at: datetime | None = None
        self._last_event_time: datetime | None = None
        self._observed_terminal = False
        self._unknown = False
        self._closed = False

    def _non_marketable_ok(self, intent: OrderIntent, quote: QuoteSnapshotV387) -> bool:
        distance = self.policy.min_distance_bps / Decimal("10000")
        if intent.side is Side.BUY:
            return intent.price is not None and intent.price <= quote.bid * (Decimal("1") - distance)
        if intent.side is Side.SELL:
            return intent.price is not None and intent.price >= quote.ask * (Decimal("1") + distance)
        return False

    def prepare(
        self,
        *,
        gate: GateResultV386,
        intent: OrderIntent,
        quote: QuoteSnapshotV387,
        now: datetime,
    ) -> V387PreparationResult:
        self.policy.validate()
        quote_error: str | None = None
        try:
            quote.validate(now=now, max_age_s=self.policy.max_quote_age_s)
        except PermissionError as exc:
            quote_error = str(exc)
        quote_age = (now - quote.event_time).total_seconds()
        checks: list[tuple[str, bool]] = [
            ("OPERATOR_SESSION_READY", gate.allowed and gate.state is OperatorSessionStateV386.READY),
            ("TESTNET_ENVIRONMENT", self.policy.environment == "TESTNET"),
            ("SYMBOL_ALLOWLIST", intent.symbol == self.policy.symbol),
            ("ORDER_TYPE_LIMIT", intent.order_type is OrderType.LIMIT),
            ("ORDER_ACTION_OPEN", intent.action is OrderAction.OPEN),
            ("TIME_IN_FORCE_GTC", intent.time_in_force == "GTC"),
            ("QUOTE_FRESH", quote_error is None and quote_age <= self.policy.max_quote_age_s),
            ("NON_MARKETABLE_PRICE", quote_error is None and self._non_marketable_ok(intent, quote)),
            ("NOTIONAL_WITHIN_TESTNET_CEILING", intent.price is not None and intent.quantity * intent.price <= self.policy.max_notional),
        ]
        allowed = all(ok for _, ok in checks)
        self.state = FirstTestnetRunStateV387.ARMED if allowed else FirstTestnetRunStateV387.BLOCKED
        reason = "ARMED_FOR_FIRST_TESTNET_ORDER" if allowed else (quote_error if quote_error else next(name for name, ok in checks if not ok))
        return V387PreparationResult(allowed, reason, tuple(checks), quote_age)

    def submit_once(
        self,
        *,
        preparation: V387PreparationResult,
        gate: GateResultV386,
        intent: OrderIntent,
        credentials: RuntimeCredentialValues,
        pre_trade_snapshot,
        now: datetime,
        reference_price=None,
    ) -> ControlledSubmitResultV385:
        if self._closed:
            raise PermissionError("FIRST_TESTNET_RUN_CLOSED")
        if self._intent_id is not None:
            raise PermissionError("FIRST_TESTNET_SINGLE_SHOT_ONLY")
        if not preparation.allowed or not gate.allowed or self.state is not FirstTestnetRunStateV387.ARMED:
            raise PermissionError("FIRST_TESTNET_ORDER_NOT_ARMED")
        self._intent_id = intent.intent_id
        result = self.session.submit_once(
            gate=gate,
            intent=intent,
            credentials=credentials,
            pre_trade_snapshot=pre_trade_snapshot,
            now=now,
            reference_price=reference_price,
        )
        self._submitted_at = now
        self._client_order_id = result.client_order_id
        if result.status == "UNKNOWN":
            self._unknown = True
            self.state = FirstTestnetRunStateV387.UNKNOWN
        else:
            self.state = FirstTestnetRunStateV387.OBSERVING
        return result

    def observe(self, event: OrderEventObservationV387) -> None:
        if self._closed:
            raise PermissionError("FIRST_TESTNET_RUN_CLOSED")
        if self._client_order_id is None or event.client_order_id != self._client_order_id:
            raise PermissionError("ORDER_EVENT_CORRELATION_MISMATCH")
        if self._submitted_at is None or event.event_time < self._submitted_at:
            raise PermissionError("ORDER_EVENT_PRE_SUBMIT")
        if self._last_event_time is not None and event.event_time < self._last_event_time:
            raise PermissionError("ORDER_EVENT_OUT_OF_ORDER")
        self._last_event_time = event.event_time
        status = event.status.upper()
        self._observed_terminal = status in {
            "FILLED", "CANCELED", "CANCELLED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"
        }
        self.state = FirstTestnetRunStateV387.RECONCILING if self._observed_terminal else FirstTestnetRunStateV387.OBSERVING

    def complete(self, *, reconciliation: ReconciliationResultV387) -> None:
        if self._unknown or self.state is FirstTestnetRunStateV387.UNKNOWN:
            raise PermissionError("UNKNOWN_REQUIRES_RECONCILIATION")
        if self._client_order_id is None:
            raise PermissionError("ORDER_NOT_SUBMITTED")
        if not self._observed_terminal:
            raise PermissionError("TERMINAL_ORDER_OBSERVATION_REQUIRED")
        if not reconciliation.green or not reconciliation.position_reconciled or not reconciliation.accounting_reconciled:
            raise PermissionError("POST_TRADE_RECONCILIATION_NOT_GREEN")
        if reconciliation.client_order_id != self._client_order_id:
            raise PermissionError("RECONCILIATION_CORRELATION_MISMATCH")
        self.state = FirstTestnetRunStateV387.COMPLETE

    def halt(self, reason: str) -> FirstTestnetRunStateV387:
        self.state = FirstTestnetRunStateV387.HALTED
        self._unknown = True
        return self.state

    def close(self) -> FirstTestnetRunStateV387:
        self._closed = True
        self.state = FirstTestnetRunStateV387.CLOSED
        return self.state
