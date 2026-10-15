from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v318.durable_decision import RiskSystemState
from trading_platform.v324.recovery_proof import RecoveryProofLedger, RecoveryProofInvalid


class RiskStateMonotonicityError(RuntimeError):
    """Risk-state semantics would permit an unsafe increase in risk budget."""


class RecoveryEventError(RiskStateMonotonicityError):
    """The recovery event is absent, malformed, stale or unaudited."""


_STATE_SEVERITY = {
    RiskSystemState.NORMAL: 0,
    RiskSystemState.ELEVATED: 1,
    RiskSystemState.RESTRICTED: 2,
    RiskSystemState.FROZEN: 3,
    RiskSystemState.EMERGENCY: 4,
    RiskSystemState.RECOVERY: 5,
}

# Conservative production mapping. A worsened state can only tighten risk.
_STATE_FACTOR = {
    RiskSystemState.NORMAL: Decimal("1"),
    RiskSystemState.ELEVATED: Decimal("0.75"),
    RiskSystemState.RESTRICTED: Decimal("0.50"),
    RiskSystemState.FROZEN: Decimal("0"),
    RiskSystemState.EMERGENCY: Decimal("0"),
    RiskSystemState.RECOVERY: Decimal("0"),
}


def _state(value: RiskSystemState | str) -> RiskSystemState:
    try:
        return value if isinstance(value, RiskSystemState) else RiskSystemState(str(value))
    except ValueError as exc:
        raise RiskStateMonotonicityError("RISK_STATE_NOT_REGISTERED") from exc


