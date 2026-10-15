from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Callable, Mapping, Protocol

from trading_platform.execution.models import OrderIntent
from trading_platform.v34.execution_bridge import BridgeStatus, ExecutionBridge, ExecutionObservation
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation
from trading_platform.v310.runtime_orchestrator import RuntimeCycleSnapshot
from trading_platform.v316.accounting_gate import AccountingGateDenied, DurableAccountingAuthority
from trading_platform.v317.durable_risk import RiskReservationConflict, RiskReservationGate
from trading_platform.v318.durable_decision import RiskDecisionConflict, DurableRiskDecisionLedger
from trading_platform.v319.durable_intent import DurableOrderIntentLedger, OrderIntentConflict
from trading_platform.v320.durable_request import DurableOrderRequestLedger, OrderRequestConflict
from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger, DispatchAttemptConflict, DispatchAttemptState
from trading_platform.v331.position_authority import PositionAuthorityConflict, PositionAuthorityLedger
from trading_platform.v332.market_authority import MarketDataAuthorityConflict, MarketDataAuthorityLedger
from trading_platform.v333.causal_ttl import CausalTTLAuthorityLedger, CausalTTLConflict
from trading_platform.v338.side_effects import DurableSideEffectExecutor, DurableSideEffectLedger, SideEffectConflict, SideEffectReplayError, SideEffectRetryBlocked, SideEffectState
from trading_platform.v21.event_store import EventStore
from trading_platform.v357.downstream_dependency import DownstreamDependencyAuthorityLedger


class GuardedExecutionGateway(Protocol):
    def submit(self, order, *, credentials: RuntimeCredentialValues) -> SubmitObservation: ...


class DispatchGuardDenied(PermissionError):
    """The runtime did not authorize an external order dispatch."""


@dataclass(frozen=True)
class DispatchReceipt:
    intent_id: str
    order_request_id: str
    client_order_id: str
    exchange_order_id: str | None
    bridge_status: BridgeStatus
    exchange_outcome: str
    trading_permission_state: str
    reason: str


