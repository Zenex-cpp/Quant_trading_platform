from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v31.authority import AuthorityDecision, AuthorityStatus
from trading_platform.v31.router import AuthorizedOrderRequest
from trading_platform.v32.capability import TradeCapability
from trading_platform.v30.truth import CanonicalAction
from trading_platform.execution.models import OrderRequest, OrderType, Side


class DurableCommitConflict(RuntimeError):
    """A durable commit identity was reused with incompatible content."""


class DurableCommitReplayError(RuntimeError):
    """The durable commit authority cannot be reconstructed safely."""


@dataclass(frozen=True)
class DurableCommitRecord:
    intent_id: str
    commit_fingerprint: str
    intent_fingerprint: str
    capability_id: str
    capability_expires_at: datetime
    authority: AuthorityDecision
    request: OrderRequest
    recorded_at_ms: int

    @property
    def order_request_id(self) -> str:
        return self.request.order_request_id

    @property
    def idempotency_key(self) -> str:
        return self.request.idempotency_key


class DurableCommitLedger:
    """Append-only, restart-safe commit authority.

    The durable commit claim is written after pure validation/request construction and
    before capability consumption. Once present for an intent, a later process must
    return the same committed request or fail closed on a content conflict. This closes
    the restart window around CommitCoordinator's in-memory state without persisting
    sockets, credentials, or transport objects.
    """

    RECORDED = "ORDER_COMMIT_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: object, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"INVALID_DURABLE_COMMIT_{field.upper()}")
        return value.isoformat()

    @classmethod
    def payload(
        cls,
        *,
        intent_id: str,
        commit_fingerprint: str,
        capability: TradeCapability,
        authorized: AuthorizedOrderRequest,
        recorded_at_ms: int,
    ) -> dict[str, Any]:
        authority = authorized.authority
        request = authorized.request
        return {
            "intent_id": intent_id,
            "commit_fingerprint": commit_fingerprint,
            "intent_fingerprint": capability.intent_fingerprint,
            "capability": {
                "capability_id": capability.capability_id,
                "expires_at": cls._iso(capability.expires_at, "CAPABILITY_EXPIRES_AT"),
            },
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
                "timestamp": cls._iso(request.timestamp, "REQUEST_TIMESTAMP"),
                "deadline": cls._iso(request.deadline, "REQUEST_DEADLINE"),
                "symbol": request.symbol,
                "side": request.side.value,
                "order_type": request.order_type.value,
                "quantity": str(request.quantity),
            },
            "recorded_at_ms": recorded_at_ms,
        }

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode()).hexdigest()

    @classmethod
    def claim(
        cls,
        *,
        intent_id: str,
        commit_fingerprint: str,
        capability: TradeCapability,
        authorized: AuthorizedOrderRequest,
        recorded_at_ms: int,
        store: EventStore,
    ) -> tuple[DurableCommitRecord, bool]:
        if not store.verify_chain():
            raise DurableCommitReplayError("DURABLE_COMMIT_EVENT_CHAIN_INVALID")
        cls._validate_inputs(intent_id, commit_fingerprint, capability, authorized, recorded_at_ms)
        if authorized.request.intent_id != intent_id:
            raise DurableCommitConflict("DURABLE_COMMIT_INTENT_ID_MISMATCH")
        existing = cls._event_for_intent(store, intent_id)
        if existing is not None:
            record = cls._from_payload(existing.payload)
            if record.commit_fingerprint != commit_fingerprint:
                raise DurableCommitConflict("DURABLE_COMMIT_INTENT_PAYLOAD_CONFLICT")
            if record.intent_fingerprint != capability.intent_fingerprint:
                raise DurableCommitConflict("DURABLE_COMMIT_INTENT_FINGERPRINT_CONFLICT")
            if record.request.intent_id != authorized.request.intent_id:
                raise DurableCommitConflict("DURABLE_COMMIT_REQUEST_INTENT_CONFLICT")
            return record, False

        payload = cls.payload(
            intent_id=intent_id,
            commit_fingerprint=commit_fingerprint,
            capability=capability,
            authorized=authorized,
            recorded_at_ms=recorded_at_ms,
        )
        event_id = f"order-commit:record:{intent_id}"
        try:
            result = store.append(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=cls.RECORDED,
                aggregate_id=intent_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            concurrent = cls._event_for_intent(store, intent_id)
            if concurrent is None:
                raise DurableCommitReplayError("DURABLE_COMMIT_CONCURRENT_APPEND_UNRESOLVED") from exc
            record = cls._from_payload(concurrent.payload)
            if record.commit_fingerprint != commit_fingerprint:
                raise DurableCommitConflict("DURABLE_COMMIT_CONCURRENT_CONFLICT") from exc
            return record, False
        if result.duplicate:
            record = cls._from_payload(result.event.payload)
            if record.commit_fingerprint != commit_fingerprint:
                raise DurableCommitConflict("DURABLE_COMMIT_CONCURRENT_CONFLICT")
            return record, False
        return cls._from_payload(payload), True

    def claim_record(
        self,
        *,
        intent_id: str,
        commit_fingerprint: str,
        capability: TradeCapability,
        authorized: AuthorizedOrderRequest,
        recorded_at_ms: int,
    ) -> tuple[DurableCommitRecord, bool]:
        return self.claim(
            intent_id=intent_id,
            commit_fingerprint=commit_fingerprint,
            capability=capability,
            authorized=authorized,
            recorded_at_ms=recorded_at_ms,
            store=self.store,
        )

    def get(self, intent_id: str) -> DurableCommitRecord | None:
        if not self.store.verify_chain():
            raise DurableCommitReplayError("DURABLE_COMMIT_EVENT_CHAIN_INVALID")
        event = self._event_for_intent(self.store, intent_id)
        return self._from_payload(event.payload) if event is not None else None

    def restore(self) -> dict[str, DurableCommitRecord]:
        if not self.store.verify_chain():
            raise DurableCommitReplayError("DURABLE_COMMIT_EVENT_CHAIN_INVALID")
        out: dict[str, DurableCommitRecord] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED:
                continue
            try:
                record = self._from_payload(event.payload)
            except Exception as exc:
                raise DurableCommitReplayError("INVALID_DURABLE_COMMIT_PAYLOAD") from exc
            if event.aggregate_id != record.intent_id or record.intent_id in out:
                raise DurableCommitReplayError("DUPLICATE_DURABLE_COMMIT_INTENT")
            out[record.intent_id] = record
        return out

    def assert_matches(
        self,
        *,
        intent_id: str,
        commit_fingerprint: str,
        capability: TradeCapability,
        authorized: AuthorizedOrderRequest,
    ) -> DurableCommitRecord:
        record = self.get(intent_id)
        if record is None:
            raise DurableCommitConflict("DURABLE_COMMIT_NOT_FOUND")
        if record.commit_fingerprint != commit_fingerprint:
            raise DurableCommitConflict("DURABLE_COMMIT_PAYLOAD_MISMATCH")
        if record.intent_fingerprint != capability.intent_fingerprint:
            raise DurableCommitConflict("DURABLE_COMMIT_INTENT_FINGERPRINT_MISMATCH")
        if record.request.order_request_id != authorized.request.order_request_id:
            raise DurableCommitConflict("DURABLE_COMMIT_REQUEST_ID_MISMATCH")
        return record

    @staticmethod
    def consumed_capability(record: DurableCommitRecord) -> TradeCapability:
        return TradeCapability(
            capability_id=record.capability_id,
            authority=record.authority,
            intent_fingerprint=record.intent_fingerprint,
            expires_at=record.capability_expires_at,
            consumed=True,
        )

    @classmethod
    def _event_for_intent(cls, store: EventStore, intent_id: str):
        for event in store.iter_events():
            if event.event_type == cls.RECORDED and event.aggregate_id == intent_id:
                return event
        return None

    @staticmethod
    def _validate_inputs(
        intent_id: str,
        commit_fingerprint: str,
        capability: TradeCapability,
        authorized: AuthorizedOrderRequest,
        recorded_at_ms: int,
    ) -> None:
        if not intent_id or not commit_fingerprint:
            raise ValueError("DURABLE_COMMIT_IDENTITY_REQUIRED")
        if recorded_at_ms < 0:
            raise ValueError("INVALID_DURABLE_COMMIT_TIMESTAMP")
        if authorized.request.intent_id != intent_id:
            raise ValueError("DURABLE_COMMIT_REQUEST_INTENT_MISMATCH")
        if not capability.capability_id or not capability.intent_fingerprint:
            raise ValueError("INVALID_DURABLE_COMMIT_CAPABILITY")
        if capability.expires_at.tzinfo is None:
            raise ValueError("INVALID_DURABLE_COMMIT_CAPABILITY_EXPIRY")
        if authorized.authority.action is not CanonicalAction.TRADE or authorized.authority.status is not AuthorityStatus.AUTHORIZED:
            raise ValueError("DURABLE_COMMIT_AUTHORITY_NOT_AUTHORIZED")

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> DurableCommitRecord:
        try:
            authority_data = dict(payload["authority"])
            request_data = dict(payload["request"])
            capability_data = dict(payload["capability"])
            authority = AuthorityDecision(
                decision_id=str(authority_data["decision_id"]),
                action=CanonicalAction(str(authority_data["action"])),
                status=AuthorityStatus(str(authority_data["status"])),
                reason=str(authority_data["reason"]),
                truth_hash=str(authority_data["truth_hash"]),
                effective_risk=Decimal(str(authority_data["effective_risk"])),
                requested_risk=Decimal(str(authority_data["requested_risk"])),
                observed_at_ns=int(authority_data["observed_at_ns"]),
                input_fingerprint=str(authority_data["input_fingerprint"]),
            )
            request = OrderRequest(
                order_request_id=str(request_data["order_request_id"]),
                correlation_id=str(request_data["correlation_id"]),
                idempotency_key=str(request_data["idempotency_key"]),
                client_order_id=str(request_data["client_order_id"]),
                intent_id=str(request_data["intent_id"]),
                risk_decision_id=str(request_data["risk_decision_id"]),
                execution_version=str(request_data["execution_version"]),
                timestamp=datetime.fromisoformat(str(request_data["timestamp"])),
                deadline=datetime.fromisoformat(str(request_data["deadline"])),
                symbol=str(request_data["symbol"]),
                side=Side(str(request_data["side"])),
                order_type=OrderType(str(request_data["order_type"])),
                quantity=Decimal(str(request_data["quantity"])),
            )
            expires_at = datetime.fromisoformat(str(capability_data["expires_at"]))
            record = DurableCommitRecord(
                intent_id=str(payload["intent_id"]),
                commit_fingerprint=str(payload["commit_fingerprint"]),
                intent_fingerprint=str(payload["intent_fingerprint"]),
                capability_id=str(capability_data["capability_id"]),
                capability_expires_at=expires_at,
                authority=authority,
                request=request,
                recorded_at_ms=int(payload["recorded_at_ms"]),
            )
            if record.request.intent_id != record.intent_id:
                raise ValueError("REQUEST_INTENT_MISMATCH")
            if record.recorded_at_ms < 0 or record.capability_expires_at.tzinfo is None:
                raise ValueError("INVALID_DURABLE_COMMIT_PAYLOAD")
            return record
        except Exception as exc:
            raise DurableCommitReplayError("INVALID_DURABLE_COMMIT_PAYLOAD") from exc
