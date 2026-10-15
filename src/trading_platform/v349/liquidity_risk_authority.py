from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from trading_platform.v349.liquidity_registry import get_production_liquidity_method


class LiquidityRiskError(RuntimeError):
    """Raised when liquidity semantics would permit unsafe risk increase."""


@dataclass(frozen=True)
class LiquidityRiskBinding:
    liquidity_stress: Decimal
    max_stress: Decimal
    floor: Decimal
    baseline_risk: Decimal
    allowed_risk: Decimal
    risk_factor: Decimal
    method: str
    method_version: str

    @property
    def worsens_with_liquidity_stress(self) -> bool:
        return self.risk_factor <= Decimal("1")


def _decimal(value: Decimal | int | float | str, error: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise LiquidityRiskError(error) from exc
    if not out.is_finite():
        raise LiquidityRiskError(error)
    return out


def conservative_liquidity_factor_decimal(
    liquidity_stress: Decimal | int | float | str,
    *,
    max_stress: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
) -> Decimal:
    stress = _decimal(liquidity_stress, "INVALID_LIQUIDITY_STRESS")
    maximum = _decimal(max_stress, "INVALID_MAX_LIQUIDITY_STRESS")
    minimum_factor = _decimal(floor, "INVALID_LIQUIDITY_FLOOR")
    if stress < 0 or maximum <= 0 or minimum_factor < 0 or minimum_factor > 1:
        raise LiquidityRiskError("INVALID_LIQUIDITY_CONFIGURATION")
    normalized = min(Decimal("1"), stress / maximum)
    return max(minimum_factor, Decimal("1") - normalized)


def bind_liquidity_to_risk(
    *,
    liquidity_stress: Decimal | int | float | str,
    baseline_risk: Decimal | int | float | str,
    max_stress: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
    method: str = "CONSERVATIVE_LINEAR",
    method_version: str = "1",
) -> LiquidityRiskBinding:
    if not method or not method_version:
        raise LiquidityRiskError("LIQUIDITY_METHOD_IDENTITY_REQUIRED")
    try:
        get_production_liquidity_method(method, method_version)
    except ValueError as exc:
        raise LiquidityRiskError(str(exc)) from exc
    baseline = _decimal(baseline_risk, "INVALID_BASELINE_RISK")
    if baseline < 0:
        raise LiquidityRiskError("INVALID_BASELINE_RISK")
    factor = conservative_liquidity_factor_decimal(
        liquidity_stress,
        max_stress=max_stress,
        floor=floor,
    )
    return LiquidityRiskBinding(
        liquidity_stress=_decimal(liquidity_stress, "INVALID_LIQUIDITY_STRESS"),
        max_stress=_decimal(max_stress, "INVALID_MAX_LIQUIDITY_STRESS"),
        floor=_decimal(floor, "INVALID_LIQUIDITY_FLOOR"),
        baseline_risk=baseline,
        allowed_risk=baseline * factor,
        risk_factor=factor,
        method=method,
        method_version=method_version,
    )


def assert_liquidity_monotone(
    *,
    lower_liquidity_stress: Decimal | int | float | str,
    lower_allowed_risk: Decimal | int | float | str,
    higher_liquidity_stress: Decimal | int | float | str,
    higher_allowed_risk: Decimal | int | float | str,
) -> None:
    low_stress = _decimal(lower_liquidity_stress, "INVALID_LOW_LIQUIDITY_STRESS")
    high_stress = _decimal(higher_liquidity_stress, "INVALID_HIGH_LIQUIDITY_STRESS")
    low_risk = _decimal(lower_allowed_risk, "INVALID_LOW_ALLOWED_RISK")
    high_risk = _decimal(higher_allowed_risk, "INVALID_HIGH_ALLOWED_RISK")
    if high_stress < low_stress:
        raise LiquidityRiskError("LIQUIDITY_COMPARISON_NOT_ORDERED")
    if high_risk > low_risk:
        raise LiquidityRiskError("RISK_MONOTONICITY_BREACH_LIQUIDITY")


def validate_liquidity_factor(factor: Decimal | int | float | str) -> Decimal:
    value = _decimal(factor, "INVALID_LIQUIDITY_FACTOR")
    if value < 0 or value > 1:
        raise LiquidityRiskError("LIQUIDITY_FACTOR_MUST_BE_NONINCREASING")
    return value
