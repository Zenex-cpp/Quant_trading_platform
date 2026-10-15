from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from trading_platform.v350.drawdown_registry import get_production_drawdown_method


class DrawdownRiskError(RuntimeError):
    """Raised when drawdown semantics would permit unsafe risk increase."""


@dataclass(frozen=True)
class DrawdownRiskBinding:
    drawdown: Decimal
    max_drawdown: Decimal
    floor: Decimal
    baseline_risk: Decimal
    allowed_risk: Decimal
    risk_factor: Decimal
    method: str
    method_version: str

    @property
    def worsens_with_drawdown(self) -> bool:
        return self.risk_factor <= Decimal("1")


def _decimal(value: Decimal | int | float | str, error: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise DrawdownRiskError(error) from exc
    if not out.is_finite():
        raise DrawdownRiskError(error)
    return out


def conservative_drawdown_factor_decimal(
    drawdown: Decimal | int | float | str,
    *,
    max_drawdown: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
) -> Decimal:
    dd = _decimal(drawdown, "INVALID_DRAWDOWN")
    maximum = _decimal(max_drawdown, "INVALID_MAX_DRAWDOWN")
    minimum_factor = _decimal(floor, "INVALID_DRAWDOWN_FLOOR")
    if dd < 0 or maximum <= 0 or minimum_factor < 0 or minimum_factor > 1:
        raise DrawdownRiskError("INVALID_DRAWDOWN_CONFIGURATION")
    normalized = min(Decimal("1"), dd / maximum)
    return max(minimum_factor, Decimal("1") - normalized)


def bind_drawdown_to_risk(
    *,
    drawdown: Decimal | int | float | str,
    baseline_risk: Decimal | int | float | str,
    max_drawdown: Decimal | int | float | str = Decimal("1"),
    floor: Decimal | int | float | str = Decimal("0"),
    method: str = "CONSERVATIVE_LINEAR",
    method_version: str = "1",
) -> DrawdownRiskBinding:
    if not method or not method_version:
        raise DrawdownRiskError("DRAWDOWN_METHOD_IDENTITY_REQUIRED")
    try:
        get_production_drawdown_method(method, method_version)
    except ValueError as exc:
        raise DrawdownRiskError(str(exc)) from exc
    baseline = _decimal(baseline_risk, "INVALID_BASELINE_RISK")
    if baseline < 0:
        raise DrawdownRiskError("INVALID_BASELINE_RISK")
    factor = conservative_drawdown_factor_decimal(drawdown, max_drawdown=max_drawdown, floor=floor)
    return DrawdownRiskBinding(
        drawdown=_decimal(drawdown, "INVALID_DRAWDOWN"),
        max_drawdown=_decimal(max_drawdown, "INVALID_MAX_DRAWDOWN"),
        floor=_decimal(floor, "INVALID_DRAWDOWN_FLOOR"),
        baseline_risk=baseline,
        allowed_risk=baseline * factor,
        risk_factor=factor,
        method=method,
        method_version=method_version,
    )


def assert_drawdown_monotone(
    *,
    lower_drawdown: Decimal | int | float | str,
    lower_allowed_risk: Decimal | int | float | str,
    higher_drawdown: Decimal | int | float | str,
    higher_allowed_risk: Decimal | int | float | str,
) -> None:
    low_dd = _decimal(lower_drawdown, "INVALID_LOW_DRAWDOWN")
    high_dd = _decimal(higher_drawdown, "INVALID_HIGH_DRAWDOWN")
    low_r = _decimal(lower_allowed_risk, "INVALID_LOW_ALLOWED_RISK")
    high_r = _decimal(higher_allowed_risk, "INVALID_HIGH_ALLOWED_RISK")
    if high_dd < low_dd:
        raise DrawdownRiskError("DRAWDOWN_COMPARISON_NOT_ORDERED")
    if high_r > low_r:
        raise DrawdownRiskError("RISK_MONOTONICITY_BREACH_DRAWDOWN")


def validate_drawdown_factor(factor: Decimal | int | float | str) -> Decimal:
    value = _decimal(factor, "INVALID_DRAWDOWN_FACTOR")
    if value < 0 or value > 1:
        raise DrawdownRiskError("DRAWDOWN_FACTOR_MUST_BE_NONINCREASING")
    return value
