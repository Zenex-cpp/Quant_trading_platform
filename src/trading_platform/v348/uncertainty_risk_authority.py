from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from trading_platform.v348.uncertainty_registry import get_production_uncertainty_method


class UncertaintyRiskError(RuntimeError):
    """Raised when uncertainty semantics would permit unsafe risk increase."""


@dataclass(frozen=True)
class UncertaintyRiskBinding:
    uncertainty: Decimal
    max_uncertainty: Decimal
    floor: Decimal
    baseline_risk: Decimal
    allowed_risk: Decimal
    risk_factor: Decimal
    method: str
    method_version: str

    @property
    def worsens_with_uncertainty(self) -> bool:
        return self.risk_factor <= Decimal("1")


def _decimal(value: Decimal | int | float | str, error: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise UncertaintyRiskError(error) from exc
    if not out.is_finite():
        raise UncertaintyRiskError(error)
    return out


def conservative_risk_factor_decimal(
    uncertainty: Decimal | int | float | str,
    *,
    max_uncertainty: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
) -> Decimal:
    u = _decimal(uncertainty, "INVALID_UNCERTAINTY")
    m = _decimal(max_uncertainty, "INVALID_MAX_UNCERTAINTY")
    f = _decimal(floor, "INVALID_UNCERTAINTY_FLOOR")
    if u < 0 or m <= 0 or f < 0 or f > 1:
        raise UncertaintyRiskError("INVALID_UNCERTAINTY_CONFIGURATION")
    normalized = min(Decimal("1"), u / m)
    return max(f, Decimal("1") - normalized)


def bind_uncertainty_to_risk(
    *,
    uncertainty: Decimal | int | float | str,
    baseline_risk: Decimal | int | float | str,
    max_uncertainty: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
    method: str = "CONSERVATIVE_LINEAR",
    method_version: str = "1",
) -> UncertaintyRiskBinding:
    if not method or not method_version:
        raise UncertaintyRiskError("UNCERTAINTY_METHOD_IDENTITY_REQUIRED")
    try:
        get_production_uncertainty_method(method, method_version)
    except ValueError as exc:
        raise UncertaintyRiskError(str(exc)) from exc
    baseline = _decimal(baseline_risk, "INVALID_BASELINE_RISK")
    if baseline < 0:
        raise UncertaintyRiskError("INVALID_BASELINE_RISK")
    factor = conservative_risk_factor_decimal(
        uncertainty,
        max_uncertainty=max_uncertainty,
        floor=floor,
    )
    allowed = baseline * factor
    return UncertaintyRiskBinding(
        uncertainty=_decimal(uncertainty, "INVALID_UNCERTAINTY"),
        max_uncertainty=_decimal(max_uncertainty, "INVALID_MAX_UNCERTAINTY"),
        floor=_decimal(floor, "INVALID_UNCERTAINTY_FLOOR"),
        baseline_risk=baseline,
        allowed_risk=allowed,
        risk_factor=factor,
        method=method,
        method_version=method_version,
    )


def assert_uncertainty_monotone(
    *,
    lower_uncertainty: Decimal | int | float | str,
    lower_allowed_risk: Decimal | int | float | str,
    higher_uncertainty: Decimal | int | float | str,
    higher_allowed_risk: Decimal | int | float | str,
) -> None:
    low_u = _decimal(lower_uncertainty, "INVALID_LOW_UNCERTAINTY")
    high_u = _decimal(higher_uncertainty, "INVALID_HIGH_UNCERTAINTY")
    low_r = _decimal(lower_allowed_risk, "INVALID_LOW_ALLOWED_RISK")
    high_r = _decimal(higher_allowed_risk, "INVALID_HIGH_ALLOWED_RISK")
    if high_u < low_u:
        raise UncertaintyRiskError("UNCERTAINTY_COMPARISON_NOT_ORDERED")
    if high_r > low_r:
        raise UncertaintyRiskError("RISK_MONOTONICITY_BREACH_UNCERTAINTY")


def validate_uncertainty_factor(factor: Decimal | int | float | str) -> Decimal:
    f = _decimal(factor, "INVALID_UNCERTAINTY_FACTOR")
    if f < 0 or f > 1:
        raise UncertaintyRiskError("UNCERTAINTY_FACTOR_MUST_BE_NONINCREASING")
    return f
