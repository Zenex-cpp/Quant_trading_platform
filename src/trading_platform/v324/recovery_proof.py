from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.operations.readiness import OperationalReadiness, ReadinessStatus
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore


class RecoveryProofInvalid(RuntimeError):
    """Recovery evidence is absent, malformed, or not verified."""


class RecoveryProofExpired(RecoveryProofInvalid):
    """Recovery proof is outside its validity window."""


class RecoveryProofConflict(RuntimeError):
    """Recovery proof identity was reused with incompatible content."""


class RecoveryProofStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class RecoveryProofRecord:
    proof_id: str
    recovery_id: str
    valid_from: datetime
    expires_at: datetime
    state_reconciled: bool
    invariants_pass: bool
    no_unresolved_critical_issue: bool
    guards_pass: bool
    state_fingerprint: str
    reconciliation_fingerprint: str
    invariants_fingerprint: str
    guards_fingerprint: str
    issued_at_ms: int

    @property
    def verified(self) -> bool:
        return (
            self.state_reconciled
            and self.invariants_pass
            and self.no_unresolved_critical_issue
            and self.guards_pass
        )

    @property
    def status(self) -> RecoveryProofStatus:
        if not self.verified:
            return RecoveryProofStatus.INVALID
        return RecoveryProofStatus.VERIFIED

    @property
    def fingerprint(self) -> str:
        return RecoveryProofLedger.fingerprint_from_payload(
            RecoveryProofLedger.payload_from_record(self)
        )


