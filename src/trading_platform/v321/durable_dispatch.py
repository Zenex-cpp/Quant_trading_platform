from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v357.downstream_dependency import (
    DependencyReference,
    DownstreamDependencyAuthorityLedger,
)


class DispatchAttemptConflict(RuntimeError):
    """A dispatch attempt identity was reused with incompatible evidence."""


class DispatchAttemptReplayError(RuntimeError):
    """The durable dispatch-attempt state cannot be reconstructed safely."""


class DispatchAttemptState(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class DurableDispatchAttempt:
    intent_id: str
    order_request_id: str
    client_order_id: str
    request_fingerprint: str
    intent_fingerprint: str
    idempotency_key: str
    attempt_id: str
    state: DispatchAttemptState
    exchange_order_id: str | None
    outcome: str | None
    reason: str | None
    attempted_at_ms: int
    observed_at_ms: int | None


class DurableDispatchAttemptLedger:
    """Append-only pre-transport dispatch-attempt authority.

    A PENDING attempt is written before external submission. A process crash between
    transport and acknowledgement therefore leaves a durable non-retryable marker.
    Re-submission of the same OrderRequest is denied until a separate reconciliation
    path resolves the execution state. Credentials, sockets and raw transport objects
    are never persisted.
    """

    ATTEMPTED = "ORDER_DISPATCH_ATTEMPTED"
    OBSERVED = "ORDER_DISPATCH_OBSERVED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _fp(payload: Mapping[str, Any]) -> str:
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()

    @classmethod
    def attempt_payload(
        cls,
        *,
        intent_id: str,
        order_request_id: str,
        client_order_id: str,
        request_fingerprint: str,
        intent_fingerprint: str,
        idempotency_key: str,
        attempt_id: str,
        attempted_at_ms: int,
    ) -> dict[str, Any]:
        return {
            "intent_id": intent_id,
            "order_request_id": order_request_id,
            "client_order_id": client_order_id,
            "request_fingerprint": request_fingerprint,
            "intent_fingerprint": intent_fingerprint,
            "idempotency_key": idempotency_key,
            "attempt_id": attempt_id,
            "state": DispatchAttemptState.PENDING.value,
            "attempted_at_ms": attempted_at_ms,
        }

    @classmethod
    def observation_payload(
        cls,
        *,
        intent_id: str,
        order_request_id: str,
        client_order_id: str,
        attempt_id: str,
        state: DispatchAttemptState,
        exchange_order_id: str | None,
        outcome: str | None,
        reason: str | None,
        observed_at_ms: int,
    ) -> dict[str, Any]:
        return {
            "intent_id": intent_id,
            "order_request_id": order_request_id,
            "client_order_id": client_order_id,
            "attempt_id": attempt_id,
            "state": state.value,
            "exchange_order_id": exchange_order_id,
            "outcome": outcome,
            "reason": reason,
            "observed_at_ms": observed_at_ms,
        }

    def _events_for_request(self, order_request_id: str) -> list[Any]:
        return [
            e for e in self.store.iter_events()
            if e.event_type in {self.ATTEMPTED, self.OBSERVED}
            and e.payload.get("order_request_id") == order_request_id
        ]

    @staticmethod
    def _parse_attempt(payload: Mapping[str, Any], occurred_at_ms: int) -> DurableDispatchAttempt:
        try:
            state = DispatchAttemptState(str(payload["state"]))
            if state is not DispatchAttemptState.PENDING:
                raise ValueError("INVALID_ATTEMPT_STATE")
            values = {
                "intent_id": str(payload["intent_id"]),
                "order_request_id": str(payload["order_request_id"]),
                "client_order_id": str(payload["client_order_id"]),
                "request_fingerprint": str(payload["request_fingerprint"]),
                "intent_fingerprint": str(payload["intent_fingerprint"]),
                "idempotency_key": str(payload["idempotency_key"]),
                "attempt_id": str(payload["attempt_id"]),
            }
            if not all(values.values()) or int(payload["attempted_at_ms"]) < 0:
                raise ValueError("INVALID_ATTEMPT_PAYLOAD")
        except Exception as exc:
            raise DispatchAttemptReplayError("INVALID_DISPATCH_ATTEMPT_PAYLOAD") from exc
        return DurableDispatchAttempt(
            **values,
            state=state,
            exchange_order_id=None,
            outcome=None,
            reason=None,
            attempted_at_ms=int(payload["attempted_at_ms"]),
            observed_at_ms=None,
        )

    @staticmethod
    def _apply_observation(prior: DurableDispatchAttempt, payload: Mapping[str, Any]) -> DurableDispatchAttempt:
        try:
            state = DispatchAttemptState(str(payload["state"]))
            if state is DispatchAttemptState.PENDING:
                raise ValueError("INVALID_OBSERVED_STATE")
            if str(payload["intent_id"]) != prior.intent_id:
                raise ValueError("INTENT_MISMATCH")
            if str(payload["order_request_id"]) != prior.order_request_id:
                raise ValueError("ORDER_REQUEST_MISMATCH")
            if str(payload["client_order_id"]) != prior.client_order_id:
                raise ValueError("CLIENT_ORDER_MISMATCH")
            if str(payload["attempt_id"]) != prior.attempt_id:
                raise ValueError("ATTEMPT_ID_MISMATCH")
            ts = int(payload["observed_at_ms"])
            if ts < prior.attempted_at_ms:
                raise ValueError("OBSERVATION_BEFORE_ATTEMPT")
        except Exception as exc:
            raise DispatchAttemptReplayError("INVALID_DISPATCH_OBSERVATION") from exc
        return DurableDispatchAttempt(
            intent_id=prior.intent_id,
            order_request_id=prior.order_request_id,
            client_order_id=prior.client_order_id,
            request_fingerprint=prior.request_fingerprint,
            intent_fingerprint=prior.intent_fingerprint,
            idempotency_key=prior.idempotency_key,
            attempt_id=prior.attempt_id,
            state=state,
            exchange_order_id=(str(payload["exchange_order_id"]) if payload.get("exchange_order_id") is not None else None),
            outcome=(str(payload["outcome"]) if payload.get("outcome") is not None else None),
            reason=(str(payload["reason"]) if payload.get("reason") is not None else None),
            attempted_at_ms=prior.attempted_at_ms,
            observed_at_ms=ts,
        )

    def get(self, order_request_id: str) -> DurableDispatchAttempt | None:
        events = self._events_for_request(order_request_id)
        if not events:
            return None
        attempts = [e for e in events if e.event_type == self.ATTEMPTED]
        observations = [e for e in events if e.event_type == self.OBSERVED]
        if len(attempts) != 1:
            raise DispatchAttemptReplayError("DISPATCH_ATTEMPT_CARDINALITY_INVALID")
        prior = self._parse_attempt(attempts[0].payload, attempts[0].occurred_at_ms)
        if observations:
            if len(observations) != 1:
                raise DispatchAttemptReplayError("DISPATCH_OBSERVATION_CARDINALITY_INVALID")
            return self._apply_observation(prior, observations[0].payload)
        return prior

    def prepare(
        self,
        *,
        intent_id: str,
        order_request_id: str,
        client_order_id: str,
        request_fingerprint: str,
        intent_fingerprint: str,
        idempotency_key: str,
        attempted_at_ms: int,
        dependency_authority: DownstreamDependencyAuthorityLedger | None = None,
    ) -> DurableDispatchAttempt:
        required = (intent_id, order_request_id, client_order_id, request_fingerprint, intent_fingerprint, idempotency_key)
        if not all(required):
            raise ValueError("DISPATCH_ATTEMPT_FIELDS_REQUIRED")
        if attempted_at_ms < 0:
            raise ValueError("INVALID_DISPATCH_ATTEMPT_TIME")
        if dependency_authority is not None:
            try:
                dependency_authority.authorize(
                    authorization_id=f"dispatch-attempt:{order_request_id}",
                    artifact_id=order_request_id,
                    artifact_type="DISPATCH_ATTEMPT",
                    dependencies=(
                        DependencyReference(
                            event_id=f"order-request:commit:{order_request_id}",
                            expected_event_type="ORDER_REQUEST_COMMITTED",
                            expected_aggregate_id=intent_id,
                        ),
                        DependencyReference(
                            event_id=f"order-intent:record:{intent_id}",
                            expected_event_type="ORDER_INTENT_RECORDED",
                            expected_aggregate_id=intent_id,
                            expected_fingerprint=intent_fingerprint,
                        ),
                    ),
                    now_ms=attempted_at_ms,
                )
            except Exception as exc:
                raise DispatchAttemptConflict(f"DOWNSTREAM_DEPENDENCY_DENIED:{exc}") from exc
        existing = self.get(order_request_id)
        attempt_id = f"dispatch:{order_request_id}"
        payload = self.attempt_payload(
            intent_id=intent_id,
            order_request_id=order_request_id,
            client_order_id=client_order_id,
            request_fingerprint=request_fingerprint,
            intent_fingerprint=intent_fingerprint,
            idempotency_key=idempotency_key,
            attempt_id=attempt_id,
            attempted_at_ms=attempted_at_ms,
        )
        if existing is not None:
            current = existing
            if (
                current.intent_id != intent_id
                or current.client_order_id != client_order_id
                or current.request_fingerprint != request_fingerprint
                or current.intent_fingerprint != intent_fingerprint
                or current.idempotency_key != idempotency_key
            ):
                raise DispatchAttemptConflict("DISPATCH_ATTEMPT_BINDING_CONFLICT")
            raise DispatchAttemptConflict("DISPATCH_ATTEMPT_ALREADY_CLAIMED")
        result = self.store.append(
            event_id=f"dispatch:attempt:{order_request_id}",
            occurred_at_ms=attempted_at_ms,
            event_type=self.ATTEMPTED,
            aggregate_id=intent_id,
            payload=payload,
        )
        if result.duplicate:
            # Another caller claimed the same side effect between our pre-check and the
            # append. Never treat that race as permission to enter external transport.
            raise DispatchAttemptConflict("DISPATCH_ATTEMPT_CONCURRENT_CLAIM")
        return self.get(order_request_id)  # type: ignore[return-value]

    def observe(
        self,
        *,
        order_request_id: str,
        state: DispatchAttemptState,
        exchange_order_id: str | None,
        outcome: str | None,
        reason: str | None,
        observed_at_ms: int,
    ) -> DurableDispatchAttempt:
        prior = self.get(order_request_id)
        if prior is None:
            raise DispatchAttemptConflict("DISPATCH_ATTEMPT_NOT_FOUND")
        if prior.state is not DispatchAttemptState.PENDING:
            expected = self._apply_observation(
                prior,
                self.observation_payload(
                    intent_id=prior.intent_id,
                    order_request_id=prior.order_request_id,
                    client_order_id=prior.client_order_id,
                    attempt_id=prior.attempt_id,
                    state=state,
                    exchange_order_id=exchange_order_id,
                    outcome=outcome,
                    reason=reason,
                    observed_at_ms=observed_at_ms,
                ),
            )
            if expected != prior:
                raise DispatchAttemptConflict("DISPATCH_ATTEMPT_ALREADY_RESOLVED")
            return prior
        payload = self.observation_payload(
            intent_id=prior.intent_id,
            order_request_id=prior.order_request_id,
            client_order_id=prior.client_order_id,
            attempt_id=prior.attempt_id,
            state=state,
            exchange_order_id=exchange_order_id,
            outcome=outcome,
            reason=reason,
            observed_at_ms=observed_at_ms,
        )
        self.store.append(
            event_id=f"dispatch:observed:{order_request_id}",
            occurred_at_ms=observed_at_ms,
            event_type=self.OBSERVED,
            aggregate_id=prior.intent_id,
            payload=payload,
        )
        return self.get(order_request_id)  # type: ignore[return-value]

    def assert_dispatchable_new(
        self,
        order_request_id: str,
        *,
        intent_id: str | None = None,
        client_order_id: str | None = None,
        request_fingerprint: str | None = None,
        intent_fingerprint: str | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        current = self.get(order_request_id)
        if current is None:
            return
        checks = {
            "intent_id": intent_id,
            "client_order_id": client_order_id,
            "request_fingerprint": request_fingerprint,
            "intent_fingerprint": intent_fingerprint,
            "idempotency_key": idempotency_key,
        }
        for name, expected in checks.items():
            if expected is not None and getattr(current, name) != expected:
                raise DispatchAttemptConflict("DISPATCH_ATTEMPT_BINDING_CONFLICT")
        if current.state is DispatchAttemptState.PENDING:
            raise DispatchAttemptConflict("DISPATCH_ATTEMPT_PENDING_REQUIRES_RECONCILIATION")
        if current.state is DispatchAttemptState.UNKNOWN:
            raise DispatchAttemptConflict("DISPATCH_ATTEMPT_UNKNOWN_REQUIRES_RECONCILIATION")
        raise DispatchAttemptConflict(f"DISPATCH_ATTEMPT_ALREADY_RESOLVED:{current.state.value}")

    def restore(self) -> dict[str, DurableDispatchAttempt]:
        if not self.store.verify_chain():
            raise DispatchAttemptReplayError("DISPATCH_ATTEMPT_EVENT_CHAIN_INVALID")
        ids: set[str] = set()
        out: dict[str, DurableDispatchAttempt] = {}
        for event in self.store.iter_events():
            if event.event_type not in {self.ATTEMPTED, self.OBSERVED}:
                continue
            rid = str(event.payload.get("order_request_id", ""))
            if not rid:
                raise DispatchAttemptReplayError("MISSING_ORDER_REQUEST_ID")
            if event.event_type == self.ATTEMPTED:
                if rid in ids:
                    raise DispatchAttemptReplayError("DUPLICATE_DISPATCH_ATTEMPT")
                record = self._parse_attempt(event.payload, event.occurred_at_ms)
                if record.order_request_id != rid or record.intent_id != event.aggregate_id:
                    raise DispatchAttemptReplayError("DISPATCH_ATTEMPT_AGGREGATE_MISMATCH")
                out[rid] = record
                ids.add(rid)
            else:
                prior = out.get(rid)
                if prior is None:
                    raise DispatchAttemptReplayError("OBSERVATION_WITHOUT_ATTEMPT")
                if prior.state is not DispatchAttemptState.PENDING:
                    raise DispatchAttemptReplayError("DUPLICATE_DISPATCH_OBSERVATION")
                out[rid] = self._apply_observation(prior, event.payload)
        return out
