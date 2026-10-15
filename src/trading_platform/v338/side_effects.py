from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Callable, Mapping

from trading_platform.v21.event_store import EventStore


class SideEffectConflict(RuntimeError):
    """An operation identity was reused with incompatible content."""


class SideEffectRetryBlocked(RuntimeError):
    """A previous attempt already crossed or may have crossed the side-effect boundary."""


class SideEffectReplayError(RuntimeError):
    """The durable side-effect journal cannot be reconstructed safely."""


class SideEffectState(str, Enum):
    STARTED = "STARTED"
    SUCCEEDED = "SUCCEEDED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SideEffectRecord:
    operation_id: str
    operation_type: str
    idempotency_key: str
    payload_fingerprint: str
    state: SideEffectState
    result_payload: Mapping[str, Any] | None
    started_at_ms: int
    completed_at_ms: int | None


class DurableSideEffectLedger:
    """Append-only journal around a real external side effect.

    The STARTED event is durable before transport is entered. A process crash after
    the external call but before its result is recorded therefore leaves STARTED and
    fail-closes the next attempt. SUCCEEDED stores only normalized, non-secret result
    data so the same retry can return the prior observation without a second side effect.
    """

    STARTED = "SIDE_EFFECT_STARTED"
    SUCCEEDED = "SIDE_EFFECT_SUCCEEDED"
    UNKNOWN = "SIDE_EFFECT_UNKNOWN"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def payload_fingerprint(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode()).hexdigest()

    @staticmethod
    def _validate_identity(
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
    ) -> None:
        if not all((operation_id, operation_type, idempotency_key, payload_fingerprint)):
            raise ValueError("SIDE_EFFECT_IDENTITY_REQUIRED")

    @classmethod
    def _started_payload(
        cls,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
        started_at_ms: int,
    ) -> dict[str, Any]:
        return {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "idempotency_key": idempotency_key,
            "payload_fingerprint": payload_fingerprint,
            "started_at_ms": started_at_ms,
        }

    @classmethod
    def _terminal_payload(
        cls,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
        state: SideEffectState,
        result_payload: Mapping[str, Any] | None,
        completed_at_ms: int,
        reason: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation_id": operation_id,
            "operation_type": operation_type,
            "idempotency_key": idempotency_key,
            "payload_fingerprint": payload_fingerprint,
            "state": state.value,
            "completed_at_ms": completed_at_ms,
        }
        if result_payload is not None:
            payload["result_payload"] = dict(result_payload)
        if reason is not None:
            payload["reason"] = reason
        return payload

    def _events(self, operation_id: str) -> list[Any]:
        return [
            e for e in self.store.iter_events()
            if e.event_type in {self.STARTED, self.SUCCEEDED, self.UNKNOWN}
            and e.payload.get("operation_id") == operation_id
        ]

    @classmethod
    def _record_from_events(cls, events: list[Any]) -> SideEffectRecord | None:
        if not events:
            return None
        starts = [e for e in events if e.event_type == cls.STARTED]
        terminals = [e for e in events if e.event_type in {cls.SUCCEEDED, cls.UNKNOWN}]
        if len(starts) != 1 or len(terminals) > 1:
            raise SideEffectReplayError("SIDE_EFFECT_CARDINALITY_INVALID")
        start = starts[0].payload
        try:
            operation_id = str(start["operation_id"])
            operation_type = str(start["operation_type"])
            idempotency_key = str(start["idempotency_key"])
            payload_fingerprint = str(start["payload_fingerprint"])
            started_at_ms = int(start["started_at_ms"])
        except Exception as exc:
            raise SideEffectReplayError("INVALID_SIDE_EFFECT_STARTED_PAYLOAD") from exc
        if not all((operation_id, operation_type, idempotency_key, payload_fingerprint)) or started_at_ms < 0:
            raise SideEffectReplayError("INVALID_SIDE_EFFECT_STARTED_PAYLOAD")
        if not terminals:
            return SideEffectRecord(operation_id, operation_type, idempotency_key, payload_fingerprint,
                                    SideEffectState.STARTED, None, started_at_ms, None)
        terminal = terminals[0].payload
        try:
            state = SideEffectState(str(terminal["state"]))
            completed_at_ms = int(terminal["completed_at_ms"])
            if state is SideEffectState.STARTED:
                raise ValueError("INVALID_TERMINAL_STATE")
            if str(terminal["operation_id"]) != operation_id:
                raise ValueError("OPERATION_ID_MISMATCH")
            if str(terminal["operation_type"]) != operation_type:
                raise ValueError("OPERATION_TYPE_MISMATCH")
            if str(terminal["idempotency_key"]) != idempotency_key:
                raise ValueError("IDEMPOTENCY_KEY_MISMATCH")
            if str(terminal["payload_fingerprint"]) != payload_fingerprint:
                raise ValueError("PAYLOAD_FINGERPRINT_MISMATCH")
            if completed_at_ms < started_at_ms:
                raise ValueError("TERMINAL_BEFORE_START")
            result = terminal.get("result_payload")
            if result is not None and not isinstance(result, dict):
                raise ValueError("INVALID_RESULT_PAYLOAD")
        except Exception as exc:
            raise SideEffectReplayError("INVALID_SIDE_EFFECT_TERMINAL_PAYLOAD") from exc
        return SideEffectRecord(operation_id, operation_type, idempotency_key, payload_fingerprint,
                                state, result, started_at_ms, completed_at_ms)

    def get(self, operation_id: str) -> SideEffectRecord | None:
        if not self.store.verify_chain():
            raise SideEffectReplayError("SIDE_EFFECT_EVENT_CHAIN_INVALID")
        return self._record_from_events(self._events(operation_id))

    def begin(
        self,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
        started_at_ms: int,
    ) -> SideEffectRecord:
        self._validate_identity(operation_id, operation_type, idempotency_key, payload_fingerprint)
        if started_at_ms < 0:
            raise ValueError("INVALID_SIDE_EFFECT_TIME")
        existing = self.get(operation_id)
        if existing is not None:
            if (
                existing.operation_type != operation_type
                or existing.idempotency_key != idempotency_key
                or existing.payload_fingerprint != payload_fingerprint
            ):
                raise SideEffectConflict("SIDE_EFFECT_IDENTITY_CONFLICT")
            if existing.state is SideEffectState.SUCCEEDED:
                return existing
            raise SideEffectRetryBlocked(f"SIDE_EFFECT_RETRY_BLOCKED:{existing.state.value}")

        result = self.store.append(
            event_id=f"side-effect:start:{operation_id}",
            occurred_at_ms=started_at_ms,
            event_type=self.STARTED,
            aggregate_id=operation_id,
            payload=self._started_payload(
                operation_id=operation_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                payload_fingerprint=payload_fingerprint,
                started_at_ms=started_at_ms,
            ),
        )
        if result.duplicate:
            existing = self.get(operation_id)
            if existing is None:
                raise SideEffectReplayError("SIDE_EFFECT_CONCURRENT_START_UNRESOLVED")
            if existing.state is SideEffectState.SUCCEEDED:
                return existing
            raise SideEffectRetryBlocked(f"SIDE_EFFECT_RETRY_BLOCKED:{existing.state.value}")
        return self._record_from_events([result.event])  # type: ignore[return-value]

    def succeed(
        self,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
        result_payload: Mapping[str, Any],
        completed_at_ms: int,
    ) -> SideEffectRecord:
        self._validate_identity(operation_id, operation_type, idempotency_key, payload_fingerprint)
        if completed_at_ms < 0:
            raise ValueError("INVALID_SIDE_EFFECT_TIME")
        current = self.get(operation_id)
        if current is None:
            raise SideEffectConflict("SIDE_EFFECT_START_MISSING")
        if current.operation_type != operation_type or current.idempotency_key != idempotency_key or current.payload_fingerprint != payload_fingerprint:
            raise SideEffectConflict("SIDE_EFFECT_IDENTITY_CONFLICT")
        if current.state is SideEffectState.SUCCEEDED:
            if dict(current.result_payload or {}) != dict(result_payload):
                raise SideEffectConflict("SIDE_EFFECT_RESULT_CONFLICT")
            return current
        if current.state is SideEffectState.UNKNOWN:
            raise SideEffectConflict("SIDE_EFFECT_UNKNOWN_CANNOT_COMPLETE")
        self.store.append(
            event_id=f"side-effect:success:{operation_id}",
            occurred_at_ms=completed_at_ms,
            event_type=self.SUCCEEDED,
            aggregate_id=operation_id,
            payload=self._terminal_payload(
                operation_id=operation_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                payload_fingerprint=payload_fingerprint,
                state=SideEffectState.SUCCEEDED,
                result_payload=result_payload,
                completed_at_ms=completed_at_ms,
            ),
        )
        return self.get(operation_id)  # type: ignore[return-value]

    def mark_unknown(
        self,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
        completed_at_ms: int,
        reason: str,
    ) -> SideEffectRecord:
        self._validate_identity(operation_id, operation_type, idempotency_key, payload_fingerprint)
        current = self.get(operation_id)
        if current is None:
            raise SideEffectConflict("SIDE_EFFECT_START_MISSING")
        if current.state is SideEffectState.SUCCEEDED:
            return current
        if current.state is SideEffectState.UNKNOWN:
            return current
        if current.operation_type != operation_type or current.idempotency_key != idempotency_key or current.payload_fingerprint != payload_fingerprint:
            raise SideEffectConflict("SIDE_EFFECT_IDENTITY_CONFLICT")
        self.store.append(
            event_id=f"side-effect:unknown:{operation_id}",
            occurred_at_ms=completed_at_ms,
            event_type=self.UNKNOWN,
            aggregate_id=operation_id,
            payload=self._terminal_payload(
                operation_id=operation_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                payload_fingerprint=payload_fingerprint,
                state=SideEffectState.UNKNOWN,
                result_payload=None,
                completed_at_ms=completed_at_ms,
                reason=reason,
            ),
        )
        return self.get(operation_id)  # type: ignore[return-value]


