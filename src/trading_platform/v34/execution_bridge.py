from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from trading_platform.execution.lifecycle import OrderLifecycle, OrderExecutionState
from trading_platform.execution.models import Fill, OrderIntent, PositionState, Side
from trading_platform.execution.unknown import UnknownOrderCase, UnknownOrderResolver, UnknownResolution
from trading_platform.accounting.ledger import FillLedger
from trading_platform.accounting.position import PositionLedger
from trading_platform.v24.pnl import FillPnLAttribution, PnLLedger
from trading_platform.v33.commit import CommitCoordinator, CommitResult, CommitStatus, ReconciliationRequired
from trading_platform.v31.router import AuthorizedOrderRequest
from trading_platform.v32.capability import TradeCapability
from trading_platform.v30.truth import OperationalTruth
from trading_platform.v319.durable_intent import DurableOrderIntentLedger
from trading_platform.v320.durable_request import DurableOrderRequestLedger
from trading_platform.v357.downstream_dependency import DownstreamDependencyAuthorityLedger
from trading_platform.core.ttl import ValidWindow
from trading_platform.v323.durable_commit import DurableCommitLedger
from trading_platform.v339.fill_authority import DurableFillAuthority


class BridgeStatus(str, Enum):
    COMMITTED = "COMMITTED"
    DUPLICATE = "DUPLICATE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    OBSERVED = "OBSERVED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ExecutionObservation:
    status: BridgeStatus
    intent_id: str
    order_request_id: str | None
    exchange_order_id: str | None = None
    client_order_id: str | None = None
    executed_qty: Decimal = Decimal("0")
    fill_ids: tuple[str, ...] = ()
    reason: str | None = None


