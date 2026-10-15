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
from trading_platform.v324.recovery_proof import RecoveryProofLedger, RecoveryProofRecord, RecoveryProofInvalid


class RecoveryReadinessAuthorityError(RuntimeError):
    """Post-recovery readiness is absent, stale, or invalid."""


class RecoveryReadinessAuthorityExpired(RecoveryReadinessAuthorityError):
    """Readiness authority is outside its proof validity window."""


class RecoveryReadinessAuthorityConflict(RecoveryReadinessAuthorityError):
    """Readiness authority identity was reused with incompatible content."""


class RecoveryReadinessStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    INVALID = "INVALID"


@dataclass(frozen=True)
class RecoveryReadinessRecord:
    authorization_id: str
    proof_id: str
    proof_fingerprint: str
    readiness_fingerprint: str
    target_mode: OperationalMode
    state_fingerprint: str
    valid_from: datetime
    expires_at: datetime
    authorized_at_ms: int
    recovery_id: str

    @property
    def status(self) -> RecoveryReadinessStatus:
        return RecoveryReadinessStatus.AUTHORIZED

    @property
    def fingerprint(self) -> str:
        return RecoveryReadinessLedger.fingerprint_from_payload(
            RecoveryReadinessLedger.payload_from_record(self)
        )


class RecoveryReadinessLedger:
    RECORDED = "RECOVERY_READINESS_AUTHORIZED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def _iso(value: datetime) -> str:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("RECOVERY_READINESS_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()

    @classmethod
    def readiness_fingerprint(cls, readiness: OperationalReadiness) -> str:
        payload = {k: bool(v) for k, v in readiness.__dict__.items()}
        return cls.fingerprint_from_payload(payload)

    @classmethod
    def payload_from_record(cls, record: RecoveryReadinessRecord) -> dict[str, Any]:
        return {
            "authorization_id": record.authorization_id,
            "proof_id": record.proof_id,
            "proof_fingerprint": record.proof_fingerprint,
            "readiness_fingerprint": record.readiness_fingerprint,
            "target_mode": record.target_mode.value,
            "state_fingerprint": record.state_fingerprint,
            "valid_from": cls._iso(record.valid_from),
            "expires_at": cls._iso(record.expires_at),
            "authorized_at_ms": record.authorized_at_ms,
            "recovery_id": record.recovery_id,
        }


    @classmethod
    def semantic_payload_from_record(cls, record: RecoveryReadinessRecord) -> dict[str, Any]:
        payload = cls.payload_from_record(record)
        payload.pop("authorized_at_ms", None)
        return payload

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> RecoveryReadinessRecord:
        try:
            rec = RecoveryReadinessRecord(
                authorization_id=str(payload["authorization_id"]),
                proof_id=str(payload["proof_id"]),
                proof_fingerprint=str(payload["proof_fingerprint"]),
                readiness_fingerprint=str(payload["readiness_fingerprint"]),
                target_mode=OperationalMode(str(payload["target_mode"])),
                state_fingerprint=str(payload["state_fingerprint"]),
                valid_from=datetime.fromisoformat(str(payload["valid_from"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                authorized_at_ms=int(payload["authorized_at_ms"]),
                recovery_id=str(payload["recovery_id"]),
            )
        except Exception as exc:
            raise RecoveryReadinessAuthorityError("INVALID_RECOVERY_READINESS_PAYLOAD") from exc
        if not rec.authorization_id or not rec.proof_id or not rec.proof_fingerprint or not rec.readiness_fingerprint or not rec.state_fingerprint or not rec.recovery_id:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_IDENTIFIERS_REQUIRED")
        if rec.valid_from.tzinfo is None or rec.expires_at.tzinfo is None:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_TIMEZONE_REQUIRED")
        if rec.expires_at <= rec.valid_from:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_WINDOW_INVALID")
        if rec.authorized_at_ms < 0:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_TIMESTAMP_INVALID")
        return rec

    def authorize(
        self,
        *,
        authorization_id: str,
        readiness: OperationalReadiness | None,
        target_mode: OperationalMode,
        proof_ledger: RecoveryProofLedger,
        proof_id: str,
        now: datetime,
        current_state_fingerprint: str,
        recorded_at_ms: int,
    ) -> RecoveryReadinessRecord:
        if target_mode not in {OperationalMode.CANARY, OperationalMode.LIVE}:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_TARGET_MODE_NOT_CONTROLLED")
        if readiness.status() is not ReadinessStatus.READY_FOR_LIVE:
            raise RecoveryReadinessAuthorityError("OPERATIONAL_READINESS_BLOCKED")
        if not authorization_id or not proof_id or not current_state_fingerprint:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_IDENTIFIERS_REQUIRED")
        if recorded_at_ms < 0:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_TIMESTAMP_INVALID")
        try:
            proof = proof_ledger.assert_valid(proof_id, now=now, current_state_fingerprint=current_state_fingerprint)
        except Exception as exc:
            raise RecoveryReadinessAuthorityError(f"RECOVERY_PROOF_REQUIRED:{exc}") from exc
        record = RecoveryReadinessRecord(
            authorization_id=authorization_id,
            proof_id=proof.proof_id,
            proof_fingerprint=proof.fingerprint,
            readiness_fingerprint=self.readiness_fingerprint(readiness),
            target_mode=target_mode,
            state_fingerprint=current_state_fingerprint,
            valid_from=proof.valid_from,
            expires_at=proof.expires_at,
            authorized_at_ms=recorded_at_ms,
            recovery_id=proof.recovery_id,
        )
        payload = self.payload_from_record(record)
        event_id = f"recovery-readiness:authorize:{authorization_id}"
        if not self.store.verify_chain():
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_EVENT_CHAIN_INVALID")
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECORDED:
                raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_EVENT_TYPE_CONFLICT")
            existing_rec = self._from_payload(existing.payload)
            if self.fingerprint_from_payload(self.semantic_payload_from_record(record)) != self.fingerprint_from_payload(self.semantic_payload_from_record(existing_rec)):
                raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_ID_CONFLICT")
            return existing_rec
        try:
            result = self.store.append(
                event_id=event_id,
                occurred_at_ms=recorded_at_ms,
                event_type=self.RECORDED,
                aggregate_id=proof.recovery_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            existing = self.store.get(event_id)
            if existing is None:
                raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_CONCURRENT_APPEND_UNRESOLVED") from exc
            existing_rec = self._from_payload(existing.payload)
            if self.fingerprint_from_payload(self.semantic_payload_from_record(record)) != self.fingerprint_from_payload(self.semantic_payload_from_record(existing_rec)):
                raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_CONCURRENT_CONFLICT") from exc
            return existing_rec
        if not self.store.verify_chain():
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_EVENT_CHAIN_INVALID")
        return self._from_payload(result.event.payload)

    def get(self, authorization_id: str) -> RecoveryReadinessRecord | None:
        if not self.store.verify_chain():
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_EVENT_CHAIN_INVALID")
        event = self.store.get(f"recovery-readiness:authorize:{authorization_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_EVENT_TYPE_MISMATCH")
        return self._from_payload(event.payload)

    def assert_valid(
        self,
        authorization_id: str,
        *,
        readiness: OperationalReadiness,
        target_mode: OperationalMode,
        proof_ledger: RecoveryProofLedger,
        now: datetime,
        current_state_fingerprint: str,
    ) -> RecoveryReadinessRecord:
        record = self.get(authorization_id)
        if record is None:
            raise RecoveryReadinessAuthorityError("RECOVERY_READINESS_NOT_FOUND")
        if record.target_mode is not target_mode:
            raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_TARGET_MODE_MISMATCH")
        if readiness is not None and self.readiness_fingerprint(readiness) != record.readiness_fingerprint:
            raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_FINGERPRINT_MISMATCH")
        if record.state_fingerprint != current_state_fingerprint:
            raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_STATE_FINGERPRINT_MISMATCH")
        now_utc = now.astimezone(timezone.utc)
        if not (record.valid_from <= now_utc < record.expires_at):
            raise RecoveryReadinessAuthorityExpired("RECOVERY_READINESS_EXPIRED")
        proof = proof_ledger.assert_valid(record.proof_id, now=now, current_state_fingerprint=current_state_fingerprint)
        if proof.fingerprint != record.proof_fingerprint:
            raise RecoveryReadinessAuthorityConflict("RECOVERY_READINESS_PROOF_CHANGED")
        return record