class DurableSideEffectExecutor:
    """Execute a side effect once and replay only its durable result."""

    def __init__(self, ledger: DurableSideEffectLedger) -> None:
        self.ledger = ledger

    def execute(
        self,
        *,
        operation_id: str,
        operation_type: str,
        idempotency_key: str,
        payload_fingerprint: str,
        started_at_ms: int,
        execute: Callable[[], Any],
        encode_result: Callable[[Any], Mapping[str, Any]],
        decode_result: Callable[[Mapping[str, Any]], Any],
    ) -> Any:
        prior = self.ledger.begin(
            operation_id=operation_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            payload_fingerprint=payload_fingerprint,
            started_at_ms=started_at_ms,
        )
        if prior.state is SideEffectState.SUCCEEDED:
            if prior.result_payload is None:
                raise SideEffectReplayError("SIDE_EFFECT_SUCCEEDED_RESULT_MISSING")
            return decode_result(prior.result_payload)
        try:
            result = execute()
        except Exception as exc:
            try:
                self.ledger.mark_unknown(
                    operation_id=operation_id,
                    operation_type=operation_type,
                    idempotency_key=idempotency_key,
                    payload_fingerprint=payload_fingerprint,
                    completed_at_ms=started_at_ms,
                    reason=type(exc).__name__,
                )
            except Exception as ledger_exc:
                raise SideEffectReplayError("SIDE_EFFECT_UNKNOWN_RECORD_FAILED") from ledger_exc
            raise
        encoded = dict(encode_result(result))
        self.ledger.succeed(
            operation_id=operation_id,
            operation_type=operation_type,
            idempotency_key=idempotency_key,
            payload_fingerprint=payload_fingerprint,
            result_payload=encoded,
            completed_at_ms=started_at_ms,
        )
        return result