def _decimal(value: Decimal | int | float | str, error: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise RiskStateMonotonicityError(error) from exc
    if not result.is_finite() or result < 0:
        raise RiskStateMonotonicityError(error)
    return result


def state_severity(state: RiskSystemState | str) -> int:
    return _STATE_SEVERITY[_state(state)]


def conservative_state_risk_factor(state: RiskSystemState | str) -> Decimal:
    return _STATE_FACTOR[_state(state)]


def validate_state_risk_factor(factor: Decimal | int | float | str) -> Decimal:
    value = _decimal(factor, "INVALID_RISK_STATE_FACTOR")
    if value > 1:
        raise RiskStateMonotonicityError("RISK_STATE_FACTOR_MUST_BE_NONINCREASING")
    return value


@dataclass(frozen=True)
class RiskBudgetStateSnapshot:
    risk_state: RiskSystemState
    remaining_budget: Decimal
    available_new_risk: Decimal
    maximum_exposure: Decimal
    state_version: str
    truth_hash: str
    observed_at_ms: int

    def payload(self) -> dict[str, Any]:
        return {
            "risk_state": self.risk_state.value,
            "remaining_budget": str(self.remaining_budget),
            "available_new_risk": str(self.available_new_risk),
            "maximum_exposure": str(self.maximum_exposure),
            "state_version": self.state_version,
            "truth_hash": self.truth_hash,
            "observed_at_ms": self.observed_at_ms,
        }

    @property
    def fingerprint(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class RiskBudgetMonotonicityGuard:
    """Enforces M29 across the three externally relevant risk-budget outputs."""

    @staticmethod
    def assert_monotone(
        *,
        previous: RiskBudgetStateSnapshot,
        current: RiskBudgetStateSnapshot,
        recovery_event: "RiskStateRecoveryEventRecord | None" = None,
    ) -> None:
        previous_state = _state(previous.risk_state)
        current_state = _state(current.risk_state)
        if state_severity(current_state) <= state_severity(previous_state):
            return
        increased = (
            current.remaining_budget > previous.remaining_budget
            or current.available_new_risk > previous.available_new_risk
            or current.maximum_exposure > previous.maximum_exposure
        )
        if not increased:
            return
        if recovery_event is None:
            raise RiskStateMonotonicityError("RISK_STATE_WORSENED_WITHOUT_RECOVERY_EVENT")
        recovery_event.assert_allows(current=current)


@dataclass(frozen=True)
class RiskStateRecoveryEventRecord:
    recovery_event_id: str
    previous_state: RiskSystemState
    current_state: RiskSystemState
    recovery_proof_id: str
    recovery_proof_fingerprint: str
    state_fingerprint: str
    validated: bool
    audited: bool
    valid_from: datetime
    expires_at: datetime
    recorded_at_ms: int
    allowed_remaining_budget: Decimal
    allowed_available_new_risk: Decimal
    allowed_maximum_exposure: Decimal

    @property
    def fingerprint(self) -> str:
        return RiskStateRecoveryEventLedger.fingerprint_from_payload(
            RiskStateRecoveryEventLedger.payload_from_record(self)
        )

    def assert_maximum_exposure(self, *, current_state: RiskSystemState | str, maximum_exposure: Decimal, now: datetime | None = None) -> None:
        if not self.validated or not self.audited:
            raise RecoveryEventError("RECOVERY_EVENT_NOT_VALIDATED_OR_AUDITED")
        if _state(current_state) is not self.current_state:
            raise RecoveryEventError("RECOVERY_EVENT_STATE_MISMATCH")
        value = _decimal(maximum_exposure, "INVALID_MAXIMUM_EXPOSURE")
        if value > self.allowed_maximum_exposure:
            raise RecoveryEventError("RECOVERY_EVENT_MAXIMUM_EXPOSURE_EXCEEDED")
        if now is not None:
            current_time = now.astimezone(timezone.utc)
            if not (self.valid_from <= current_time < self.expires_at):
                raise RecoveryEventError("RECOVERY_EVENT_EXPIRED_OR_NOT_YET_VALID")

    def assert_allows(self, *, current: RiskBudgetStateSnapshot, now: datetime | None = None) -> None:
        if not self.validated or not self.audited:
            raise RecoveryEventError("RECOVERY_EVENT_NOT_VALIDATED_OR_AUDITED")
        if current.risk_state is not self.current_state:
            raise RecoveryEventError("RECOVERY_EVENT_STATE_MISMATCH")
        if current.remaining_budget > self.allowed_remaining_budget:
            raise RecoveryEventError("RECOVERY_EVENT_REMAINING_BUDGET_EXCEEDED")
        if current.available_new_risk > self.allowed_available_new_risk:
            raise RecoveryEventError("RECOVERY_EVENT_AVAILABLE_NEW_RISK_EXCEEDED")
        if current.maximum_exposure > self.allowed_maximum_exposure:
            raise RecoveryEventError("RECOVERY_EVENT_MAXIMUM_EXPOSURE_EXCEEDED")
        if now is not None:
            current_time = now.astimezone(timezone.utc)
            if not (self.valid_from <= current_time < self.expires_at):
                raise RecoveryEventError("RECOVERY_EVENT_EXPIRED_OR_NOT_YET_VALID")


class RiskStateRecoveryEventLedger:
    """Durable, audited recovery-event authority used by the M29 exception."""

    RECORDED = "RISK_STATE_RECOVERY_EVENT_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def fingerprint_from_payload(payload: Mapping[str, Any]) -> str:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
        return sha256(body.encode()).hexdigest()

    @staticmethod
    def _iso(value: datetime) -> str:
        if value.tzinfo is None:
            raise RecoveryEventError("RECOVERY_EVENT_TIMEZONE_REQUIRED")
        return value.astimezone(timezone.utc).isoformat()

    @classmethod
    def payload_from_record(cls, record: RiskStateRecoveryEventRecord) -> dict[str, Any]:
        return {
            "recovery_event_id": record.recovery_event_id,
            "previous_state": record.previous_state.value,
            "current_state": record.current_state.value,
            "recovery_proof_id": record.recovery_proof_id,
            "recovery_proof_fingerprint": record.recovery_proof_fingerprint,
            "state_fingerprint": record.state_fingerprint,
            "validated": record.validated,
            "audited": record.audited,
            "valid_from": cls._iso(record.valid_from),
            "expires_at": cls._iso(record.expires_at),
            "recorded_at_ms": record.recorded_at_ms,
            "allowed_remaining_budget": str(record.allowed_remaining_budget),
            "allowed_available_new_risk": str(record.allowed_available_new_risk),
            "allowed_maximum_exposure": str(record.allowed_maximum_exposure),
        }

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any]) -> RiskStateRecoveryEventRecord:
        try:
            record = RiskStateRecoveryEventRecord(
                recovery_event_id=str(payload["recovery_event_id"]),
                previous_state=_state(payload["previous_state"]),
                current_state=_state(payload["current_state"]),
                recovery_proof_id=str(payload["recovery_proof_id"]),
                recovery_proof_fingerprint=str(payload["recovery_proof_fingerprint"]),
                state_fingerprint=str(payload["state_fingerprint"]),
                validated=bool(payload["validated"]),
                audited=bool(payload["audited"]),
                valid_from=datetime.fromisoformat(str(payload["valid_from"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                recorded_at_ms=int(payload["recorded_at_ms"]),
                allowed_remaining_budget=Decimal(str(payload["allowed_remaining_budget"])),
                allowed_available_new_risk=Decimal(str(payload["allowed_available_new_risk"])),
                allowed_maximum_exposure=Decimal(str(payload["allowed_maximum_exposure"])),
            )
        except Exception as exc:
            raise RecoveryEventError("INVALID_RECOVERY_EVENT_PAYLOAD") from exc
        if not record.recovery_event_id or not record.recovery_proof_id or not record.recovery_proof_fingerprint:
            raise RecoveryEventError("RECOVERY_EVENT_IDENTIFIERS_REQUIRED")
        if record.expires_at <= record.valid_from:
            raise RecoveryEventError("RECOVERY_EVENT_WINDOW_INVALID")
        if record.current_state is not record.previous_state:
            if record.allowed_remaining_budget < 0 or record.allowed_available_new_risk < 0 or record.allowed_maximum_exposure < 0:
                raise RecoveryEventError("RECOVERY_EVENT_RISK_OUTPUT_INVALID")
        return record

    def record(
        self,
        record: RiskStateRecoveryEventRecord,
        *,
        proof_ledger: RecoveryProofLedger,
        now: datetime,
        current_state_fingerprint: str,
    ) -> RiskStateRecoveryEventRecord:
        if not self.store.verify_chain():
            raise RecoveryEventError("RECOVERY_EVENT_EVENT_CHAIN_INVALID")
        if not record.validated or not record.audited:
            raise RecoveryEventError("RECOVERY_EVENT_NOT_VALIDATED_OR_AUDITED")
        if state_severity(record.current_state) < state_severity(record.previous_state):
            raise RecoveryEventError("RECOVERY_EVENT_NOT_A_RECOVERY_TRANSITION")
        if record.state_fingerprint != current_state_fingerprint:
            raise RecoveryEventError("RECOVERY_EVENT_STATE_FINGERPRINT_STALE")
        if record.recorded_at_ms < 0:
            raise RecoveryEventError("RECOVERY_EVENT_TIMESTAMP_INVALID")
        try:
            proof = proof_ledger.assert_valid(
                record.recovery_proof_id,
                now=now,
                current_state_fingerprint=current_state_fingerprint,
            )
        except RecoveryProofInvalid as exc:
            raise RecoveryEventError(f"RECOVERY_EVENT_RECOVERY_PROOF_INVALID:{exc}") from exc
        if proof.fingerprint != record.recovery_proof_fingerprint:
            raise RecoveryEventError("RECOVERY_EVENT_RECOVERY_PROOF_FINGERPRINT_MISMATCH")
        if not (record.valid_from <= now.astimezone(timezone.utc) < record.expires_at):
            raise RecoveryEventError("RECOVERY_EVENT_EXPIRED_OR_NOT_YET_VALID")
        payload = self.payload_from_record(record)
        event_id = f"risk-state-recovery:event:{record.recovery_event_id}"
        existing = self.store.get(event_id)
        if existing is not None:
            if existing.event_type != self.RECORDED:
                raise RecoveryEventError("RECOVERY_EVENT_TYPE_CONFLICT")
            if self.fingerprint_from_payload(existing.payload) != self.fingerprint_from_payload(payload):
                raise RecoveryEventError("RECOVERY_EVENT_ID_CONFLICT")
            return self._from_payload(existing.payload)
        try:
            result = self.store.append(
                event_id=event_id,
                occurred_at_ms=record.recorded_at_ms,
                event_type=self.RECORDED,
                aggregate_id=record.recovery_event_id,
                payload=payload,
            )
        except RuntimeError as exc:
            if str(exc) != "EVENT_APPEND_CONFLICT":
                raise
            existing = self.store.get(event_id)
            if existing is None:
                raise RecoveryEventError("RECOVERY_EVENT_CONCURRENT_APPEND_UNRESOLVED") from exc
            if self.fingerprint_from_payload(existing.payload) != self.fingerprint_from_payload(payload):
                raise RecoveryEventError("RECOVERY_EVENT_CONCURRENT_CONFLICT") from exc
            return self._from_payload(existing.payload)
        if not self.store.verify_chain():
            raise RecoveryEventError("RECOVERY_EVENT_EVENT_CHAIN_INVALID")
        return self._from_payload(result.event.payload)

    def get(self, recovery_event_id: str) -> RiskStateRecoveryEventRecord | None:
        if not self.store.verify_chain():
            raise RecoveryEventError("RECOVERY_EVENT_EVENT_CHAIN_INVALID")
        event = self.store.get(f"risk-state-recovery:event:{recovery_event_id}")
        if event is None:
            return None
        if event.event_type != self.RECORDED:
            raise RecoveryEventError("RECOVERY_EVENT_TYPE_MISMATCH")
        return self._from_payload(event.payload)