class ExecutionBridge:
    """Safe boundary from authorized request to exchange observations and accounting.

    This class deliberately does not perform network I/O. An adapter supplies normalized
    exchange acknowledgements/fills; the bridge enforces lifecycle, idempotency and the
    UNKNOWN -> reconciliation path before accepting further execution state.
    """
    def __init__(self, *, commit: CommitCoordinator | None = None,
                 fill_ledger: FillLedger | None = None,
                 position_ledger: PositionLedger | None = None,
                 pnl_ledger: PnLLedger | None = None,
                 order_intent_ledger: DurableOrderIntentLedger | None = None,
                 order_request_ledger: DurableOrderRequestLedger | None = None,
                 durable_commit_ledger: DurableCommitLedger | None = None,
                 fill_authority: DurableFillAuthority | None = None):
        self.commit = commit or CommitCoordinator(durable_ledger=durable_commit_ledger)
        self.durable_commit_ledger = durable_commit_ledger
        self.fill_ledger = fill_ledger or FillLedger()
        self.position_ledger = position_ledger or PositionLedger()
        self.pnl_ledger = pnl_ledger or PnLLedger()
        self.order_intent_ledger = order_intent_ledger
        self.order_request_ledger = order_request_ledger
        self.fill_authority = fill_authority
        self._requests: dict[str, AuthorizedOrderRequest] = {}
        self._lifecycles: dict[str, OrderLifecycle] = {}
        self._unknown = UnknownOrderResolver()

    def commit_intent(self, *, capability: TradeCapability, intent: OrderIntent,
                      truth: OperationalTruth, now: datetime,
                      position_state: PositionState, market_window: ValidWindow,
                      upstream_windows: list[ValidWindow], risk_valid: bool) -> ExecutionObservation:
        try:
            result: CommitResult = self.commit.commit(
                capability=capability, intent=intent, truth=truth, now=now,
                position_state=position_state, market_window=market_window,
                upstream_windows=upstream_windows, risk_valid=risk_valid,
            )
        except ReconciliationRequired:
            return ExecutionObservation(
                status=BridgeStatus.RECONCILIATION_REQUIRED,
                intent_id=intent.intent_id,
                order_request_id=None,
                reason="UNKNOWN_EXECUTION_STATE",
            )
        if result.status is CommitStatus.DUPLICATE:
            req_id = result.request.order_request_id if result.request else None
            return ExecutionObservation(BridgeStatus.DUPLICATE, intent.intent_id, req_id)
        req = result.request
        if req is None:
            raise RuntimeError("COMMIT_RESULT_MISSING_REQUEST")
        if self.order_intent_ledger is not None:
            self.order_intent_ledger.record(intent, recorded_at_ms=int(now.timestamp() * 1000))
        if self.order_request_ledger is not None:
            intent_fp = self.order_intent_ledger.fingerprint(intent) if self.order_intent_ledger is not None else DurableOrderIntentLedger.fingerprint(intent)
            dependency_authority = None
            if self.order_intent_ledger is not None and self.order_intent_ledger.store is self.order_request_ledger.store:
                dependency_authority = DownstreamDependencyAuthorityLedger(self.order_request_ledger.store)
                self.order_request_ledger.dependency_authority = dependency_authority
            self.order_request_ledger.record(req, intent_fingerprint=intent_fp, recorded_at_ms=int(now.timestamp() * 1000))
        self._requests[intent.intent_id] = req
        self._lifecycles[intent.intent_id] = OrderLifecycle()
        # CommitCoordinator is the authoritative transition point; mirror SUBMITTED locally.
        self._lifecycles[intent.intent_id].apply(
            OrderExecutionState.SUBMITTED,
            event_id="bridge-commit:" + intent.intent_id,
            idempotency_key=req.request.idempotency_key,
        )
        return ExecutionObservation(BridgeStatus.COMMITTED, intent.intent_id, req.order_request_id,
                                    client_order_id=req.request.client_order_id)

    def committed_request(self, intent_id: str) -> AuthorizedOrderRequest:
        req = self._requests.get(intent_id)
        if req is None:
            raise ValueError("ORDER_REQUEST_NOT_COMMITTED")
        return req

    def assert_dispatchable(self, intent_id: str) -> None:
        """Reject external dispatch while the local execution lifecycle is uncertain."""
        lifecycle = self._lifecycles.get(intent_id)
        if lifecycle is None:
            raise ValueError("ORDER_REQUEST_NOT_COMMITTED")
        if lifecycle.state is OrderExecutionState.UNKNOWN:
            self.require_reconciliation(intent_id)
        if lifecycle.state not in {OrderExecutionState.SUBMITTED, OrderExecutionState.ACKNOWLEDGED, OrderExecutionState.PARTIALLY_FILLED}:
            raise PermissionError(f"ORDER_NOT_DISPATCHABLE:{lifecycle.state.value}")

    def observe_ack(self, *, intent_id: str, status: str,
                    exchange_order_id: str | None = None,
                    executed_qty: Decimal = Decimal("0"),
                    client_order_id: str | None = None) -> ExecutionObservation:
        lifecycle = self._lifecycles[intent_id]
        normalized = status.upper()
        target = {
            "NEW": OrderExecutionState.ACKNOWLEDGED,
            "ACKNOWLEDGED": OrderExecutionState.ACKNOWLEDGED,
            "PARTIALLY_FILLED": OrderExecutionState.PARTIALLY_FILLED,
            "FILLED": OrderExecutionState.FILLED,
            "CANCELED": OrderExecutionState.CANCELLED,
            "CANCELLED": OrderExecutionState.CANCELLED,
            "REJECTED": OrderExecutionState.REJECTED,
            "EXPIRED": OrderExecutionState.EXPIRED,
        }.get(normalized)
        if target is None:
            self.mark_unknown(intent_id, exchange_order_id=exchange_order_id, client_order_id=client_order_id)
            return ExecutionObservation(BridgeStatus.UNKNOWN, intent_id,
                                        self._requests[intent_id].order_request_id,
                                        exchange_order_id=exchange_order_id,
                                        client_order_id=client_order_id,
                                        executed_qty=executed_qty,
                                        reason="UNRECOGNIZED_EXCHANGE_STATUS")
        lifecycle.apply(target, event_id=f"ack:{intent_id}:{normalized}:{executed_qty}",
                        idempotency_key=f"ack:{intent_id}:{normalized}:{executed_qty}")
        bridge_status = {
            OrderExecutionState.FILLED: BridgeStatus.FILLED,
            OrderExecutionState.CANCELLED: BridgeStatus.CANCELLED,
            OrderExecutionState.REJECTED: BridgeStatus.REJECTED,
        }.get(target, BridgeStatus.OBSERVED)
        return ExecutionObservation(bridge_status, intent_id, self._requests[intent_id].order_request_id,
                                    exchange_order_id=exchange_order_id,
                                    client_order_id=client_order_id,
                                    executed_qty=executed_qty)

    def apply_fill(self, *, intent: OrderIntent, fill: Fill) -> ExecutionObservation:
        req = self._requests.get(intent.intent_id)
        if req is None:
            raise ValueError("ORDER_REQUEST_NOT_COMMITTED")
        if fill.order_request_id != req.order_request_id:
            raise ValueError("FILL_ORDER_REQUEST_MISMATCH")
        is_new_authority = True
        if self.fill_authority is not None:
            acceptance = self.fill_authority.accept(
                fill,
                occurred_at_ms=int((fill.event_time.timestamp() * 1000) if hasattr(fill.event_time, "timestamp") else (fill.event_time or 0)),
            )
            is_new_authority = acceptance.created
            if not acceptance.created:
                return ExecutionObservation(BridgeStatus.DUPLICATE, intent.intent_id, req.order_request_id,
                                            exchange_order_id=fill.exchange_order_id,
                                            executed_qty=self.fill_ledger.total_quantity(req.order_request_id),
                                            fill_ids=(fill.fill_id,), reason="FILL_ALREADY_ACCEPTED")
        _, is_new_local = self.fill_ledger.apply_once(fill)
        is_new = is_new_authority and is_new_local
        if not is_new:
            return ExecutionObservation(BridgeStatus.DUPLICATE, intent.intent_id, req.order_request_id,
                                        exchange_order_id=fill.exchange_order_id,
                                        executed_qty=self.fill_ledger.total_quantity(req.order_request_id),
                                        fill_ids=(fill.fill_id,), reason="FILL_ALREADY_ACCEPTED")
        self.position_ledger.apply_fill(intent.symbol, fill, intent.side)
        realized = Decimal("0")
        # Realized P&L is kept conservative here: exact offsetting logic remains in the
        # accounting layer; this bridge never invents P&L from an incomplete execution state.
        self.pnl_ledger.apply(FillPnLAttribution(
            fill_id=fill.fill_id,
            order_id=fill.order_request_id,
            symbol=intent.symbol,
            trade_fee=fill.fee,
            funding=fill.funding,
            slippage=fill.slippage,
            market_impact=fill.market_impact,
            realized_pnl=realized,
        ))
        return ExecutionObservation(BridgeStatus.OBSERVED, intent.intent_id, req.order_request_id,
                                    exchange_order_id=fill.exchange_order_id,
                                    executed_qty=self.fill_ledger.total_quantity(req.order_request_id),
                                    fill_ids=(fill.fill_id,))

    def mark_unknown(self, intent_id: str, *, exchange_order_id: str | None,
                     client_order_id: str | None) -> None:
        lifecycle = self._lifecycles.setdefault(intent_id, OrderLifecycle())
        if lifecycle.state is not OrderExecutionState.UNKNOWN:
            lifecycle.apply(OrderExecutionState.UNKNOWN, event_id="unknown:" + intent_id,
                            idempotency_key="unknown:" + intent_id)
        self._unknown.open(UnknownOrderCase(
            "case:" + intent_id,
            client_order_id or "unknown:" + intent_id,
            exchange_order_id,
        ))

    def require_reconciliation(self, intent_id: str) -> None:
        self._unknown.assert_no_blind_retry("case:" + intent_id)

    def assert_reconciliation_open(self, intent_id: str) -> None:
        case = self._unknown.cases.get("case:" + intent_id)
        if case is None or case.status != "OPEN":
            raise ValueError("RECONCILIATION_CASE_NOT_OPEN")

    def reconcile_resolved(self, intent_id: str, *, resolved_state: OrderExecutionState,
                           evidence_id: str, resolution: UnknownResolution = UnknownResolution.RECONCILED) -> ExecutionObservation:
        self._unknown.resolve("case:" + intent_id, resolution)
        lifecycle = self._lifecycles[intent_id]
        lifecycle.apply(resolved_state, event_id=f"reconcile:{intent_id}:{evidence_id}",
                        idempotency_key=f"reconcile:{intent_id}:{evidence_id}")
        return ExecutionObservation(BridgeStatus.OBSERVED, intent_id,
                                    self._requests[intent_id].order_request_id,
                                    reason="RECONCILIATION_VERIFIED")

