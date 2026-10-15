"""V3.85 controlled Testnet mutation boundary.

Contract:
    active activation + valid pre-trade snapshot
    -> durable snapshot record
    -> durable dispatch-attempt claim
    -> exactly one external submit attempt
    -> observation or UNKNOWN

UNKNOWN is fail-closed: no blind retry is permitted until a separate reconciliation
path resolves the dispatch attempt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.execution.models import OrderIntent, OrderRequest
from trading_platform.v21.event_store import EventStore
from trading_platform.v321.durable_dispatch import (
    DurableDispatchAttemptLedger,
    DispatchAttemptState,
    DispatchAttemptConflict,
)
from trading_platform.v380.order_adapter import BinanceTestnetOrderAdapterV380
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v384 import TestnetExecutionActivationAuthorityV384


class ControlledSubmitError(RuntimeError):
    pass


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def _request_payload(request: OrderRequest) -> dict[str, Any]:
    return {
        "order_request_id": request.order_request_id,
        "correlation_id": request.correlation_id,
        "idempotency_key": request.idempotency_key,
        "client_order_id": request.client_order_id,
        "intent_id": request.intent_id,
        "risk_decision_id": request.risk_decision_id,
        "execution_version": request.execution_version,
        "timestamp": request.timestamp.isoformat() if hasattr(request.timestamp, "isoformat") else str(request.timestamp),
        "deadline": request.deadline.isoformat() if hasattr(request.deadline, "isoformat") else str(request.deadline),
        "symbol": request.symbol,
        "side": request.side.value,
        "order_type": request.order_type.value,
        "quantity": str(request.quantity),
        "price": str(request.price) if request.price is not None else None,
        "time_in_force": request.time_in_force,
    }


def _intent_payload(intent: OrderIntent) -> dict[str, Any]:
    return {
        "intent_id": intent.intent_id,
        "decision_id": intent.decision_id,
        "portfolio_decision_id": intent.portfolio_decision_id,
        "risk_decision_id": intent.risk_decision_id,
        "strategy_id": intent.strategy_id,
        "model_id": intent.model_id,
        "execution_version": intent.execution_version,
        "symbol": intent.symbol,
        "side": intent.side.value,
        "action": intent.action.value,
        "quantity": str(intent.quantity),
        "order_type": intent.order_type.value,
        "valid_from": intent.window.valid_from.isoformat(),
        "expires_at": intent.window.expires_at.isoformat(),
        "price": str(intent.price) if intent.price is not None else None,
        "time_in_force": intent.time_in_force,
        "risk_reservation_id": intent.risk_reservation_id,
    }


@dataclass(frozen=True)
class PreTradeSnapshotV385:
    snapshot_id: str
    captured_at: datetime
    intent_id: str
    order_request_id: str
    decision_chain_hash: str
    positions_hash: str
    portfolio_hash: str
    risk_hash: str
    limits_hash: str
    market_hash: str
    liquidity_hash: str
    model_health_hash: str
    strategy_health_hash: str
    versions_hash: str
    position_state: str
    accounting_state: str
    reconciliation_state: str
    market_stale: bool

    def validate(self, *, now: datetime) -> None:
        if now < self.captured_at:
            raise ControlledSubmitError("PRE_TRADE_SNAPSHOT_TIME_IN_FUTURE")
        required = (
            self.snapshot_id, self.intent_id, self.order_request_id, self.decision_chain_hash,
            self.positions_hash, self.portfolio_hash, self.risk_hash, self.limits_hash,
            self.market_hash, self.liquidity_hash, self.model_health_hash,
            self.strategy_health_hash, self.versions_hash,
        )
        if not all(required):
            raise ControlledSubmitError("PRE_TRADE_SNAPSHOT_FIELDS_REQUIRED")
        if self.position_state == "UNKNOWN":
            raise ControlledSubmitError("POSITION_UNKNOWN")
        if self.accounting_state != "RECONCILED":
            raise ControlledSubmitError("ACCOUNTING_NOT_RECONCILED")
        if self.reconciliation_state != "GREEN":
            raise ControlledSubmitError("RECONCILIATION_NOT_GREEN")
        if self.market_stale:
            raise ControlledSubmitError("MARKET_DATA_STALE")

    @property
    def fingerprint(self) -> str:
        return _hash(self.__dict__)


class PreTradeSnapshotLedgerV385:
    EVENT = "PRE_TRADE_SNAPSHOT_CAPTURED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def capture(self, snapshot: PreTradeSnapshotV385) -> PreTradeSnapshotV385:
        payload = dict(snapshot.__dict__)
        payload["captured_at"] = snapshot.captured_at.isoformat()
        result = self.store.append(
            event_id=f"pretrade:snapshot:{snapshot.snapshot_id}",
            occurred_at_ms=int(snapshot.captured_at.timestamp() * 1000),
            event_type=self.EVENT,
            aggregate_id=snapshot.intent_id,
            payload=payload,
        )
        if result.duplicate and _hash(result.event.payload) != _hash(payload):
            raise ControlledSubmitError("PRE_TRADE_SNAPSHOT_ID_REUSE_CONFLICT")
        return snapshot

    def get(self, snapshot_id: str) -> PreTradeSnapshotV385 | None:
        for event in self.store.iter_events():
            if event.event_type == self.EVENT and event.payload.get("snapshot_id") == snapshot_id:
                p = dict(event.payload)
                p["captured_at"] = datetime.fromisoformat(str(p["captured_at"]))
                return PreTradeSnapshotV385(**p)
        return None


@dataclass(frozen=True)
class ControlledSubmitResultV385:
    status: str
    order_request_id: str
    client_order_id: str
    dispatch_attempt_id: str
    exchange_order_id: str | None
    outcome: str | None
    reason: str | None
    snapshot_id: str


class ControlledTestnetSubmitAuthorityV385:
    """Single controlled mutation path; credentials never enter durable state."""
    __test__ = False

    def __init__(
        self,
        *,
        activation: TestnetExecutionActivationAuthorityV384,
        gateway,
        event_store: EventStore | None = None,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.activation = activation
        self.gateway = gateway
        self.store = event_store or EventStore()
        self.snapshot_ledger = PreTradeSnapshotLedgerV385(self.store)
        self.dispatch_ledger = DurableDispatchAttemptLedger(self.store)
        self.adapter = BinanceTestnetOrderAdapterV380(
            gateway=gateway,
            mutation_gate=_ActivationMutationGate(activation, clock),
        )
        self.clock = clock

    def submit(
        self,
        intent: OrderIntent,
        *,
        credentials: RuntimeCredentialValues,
        pre_trade_snapshot: PreTradeSnapshotV385,
        now: datetime,
        reference_price: Decimal | None = None,
    ) -> ControlledSubmitResultV385:
        intent.validate(now)
        pre_trade_snapshot.validate(now=now)
        if pre_trade_snapshot.intent_id != intent.intent_id:
            raise ControlledSubmitError("PRE_TRADE_SNAPSHOT_INTENT_MISMATCH")
        request = self.adapter.to_order_request(intent, now=now)
        if pre_trade_snapshot.order_request_id != request.order_request_id:
            raise ControlledSubmitError("PRE_TRADE_SNAPSHOT_ORDER_REQUEST_MISMATCH")
        authorization = self.activation.authorize(intent=intent, reference_price=reference_price, now=now)
        if not authorization.allowed:
            raise ControlledSubmitError(authorization.reason)

        self.snapshot_ledger.capture(pre_trade_snapshot)
        attempt = self.dispatch_ledger.prepare(
            intent_id=intent.intent_id,
            order_request_id=request.order_request_id,
            client_order_id=request.client_order_id,
            request_fingerprint=_hash(_request_payload(request)),
            intent_fingerprint=_hash(_intent_payload(intent)),
            idempotency_key=request.idempotency_key,
            attempted_at_ms=int(now.timestamp() * 1000),
        )
        try:
            observation: SubmitObservation = self.gateway.submit(request, credentials=credentials)
        except Exception as exc:
            self.dispatch_ledger.observe(
                order_request_id=request.order_request_id,
                state=DispatchAttemptState.UNKNOWN,
                exchange_order_id=None,
                outcome="TRANSPORT_EXCEPTION",
                reason=type(exc).__name__,
                observed_at_ms=int(now.timestamp() * 1000),
            )
            raise ControlledSubmitError("EXTERNAL_SUBMIT_UNKNOWN_REQUIRES_RECONCILIATION") from exc

        mapped = {
            ExchangeOutcome.ACKNOWLEDGED: DispatchAttemptState.ACKNOWLEDGED,
            ExchangeOutcome.REJECTED: DispatchAttemptState.REJECTED,
            ExchangeOutcome.UNKNOWN: DispatchAttemptState.UNKNOWN,
        }.get(observation.outcome, DispatchAttemptState.UNKNOWN)
        self.dispatch_ledger.observe(
            order_request_id=request.order_request_id,
            state=mapped,
            exchange_order_id=observation.exchange_order_id,
            outcome=observation.outcome.value,
            reason=str(observation.raw.get("msg")) if isinstance(observation.raw, Mapping) and observation.raw.get("msg") else None,
            observed_at_ms=int(now.timestamp() * 1000),
        )
        return ControlledSubmitResultV385(
            status=mapped.value,
            order_request_id=request.order_request_id,
            client_order_id=request.client_order_id,
            dispatch_attempt_id=attempt.attempt_id,
            exchange_order_id=observation.exchange_order_id,
            outcome=observation.outcome.value,
            reason=None,
            snapshot_id=pre_trade_snapshot.snapshot_id,
        )


class _ActivationMutationGate:
    def __init__(self, activation: TestnetExecutionActivationAuthorityV384, clock) -> None:
        self.activation = activation
        self.clock = clock

    def authorize(self, *, intent: OrderIntent, reference_price: Decimal | None = None) -> None:
        result = self.activation.authorize(intent=intent, reference_price=reference_price, now=self.clock())
        if not result.allowed:
            raise PermissionError(result.reason)
