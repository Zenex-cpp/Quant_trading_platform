from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v20.reconciliation import ReconciliationResult, ReconciliationState
from trading_platform.v21.event_store import EventStore


class ReconciliationAuthorityError(RuntimeError):
    """Reconciliation evidence is absent, stale, mismatched or unsafe for activation."""


class ReconciliationAuthorityConflict(ReconciliationAuthorityError):
    """A reconciliation authorization identity was reused with incompatible content."""


@dataclass(frozen=True)
class ReconciliationAuthorization:
    authorization_id: str
    scope_id: str
    case_id: str
    state: ReconciliationState
    critical: bool
    rest_hash: str
    stream_hash: str
    diff_fingerprint: str
    reason: str
    valid_from: datetime
    expires_at: datetime
    observed_at_ms: int
    operator: str

    @property
    def fingerprint(self) -> str:
        return ReconciliationAuthorityLedger.fingerprint_from_payload(
            ReconciliationAuthorityLedger.payload_from_record(self)
        )


class ReconciliationAuthorityLedger:
    """Durable fail-closed reconciliation authority for deployment activation.

    Every reconciliation observation is append-only. A later critical mismatch becomes
    the latest observation for the scope and therefore invalidates any older green
    activation authorization until a new green observation is recorded.
    """

    RECORDED = "RECONCILIATION_EVIDENCE_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"INVALID_RECONCILIATION_{field}")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode("utf-8")).hexdigest()

    @classmethod
    def diff_fingerprint(cls, result: ReconciliationResult) -> str:
        diff = result.diff
        return cls.fingerprint_from_payload({
            "missing_in_rest": list(diff.missing_in_rest),
            "missing_in_stream": list(diff.missing_in_stream),
            "status_mismatches": list(diff.status_mismatches),
            "quantity_mismatches": list(diff.quantity_mismatches),
            "position_mismatches": list(diff.position_mismatches),
            "stale_stream": bool(diff.stale_stream),
            "stream_unhealthy": bool(diff.stream_unhealthy),
        })

    @classmethod
    def payload_from_record(cls, record: ReconciliationAuthorization) -> dict[str, Any]:
        return {
            "authorization_id": record.authorization_id,
            "scope_id": record.scope_id,
            "case_id": record.case_id,
            "state": record.state.value,
            "critical": record.critical,
            "rest_hash": record.rest_hash,
            "stream_hash": record.stream_hash,
            "diff_fingerprint": record.diff_fingerprint,
            "reason": record.reason,
            "valid_from": cls._iso(record.valid_from, "VALID_FROM"),
            "expires_at": cls._iso(record.expires_at, "EXPIRES_AT"),
            "observed_at_ms": record.observed_at_ms,
            "operator": record.operator,
        }

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> ReconciliationAuthorization:
        try:
            authorization_id = str(payload["authorization_id"])
            scope_id = str(payload["scope_id"])
            case_id = str(payload["case_id"])
            state = ReconciliationState(str(payload["state"]))
            critical = bool(payload["critical"])
            rest_hash = str(payload["rest_hash"])
            stream_hash = str(payload["stream_hash"])
            diff_fingerprint = str(payload["diff_fingerprint"])
            reason = str(payload["reason"])
            valid_from = datetime.fromisoformat(str(payload["valid_from"])).astimezone(timezone.utc)
            expires_at = datetime.fromisoformat(str(payload["expires_at"])).astimezone(timezone.utc)
            observed_at_ms = int(payload["observed_at_ms"])
            operator = str(payload["operator"])
        except Exception as exc:
            raise ReconciliationAuthorityError("INVALID_RECONCILIATION_AUTHORIZATION_PAYLOAD") from exc
        if not all((authorization_id, scope_id, case_id, rest_hash, stream_hash, diff_fingerprint, reason, operator)):
            raise ReconciliationAuthorityError("RECONCILIATION_AUTHORIZATION_FIELDS_REQUIRED")
        if expires_at <= valid_from:
            raise ReconciliationAuthorityError("RECONCILIATION_AUTHORIZATION_WINDOW_INVALID")
        if observed_at_ms < 0:
            raise ReconciliationAuthorityError("RECONCILIATION_AUTHORIZATION_TIMESTAMP_INVALID")
        return ReconciliationAuthorization(
            authorization_id=authorization_id,
            scope_id=scope_id,
            case_id=case_id,
            state=state,
            critical=critical,
            rest_hash=rest_hash,
            stream_hash=stream_hash,
            diff_fingerprint=diff_fingerprint,
            reason=reason,
            valid_from=valid_from,
            expires_at=expires_at,
            observed_at_ms=observed_at_ms,
            operator=operator,
        )

    def record_result(
        self,
        *,
        authorization_id: str,
        scope_id: str,
        case_id: str,
        result: ReconciliationResult,
        valid_from: datetime,
        expires_at: datetime,
        observed_at_ms: int,
        operator: str = "system",
    ) -> tuple[ReconciliationAuthorization, bool]:
        if not authorization_id or not scope_id or not case_id or not operator:
            raise ValueError("RECONCILIATION_AUTHORIZATION_IDENTIFIERS_REQUIRED")
        if not self.store.verify_chain():
            raise ReconciliationAuthorityError("RECONCILIATION_EVENT_CHAIN_INVALID")
        if valid_from.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("RECONCILIATION_AUTHORIZATION_TIMEZONE_REQUIRED")
        vf = valid_from.astimezone(timezone.utc)
        ex = expires_at.astimezone(timezone.utc)
        if ex <= vf:
            raise ValueError("RECONCILIATION_AUTHORIZATION_WINDOW_INVALID")
        if observed_at_ms < 0:
            raise ValueError("RECONCILIATION_AUTHORIZATION_TIMESTAMP_INVALID")
        critical = result.state is not ReconciliationState.GREEN or not result.trading_allowed
        record = ReconciliationAuthorization(
            authorization_id=authorization_id,
            scope_id=scope_id,
            case_id=case_id,
            state=result.state,
            critical=critical,
            rest_hash=result.rest_hash,
            stream_hash=result.stream_hash,
            diff_fingerprint=self.diff_fingerprint(result),
            reason=result.reason,
            valid_from=vf,
            expires_at=ex,
            observed_at_ms=observed_at_ms,
            operator=operator,
        )
        payload = self.payload_from_record(record)
        event_id = f"reconciliation-evidence:record:{authorization_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECORDED:
                raise ReconciliationAuthorityConflict("RECONCILIATION_EVENT_TYPE_CONFLICT")
            if self.fingerprint_from_payload(existing.payload) != self.fingerprint_from_payload(payload):
                raise ReconciliationAuthorityConflict("RECONCILIATION_AUTHORIZATION_ID_CONFLICT")
            return self._from_payload(existing.payload), False
        try:
            result_append = self.store.append(
                event_id=event_id,
                occurred_at_ms=observed_at_ms,
                event_type=self.RECORDED,
                aggregate_id=scope_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            concurrent = self.store.get(event_id)
            if concurrent is None:
                raise ReconciliationAuthorityError("RECONCILIATION_CONCURRENT_APPEND_UNRESOLVED") from exc
            if self.fingerprint_from_payload(concurrent.payload) != self.fingerprint_from_payload(payload):
                raise ReconciliationAuthorityConflict("RECONCILIATION_CONCURRENT_CONFLICT") from exc
            return self._from_payload(concurrent.payload), False
        if result_append.duplicate:
            restored = self._from_payload(result_append.event.payload)
            if restored.fingerprint != record.fingerprint:
                raise ReconciliationAuthorityConflict("RECONCILIATION_DUPLICATE_CONFLICT")
            return restored, False
        if not self.store.verify_chain():
            raise ReconciliationAuthorityError("RECONCILIATION_EVENT_CHAIN_INVALID")
        return record, True

    def get(self, authorization_id: str) -> ReconciliationAuthorization | None:
        if not self.store.verify_chain():
            raise ReconciliationAuthorityError("RECONCILIATION_EVENT_CHAIN_INVALID")
        event = self.store.get(f"reconciliation-evidence:record:{authorization_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise ReconciliationAuthorityError("RECONCILIATION_EVENT_TYPE_MISMATCH")
        return self._from_payload(event.payload)

    def latest_for_scope(self, scope_id: str) -> ReconciliationAuthorization | None:
        if not self.store.verify_chain():
            raise ReconciliationAuthorityError("RECONCILIATION_EVENT_CHAIN_INVALID")
        latest: ReconciliationAuthorization | None = None
        latest_sequence = -1
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED or event.aggregate_id != scope_id:
                continue
            if event.sequence > latest_sequence:
                latest = self._from_payload(event.payload)
                latest_sequence = event.sequence
        return latest

    def assert_activation_safe(
        self,
        authorization_id: str,
        *,
        now: datetime,
        scope_id: str,
        current_rest_hash: str | None = None,
        current_stream_hash: str | None = None,
    ) -> ReconciliationAuthorization:
        record = self.get(authorization_id)
        if record is None:
            raise ReconciliationAuthorityError("RECONCILIATION_AUTHORIZATION_NOT_FOUND")
        if record.scope_id != scope_id:
            raise ReconciliationAuthorityError("RECONCILIATION_SCOPE_MISMATCH")
        latest = self.latest_for_scope(scope_id)
        if latest is None or latest.authorization_id != record.authorization_id:
            raise ReconciliationAuthorityError("RECONCILIATION_AUTHORIZATION_SUPERSEDED")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise ReconciliationAuthorityError("RECONCILIATION_AUTHORIZATION_EXPIRED")
        if record.critical or record.state is not ReconciliationState.GREEN:
            raise ReconciliationAuthorityError(f"RECONCILIATION_CRITICAL_MISMATCH:{record.reason}")
        if current_rest_hash is not None and record.rest_hash != current_rest_hash:
            raise ReconciliationAuthorityError("RECONCILIATION_REST_HASH_MISMATCH")
        if current_stream_hash is not None and record.stream_hash != current_stream_hash:
            raise ReconciliationAuthorityError("RECONCILIATION_STREAM_HASH_MISMATCH")
        return record
