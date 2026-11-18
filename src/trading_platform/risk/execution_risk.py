"""Conservative monotone caps for execution risk and concentrated exposure.

The inputs here are policy-bound normalized severities, not market measurements.
Callers remain responsible for sourcing and authenticating those measurements.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, Overflow


_ZERO = Decimal("0")
_ONE = Decimal("1")


def _finite_decimal(value: Decimal | int | float | str, error: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(error) from exc
    if not result.is_finite():
        raise ValueError(error)
    return result


def _normalized(value: Decimal | int | float | str, error: str) -> Decimal:
    result = _finite_decimal(value, error)
    if not _ZERO <= result <= _ONE:
        raise ValueError(error)
    return result


def validate_execution_risk_factor(factor: Decimal | int | float | str) -> Decimal:
    return _normalized(factor, "INVALID_EXECUTION_RISK_FACTOR")


def execution_risk_factor(execution_risk: Decimal | int | float | str) -> Decimal:
    """Map normalized execution hazard [0, 1] to a nonincreasing size factor."""
    return _ONE - _normalized(execution_risk, "EXECUTION_RISK_OUT_OF_RANGE")


def cap_position_size(
    base_position_size: Decimal | int | float | str,
    *,
    execution_risk: Decimal | int | float | str,
) -> Decimal:
    """Apply the execution-risk factor to a caller-supplied position-size ceiling."""
    base = _finite_decimal(base_position_size, "INVALID_BASE_POSITION_SIZE")
    if base < _ZERO:
        raise ValueError("INVALID_BASE_POSITION_SIZE")
    try:
        result = base * execution_risk_factor(execution_risk)
    except (InvalidOperation, Overflow) as exc:
        raise ValueError("POSITION_SIZE_CAP_OVERFLOW") from exc
    if not result.is_finite():
        raise ValueError("POSITION_SIZE_CAP_OVERFLOW")
    return result


def concentration_adjusted_correlated_exposure_cap(
    base_correlated_exposure_cap: Decimal | int | float | str,
    *,
    concentration: Decimal | int | float | str,
    maximum_concentration: Decimal | int | float | str = _ONE,
) -> Decimal:
    """Reduce a correlated-exposure cap monotonically as concentration worsens.

    `concentration` and `maximum_concentration` are normalized [0, 1] values.
    A concentration at or above the configured maximum permits no new correlated
    exposure. This caps an independently measured exposure; it does not estimate
    correlations or authenticate the portfolio inputs.
    """
    base = _finite_decimal(base_correlated_exposure_cap, "INVALID_CORRELATED_EXPOSURE_CAP")
    if base < _ZERO:
        raise ValueError("INVALID_CORRELATED_EXPOSURE_CAP")
    severity = _normalized(concentration, "CONCENTRATION_OUT_OF_RANGE")
    maximum = _normalized(maximum_concentration, "MAXIMUM_CONCENTRATION_OUT_OF_RANGE")
    if maximum == _ZERO:
        raise ValueError("MAXIMUM_CONCENTRATION_MUST_BE_POSITIVE")
    if severity >= maximum:
        return _ZERO
    try:
        result = base * (_ONE - severity / maximum)
    except (InvalidOperation, Overflow) as exc:
        raise ValueError("CORRELATED_EXPOSURE_CAP_OVERFLOW") from exc
    if not result.is_finite():
        raise ValueError("CORRELATED_EXPOSURE_CAP_OVERFLOW")
    return result