class RecoveryProofLedger:
    """Append-only recovery-proof authority backed by the existing EventStore.

    A proof is a durable, immutable artifact. It can authorize a readiness check only
    when its four required recovery predicates are true, its validity window is active,
    and the proof remains bound to the current state fingerprint.
    """

    RECORDED = "RECOVERY_PROOF_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: object, field: str) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(f"INVALID_RECOVERY_PROOF_{field.upper()}")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
        return sha256(body.encode()).hexdigest()

    @classmethod
    def payload(
        cls,
        *,
        proof_id: str,
        recovery_id: str,
        valid_from: datetime,
        expires_at: datetime,
        state_reconciled: bool,
        invariants_pass: bool,
        no_unresolved_critical_issue: bool,
        guards_pass: bool,
        state_fingerprint: str,
        reconciliation_fingerprint: str,
        invariants_fingerprint: str,
        guards_fingerprint: str,
        issued_at_ms: int,
    ) -> dict[str, Any]:
        return {
            "proof_id": proof_id,
            "recovery_id": recovery_id,
            "valid_from": cls._iso(valid_from, "VALID_FROM"),
            "expires_at": cls._iso(expires_at, "EXPIRES_AT"),
            "state_reconciled": bool(state_reconciled),
            "invariants_pass": bool(invariants_pass),
            "no_unresolved_critical_issue": bool(no_unresolved_critical_issue),
            "guards_pass": bool(guards_pass),
            "state_fingerprint": state_fingerprint,
            "reconciliation_fingerprint": reconciliation_fingerprint,
            "invariants_fingerprint": invariants_fingerprint,
            "guards_fingerprint": guards_fingerprint,
            "issued_at_ms": int(issued_at_ms),
        }

    @classmethod
    def payload_from_record(cls, record: RecoveryProofRecord) -> dict[str, Any]:
        return cls.payload(
            proof_id=record.proof_id,
            recovery_id=record.recovery_id,
            valid_from=record.valid_from,
            expires_at=record.expires_at,
            state_reconciled=record.state_reconciled,
            invariants_pass=record.invariants_pass,
            no_unresolved_critical_issue=record.no_unresolved_critical_issue,
            guards_pass=record.guards_pass,
            state_fingerprint=record.state_fingerprint,
            reconciliation_fingerprint=record.reconciliation_fingerprint,
            invariants_fingerprint=record.invariants_fingerprint,
            guards_fingerprint=record.guards_fingerprint,
            issued_at_ms=record.issued_at_ms,
        )

    @classmethod
    def record(
        cls,
        *,
        proof_id: str,
        recovery_id: str,
        valid_from: datetime,
        expires_at: datetime,
        state_reconciled: bool,
        invariants_pass: bool,
        no_unresolved_critical_issue: bool,
        guards_pass: bool,
        state_fingerprint: str,
        reconciliation_fingerprint: str,
        invariants_fingerprint: str,
        guards_fingerprint: str,
        issued_at_ms: int,
        store: EventStore,
    ) -> RecoveryProofRecord:
        cls._validate_inputs(
            proof_id=proof_id,
            recovery_id=recovery_id,
            valid_from=valid_from,
            expires_at=expires_at,
            state_reconciled=state_reconciled,
            invariants_pass=invariants_pass,
            no_unresolved_critical_issue=no_unresolved_critical_issue,
            guards_pass=guards_pass,
            state_fingerprint=state_fingerprint,
            reconciliation_fingerprint=reconciliation_fingerprint,
            invariants_fingerprint=invariants_fingerprint,
            guards_fingerprint=guards_fingerprint,
            issued_at_ms=issued_at_ms,
        )
        if not (state_reconciled and invariants_pass and no_unresolved_critical_issue and guards_pass):
            raise RecoveryProofInvalid("RECOVERY_PROOF_PREDICATES_NOT_VERIFIED")

        event_id = f"recovery-proof:record:{proof_id}"
        payload = cls.payload(
            proof_id=proof_id,
            recovery_id=recovery_id,
            valid_from=valid_from,
            expires_at=expires_at,
            state_reconciled=state_reconciled,
            invariants_pass=invariants_pass,
            no_unresolved_critical_issue=no_unresolved_critical_issue,
            guards_pass=guards_pass,
            state_fingerprint=state_fingerprint,
            reconciliation_fingerprint=reconciliation_fingerprint,
            invariants_fingerprint=invariants_fingerprint,
            guards_fingerprint=guards_fingerprint,
            issued_at_ms=issued_at_ms,
        )
        try:
            result = store.append(
                event_id=event_id,
                occurred_at_ms=issued_at_ms,
                event_type=cls.RECORDED,
                aggregate_id=recovery_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            existing = store.get(event_id)
            if existing is None:
                raise
            if existing.event_type != cls.RECORDED or cls.fingerprint_from_payload(existing.payload) != cls.fingerprint_from_payload(payload):
                raise RecoveryProofConflict("RECOVERY_PROOF_ID_CONFLICT") from exc
            result = None
        if not store.verify_chain():
            raise RecoveryProofInvalid("RECOVERY_PROOF_EVENT_CHAIN_INVALID")
        event = result.event if result is not None else store.get(event_id)
        if event is None:
            raise RecoveryProofInvalid("RECOVERY_PROOF_EVENT_MISSING")
        return cls._from_payload(event.payload)

    def get(self, proof_id: str) -> RecoveryProofRecord | None:
        if not self.store.verify_chain():
            raise RecoveryProofInvalid("RECOVERY_PROOF_EVENT_CHAIN_INVALID")
        event = self.store.get(f"recovery-proof:record:{proof_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise RecoveryProofInvalid("RECOVERY_PROOF_EVENT_TYPE_MISMATCH")
        record = self._from_payload(event.payload)
        if record.proof_id != proof_id:
            raise RecoveryProofConflict("RECOVERY_PROOF_ID_MISMATCH")
        return record

    def assert_valid(
        self,
        proof_id: str,
        *,
        now: datetime,
        current_state_fingerprint: str,
    ) -> RecoveryProofRecord:
        record = self.get(proof_id)
        if record is None:
            raise RecoveryProofInvalid("RECOVERY_PROOF_NOT_FOUND")
        if not record.verified:
            raise RecoveryProofInvalid("RECOVERY_PROOF_NOT_VERIFIED")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise RecoveryProofExpired("RECOVERY_PROOF_EXPIRED")
        if record.state_fingerprint != current_state_fingerprint:
            raise RecoveryProofConflict("RECOVERY_PROOF_STATE_FINGERPRINT_MISMATCH")
        return record

    def restore(self) -> dict[str, RecoveryProofRecord]:
        if not self.store.verify_chain():
            raise RecoveryProofInvalid("RECOVERY_PROOF_EVENT_CHAIN_INVALID")
        out: dict[str, RecoveryProofRecord] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED:
                continue
            record = self._from_payload(event.payload)
            if record.proof_id in out:
                raise RecoveryProofInvalid("DUPLICATE_RECOVERY_PROOF_ID")
            out[record.proof_id] = record
        return out

    @staticmethod
    def _validate_inputs(
        *,
        proof_id: str,
        recovery_id: str,
        valid_from: datetime,
        expires_at: datetime,
        state_reconciled: bool,
        invariants_pass: bool,
        no_unresolved_critical_issue: bool,
        guards_pass: bool,
        state_fingerprint: str,
        reconciliation_fingerprint: str,
        invariants_fingerprint: str,
        guards_fingerprint: str,
        issued_at_ms: int,
    ) -> None:
        if not proof_id or not recovery_id:
            raise ValueError("RECOVERY_PROOF_IDENTIFIERS_REQUIRED")
        for name, value in {
            "state_fingerprint": state_fingerprint,
            "reconciliation_fingerprint": reconciliation_fingerprint,
            "invariants_fingerprint": invariants_fingerprint,
            "guards_fingerprint": guards_fingerprint,
        }.items():
            if not value or not isinstance(value, str):
                raise ValueError(f"{name.upper()}_REQUIRED")
        if valid_from.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("RECOVERY_PROOF_TIMEZONE_REQUIRED")
        if expires_at <= valid_from:
            raise ValueError("RECOVERY_PROOF_INVALID_WINDOW")
        if issued_at_ms < 0:
            raise ValueError("RECOVERY_PROOF_INVALID_ISSUED_AT")

    @staticmethod
    def _from_payload(payload: Mapping[str, Any]) -> RecoveryProofRecord:
        try:
            valid_from = datetime.fromisoformat(str(payload["valid_from"]))
            expires_at = datetime.fromisoformat(str(payload["expires_at"]))
            record = RecoveryProofRecord(
                proof_id=str(payload["proof_id"]),
                recovery_id=str(payload["recovery_id"]),
                valid_from=valid_from,
                expires_at=expires_at,
                state_reconciled=bool(payload["state_reconciled"]),
                invariants_pass=bool(payload["invariants_pass"]),
                no_unresolved_critical_issue=bool(payload["no_unresolved_critical_issue"]),
                guards_pass=bool(payload["guards_pass"]),
                state_fingerprint=str(payload["state_fingerprint"]),
                reconciliation_fingerprint=str(payload["reconciliation_fingerprint"]),
                invariants_fingerprint=str(payload["invariants_fingerprint"]),
                guards_fingerprint=str(payload["guards_fingerprint"]),
                issued_at_ms=int(payload["issued_at_ms"]),
            )
            RecoveryProofLedger._validate_inputs(
                proof_id=record.proof_id,
                recovery_id=record.recovery_id,
                valid_from=record.valid_from,
                expires_at=record.expires_at,
                state_reconciled=record.state_reconciled,
                invariants_pass=record.invariants_pass,
                no_unresolved_critical_issue=record.no_unresolved_critical_issue,
                guards_pass=record.guards_pass,
                state_fingerprint=record.state_fingerprint,
                reconciliation_fingerprint=record.reconciliation_fingerprint,
                invariants_fingerprint=record.invariants_fingerprint,
                guards_fingerprint=record.guards_fingerprint,
                issued_at_ms=record.issued_at_ms,
            )
            return record
        except Exception as exc:
            raise RecoveryProofInvalid("INVALID_RECOVERY_PROOF_PAYLOAD") from exc


def require_recovery_proof(
    ledger: RecoveryProofLedger,
    proof_id: str,
    *,
    now: datetime,
    current_state_fingerprint: str,
) -> RecoveryProofRecord:
    """Machine-checkable M28 gate for post-recovery operation."""
    return ledger.assert_valid(
        proof_id,
        now=now,
        current_state_fingerprint=current_state_fingerprint,
    )


def require_live_readiness(
    readiness: OperationalReadiness,
    *,
    target_mode: OperationalMode,
    proof_ledger: RecoveryProofLedger,
    proof_id: str | None,
    now: datetime,
    current_state_fingerprint: str,
) -> RecoveryProofRecord | None:
    """Fail closed before CANARY/LIVE activation.

    This is deliberately a separate integration boundary so the legacy boolean
    `OperationalReadiness.recovery_proof` cannot be mistaken for durable evidence.
    """
    if target_mode not in {
        OperationalMode.CANARY,
        OperationalMode.LIVE,
    }:
        return None
    if readiness.status() is not ReadinessStatus.READY_FOR_LIVE:
        raise PermissionError("OPERATIONAL_READINESS_BLOCKED")
    if not proof_id:
        raise PermissionError("RECOVERY_PROOF_REQUIRED_FOR_OPERATIONAL_MODE")
    return require_recovery_proof(
        proof_ledger,
        proof_id,
        now=now,
        current_state_fingerprint=current_state_fingerprint,
    )
