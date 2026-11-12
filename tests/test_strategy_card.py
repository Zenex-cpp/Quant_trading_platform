from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from trading_platform.research.strategy_card import StrategyCard


def make_card(**updates) -> StrategyCard:
    values = {
        "strategy_id": "MEAN-REVERSION",
        "strategy_version": "1",
        "hypothesis": "Short-lived price dislocations revert after liquidity recovers.",
        "intended_use": "Offline research evaluation.",
        "validity_scope": "Liquid spot instruments on five-minute bars.",
        "instruments": ("BTCUSDT",),
        "timeframes": ("5m",),
        "regimes": ("RANGE",),
        "prohibited_regimes": ("DISORDERLY",),
        "entry_logic": "Enter only after the validated dislocation threshold.",
        "exit_logic": "Exit at the pre-registered mean or stop boundary.",
        "signal_dependencies": ("zscore-v1",),
        "portfolio_constraints": "Single instrument and bounded allocation.",
        "risk_controls": "Risk authority must approve every new entry.",
        "data_requirements": ("PIT OHLCV with audited source and revisions.",),
        "execution_assumptions": "Simulation only; no venue submission.",
        "cost_assumptions": "Fees and impact are recorded separately.",
        "capacity_limits": "Not established until real depth data is reviewed.",
        "turnover_limits": "Reject evaluation above the pre-registered turnover cap.",
        "monitoring_metrics": ("drawdown", "slippage"),
        "known_limitations": "Synthetic evidence does not establish profitability.",
        "failure_modes": "Disable new entries on stale data or reconciliation failure.",
        "dependencies": ("feature-v1", "risk-policy-v1"),
        "owner": "research",
        "approval_scope": "No production approval requested.",
    }
    values.update(updates)
    return StrategyCard(**values)


def test_strategy_card_fingerprint_is_canonical_and_covers_every_field():
    first = make_card()
    equivalent = make_card()
    changed = make_card(cost_assumptions="Fees only; impact is unknown.")

    assert first.canonical_json() == equivalent.canonical_json()
    assert first.fingerprint() == equivalent.fingerprint()
    assert first.fingerprint() != changed.fingerprint()
    assert len(first.fingerprint()) == 64


def test_strategy_card_is_immutable():
    card = make_card()

    with pytest.raises(FrozenInstanceError):
        card.strategy_version = "2"


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("hypothesis", " ", "STRATEGY_CARD_HYPOTHESIS_REQUIRED"),
        ("instruments", ["BTCUSDT"], "STRATEGY_CARD_INSTRUMENTS_MUST_BE_TUPLE"),
        ("timeframes", ("5m", "5m"), "STRATEGY_CARD_TIMEFRAMES_DUPLICATE_ITEM"),
        ("regimes", ("RANGE", ""), "STRATEGY_CARD_REGIMES_ITEM_INVALID"),
    ],
)
def test_strategy_card_rejects_missing_or_mutable_template_values(field, value, error):
    with pytest.raises(ValueError, match=error):
        make_card(**{field: value})
