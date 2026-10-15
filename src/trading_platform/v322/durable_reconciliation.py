from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v321.durable_dispatch import (
    DispatchAttemptConflict,
    DispatchAttemptState,
    DurableDispatchAttempt,
    DurableDispatchAttemptLedger,
)


class DispatchReconciliationConflict(RuntimeError):
    """A reconciliation evidence record conflicts with durable dispatch authority."""


class DispatchReconciliationReplayError(RuntimeError):
    """The durable reconciliation evidence cannot be reconstructed safely."""


@dataclass(frozen=True)
class DurableDispatchReconciliation:
    order_request_id: str
    intent_id: str
    attempt_id: str
    client_order_id: str
    resolved_state: DispatchAttemptState
    exchange_order_id: str | None
    evidence_id: str
    evidence_source: str
    evidence_fingerprint: str
    observed_at_ms: int


class DurableDispatchReconciliationLedger:
    """Durable closure evidence for PENDING/UNKNOWN dispatch attempts.

    Reconciliation never authorizes a second submission of the same OrderRequest. It only
    records independently obtained evidence that resolves the existing dispatch attempt.
    Raw exchange payloads, credentials and transport objects are intentionally excluded.
    """

    RECONCILED = "ORDER_DISPATCH_RECONCILED"
    _HEX64 = re.compile(r"^[0-9a-f]{64}$")
    _SOURCES = {"USER_STREAM", "REST_ORDER_STATUS", "SUBMIT_RESPONSE"}

    def __init__(
        self,
        store: EventStore | None = None,
        *,
        attempts: DurableDispatchAttemptLedger | None = None,
    ) -> None:
        self.store = store or EventStore()
        self.attempts = attempts or DurableDispatchAttemptLedger(self.store)

    @staticmethod
    def evidence_fingerprint(payload: Mapping[str, Any]) -> str:
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return sha256(body).hexdigest()

    @classmethod
    def payload(
        cls,
        *,
        order_request_id: str,
        intent_id: str,
        attempt_id: str,
        client_order_id: str,
        resolved_state: DispatchAttemptState,
        exchange_order_id: str | None,
        evidence_id: str,
        evidence_source: str,
        evidence_fingerprint: str,
        observed_at_ms: int,
    ) -> dict[str, Any]:
        if resolved_state in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
            raise ValueError("RECONCILIATION_MUST_RESOLVE_TERMINAL_STATE")
        return {
            "order_request_id": order_request_id,
            "intent_id": intent_id,
            "attempt_id": attempt_id,
            "client_order_id": client_order_id,
            "resolved_state": resolved_state.value,
            "exchange_order_id": exchange_order_id,
            "evidence_id": evidence_id,
            "evidence_source": evidence_source,
            "evidence_fingerprint": evidence_fingerprint,
            "observed_at_ms": observed_at_ms,
        }

    @classmethod
    def _parse_payload(cls, payload: Mapping[str, Any]) -> DurableDispatchReconciliation:
        try:
            state = DispatchAttemptState(str(payload["resolved_state"]))
            if state in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
                raise ValueError("NON_TERMINAL_RECONCILIATION")
            evidence_id = str(payload["evidence_id"])
            source = str(payload["evidence_source"])
            evidence_fp = str(payload["evidence_fingerprint"])
            ts = int(payload["observed_at_ms"])
            if not all((str(payload["order_request_id"]), str(payload["intent_id"]),
                        str(payload["attempt_id"]), str(payload["client_order_id"]),
                        evidence_id, source, evidence_fp)):
                raise ValueError("RECONCILIATION_FIELDS_REQUIRED")
            if source not in cls._SOURCES:
                raise ValueError("INVALID_RECONCILIATION_SOURCE")
            if not cls._HEX64.fullmatch(evidence_fp):
                raise ValueError("INVALID_RECONCILIATION_FINGERPRINT")
            if ts < 0:
                raise ValueError("INVALID_RECONCILIATION_TIME")
        except Exception as exc:
            raise DispatchReconciliationReplayError("INVALID_RECONCILIATION_PAYLOAD") from exc
        return DurableDispatchReconciliation(
            order_request_id=str(payload["order_request_id"]),
            intent_id=str(payload["intent_id"]),
            attempt_id=str(payload["attempt_id"]),
            client_order_id=str(payload["client_order_id"]),
            resolved_state=state,
            exchange_order_id=(str(payload["exchange_order_id"]) if payload.get("exchange_order_id") is not None else None),
            evidence_id=evidence_id,
            evidence_source=source,
            evidence_fingerprint=evidence_fp,
            observed_at_ms=ts,
        )

    def _event(self, order_request_id: str):
        matches = [
            e for e in self.store.iter_events()
            if e.event_type == self.RECONCILED
            and e.payload.get("order_request_id") == order_request_id
        ]
        if len(matches) > 1:
            raise DispatchReconciliationReplayError("DUPLICATE_RECONCILIATION_EVENT")
        return matches[0] if matches else None

    def get(self, order_request_id: str) -> DurableDispatchReconciliation | None:
        attempt = self.attempts.get(order_request_id)
        event = self._event(order_request_id)
        if event is None:
            return None
        record = self._parse_payload(event.payload)
        if record.order_request_id != order_request_id:
            raise DispatchReconciliationReplayError("RECONCILIATION_REQUEST_ID_MISMATCH")
        if attempt is None:
            raise DispatchReconciliationReplayError("RECONCILIATION_WITHOUT_ATTEMPT")
        if record.intent_id != attempt.intent_id or record.attempt_id != attempt.attempt_id or record.client_order_id != attempt.client_order_id:
            raise DispatchReconciliationReplayError("RECONCILIATION_ATTEMPT_BINDING_MISMATCH")
        if event.occurred_at_ms < attempt.attempted_at_ms:
            raise DispatchReconciliationReplayError("RECONCILIATION_BEFORE_ATTEMPT")
        if attempt.observed_at_ms is not None and event.occurred_at_ms < attempt.observed_at_ms:
            raise DispatchReconciliationReplayError("RECONCILIATION_BEFORE_OBSERVATION")
        if attempt.state not in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
            # A reconciliation event is only meaningful as closure of an unresolved attempt.
            raise DispatchReconciliationReplayError("RECONCILIATION_AFTER_TERMINAL_ATTEMPT")
        if attempt.exchange_order_id and record.exchange_order_id and attempt.exchange_order_id != record.exchange_order_id:
            raise DispatchReconciliationReplayError("RECONCILIATION_EXCHANGE_ORDER_MISMATCH")
        return record

    def reconcile(
        self,
        *,
        order_request_id: str,
        resolved_state: DispatchAttemptState,
        evidence_id: str,
        evidence_source: str,
        evidence_fingerprint: str,
        exchange_order_id: str | None,
        observed_at_ms: int,
    ) -> DurableDispatchReconciliation:
        if resolved_state in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
            raise DispatchReconciliationConflict("RECONCILIATION_MUST_RESOLVE_TERMINAL_STATE")
        if evidence_source not in self._SOURCES:
            raise DispatchReconciliationConflict("INVALID_RECONCILIATION_SOURCE")
        if not evidence_id or not self._HEX64.fullmatch(evidence_fingerprint):
            raise DispatchReconciliationConflict("RECONCILIATION_EVIDENCE_INVALID")
        if observed_at_ms < 0:
            raise DispatchReconciliationConflict("INVALID_RECONCILIATION_TIME")
        attempt = self.attempts.get(order_request_id)
        if attempt is None:
            raise DispatchReconciliationConflict("RECONCILIATION_ATTEMPT_NOT_FOUND")
        if attempt.state not in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
            raise DispatchReconciliationConflict("RECONCILIATION_ATTEMPT_ALREADY_RESOLVED")
        if observed_at_ms < (attempt.observed_at_ms or attempt.attempted_at_ms):
            raise DispatchReconciliationConflict("RECONCILIATION_BEFORE_ATTEMPT_EVIDENCE")
        if attempt.exchange_order_id and exchange_order_id and attempt.exchange_order_id != exchange_order_id:
            raise DispatchReconciliationConflict("RECONCILIATION_EXCHANGE_ORDER_CONFLICT")

        payload = self.payload(
            order_request_id=attempt.order_request_id,
            intent_id=attempt.intent_id,
            attempt_id=attempt.attempt_id,
            client_order_id=attempt.client_order_id,
            resolved_state=resolved_state,
            exchange_order_id=exchange_order_id or attempt.exchange_order_id,
            evidence_id=evidence_id,
            evidence_source=evidence_source,
            evidence_fingerprint=evidence_fingerprint,
            observed_at_ms=observed_at_ms,
        )
        event_id = f"dispatch:reconciled:{order_request_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECONCILED or dict(existing.payload) != payload:
                raise DispatchReconciliationConflict("RECONCILIATION_EVIDENCE_CONFLICT")
            return self._parse_payload(existing.payload)
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=observed_at_ms,
            event_type=self.RECONCILED,
            aggregate_id=attempt.intent_id,
            payload=payload,
        )
        if result.duplicate:
            raise DispatchReconciliationConflict("RECONCILIATION_CONCURRENT_CLAIM")
        return self._parse_payload(payload)

    def restore(self) -> dict[str, DurableDispatchReconciliation]:
        if not self.store.verify_chain():
            raise DispatchReconciliationReplayError("DISPATCH_RECONCILIATION_EVENT_CHAIN_INVALID")
        # Replay the attempt ledger first so any reconciliation must bind to a known attempt.
        attempts = self.attempts.restore()
        out: dict[str, DurableDispatchReconciliation] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECONCILED:
                continue
            record = self._parse_payload(event.payload)
            if record.order_request_id in out:
                raise DispatchReconciliationReplayError("DUPLICATE_RECONCILIATION_EVENT")
            attempt = attempts.get(record.order_request_id)
            if attempt is None:
                raise DispatchReconciliationReplayError("RECONCILIATION_WITHOUT_ATTEMPT")
            if event.aggregate_id != record.intent_id:
                raise DispatchReconciliationReplayError("RECONCILIATION_AGGREGATE_MISMATCH")
            if record.intent_id != attempt.intent_id or record.attempt_id != attempt.attempt_id or record.client_order_id != attempt.client_order_id:
                raise DispatchReconciliationReplayError("RECONCILIATION_ATTEMPT_BINDING_MISMATCH")
            if event.occurred_at_ms < attempt.attempted_at_ms:
                raise DispatchReconciliationReplayError("RECONCILIATION_BEFORE_ATTEMPT")
            if attempt.observed_at_ms is not None and event.occurred_at_ms < attempt.observed_at_ms:
                raise DispatchReconciliationReplayError("RECONCILIATION_BEFORE_OBSERVATION")
            if attempt.state not in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
                raise DispatchReconciliationReplayError("RECONCILIATION_AFTER_TERMINAL_ATTEMPT")
            if attempt.exchange_order_id and record.exchange_order_id and attempt.exchange_order_id != record.exchange_order_id:
                raise DispatchReconciliationReplayError("RECONCILIATION_EXCHANGE_ORDER_MISMATCH")
            out[record.order_request_id] = record
        return out

    def unresolved(self) -> dict[str, DurableDispatchAttempt]:
        attempts = self.attempts.restore()
        reconciled = self.restore()
        return {
            rid: rec for rid, rec in attempts.items()
            if rec.state in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}
            and rid not in reconciled
        }

    def assert_recovery_closed(self) -> None:
        unresolved = self.unresolved()
        if unresolved:
            raise DispatchReconciliationConflict(
                "DISPATCH_RECONCILIATION_RECOVERY_INCOMPLETE:" + ",".join(sorted(unresolved))
            )
