from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
import json
from decimal import Decimal
from threading import RLock
from typing import Any

from trading_platform.v32.capability import CapabilityAuthority, TradeCapability
from trading_platform.v31.router import AuthorizedOrderRequest, ExecutionRouter
from trading_platform.execution.models import OrderIntent, PositionState, OrderState
from trading_platform.execution.lifecycle import OrderLifecycle, OrderExecutionState
from trading_platform.execution.unknown import UnknownOrderResolver, UnknownOrderCase
from trading_platform.events.idempotency import IdempotencyStore, Operation
from trading_platform.core.ttl import ValidWindow
from trading_platform.v30.truth import OperationalTruth
from trading_platform.v323.durable_commit import DurableCommitLedger, DurableCommitConflict, DurableCommitReplayError
from trading_platform.v33.reconciliation import ReconciliationRequest, require_reconciliation, ReconciliationRequired

class CommitStatus(str, Enum):
    COMMITTED = "COMMITTED"
    DUPLICATE = "DUPLICATE"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"

@dataclass(frozen=True)
class CommitResult:
    status: CommitStatus
    request: AuthorizedOrderRequest | None
    capability: TradeCapability | None
    reconciliation: ReconciliationRequest | None = None

class CommitCoordinator:
    """Single execution commit point.

    Properties:
    - exact request is fingerprinted before capability consumption;
    - idempotent duplicates return the original committed request;
    - UNKNOWN position/order state never dispatches and instead requires reconciliation;
    - one successful capability consumption maps to at most one OrderRequest.
    """
    def __init__(self, *, capabilities: CapabilityAuthority | None = None,
                 router: ExecutionRouter | None = None,
                 idempotency: IdempotencyStore | None = None,
                 durable_ledger: DurableCommitLedger | None = None):
        self.capabilities = capabilities or CapabilityAuthority()
        self.router = router or ExecutionRouter(authority=self.capabilities.authority)
        self.idempotency = idempotency or IdempotencyStore()
        self.durable_ledger = durable_ledger
        self._lock = RLock()
        self._committed: dict[str, CommitResult] = {}
        self._lifecycles: dict[str, OrderLifecycle] = {}
        self._unknown = UnknownOrderResolver()

    @staticmethod
    def _payload(intent: OrderIntent) -> dict[str, Any]:
        return {"intent_id":intent.intent_id,"decision_id":intent.decision_id,
                "risk_decision_id":intent.risk_decision_id,"portfolio_decision_id":intent.portfolio_decision_id,
                "symbol":intent.symbol,"side":intent.side.value,"action":intent.action.value,
                "quantity":str(intent.quantity),"order_type":intent.order_type.value,
                "price":str(intent.price) if intent.price is not None else None,
                "execution_version":intent.execution_version}

    @staticmethod
    def _fp(payload: dict[str, Any]) -> str:
        return sha256(json.dumps(payload, sort_keys=True, separators=(",",":"), default=str).encode()).hexdigest()

    def commit(self, *, capability: TradeCapability, intent: OrderIntent, truth: OperationalTruth,
               now: datetime, position_state: PositionState, market_window: ValidWindow,
               upstream_windows: list[ValidWindow], risk_valid: bool) -> CommitResult:
        payload = self._payload(intent)
        fp = self._fp({"intent":payload,"truth_hash":truth.state_hash,
                       "requested_risk":str(capability.authority.requested_risk)})
        idem_key = "order-commit:" + fp
        with self._lock:
            lifecycle = self._lifecycles.setdefault(intent.intent_id, OrderLifecycle())
            prior = self._committed.get(idem_key)
            if self.durable_ledger is not None:
                durable_existing = self.durable_ledger.get(intent.intent_id)
                if durable_existing is not None:
                    if durable_existing.commit_fingerprint != fp:
                        raise DurableCommitConflict("DURABLE_COMMIT_PAYLOAD_MISMATCH")
                    if durable_existing.intent_fingerprint != capability.intent_fingerprint:
                        raise DurableCommitConflict("DURABLE_COMMIT_INTENT_FINGERPRINT_MISMATCH")
                    lifecycle.apply(OrderExecutionState.SUBMITTED, event_id="commit:"+intent.intent_id,
                                    idempotency_key=idem_key)
                    duplicate = CommitResult(
                        CommitStatus.DUPLICATE,
                        AuthorizedOrderRequest(durable_existing.authority, durable_existing.request),
                        self.durable_ledger.consumed_capability(durable_existing),
                    )
                    self._committed[idem_key] = duplicate
                    return duplicate
                if prior is not None:
                    raise DurableCommitReplayError("IN_MEMORY_COMMIT_MISSING_DURABLE_RECORD")
            elif prior is not None:
                return CommitResult(CommitStatus.DUPLICATE, prior.request, prior.capability, prior.reconciliation)

            if position_state is PositionState.UNKNOWN or lifecycle.state is OrderExecutionState.UNKNOWN:
                rec = require_reconciliation(intent_id=intent.intent_id, reason="UNKNOWN_EXECUTION_STATE")
                result = CommitResult(CommitStatus.RECONCILIATION_REQUIRED, None, capability, rec)
                self._committed[idem_key] = result
                self._unknown.open(UnknownOrderCase(f"case:{intent.intent_id}", "unknown:"+intent.intent_id, None))
                raise ReconciliationRequired("UNKNOWN_ORDER_REQUIRES_RECONCILIATION")

            # Validate capability without consuming it. This is pure validation: no state mutation.
            self.capabilities.validate(capability, now=now, truth=truth, intent_payload=payload)

            # Build request only after all safety checks. No external side effect is performed here.
            out = self.router.route(intent=intent, truth=truth, now=now, position_state=position_state,
                                    market_window=market_window, upstream_windows=upstream_windows,
                                    risk_valid=risk_valid, requested_risk=capability.authority.requested_risk,
                                    decision_id=capability.authority.decision_id, input_payload=payload)

            # Durable authority closes the restart window around this in-memory coordinator.
            # The claim is deliberately written before capability consumption: a crash after
            # the claim cannot cause a fresh commit for the same Intent on restart.
            if self.durable_ledger is not None:
                durable_record, created = self.durable_ledger.claim_record(
                    intent_id=intent.intent_id,
                    commit_fingerprint=fp,
                    capability=capability,
                    authorized=out,
                    recorded_at_ms=int(now.timestamp() * 1000),
                )
                if not created:
                    consumed = self.durable_ledger.consumed_capability(durable_record)
                    lifecycle.apply(OrderExecutionState.SUBMITTED, event_id="commit:"+intent.intent_id,
                                    idempotency_key=idem_key)
                    duplicate = CommitResult(CommitStatus.DUPLICATE,
                                             AuthorizedOrderRequest(durable_record.authority, durable_record.request),
                                             consumed)
                    self._committed[idem_key] = duplicate
                    return duplicate

            # Atomic commit point: consume exactly once after the durable claim exists.
            consumed = self.capabilities.consume(capability, now=now, truth=truth, intent_payload=payload)
            lifecycle.apply(OrderExecutionState.SUBMITTED, event_id="commit:"+intent.intent_id,
                            idempotency_key=idem_key)
            result = CommitResult(CommitStatus.COMMITTED, out, consumed)
            self._committed[idem_key] = result
            self.idempotency.execute_once(Operation(idem_key, "ORDER_COMMIT", fp), result)
            return result

    def lifecycle_state(self, intent_id: str) -> OrderExecutionState:
        return self._lifecycles[intent_id].state

    def mark_unknown(self, intent_id: str, *, client_order_id: str, exchange_order_id: str | None = None) -> None:
        with self._lock:
            lifecycle = self._lifecycles.setdefault(intent_id, OrderLifecycle())
            lifecycle.apply(OrderExecutionState.UNKNOWN, event_id="unknown:"+intent_id,
                            idempotency_key="unknown:"+intent_id)
            self._unknown.open(UnknownOrderCase("case:"+intent_id, client_order_id, exchange_order_id))

    def assert_no_retry_until_reconciled(self, intent_id: str) -> None:
        self._unknown.assert_no_blind_retry("case:"+intent_id)
