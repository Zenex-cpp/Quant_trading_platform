from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from trading_platform.v25.health import EvidenceFreshness, HealthAssessment, HealthState
from trading_platform.v351.model_health_registry import get_production_model_health_method


class ModelHealthRiskError(RuntimeError):
    """Raised when model-health semantics would permit unsafe risk increase."""


@dataclass(frozen=True)
class ModelHealthRiskBinding:
    model_health: Decimal
    max_model_health: Decimal
    floor: Decimal
    baseline_risk: Decimal
    allowed_risk: Decimal
    risk_factor: Decimal
    method: str
    method_version: str
    assessment_id: str
    source_fingerprint: str
    health_state: HealthState

    @property
    def worsens_with_model_health_degradation(self) -> bool:
        return self.risk_factor <= Decimal("1")


def _decimal(value: Decimal | int | float | str, error: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ModelHealthRiskError(error) from exc
    if not out.is_finite():
        raise ModelHealthRiskError(error)
    return out


def _validate_assessment(assessment: HealthAssessment, assessment_id: str, now_ns: int | None = None) -> None:
    if not assessment_id:
        raise ModelHealthRiskError("MODEL_HEALTH_ASSESSMENT_ID_REQUIRED")
    if getattr(assessment, "assessment_id", None) != assessment_id:
        raise ModelHealthRiskError("MODEL_HEALTH_ASSESSMENT_ID_MISMATCH")
    if not getattr(assessment, "evidence_fresh", False):
        raise ModelHealthRiskError("MODEL_HEALTH_EVIDENCE_STALE")
    if getattr(assessment, "drift_critical", True) or not getattr(assessment, "quality_ok", False):
        raise ModelHealthRiskError("MODEL_HEALTH_ASSESSMENT_NOT_SAFE")
    state = getattr(assessment, "state", HealthState.UNKNOWN)
    if state not in {HealthState.HEALTHY, HealthState.DEGRADED}:
        state_name = getattr(state, "value", str(state))
        raise ModelHealthRiskError(f"MODEL_HEALTH_STATE_NOT_APPLICABLE:{state_name}")
    source_evidence = getattr(assessment, "source_evidence", None)
    assessed_at_ns = getattr(assessment, "assessed_at_ns", None)
    if not isinstance(source_evidence, EvidenceFreshness) or assessed_at_ns is None:
        raise ModelHealthRiskError("MODEL_HEALTH_SOURCE_PROVENANCE_REQUIRED")
    source_fresh_at = getattr(assessment, "source_fresh_at", None)
    if not callable(source_fresh_at):
        raise ModelHealthRiskError("MODEL_HEALTH_SOURCE_PROVENANCE_REQUIRED")
    if not source_fresh_at(assessed_at_ns):
        raise ModelHealthRiskError("MODEL_HEALTH_SOURCE_EVIDENCE_INVALID")
    if now_ns is not None and not source_fresh_at(now_ns):
        raise ModelHealthRiskError("MODEL_HEALTH_SOURCE_EXPIRED")
    if not getattr(assessment, "source_fingerprint", None):
        raise ModelHealthRiskError("MODEL_HEALTH_SOURCE_FINGERPRINT_REQUIRED")


def conservative_model_health_factor_decimal(
    model_health: Decimal | int | float | str,
    *,
    max_model_health: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
) -> Decimal:
    health = _decimal(model_health, "INVALID_MODEL_HEALTH")
    maximum = _decimal(max_model_health, "INVALID_MAX_MODEL_HEALTH")
    minimum_factor = _decimal(floor, "INVALID_MODEL_HEALTH_FLOOR")
    if health < 0 or maximum <= 0 or health > maximum or minimum_factor < 0 or minimum_factor > 1:
        raise ModelHealthRiskError("INVALID_MODEL_HEALTH_CONFIGURATION")
    normalized = min(Decimal("1"), health / maximum)
    return max(minimum_factor, normalized)


def bind_model_health_to_risk(
    *,
    model_health: Decimal | int | float | str,
    baseline_risk: Decimal | int | float | str,
    assessment: HealthAssessment,
    assessment_id: str,
    max_model_health: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
    method: str = "CONSERVATIVE_LINEAR",
    method_version: str = "1",
    now_ns: int | None = None,
) -> ModelHealthRiskBinding:
    if not method or not method_version:
        raise ModelHealthRiskError("MODEL_HEALTH_METHOD_IDENTITY_REQUIRED")
    try:
        get_production_model_health_method(method, method_version)
    except ValueError as exc:
        raise ModelHealthRiskError(str(exc)) from exc
    _validate_assessment(assessment, assessment_id, now_ns)
    baseline = _decimal(baseline_risk, "INVALID_BASELINE_RISK")
    if baseline < 0:
        raise ModelHealthRiskError("INVALID_BASELINE_RISK")
    factor = conservative_model_health_factor_decimal(
        model_health,
        max_model_health=max_model_health,
        floor=floor,
    )
    return ModelHealthRiskBinding(
        model_health=_decimal(model_health, "INVALID_MODEL_HEALTH"),
        max_model_health=_decimal(max_model_health, "INVALID_MAX_MODEL_HEALTH"),
        floor=_decimal(floor, "INVALID_MODEL_HEALTH_FLOOR"),
        baseline_risk=baseline,
        allowed_risk=baseline * factor,
        risk_factor=factor,
        method=method,
        method_version=method_version,
        assessment_id=assessment_id,
        source_fingerprint=str(getattr(assessment, "source_fingerprint")),
        health_state=assessment.state,
    )


def assert_model_health_monotone(
    *,
    higher_health: Decimal | int | float | str,
    higher_allowed_risk: Decimal | int | float | str,
    lower_health: Decimal | int | float | str,
    lower_allowed_risk: Decimal | int | float | str,
) -> None:
    good_h = _decimal(higher_health, "INVALID_HIGHER_MODEL_HEALTH")
    worse_h = _decimal(lower_health, "INVALID_LOWER_MODEL_HEALTH")
    good_r = _decimal(higher_allowed_risk, "INVALID_HIGHER_ALLOWED_RISK")
    worse_r = _decimal(lower_allowed_risk, "INVALID_LOWER_ALLOWED_RISK")
    if good_h < worse_h:
        raise ModelHealthRiskError("MODEL_HEALTH_COMPARISON_NOT_ORDERED")
    if worse_r > good_r:
        raise ModelHealthRiskError("RISK_MONOTONICITY_BREACH_MODEL_HEALTH")


def validate_model_health_factor(factor: Decimal | int | float | str) -> Decimal:
    value = _decimal(factor, "INVALID_MODEL_HEALTH_FACTOR")
    if value < 0 or value > 1:
        raise ModelHealthRiskError("MODEL_HEALTH_FACTOR_MUST_BE_NONINCREASING")
    return value
