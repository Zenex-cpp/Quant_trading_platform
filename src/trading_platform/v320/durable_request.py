from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any

from trading_platform.execution.models import OrderRequest, OrderType, Side
from trading_platform.v30.truth import CanonicalAction
from trading_platform.v31.authority import AuthorityDecision, AuthorityStatus
from trading_platform.v31.router import AuthorizedOrderRequest
from trading_platform.v21.event_store import EventStore
from trading_platform.v319.durable_intent import DurableOrderIntentLedger
from trading_platform.v357.downstream_dependency import (
    DependencyReference,
    DownstreamDependencyAuthorityLedger,
)


class OrderRequestConflict(RuntimeError):
    """A durable OrderRequest identity was reused with different content."""


class OrderRequestReplayError(RuntimeError):
    """The durable OrderRequest ledger cannot be reconstructed safely."""


@dataclass(frozen=True)
class DurableOrderRequest:
    intent_id: str
    request: OrderRequest
    authority: AuthorityDecision
    intent_fingerprint: str
    recorded_at_ms: int
    fingerprint: str


class DurableOrderRequestLedger:
    """Append-only, hash-chained, restart-safe committed OrderRequest authority."""

    COMMITTED = "ORDER_REQUEST_COMMITTED"

    def __init__(self, store: EventStore | None = None, *, dependency_authority=None) -> None:
        self.store = store or EventStore()
        self.dependency_authority = dependency_authority

    @staticmethod
    def _iso(value: object, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"INVALID_ORDER_REQUEST_{field.upper()}")
        return value.isoformat()

    @classmethod
    def payload(cls, authorized: AuthorizedOrderRequest, *, intent_fingerprint: str) -> dict[str, Any]:
        authority = authorized.authority
        request = authorized.request
        return {
            "intent_id": request.intent_id,
            "intent_fingerprint": intent_fingerprint,
            "authority": {
                "decision_id": authority.decision_id,
                "action": authority.action.value,
                "status": authority.status.value,
                "reason": authority.reason,
                "truth_hash": authority.truth_hash,
                "effective_risk": str(authority.effective_risk),
                "requested_risk": str(authority.requested_risk),
                "observed_at_ns": authority.observed_at_ns,
                "input_fingerprint": authority.input_fingerprint,
            },
            "request": {
                "order_request_id": request.order_request_id,
                "correlation_id": request.correlation_id,
                "idempotency_key": request.idempotency_key,
                "client_order_id": request.client_order_id,
                "intent_id": request.intent_id,
                "risk_decision_id": request.risk_decision_id,
                "execution_version": request.execution_version,
                "timestamp": cls._iso(request.timestamp, "TIMESTAMP"),
                "deadline": cls._iso(request.deadline, "DEADLINE"),
                "symbol": request.symbol,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "quantity": str(request.quantity),
            },
        }

    @staticmethod
    def fingerprint_from_payload(payload: dict[str, Any]) -> str:
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def fingerprint(cls, authorized: AuthorizedOrderRequest, *, intent_fingerprint: str) -> str:
        return cls.fingerprint_from_payload(cls.payload(authorized, intent_fingerprint=intent_fingerprint))

    @staticmethod
    def _validate_authority(authority: AuthorityDecision) -> None:
        if authority.action is not CanonicalAction.TRADE or authority.status is not AuthorityStatus.AUTHORIZED:
            raise ValueError("ORDER_REQUEST_AUTHORITY_NOT_AUTHORIZED")
        if authority.observed_at_ns < 0:
            raise ValueError("INVALID_AUTHORITY_TIMESTAMP")
        if any(v < 0 or not v.is_finite() for v in (authority.effective_risk, authority.requested_risk)):
            raise ValueError("INVALID_AUTHORITY_RISK")

    @staticmethod
    def _validate_request(request: OrderRequest) -> None:
        if not request.order_request_id:
            raise ValueError("ORDER_REQUEST_ID_REQUIRED")
        if not request.intent_id:
            raise ValueError("ORDER_REQUEST_INTENT_ID_REQUIRED")
        if not request.client_order_id:
            raise ValueError("CLIENT_ORDER_ID_REQUIRED")
        if request.quantity <= 0 or not request.quantity.is_finite():
            raise ValueError("INVALID_ORDER_REQUEST_QUANTITY")
        if not isinstance(request.timestamp, datetime) or request.timestamp.tzinfo is None:
            raise ValueError("INVALID_ORDER_REQUEST_TIMESTAMP")
        if not isinstance(request.deadline, datetime) or request.deadline.tzinfo is None:
            raise ValueError("INVALID_ORDER_REQUEST_DEADLINE")
        if request.deadline < request.timestamp:
            raise ValueError("ORDER_REQUEST_DEADLINE_BEFORE_TIMESTAMP")

    def record(self, authorized: AuthorizedOrderRequest, *, intent_fingerprint: str,
               recorded_at_ms: int) -> DurableOrderRequest:
        request = authorized.request
        authority = authorized.authority
        self._validate_request(request)
        self._validate_authority(authority)
        if not intent_fingerprint:
            raise ValueError("INTENT_FINGERPRINT_REQUIRED")
        if recorded_at_ms < 0:
            raise ValueError("INVALID_ORDER_REQUEST_TIMESTAMP")
        if request.risk_decision_id != authority.decision_id:
            raise ValueError("ORDER_REQUEST_RISK_DECISION_MISMATCH")

        dependency_authority = self.dependency_authority
        if dependency_authority is not None:
            try:
                dependency_authority.authorize(
                authorization_id=f"order-request:{request.order_request_id}",
                artifact_id=request.order_request_id,
                artifact_type="ORDER_REQUEST",
                dependencies=(
                    DependencyReference(
                        event_id=f"order-intent:record:{request.intent_id}",
                        expected_event_type=DurableOrderIntentLedger.RECORDED,
                        expected_aggregate_id=request.intent_id,
                        expected_fingerprint=intent_fingerprint,
                    ),
                    DependencyReference(
                        event_id=f"risk-decision:record:{request.risk_decision_id}",
                        expected_event_type="RISK_DECISION_RECORDED",
                        expected_aggregate_id=request.risk_decision_id,
                    ),
                ),
                    now_ms=recorded_at_ms,
                )
            except Exception as exc:
                raise OrderRequestConflict(f"DOWNSTREAM_DEPENDENCY_DENIED:{exc}") from exc

        payload = self.payload(authorized, intent_fingerprint=intent_fingerprint)
        fp = self.fingerprint_from_payload(payload)
        event_id = f"order-request:commit:{request.order_request_id}"
        event = self.store.get(event_id)
        if event is not None:
            if event.event_type != self.COMMITTED or dict(event.payload) != payload:
                raise OrderRequestConflict("ORDER_REQUEST_ID_PAYLOAD_CONFLICT")
            restored = self._from_payload(event.payload)
            return DurableOrderRequest(restored[0], restored[1], restored[2], restored[3], event.occurred_at_ms, fp)

        existing_for_intent = self._find_event_by_intent(request.intent_id)
        if existing_for_intent is not None and dict(existing_for_intent.payload) != payload:
            raise OrderRequestConflict("ORDER_REQUEST_INTENT_PAYLOAD_CONFLICT")

        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=recorded_at_ms,
            event_type=self.COMMITTED,
            aggregate_id=request.intent_id,
            payload=payload,
        )
        if result.event.event_type != self.COMMITTED:
            raise OrderRequestReplayError("ORDER_REQUEST_EVENT_TYPE_INVALID")
        return DurableOrderRequest(request.intent_id, request, authority, intent_fingerprint, recorded_at_ms, fp)

    def restore(self) -> dict[str, DurableOrderRequest]:
        if not self.store.verify_chain():
            raise OrderRequestReplayError("ORDER_REQUEST_EVENT_CHAIN_INVALID")
        out: dict[str, DurableOrderRequest] = {}
        request_ids: dict[str, str] = {}
        for event in self.store.iter_events():
            if event.event_type != self.COMMITTED:
                continue
            try:
                intent_id, request, authority, intent_fp = self._from_payload(event.payload)
                fp = self.fingerprint_from_payload(dict(event.payload))
            except Exception as exc:
                raise OrderRequestReplayError("INVALID_ORDER_REQUEST_PAYLOAD") from exc
            if event.aggregate_id != intent_id or request.intent_id != intent_id:
                raise OrderRequestReplayError("ORDER_REQUEST_AGGREGATE_MISMATCH")
            prior = out.get(intent_id)
            if prior is not None and prior.fingerprint != fp:
                raise OrderRequestReplayError("DUPLICATE_ORDER_REQUEST_INTENT")
            prior_request_id = request_ids.get(request.order_request_id)
            if prior_request_id is not None and prior_request_id != intent_id:
                raise OrderRequestReplayError("DUPLICATE_ORDER_REQUEST_ID")
            out[intent_id] = DurableOrderRequest(intent_id, request, authority, intent_fp, event.occurred_at_ms, fp)
            request_ids[request.order_request_id] = intent_id
        return out

    def get(self, intent_id: str) -> DurableOrderRequest | None:
        return self.restore().get(intent_id)

    def assert_matches(self, *, intent_id: str, authorized: AuthorizedOrderRequest,
                       intent_fingerprint: str) -> DurableOrderRequest:
        if authorized.request.intent_id != intent_id:
            raise OrderRequestConflict("ORDER_REQUEST_INTENT_ID_MISMATCH")
        record = self.get(intent_id)
        if record is None:
            raise OrderRequestConflict("ORDER_REQUEST_NOT_FOUND")
        if record.intent_fingerprint != intent_fingerprint:
            raise OrderRequestConflict("ORDER_REQUEST_INTENT_FINGERPRINT_MISMATCH")
        expected = self.fingerprint(authorized, intent_fingerprint=intent_fingerprint)
        if record.fingerprint != expected:
            raise OrderRequestConflict("ORDER_REQUEST_PAYLOAD_MISMATCH")
        if record.request.order_request_id != authorized.request.order_request_id:
            raise OrderRequestConflict("ORDER_REQUEST_ID_MISMATCH")
        if record.intent_fingerprint != intent_fingerprint:
            raise OrderRequestConflict("ORDER_REQUEST_INTENT_FINGERPRINT_MISMATCH")
        return record

    def _find_event_by_intent(self, intent_id: str):
        for event in self.store.iter_events():
            if event.event_type == self.COMMITTED and event.aggregate_id == intent_id:
                return event
        return None

    @classmethod
    def _from_payload(cls, payload: Any) -> tuple[str, OrderRequest, AuthorityDecision, str]:
        if not isinstance(payload, dict):
            raise OrderRequestReplayError("INVALID_ORDER_REQUEST_PAYLOAD")
        try:
            intent_id = str(payload["intent_id"])
            intent_fp = str(payload["intent_fingerprint"])
            a = payload["authority"]
            r = payload["request"]
            authority = AuthorityDecision(
                decision_id=str(a["decision_id"]),
                action=CanonicalAction(str(a["action"])),
                status=AuthorityStatus(str(a["status"])),
                reason=str(a["reason"]),
                truth_hash=str(a["truth_hash"]),
                effective_risk=Decimal(str(a["effective_risk"])),
                requested_risk=Decimal(str(a["requested_risk"])),
                observed_at_ns=int(a["observed_at_ns"]),
                input_fingerprint=str(a["input_fingerprint"]),
            )
            request = OrderRequest(
                order_request_id=str(r["order_request_id"]),
                correlation_id=str(r["correlation_id"]),
                idempotency_key=str(r["idempotency_key"]),
                client_order_id=str(r["client_order_id"]),
                intent_id=str(r["intent_id"]),
                risk_decision_id=str(r["risk_decision_id"]),
                execution_version=str(r["execution_version"]),
                timestamp=datetime.fromisoformat(str(r["timestamp"])),
                deadline=datetime.fromisoformat(str(r["deadline"])),
                symbol=str(r["symbol"]),
                side=Side(str(r["side"])),
                order_type=OrderType(str(r["order_type"])),
                quantity=Decimal(str(r["quantity"])),
            )
        except Exception as exc:
            raise OrderRequestReplayError("INVALID_ORDER_REQUEST_PAYLOAD") from exc
        if request.intent_id != intent_id:
            raise OrderRequestReplayError("ORDER_REQUEST_INTENT_ID_MISMATCH")
        if not intent_fp:
            raise OrderRequestReplayError("ORDER_REQUEST_INTENT_FINGERPRINT_MISSING")
        try:
            cls._validate_request(request)
            cls._validate_authority(authority)
        except ValueError as exc:
            raise OrderRequestReplayError(str(exc)) from exc
        if request.risk_decision_id != authority.decision_id:
            raise OrderRequestReplayError("ORDER_REQUEST_RISK_DECISION_MISMATCH")
        return intent_id, request, authority, intent_fp
