from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore
from trading_platform.v25.health import HealthAssessment, HealthState


class RiskDecisionConflict(RuntimeError):
    """The durable risk decision cannot safely satisfy the requested operation."""


class RiskDecisionReplayError(RuntimeError):
    """The durable risk-decision history cannot be reconstructed safely."""


class RiskDecisionAction(str, Enum):
    ALLOW = "ALLOW"
    REDUCE = "REDUCE"
    REJECT = "REJECT"
    EXIT = "EXIT"
    EMERGENCY_HALT = "EMERGENCY_HALT"


class RiskSystemState(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"
    EMERGENCY = "EMERGENCY"
    RECOVERY = "RECOVERY"


@dataclass(frozen=True)
class RiskDecisionRecord:
    decision_id: str
    action: RiskDecisionAction
    risk_state: RiskSystemState
    requested_exposure: Decimal
    allowed_exposure: Decimal
    active_limits: Mapping[str, Decimal]
    multipliers: Mapping[str, Decimal]
    rejection_reason: str | None
    reservation_id: str | None
    intent_id: str
    created_at_ms: int
    valid_from_ms: int
    expires_at_ms: int
    configuration_version: str
    risk_state_version: str
    portfolio_version: str
    position_version: str
    provenance_id: str
    truth_hash: str
    input_fingerprint: str
    uncertainty: Decimal | None = None
    uncertainty_max: Decimal | None = None
    uncertainty_floor: Decimal = Decimal("0")
    uncertainty_risk_factor: Decimal | None = None
    uncertainty_method: str | None = None
    uncertainty_method_version: str | None = None
    liquidity_stress: Decimal | None = None
    liquidity_max: Decimal | None = None
    liquidity_floor: Decimal = Decimal("0")
    liquidity_risk_factor: Decimal | None = None
    liquidity_method: str | None = None
    liquidity_method_version: str | None = None
    drawdown: Decimal | None = None
    drawdown_max: Decimal | None = None
    drawdown_floor: Decimal = Decimal("0")
    drawdown_risk_factor: Decimal | None = None
    drawdown_method: str | None = None
    drawdown_method_version: str | None = None
    model_health: Decimal | None = None
    model_health_max: Decimal | None = None
    model_health_floor: Decimal = Decimal("0")
    model_health_risk_factor: Decimal | None = None
    model_health_method: str | None = None
    model_health_method_version: str | None = None
    model_health_assessment_id: str | None = None
    model_health_state: str | None = None
    model_health_evidence_fresh: bool | None = None
    model_health_drift_critical: bool | None = None
    model_health_quality_ok: bool | None = None
    risk_state_factor: Decimal = Decimal("1")
    recovery_event_id: str | None = None

    def payload(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "action": self.action.value,
            "risk_state": self.risk_state.value,
            "requested_exposure": str(self.requested_exposure),
            "allowed_exposure": str(self.allowed_exposure),
            "active_limits": {k: str(v) for k, v in sorted(self.active_limits.items())},
            "multipliers": {k: str(v) for k, v in sorted(self.multipliers.items())},
            "rejection_reason": self.rejection_reason,
            "reservation_id": self.reservation_id,
            "intent_id": self.intent_id,
            "created_at_ms": self.created_at_ms,
            "valid_from_ms": self.valid_from_ms,
            "expires_at_ms": self.expires_at_ms,
            "configuration_version": self.configuration_version,
            "risk_state_version": self.risk_state_version,
            "portfolio_version": self.portfolio_version,
            "position_version": self.position_version,
            "provenance_id": self.provenance_id,
            "truth_hash": self.truth_hash,
            "input_fingerprint": self.input_fingerprint,
            "uncertainty": None if self.uncertainty is None else str(self.uncertainty),
            "uncertainty_max": None if self.uncertainty_max is None else str(self.uncertainty_max),
            "uncertainty_floor": str(self.uncertainty_floor),
            "uncertainty_risk_factor": None if self.uncertainty_risk_factor is None else str(self.uncertainty_risk_factor),
            "uncertainty_method": self.uncertainty_method,
            "uncertainty_method_version": self.uncertainty_method_version,
            "liquidity_stress": None if self.liquidity_stress is None else str(self.liquidity_stress),
            "liquidity_max": None if self.liquidity_max is None else str(self.liquidity_max),
            "liquidity_floor": str(self.liquidity_floor),
            "liquidity_risk_factor": None if self.liquidity_risk_factor is None else str(self.liquidity_risk_factor),
            "liquidity_method": self.liquidity_method,
            "liquidity_method_version": self.liquidity_method_version,
            "drawdown": None if self.drawdown is None else str(self.drawdown),
            "drawdown_max": None if self.drawdown_max is None else str(self.drawdown_max),
            "drawdown_floor": str(self.drawdown_floor),
            "drawdown_risk_factor": None if self.drawdown_risk_factor is None else str(self.drawdown_risk_factor),
            "drawdown_method": self.drawdown_method,
            "drawdown_method_version": self.drawdown_method_version,
            "model_health": None if self.model_health is None else str(self.model_health),
            "model_health_max": None if self.model_health_max is None else str(self.model_health_max),
            "model_health_floor": str(self.model_health_floor),
            "model_health_risk_factor": None if self.model_health_risk_factor is None else str(self.model_health_risk_factor),
            "model_health_method": self.model_health_method,
            "model_health_method_version": self.model_health_method_version,
            "model_health_assessment_id": self.model_health_assessment_id,
            "model_health_state": self.model_health_state,
            "model_health_evidence_fresh": self.model_health_evidence_fresh,
            "model_health_drift_critical": self.model_health_drift_critical,
            "model_health_quality_ok": self.model_health_quality_ok,
            "risk_state_factor": str(self.risk_state_factor),
            "recovery_event_id": self.recovery_event_id,
        }

    @property
    def fingerprint(self) -> str:
        body = dict(self.payload())
        body.pop("decision_id", None)
        return sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class RiskDecisionGateSnapshot:
    decision_id: str
    action: RiskDecisionAction
    risk_state: RiskSystemState
    valid_from_ms: int
    expires_at_ms: int
    reservation_id: str | None
    truth_hash: str
    uncertainty: Decimal | None = None
    uncertainty_risk_factor: Decimal | None = None
    liquidity_stress: Decimal | None = None
    liquidity_risk_factor: Decimal | None = None
    drawdown: Decimal | None = None
    drawdown_risk_factor: Decimal | None = None
    model_health: Decimal | None = None
    model_health_risk_factor: Decimal | None = None
    model_health_assessment_id: str | None = None


class DurableRiskDecisionLedger:
    """Append-only, hash-chained, restart-safe risk-decision ledger."""

    RECORDED = "RISK_DECISION_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def record(self, decision: RiskDecisionRecord) -> RiskDecisionRecord:
        self._validate(decision)
        existing = self.store.get(f"risk-decision:record:{decision.decision_id}")
        if existing is not None:
            if existing.event_type != self.RECORDED:
                raise RiskDecisionReplayError("RISK_DECISION_EVENT_ID_COLLISION")
            if dict(existing.payload) != decision.payload():
                raise RiskDecisionConflict("RISK_DECISION_ID_PAYLOAD_CONFLICT")
            return self._record_from_payload(existing.payload)
        result = self.store.append(
            event_id=f"risk-decision:record:{decision.decision_id}",
            occurred_at_ms=decision.created_at_ms,
            event_type=self.RECORDED,
            aggregate_id=decision.decision_id,
            payload=decision.payload(),
        )
        if result.duplicate and dict(result.event.payload) != decision.payload():
            raise RiskDecisionConflict("RISK_DECISION_ID_PAYLOAD_CONFLICT")
        return decision

    def restore(self) -> dict[str, RiskDecisionRecord]:
        if not self.store.verify_chain():
            raise RiskDecisionReplayError("RISK_DECISION_EVENT_CHAIN_INVALID")
        decisions: dict[str, RiskDecisionRecord] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED:
                raise RiskDecisionReplayError(f"UNKNOWN_RISK_DECISION_EVENT_TYPE:{event.event_type}")
            decision = self._record_from_payload(event.payload)
            if decision.decision_id in decisions:
                raise RiskDecisionReplayError("DUPLICATE_RISK_DECISION_ID")
            decisions[decision.decision_id] = decision
        return decisions

    def get(self, decision_id: str) -> RiskDecisionRecord | None:
        decisions = self.restore()
        return decisions.get(decision_id)

    def decisions(self) -> tuple[RiskDecisionRecord, ...]:
        values = self.restore().values()
        return tuple(sorted(values, key=lambda d: d.decision_id))

    def assert_valid_for_new_risk(
        self,
        *,
        decision_id: str,
        now_ms: int,
        intent_id: str,
        reservation_id: str | None,
        requested_exposure: Decimal,
        truth_hash: str,
        configuration_version: str | None = None,
        risk_state_version: str | None = None,
        portfolio_version: str | None = None,
        position_version: str | None = None,
        uncertainty: Decimal | None = None,
        liquidity_stress: Decimal | None = None,
        drawdown: Decimal | None = None,
        model_health: Decimal | None = None,
        model_health_assessment_id: str | None = None,
    ) -> RiskDecisionGateSnapshot:
        decision = self.get(decision_id)
        if decision is None:
            raise RiskDecisionConflict("RISK_DECISION_NOT_FOUND")
        if decision.action is not RiskDecisionAction.ALLOW:
            raise RiskDecisionConflict(f"RISK_DECISION_ACTION_DENIED:{decision.action.value}")
        if decision.risk_state in {RiskSystemState.FROZEN, RiskSystemState.EMERGENCY, RiskSystemState.RECOVERY}:
            raise RiskDecisionConflict(f"RISK_DECISION_STATE_DENIED:{decision.risk_state.value}")
        if not (decision.valid_from_ms <= now_ms < decision.expires_at_ms):
            raise RiskDecisionConflict("RISK_DECISION_EXPIRED_OR_NOT_YET_VALID")
        if decision.intent_id != intent_id:
            raise RiskDecisionConflict("RISK_DECISION_INTENT_MISMATCH")
        if decision.reservation_id != reservation_id:
            raise RiskDecisionConflict("RISK_DECISION_RESERVATION_MISMATCH")
        requested = self._amount(requested_exposure, "INVALID_REQUESTED_EXPOSURE")
        if requested > decision.allowed_exposure:
            raise RiskDecisionConflict("RISK_DECISION_EXPOSURE_LIMIT")
        if decision.uncertainty is not None:
            if uncertainty is None:
                raise RiskDecisionConflict("RISK_DECISION_UNCERTAINTY_REQUIRED")
            current_uncertainty = DurableRiskDecisionLedger._amount(uncertainty, "INVALID_UNCERTAINTY")
            if current_uncertainty != decision.uncertainty:
                raise RiskDecisionConflict("RISK_DECISION_UNCERTAINTY_STALE")
        elif uncertainty is not None:
            raise RiskDecisionConflict("RISK_DECISION_UNCERTAINTY_PROVENANCE_MISSING")
        if decision.liquidity_stress is not None:
            if liquidity_stress is None:
                raise RiskDecisionConflict("RISK_DECISION_LIQUIDITY_REQUIRED")
            current_liquidity = DurableRiskDecisionLedger._amount(liquidity_stress, "INVALID_LIQUIDITY_STRESS")
            if current_liquidity != decision.liquidity_stress:
                raise RiskDecisionConflict("RISK_DECISION_LIQUIDITY_STALE")
        elif liquidity_stress is not None:
            raise RiskDecisionConflict("RISK_DECISION_LIQUIDITY_PROVENANCE_MISSING")
        if decision.drawdown is not None:
            if drawdown is None:
                raise RiskDecisionConflict("RISK_DECISION_DRAWDOWN_REQUIRED")
            current_drawdown = DurableRiskDecisionLedger._amount(drawdown, "INVALID_DRAWDOWN")
            if current_drawdown != decision.drawdown:
                raise RiskDecisionConflict("RISK_DECISION_DRAWDOWN_STALE")
        elif drawdown is not None:
            raise RiskDecisionConflict("RISK_DECISION_DRAWDOWN_PROVENANCE_MISSING")
        if decision.model_health is not None:
            if model_health is None:
                raise RiskDecisionConflict("RISK_DECISION_MODEL_HEALTH_REQUIRED")
            current_health = DurableRiskDecisionLedger._amount(model_health, "INVALID_MODEL_HEALTH")
            if current_health != decision.model_health:
                raise RiskDecisionConflict("RISK_DECISION_MODEL_HEALTH_STALE")
            if model_health_assessment_id is None:
                raise RiskDecisionConflict("RISK_DECISION_MODEL_HEALTH_ASSESSMENT_REQUIRED")
            if model_health_assessment_id != decision.model_health_assessment_id:
                raise RiskDecisionConflict("RISK_DECISION_MODEL_HEALTH_ASSESSMENT_STALE")
        elif model_health is not None or model_health_assessment_id is not None:
            raise RiskDecisionConflict("RISK_DECISION_MODEL_HEALTH_PROVENANCE_MISSING")
        if decision.truth_hash != truth_hash:
            raise RiskDecisionConflict("RISK_DECISION_TRUTH_HASH_STALE")
        checks = (
            ("configuration_version", configuration_version),
            ("risk_state_version", risk_state_version),
            ("portfolio_version", portfolio_version),
            ("position_version", position_version),
        )
        for name, expected in checks:
            actual = getattr(decision, name)
            if expected is not None and actual != expected:
                raise RiskDecisionConflict(f"RISK_DECISION_{name.upper()}_MISMATCH")
        return RiskDecisionGateSnapshot(
            decision_id=decision.decision_id,
            action=decision.action,
            risk_state=decision.risk_state,
            valid_from_ms=decision.valid_from_ms,
            expires_at_ms=decision.expires_at_ms,
            reservation_id=decision.reservation_id,
            truth_hash=decision.truth_hash,
            uncertainty=decision.uncertainty,
            uncertainty_risk_factor=decision.uncertainty_risk_factor,
            liquidity_stress=decision.liquidity_stress,
            liquidity_risk_factor=decision.liquidity_risk_factor,
            drawdown=decision.drawdown,
            drawdown_risk_factor=decision.drawdown_risk_factor,
            model_health=decision.model_health,
            model_health_risk_factor=decision.model_health_risk_factor,
            model_health_assessment_id=decision.model_health_assessment_id,
        )

    @staticmethod
    def _validate(decision: RiskDecisionRecord) -> None:
        if not decision.decision_id or not decision.intent_id or not decision.risk_state_version:
            raise ValueError("INVALID_RISK_DECISION_IDENTITY")
        if not decision.configuration_version or not decision.portfolio_version or not decision.position_version:
            raise ValueError("INVALID_RISK_DECISION_VERSIONS")
        if not decision.provenance_id or not decision.truth_hash or not decision.input_fingerprint:
            raise ValueError("INVALID_RISK_DECISION_PROVENANCE")
        requested = DurableRiskDecisionLedger._amount(decision.requested_exposure, "INVALID_REQUESTED_EXPOSURE")
        allowed = DurableRiskDecisionLedger._amount(decision.allowed_exposure, "INVALID_ALLOWED_EXPOSURE")
        if allowed > requested:
            raise ValueError("RISK_ALLOWED_EXCEEDS_REQUESTED")
        from trading_platform.v356.risk_state_monotonicity import conservative_state_risk_factor
        expected_state_factor = conservative_state_risk_factor(decision.risk_state)
        state_factor = DurableRiskDecisionLedger._amount(decision.risk_state_factor, "INVALID_RISK_STATE_FACTOR")
        if state_factor > 1:
            raise ValueError("RISK_STATE_FACTOR_MUST_BE_NONINCREASING")
        if decision.recovery_event_id is None and state_factor != expected_state_factor:
            raise ValueError("RISK_STATE_FACTOR_MISMATCH")
        if decision.recovery_event_id is None and allowed > requested * expected_state_factor:
            raise ValueError("RISK_ALLOWED_EXCEEDS_RISK_STATE_CAP")
        if decision.uncertainty is not None:
            if decision.uncertainty_max is None:
                raise ValueError("UNCERTAINTY_MAX_REQUIRED")
            if not decision.uncertainty_method or not decision.uncertainty_method_version:
                raise ValueError("UNCERTAINTY_METHOD_IDENTITY_REQUIRED")
            try:
                from trading_platform.v348.uncertainty_risk_authority import bind_uncertainty_to_risk
                binding = bind_uncertainty_to_risk(
                    uncertainty=decision.uncertainty, baseline_risk=requested,
                    max_uncertainty=decision.uncertainty_max, floor=decision.uncertainty_floor,
                    method=decision.uncertainty_method, method_version=decision.uncertainty_method_version,
                )
            except Exception as exc:
                raise ValueError("INVALID_UNCERTAINTY_RISK_BINDING") from exc
            if decision.uncertainty_risk_factor is None or decision.uncertainty_risk_factor != binding.risk_factor:
                raise ValueError("UNCERTAINTY_RISK_FACTOR_MISMATCH")
            if allowed > binding.allowed_risk:
                raise ValueError("RISK_ALLOWED_EXCEEDS_UNCERTAINTY_CAP")
        elif any(v is not None for v in (decision.uncertainty_max, decision.uncertainty_risk_factor, decision.uncertainty_method, decision.uncertainty_method_version)):
            raise ValueError("UNCERTAINTY_PROVENANCE_INCOMPLETE")
        elif decision.uncertainty_floor != Decimal("0"):
            raise ValueError("UNCERTAINTY_FLOOR_WITHOUT_UNCERTAINTY")
        if decision.liquidity_stress is not None:
            if decision.liquidity_max is None:
                raise ValueError("LIQUIDITY_MAX_REQUIRED")
            if not decision.liquidity_method or not decision.liquidity_method_version:
                raise ValueError("LIQUIDITY_METHOD_IDENTITY_REQUIRED")
            try:
                from trading_platform.v349.liquidity_risk_authority import bind_liquidity_to_risk
                binding = bind_liquidity_to_risk(
                    liquidity_stress=decision.liquidity_stress, baseline_risk=requested,
                    max_stress=decision.liquidity_max, floor=decision.liquidity_floor,
                    method=decision.liquidity_method, method_version=decision.liquidity_method_version,
                )
            except Exception as exc:
                raise ValueError("INVALID_LIQUIDITY_RISK_BINDING") from exc
            if decision.liquidity_risk_factor is None or decision.liquidity_risk_factor != binding.risk_factor:
                raise ValueError("LIQUIDITY_RISK_FACTOR_MISMATCH")
            if allowed > binding.allowed_risk:
                raise ValueError("RISK_ALLOWED_EXCEEDS_LIQUIDITY_CAP")
        elif any(v is not None for v in (decision.liquidity_max, decision.liquidity_risk_factor, decision.liquidity_method, decision.liquidity_method_version)):
            raise ValueError("LIQUIDITY_PROVENANCE_INCOMPLETE")
        elif decision.liquidity_floor != Decimal("0"):
            raise ValueError("LIQUIDITY_FLOOR_WITHOUT_LIQUIDITY")
        if decision.drawdown is not None:
            if decision.drawdown_max is None:
                raise ValueError("DRAWDOWN_MAX_REQUIRED")
            if not decision.drawdown_method or not decision.drawdown_method_version:
                raise ValueError("DRAWDOWN_METHOD_IDENTITY_REQUIRED")
            try:
                from trading_platform.v350.drawdown_risk_authority import bind_drawdown_to_risk
                binding = bind_drawdown_to_risk(
                    drawdown=decision.drawdown, baseline_risk=requested,
                    max_drawdown=decision.drawdown_max, floor=decision.drawdown_floor,
                    method=decision.drawdown_method, method_version=decision.drawdown_method_version,
                )
            except Exception as exc:
                raise ValueError("INVALID_DRAWDOWN_RISK_BINDING") from exc
            if decision.drawdown_risk_factor is None or decision.drawdown_risk_factor != binding.risk_factor:
                raise ValueError("DRAWDOWN_RISK_FACTOR_MISMATCH")
            if allowed > binding.allowed_risk:
                raise ValueError("RISK_ALLOWED_EXCEEDS_DRAWDOWN_CAP")
        elif any(v is not None for v in (decision.drawdown_max, decision.drawdown_risk_factor, decision.drawdown_method, decision.drawdown_method_version)):
            raise ValueError("DRAWDOWN_PROVENANCE_INCOMPLETE")
        elif decision.drawdown_floor != Decimal("0"):
            raise ValueError("DRAWDOWN_FLOOR_WITHOUT_DRAWDOWN")
        if decision.model_health is not None:
            if decision.model_health_max is None:
                raise ValueError("MODEL_HEALTH_MAX_REQUIRED")
            if not decision.model_health_method or not decision.model_health_method_version:
                raise ValueError("MODEL_HEALTH_METHOD_IDENTITY_REQUIRED")
            if not decision.model_health_assessment_id or decision.model_health_state is None:
                raise ValueError("MODEL_HEALTH_ASSESSMENT_PROVENANCE_REQUIRED")
            if decision.model_health_evidence_fresh is not True or decision.model_health_drift_critical is not False or decision.model_health_quality_ok is not True:
                raise ValueError("MODEL_HEALTH_ASSESSMENT_NOT_SAFE")
            try:
                from trading_platform.v351.model_health_risk_authority import bind_model_health_to_risk
                assessment = HealthAssessment(
                    state=HealthState(str(decision.model_health_state)),
                    evidence_fresh=bool(decision.model_health_evidence_fresh),
                    drift_critical=bool(decision.model_health_drift_critical),
                    quality_ok=bool(decision.model_health_quality_ok),
                    reason="DURABLE_RESTORED",
                    assessment_id=str(decision.model_health_assessment_id),
                )
                binding = bind_model_health_to_risk(
                    model_health=decision.model_health, baseline_risk=requested,
                    assessment=assessment, assessment_id=decision.model_health_assessment_id,
                    max_model_health=decision.model_health_max, floor=decision.model_health_floor,
                    method=decision.model_health_method, method_version=decision.model_health_method_version,
                )
            except Exception as exc:
                raise ValueError("INVALID_MODEL_HEALTH_RISK_BINDING") from exc
            if decision.model_health_risk_factor is None or decision.model_health_risk_factor != binding.risk_factor:
                raise ValueError("MODEL_HEALTH_RISK_FACTOR_MISMATCH")
            if allowed > binding.allowed_risk:
                raise ValueError("RISK_ALLOWED_EXCEEDS_MODEL_HEALTH_CAP")
        elif any(v is not None for v in (decision.model_health_max, decision.model_health_risk_factor, decision.model_health_method, decision.model_health_method_version, decision.model_health_assessment_id, decision.model_health_state, decision.model_health_evidence_fresh, decision.model_health_drift_critical, decision.model_health_quality_ok)):
            raise ValueError("MODEL_HEALTH_PROVENANCE_INCOMPLETE")
        elif decision.model_health_floor != Decimal("0"):
            raise ValueError("MODEL_HEALTH_FLOOR_WITHOUT_MODEL_HEALTH")
        if decision.created_at_ms < 0 or decision.valid_from_ms < decision.created_at_ms or decision.expires_at_ms <= decision.valid_from_ms:
            raise ValueError("INVALID_RISK_DECISION_TTL")
        for field_name, values in (("active_limits", decision.active_limits), ("multipliers", decision.multipliers)):
            for key, value in values.items():
                if not key or DurableRiskDecisionLedger._amount(value, f"INVALID_{field_name.upper()}") < 0:
                    raise ValueError(f"INVALID_{field_name.upper()}")
        if decision.action is RiskDecisionAction.ALLOW and decision.allowed_exposure <= 0:
            raise ValueError("ALLOW_REQUIRES_POSITIVE_ALLOWED_EXPOSURE")
        if decision.action is not RiskDecisionAction.ALLOW and not decision.rejection_reason:
            raise ValueError("NON_ALLOW_REASON_REQUIRED")

    @staticmethod
    def _amount(value: Decimal, error: str) -> Decimal:
        try:
            out = Decimal(str(value))
        except Exception as exc:
            raise ValueError(error) from exc
        if not out.is_finite() or out < 0:
            raise ValueError(error)
        return out

    @staticmethod
    def _record_from_payload(payload: Mapping[str, Any]) -> RiskDecisionRecord:
        try:
            return RiskDecisionRecord(
                decision_id=str(payload["decision_id"]),
                action=RiskDecisionAction(str(payload["action"])),
                risk_state=RiskSystemState(str(payload["risk_state"])),
                requested_exposure=Decimal(str(payload["requested_exposure"])),
                allowed_exposure=Decimal(str(payload["allowed_exposure"])),
                active_limits={str(k): Decimal(str(v)) for k, v in dict(payload["active_limits"]).items()},
                multipliers={str(k): Decimal(str(v)) for k, v in dict(payload["multipliers"]).items()},
                rejection_reason=None if payload.get("rejection_reason") is None else str(payload["rejection_reason"]),
                reservation_id=None if payload.get("reservation_id") is None else str(payload["reservation_id"]),
                intent_id=str(payload["intent_id"]),
                created_at_ms=int(payload["created_at_ms"]),
                valid_from_ms=int(payload["valid_from_ms"]),
                expires_at_ms=int(payload["expires_at_ms"]),
                configuration_version=str(payload["configuration_version"]),
                risk_state_version=str(payload["risk_state_version"]),
                portfolio_version=str(payload["portfolio_version"]),
                position_version=str(payload["position_version"]),
                provenance_id=str(payload["provenance_id"]),
                truth_hash=str(payload["truth_hash"]),
                input_fingerprint=str(payload["input_fingerprint"]),
                uncertainty=None if payload.get("uncertainty") is None else Decimal(str(payload["uncertainty"])),
                uncertainty_max=None if payload.get("uncertainty_max") is None else Decimal(str(payload["uncertainty_max"])),
                uncertainty_floor=Decimal(str(payload.get("uncertainty_floor", "0"))),
                uncertainty_risk_factor=None if payload.get("uncertainty_risk_factor") is None else Decimal(str(payload["uncertainty_risk_factor"])),
                uncertainty_method=None if payload.get("uncertainty_method") is None else str(payload["uncertainty_method"]),
                uncertainty_method_version=None if payload.get("uncertainty_method_version") is None else str(payload["uncertainty_method_version"]),
                liquidity_stress=None if payload.get("liquidity_stress") is None else Decimal(str(payload["liquidity_stress"])),
                liquidity_max=None if payload.get("liquidity_max") is None else Decimal(str(payload["liquidity_max"])),
                liquidity_floor=Decimal(str(payload.get("liquidity_floor", "0"))),
                liquidity_risk_factor=None if payload.get("liquidity_risk_factor") is None else Decimal(str(payload["liquidity_risk_factor"])),
                liquidity_method=None if payload.get("liquidity_method") is None else str(payload["liquidity_method"]),
                liquidity_method_version=None if payload.get("liquidity_method_version") is None else str(payload["liquidity_method_version"]),
                drawdown=None if payload.get("drawdown") is None else Decimal(str(payload["drawdown"])),
                drawdown_max=None if payload.get("drawdown_max") is None else Decimal(str(payload["drawdown_max"])),
                drawdown_floor=Decimal(str(payload.get("drawdown_floor", "0"))),
                drawdown_risk_factor=None if payload.get("drawdown_risk_factor") is None else Decimal(str(payload["drawdown_risk_factor"])),
                drawdown_method=None if payload.get("drawdown_method") is None else str(payload["drawdown_method"]),
                drawdown_method_version=None if payload.get("drawdown_method_version") is None else str(payload["drawdown_method_version"]),
                model_health=None if payload.get("model_health") is None else Decimal(str(payload["model_health"])),
                model_health_max=None if payload.get("model_health_max") is None else Decimal(str(payload["model_health_max"])),
                model_health_floor=Decimal(str(payload.get("model_health_floor", "0"))),
                model_health_risk_factor=None if payload.get("model_health_risk_factor") is None else Decimal(str(payload["model_health_risk_factor"])),
                model_health_method=None if payload.get("model_health_method") is None else str(payload["model_health_method"]),
                model_health_method_version=None if payload.get("model_health_method_version") is None else str(payload["model_health_method_version"]),
                model_health_assessment_id=None if payload.get("model_health_assessment_id") is None else str(payload["model_health_assessment_id"]),
                model_health_state=None if payload.get("model_health_state") is None else str(payload["model_health_state"]),
                model_health_evidence_fresh=None if payload.get("model_health_evidence_fresh") is None else bool(payload["model_health_evidence_fresh"]),
                model_health_drift_critical=None if payload.get("model_health_drift_critical") is None else bool(payload["model_health_drift_critical"]),
                model_health_quality_ok=None if payload.get("model_health_quality_ok") is None else bool(payload["model_health_quality_ok"]),
                risk_state_factor=Decimal(str(payload.get("risk_state_factor", "1"))),
                recovery_event_id=None if payload.get("recovery_event_id") is None else str(payload["recovery_event_id"]),
            )
        except Exception as exc:
            raise RiskDecisionReplayError("INVALID_RISK_DECISION_PAYLOAD") from exc
