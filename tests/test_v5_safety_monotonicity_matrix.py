from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.risk.monotonicity import (
    assert_risk_ceiling,
    adjusted_risk,
    conservative_drawdown_factor_decimal,
    conservative_model_health_factor_decimal,
    conservative_risk_factor_decimal,
    conservative_liquidity_factor_decimal,
)
from trading_platform.risk.execution_risk import (
    cap_position_size,
    concentration_adjusted_correlated_exposure_cap,
    execution_risk_factor,
)
from trading_platform.v318.durable_decision import RiskSystemState
from trading_platform.v356.risk_state_monotonicity import (
    conservative_state_risk_factor,
    state_severity,
)


ROOT = Path(__file__).resolve().parents[1]


def matrix_rows() -> list[dict[str, str]]:
    with (ROOT / "schemas/v5_safety_monotonicity_matrix.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        return list(csv.DictReader(stream))


def test_safety_matrix_covers_prompt_dimensions_and_real_references():
    rows = matrix_rows()
    assert [row["invariant_id"] for row in rows] == [f"SM-{i:02d}" for i in range(1, 9)]
    by_id = {row["invariant_id"]: row for row in rows}
    assert by_id["SM-05"]["status"] == "ENFORCED_TESTED"
    assert by_id["SM-06"]["status"] == "ENFORCED_TESTED"
    assert by_id["SM-08"]["status"] == "PARTIAL"
    assert all(row["residual_gap"].strip() for row in rows)

    for row in rows:
        for column in ("implementation_reference", "test_reference"):
            for reference in filter(None, row[column].split(";")):
                assert (ROOT / reference).is_file(), (row["invariant_id"], reference)
        if row["status"] == "NOT_IMPLEMENTED":
            assert not row["implementation_reference"]
            assert not row["test_reference"]


@pytest.mark.parametrize("factor", [
    conservative_risk_factor_decimal,
    conservative_liquidity_factor_decimal,
    conservative_drawdown_factor_decimal,
])
def test_worsening_uncertainty_liquidity_and_drawdown_never_raise_factors(factor):
    values = [factor(Decimal(str(x)), floor=Decimal("0.1")) for x in (0, "0.25", "0.5", "0.75", 1, 2)]
    assert all(left >= right for left, right in zip(values, values[1:]))


def test_worse_model_health_and_risk_state_never_raise_factors():
    health_factors = [
        conservative_model_health_factor_decimal(Decimal(str(x)))
        for x in (1, "0.75", "0.5", "0.25", 0)
    ]
    assert all(left >= right for left, right in zip(health_factors, health_factors[1:]))

    ordered_states = [
        RiskSystemState.NORMAL,
        RiskSystemState.ELEVATED,
        RiskSystemState.RESTRICTED,
        RiskSystemState.FROZEN,
        RiskSystemState.EMERGENCY,
        RiskSystemState.RECOVERY,
    ]
    assert all(state_severity(a) <= state_severity(b) for a, b in zip(ordered_states, ordered_states[1:]))
    factors = [conservative_state_risk_factor(state) for state in ordered_states]
    assert all(left >= right for left, right in zip(factors, factors[1:]))


def test_absolute_risk_ceiling_rejects_risk_and_exposure_breaches():
    assert_risk_ceiling(Decimal("5"), Decimal("5"), Decimal("7"), Decimal("7"))
    with pytest.raises(ValueError, match="ABSOLUTE_RISK_CEILING_BREACH"):
        assert_risk_ceiling(Decimal("6"), Decimal("5"), Decimal("7"), Decimal("7"))
    with pytest.raises(ValueError, match="ABSOLUTE_EXPOSURE_CEILING_BREACH"):
        assert_risk_ceiling(Decimal("5"), Decimal("5"), Decimal("8"), Decimal("7"))


def test_higher_execution_risk_never_allows_a_larger_position():
    levels = [Decimal("0"), Decimal("0.25"), Decimal("0.5"), Decimal("0.75"), Decimal("1")]
    sizes = [cap_position_size(Decimal("100"), execution_risk=level) for level in levels]
    assert sizes == [Decimal("100"), Decimal("75.00"), Decimal("50.0"), Decimal("25.00"), Decimal("0")]
    assert all(left >= right for left, right in zip(sizes, sizes[1:]))
    assert [execution_risk_factor(level) for level in levels] == [Decimal("1"), Decimal("0.75"), Decimal("0.5"), Decimal("0.25"), Decimal("0")]
    adjusted = [adjusted_risk(Decimal("100"), execution_risk=level) for level in levels]
    assert adjusted == sizes
    assert all(left >= right for left, right in zip(adjusted, adjusted[1:]))
    with pytest.raises(ValueError, match="EXECUTION_RISK_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("100"), execution_risk=Decimal("0.75"), execution_risk_factor=Decimal("0.5"))
    with pytest.raises(ValueError, match="INVALID_EXECUTION_RISK_FACTOR"):
        adjusted_risk(Decimal("100"), execution_risk_factor=Decimal("1.01"))


@pytest.mark.parametrize("invalid", [Decimal("-0.01"), Decimal("1.01"), Decimal("NaN"), Decimal("Infinity")])
def test_execution_risk_rejects_invalid_or_unnormalized_values(invalid):
    with pytest.raises(ValueError, match="EXECUTION_RISK_OUT_OF_RANGE"):
        execution_risk_factor(invalid)


def test_higher_concentration_never_raises_correlated_exposure_cap():
    levels = [Decimal("0"), Decimal("0.25"), Decimal("0.5"), Decimal("0.75"), Decimal("1")]
    caps = [
        concentration_adjusted_correlated_exposure_cap(
            Decimal("100"), concentration=level, maximum_concentration=Decimal("1")
        )
        for level in levels
    ]
    assert caps == [Decimal("100"), Decimal("75.00"), Decimal("50.0"), Decimal("25.00"), Decimal("0")]
    assert all(left >= right for left, right in zip(caps, caps[1:]))
    assert concentration_adjusted_correlated_exposure_cap(
        Decimal("100"), concentration=Decimal("0.6"), maximum_concentration=Decimal("0.5")
    ) == Decimal("0")
    with pytest.raises(ValueError, match="MAXIMUM_CONCENTRATION_MUST_BE_POSITIVE"):
        concentration_adjusted_correlated_exposure_cap(Decimal("100"), concentration=Decimal("0"), maximum_concentration=Decimal("0"))
    with pytest.raises(ValueError, match="CONCENTRATION_OUT_OF_RANGE"):
        concentration_adjusted_correlated_exposure_cap(Decimal("100"), concentration=Decimal("-0.01"))