class GuardedExecutionDispatcher:
    """Final pre-dispatch guard between committed requests and exchange transport.

    The dispatcher is deliberately small and synchronous. It checks the authoritative
    runtime snapshot immediately before the transport call, then delegates the exact
    committed OrderRequest to the exchange gateway. No request is sent when trading is
    not allowed, when the bridge has unresolved UNKNOWN state, or when the request cannot
    be found for the intent.

    A separate cancellation/close-only policy is intentionally not inferred here: this
    guard protects risk-increasing submit operations. Risk-reducing actions must use an
    explicit close-only authorization path elsewhere in the platform.
    """

    def __init__(
        self,
        *,
        bridge: ExecutionBridge,
        gateway: GuardedExecutionGateway,
        permission_snapshot: Callable[[], RuntimeCycleSnapshot],
        accounting_authority: DurableAccountingAuthority | None = None,
        risk_reservation_gate: RiskReservationGate | None = None,
        risk_decision_ledger: DurableRiskDecisionLedger | None = None,
        order_intent_ledger: DurableOrderIntentLedger | None = None,
        order_request_ledger: DurableOrderRequestLedger | None = None,
        dispatch_attempt_ledger: DurableDispatchAttemptLedger | None = None,
        position_authority: PositionAuthorityLedger | None = None,
        market_data_authority: MarketDataAuthorityLedger | None = None,
        causal_ttl_authority: CausalTTLAuthorityLedger | None = None,
        side_effect_ledger: DurableSideEffectLedger | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.bridge = bridge
        self.gateway = gateway
        self.permission_snapshot = permission_snapshot
        self.accounting_authority = accounting_authority
        self.risk_reservation_gate = risk_reservation_gate
        self.risk_decision_ledger = risk_decision_ledger
        self.order_intent_ledger = order_intent_ledger
        self.order_request_ledger = order_request_ledger
        self.dispatch_attempt_ledger = dispatch_attempt_ledger
        self.position_authority = position_authority
        self.market_data_authority = market_data_authority
        self.causal_ttl_authority = causal_ttl_authority
        if side_effect_ledger is None:
            side_effect_ledger = DurableSideEffectLedger(
                dispatch_attempt_ledger.store if dispatch_attempt_ledger is not None else EventStore()
            )
        self.side_effect_ledger = side_effect_ledger
        self.side_effect_executor = DurableSideEffectExecutor(self.side_effect_ledger)
        self.clock_ms = clock_ms or (lambda: int(datetime.now(timezone.utc).timestamp() * 1000))

    def dispatch_submit(
        self,
        *,
        intent: OrderIntent,
        credentials: RuntimeCredentialValues,
    ) -> DispatchReceipt:
        req = self.bridge.committed_request(intent.intent_id)
        now_ms = self.clock_ms()
        now_dt = datetime.fromtimestamp(now_ms / 1000.0, tz=timezone.utc)
        snap = self.permission_snapshot()
        if not snap.trading_allowed:
            raise DispatchGuardDenied(f"TRADING_NOT_ALLOWED:{snap.state.value}:{snap.reason}")
        if snap.recovery_required:
            raise DispatchGuardDenied("RECOVERY_REQUIRED")
        if self.position_authority is not None:
            try:
                self.position_authority.assert_orderable(
                    symbol=intent.symbol, action=intent.action, now_ms=now_ms,
                )
            except PositionAuthorityConflict as exc:
                raise DispatchGuardDenied(f"POSITION_AUTHORITY_DENIED:{exc}") from exc
        if intent.action in {intent.action.OPEN, intent.action.INCREASE} and self.market_data_authority is not None:
            try:
                self.market_data_authority.assert_fresh(symbol=intent.symbol, now_ms=now_ms, feed_id="primary")
            except MarketDataAuthorityConflict as exc:
                raise DispatchGuardDenied(f"MARKET_DATA_AUTHORITY_DENIED:{exc}") from exc
        if self._intent_authority_fingerprint(intent, req.authority.truth_hash, req.authority.requested_risk) != req.authority.input_fingerprint:
            raise DispatchGuardDenied("COMMITTED_INTENT_MISMATCH")
        if self.order_intent_ledger is not None:
            try:
                self.order_intent_ledger.assert_matches(intent)
            except OrderIntentConflict as exc:
                raise DispatchGuardDenied(f"ORDER_INTENT_DURABLE_DENIED:{exc}") from exc
        if self.order_request_ledger is not None:
            try:
                intent_fp = (self.order_intent_ledger.fingerprint(intent)
                             if self.order_intent_ledger is not None
                             else DurableOrderIntentLedger.fingerprint(intent))
                self.order_request_ledger.assert_matches(
                    intent_id=intent.intent_id, authorized=req, intent_fingerprint=intent_fp,
                )
            except OrderRequestConflict as exc:
                raise DispatchGuardDenied(f"ORDER_REQUEST_DURABLE_DENIED:{exc}") from exc
        if intent.action in {intent.action.OPEN, intent.action.INCREASE} and self.causal_ttl_authority is not None:
            try:
                valid_from_ms = int(intent.window.valid_from.timestamp() * 1000)
                expires_at_ms = int(intent.window.expires_at.timestamp() * 1000)
                self.causal_ttl_authority.assert_intent_chain_valid(
                    intent_id=intent.intent_id,
                    now_ms=now_ms,
                    expected_valid_from_ms=valid_from_ms,
                    expected_expires_at_ms=expires_at_ms,
                )
            except CausalTTLConflict as exc:
                raise DispatchGuardDenied(f"CAUSAL_TTL_DENIED:{exc}") from exc
        if self.risk_decision_ledger is not None:
            try:
                intent.validate(now_dt)
            except (ValueError, TypeError) as exc:
                raise DispatchGuardDenied(f"ORDER_INTENT_NOT_FRESH:{exc}") from exc
            deadline = req.request.deadline
            if not isinstance(deadline, datetime) or deadline.tzinfo is None:
                raise DispatchGuardDenied("ORDER_DEADLINE_INVALID")
            if now_dt >= deadline:
                raise DispatchGuardDenied("ORDER_REQUEST_EXPIRED")
        attempt_intent_fp = (self.order_intent_ledger.fingerprint(intent)
                             if self.order_intent_ledger is not None
                             else DurableOrderIntentLedger.fingerprint(intent))
        attempt_request_fp = DurableOrderRequestLedger.fingerprint(req, intent_fingerprint=attempt_intent_fp)
        cached_side_effect = self.side_effect_ledger.get(req.request.order_request_id)
        if cached_side_effect is not None:
            if cached_side_effect.state is not SideEffectState.SUCCEEDED:
                raise DispatchGuardDenied(
                    f"SIDE_EFFECT_RETRY_BLOCKED:{cached_side_effect.state.value}"
                )
            try:
                cached_observation = self._decode_submit_observation(cached_side_effect.result_payload or {})
            except SideEffectReplayError as exc:
                raise DispatchGuardDenied(f"SIDE_EFFECT_AUTHORITY_DENIED:{exc}") from exc
            if cached_observation.client_order_id != req.request.client_order_id:
                raise DispatchGuardDenied("SIDE_EFFECT_REPLAY_CLIENT_ORDER_MISMATCH")
            mapped = self.bridge.observe_ack(
                intent_id=intent.intent_id,
                status=self._bridge_status(cached_observation),
                exchange_order_id=cached_observation.exchange_order_id,
                client_order_id=cached_observation.client_order_id,
                executed_qty=self._executed_qty(cached_observation.raw),
            )
            return DispatchReceipt(
                intent_id=intent.intent_id,
                order_request_id=req.request.order_request_id,
                client_order_id=req.request.client_order_id,
                exchange_order_id=cached_observation.exchange_order_id,
                bridge_status=mapped.status,
                exchange_outcome=cached_observation.outcome.value,
                trading_permission_state=snap.state.value,
                reason=cached_observation.reason or mapped.reason or "DISPATCH_REPLAYED_FROM_DURABLE_RESULT",
            )
        if self.accounting_authority is not None:
            try:
                self.accounting_authority.assert_new_risk_allowed()
            except AccountingGateDenied as exc:
                raise DispatchGuardDenied(str(exc)) from exc
        if self.dispatch_attempt_ledger is not None:
            try:
                self.dispatch_attempt_ledger.assert_dispatchable_new(
                    req.request.order_request_id,
                    intent_id=intent.intent_id,
                    client_order_id=req.request.client_order_id,
                    request_fingerprint=attempt_request_fp,
                    intent_fingerprint=attempt_intent_fp,
                    idempotency_key=req.request.idempotency_key,
                )
            except DispatchAttemptConflict as exc:
                raise DispatchGuardDenied(f"DISPATCH_ATTEMPT_DENIED:{exc}") from exc
        self.bridge.assert_dispatchable(intent.intent_id)
        accounting_hash = None
        if self.accounting_authority is not None:
            accounting_hash = self.accounting_authority.snapshot().projection_hash
        if self.risk_decision_ledger is not None:
            reservation_id = intent.risk_reservation_id
            try:
                self.risk_decision_ledger.assert_valid_for_new_risk(
                    decision_id=intent.risk_decision_id,
                    now_ms=now_ms,
                    intent_id=intent.intent_id,
                    reservation_id=reservation_id,
                    requested_exposure=Decimal(str(req.authority.requested_risk)),
                    truth_hash=req.authority.truth_hash,
                )
            except RiskDecisionConflict as exc:
                raise DispatchGuardDenied(f"RISK_DECISION_DENIED:{exc}") from exc
        if self.dispatch_attempt_ledger is not None:
            try:
                self.dispatch_attempt_ledger.prepare(
                    intent_id=intent.intent_id,
                    order_request_id=req.request.order_request_id,
                    client_order_id=req.request.client_order_id,
                    request_fingerprint=attempt_request_fp,
                    intent_fingerprint=attempt_intent_fp,
                    idempotency_key=req.request.idempotency_key,
                    attempted_at_ms=now_ms,
                    dependency_authority=(
                        DownstreamDependencyAuthorityLedger(self.dispatch_attempt_ledger.store)
                        if self.order_request_ledger is not None
                        and self.order_request_ledger.store is self.dispatch_attempt_ledger.store
                        else None
                    ),
                )
            except DispatchAttemptConflict as exc:
                raise DispatchGuardDenied(f"DISPATCH_ATTEMPT_DENIED:{exc}") from exc

        if self.risk_reservation_gate is not None:
            reservation_id = intent.risk_reservation_id
            if not reservation_id:
                raise DispatchGuardDenied("RISK_RESERVATION_REQUIRED")
            if not accounting_hash:
                raise DispatchGuardDenied("RISK_ACCOUNTING_PROJECTION_REQUIRED")
            try:
                self.risk_reservation_gate.consume_for_dispatch(
                    reservation_id=reservation_id,
                    intent_id=intent.intent_id,
                    risk_decision_id=intent.risk_decision_id,
                    requested_risk=Decimal(str(req.authority.requested_risk)),
                    accounting_projection_hash=accounting_hash,
                    occurred_at_ms=now_ms,
                )
            except RiskReservationConflict as exc:
                raise DispatchGuardDenied(f"RISK_RESERVATION_DENIED:{exc}") from exc
        try:
            observation = self.side_effect_executor.execute(
                operation_id=req.request.order_request_id,
                operation_type="ORDER_SUBMIT",
                idempotency_key=req.request.idempotency_key,
                payload_fingerprint=attempt_request_fp,
                started_at_ms=now_ms,
                execute=lambda: self.gateway.submit(req.request, credentials=credentials),
                encode_result=self._encode_submit_observation,
                decode_result=self._decode_submit_observation,
            )
        except SideEffectRetryBlocked as exc:
            raise DispatchGuardDenied(f"SIDE_EFFECT_RETRY_BLOCKED:{exc}") from exc
        except (SideEffectConflict, SideEffectReplayError) as exc:
            raise DispatchGuardDenied(f"SIDE_EFFECT_AUTHORITY_DENIED:{exc}") from exc
        except Exception as exc:
            if self.dispatch_attempt_ledger is not None:
                try:
                    self.dispatch_attempt_ledger.observe(
                        order_request_id=req.request.order_request_id,
                        state=DispatchAttemptState.UNKNOWN,
                        exchange_order_id=None,
                        outcome="UNKNOWN",
                        reason="SUBMIT_EXCEPTION",
                        observed_at_ms=self.clock_ms(),
                    )
                except DispatchAttemptConflict as ledger_exc:
                    raise DispatchGuardDenied(f"DISPATCH_ATTEMPT_DENIED:{ledger_exc}") from exc
            raise
        if self.dispatch_attempt_ledger is not None:
            final_state = {
                "ACKNOWLEDGED": DispatchAttemptState.ACKNOWLEDGED,
                "REJECTED": DispatchAttemptState.REJECTED,
                "CANCELLED": DispatchAttemptState.CANCELLED,
                "UNKNOWN": DispatchAttemptState.UNKNOWN,
            }[observation.outcome.value]
            try:
                self.dispatch_attempt_ledger.observe(
                    order_request_id=req.request.order_request_id,
                    state=final_state,
                    exchange_order_id=observation.exchange_order_id,
                    outcome=observation.outcome.value,
                    reason=observation.reason,
                    observed_at_ms=self.clock_ms(),
                )
            except DispatchAttemptConflict as exc:
                raise DispatchGuardDenied(f"DISPATCH_ATTEMPT_DENIED:{exc}") from exc
        mapped = self.bridge.observe_ack(
            intent_id=intent.intent_id,
            status=self._bridge_status(observation),
            exchange_order_id=observation.exchange_order_id,
            client_order_id=observation.client_order_id,
            executed_qty=self._executed_qty(observation.raw),
        )
        return DispatchReceipt(
            intent_id=intent.intent_id,
            order_request_id=req.request.order_request_id,
            client_order_id=req.request.client_order_id,
            exchange_order_id=observation.exchange_order_id,
            bridge_status=mapped.status,
            exchange_outcome=observation.outcome.value,
            trading_permission_state=snap.state.value,
            reason=observation.reason or mapped.reason or "DISPATCH_ACCEPTED",
        )

    @staticmethod
    def _intent_authority_fingerprint(intent: OrderIntent, truth_hash: str, requested_risk: Decimal) -> str:
        payload: dict[str, Any] = {
            "intent_id": intent.intent_id,
            "decision_id": intent.decision_id,
            "risk_decision_id": intent.risk_decision_id,
            "portfolio_decision_id": intent.portfolio_decision_id,
            "symbol": intent.symbol,
            "side": intent.side.value,
            "action": intent.action.value,
            "quantity": str(intent.quantity),
            "order_type": intent.order_type.value,
            "price": str(intent.price) if intent.price is not None else None,
            "execution_version": intent.execution_version,
        }
        body = json.dumps({
            "action": "TRADE",
            "truth_hash": truth_hash,
            "requested_risk": str(requested_risk),
            "payload": payload,
        }, sort_keys=True, separators=(",", ":"), default=str).encode()
        return sha256(body).hexdigest()


    @staticmethod
    def _encode_submit_observation(observation: SubmitObservation) -> Mapping[str, Any]:
        return {
            "outcome": observation.outcome.value,
            "client_order_id": observation.client_order_id,
            "exchange_order_id": observation.exchange_order_id,
            "reason": observation.reason,
        }

    @staticmethod
    def _decode_submit_observation(payload: Mapping[str, Any]) -> SubmitObservation:
        from trading_platform.v35.binance_execution import ExchangeOutcome
        try:
            return SubmitObservation(
                outcome=ExchangeOutcome(str(payload["outcome"])),
                client_order_id=str(payload["client_order_id"]),
                exchange_order_id=(str(payload["exchange_order_id"]) if payload.get("exchange_order_id") is not None else None),
                raw=None,
                reason=(str(payload["reason"]) if payload.get("reason") is not None else None),
            )
        except Exception as exc:
            raise SideEffectReplayError("INVALID_ORDER_SUBMIT_REPLAY_RESULT") from exc

    @staticmethod
    def _bridge_status(observation: SubmitObservation) -> str:
        return observation.outcome.value

    @staticmethod
    def _executed_qty(raw: Mapping[str, object] | None) -> Decimal:
        if not raw:
            return Decimal("0")
        value = raw.get("executedQty")
        try:
            return Decimal(str(value)) if value is not None else Decimal("0")
        except Exception:
            return Decimal("0")
