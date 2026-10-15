from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import (
    BacktestEngine,
    BacktestStageFunctions,
    DeterminismClass,
    ExecutionModelConfig,
    MarketEvent,
    RejectionReason,
    SimulationMode,
)
from trading_platform.v374.stress_execution_model import (
    StressBacktestEngine,
    StressExecutionModelConfig,
    StressRejectionReason,
)

SYMBOL = "BTCUSDT"


def _event(offset: int, close: str, volume: str = "10") -> MarketEvent:
    price = Decimal(close)
    return MarketEvent(
        event_offset=offset,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=offset),
        symbol=SYMBOL,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal(volume),
    )


def _wide_window() -> ValidWindow:
    return ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def _buy_every_bar_stages(quantity: str = "1") -> BacktestStageFunctions:
    def intent_fn(event, risk_decision):
        return OrderIntent(
            intent_id=f"I-{event.event_offset}",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="EM-STRESS",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal(quantity),
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    return BacktestStageFunctions(
        feature_fn=lambda event: None,
        regime_fn=lambda event, feature: None,
        prediction_fn=lambda event, feature, regime: None,
        signal_fn=lambda event, prediction: None,
        opportunity_fn=lambda event, signal, regime: None,
        portfolio_fn=lambda event, opportunity, qty: None,
        risk_fn=lambda event, decision, qty: None,
        intent_fn=intent_fn,
    )


def test_stress_config_rejects_non_stress_mode():
    with pytest.raises(ValueError):
        StressExecutionModelConfig(
            version="S1",
            mode=SimulationMode.REALISTIC,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,
            stress_slippage_multiplier=Decimal("2"),
        )


def test_stress_config_requires_at_least_one_adverse_parameter():
    with pytest.raises(ValueError):
        StressExecutionModelConfig(
            version="S1",
            mode=SimulationMode.STRESS,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,
        )


def test_stress_config_determinism_mismatch_is_rejected():
    with pytest.raises(ValueError):
        StressExecutionModelConfig(
            version="S1",
            mode=SimulationMode.STRESS,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,  # wrong: rejection_probability>0 needs STOCHASTIC_BUT_SEEDED
            rejection_probability=Decimal("0.2"),
        )


def test_stress_engine_requires_stress_config():
    base_model = ExecutionModelConfig(
        version="S1",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
    )
    with pytest.raises(ValueError):
        StressBacktestEngine(_buy_every_bar_stages(), base_model, SYMBOL)


def test_liquidity_cap_rejects_oversized_order():
    model = StressExecutionModelConfig(
        version="S-LIQ",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        liquidity_participation_cap=Decimal("0.1"),  # max 10% of bar volume
    )
    # bar volume = 10 -> max fillable = 1; requesting 5 must be rejected
    engine = StressBacktestEngine(_buy_every_bar_stages(quantity="5"), model, SYMBOL)
    result = engine.run([_event(0, "100", volume="10")])
    assert result.fills == ()
    assert result.rejected_intents[0].reason is StressRejectionReason.LIQUIDITY_CAP_EXCEEDED


def test_liquidity_cap_allows_order_within_cap():
    model = StressExecutionModelConfig(
        version="S-LIQ2",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        liquidity_participation_cap=Decimal("0.5"),  # max 50% of bar volume
    )
    engine = StressBacktestEngine(_buy_every_bar_stages(quantity="5"), model, SYMBOL)
    result = engine.run([_event(0, "100", volume="10")])
    assert len(result.fills) == 1


def test_stress_rejection_probability_is_seeded_and_reproducible():
    model = StressExecutionModelConfig(
        version="S-REJ",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.STOCHASTIC_BUT_SEEDED,
        rejection_probability=Decimal("0.5"),
    )
    events = [_event(i, "100") for i in range(30)]
    r1 = StressBacktestEngine(_buy_every_bar_stages(), model, SYMBOL, seed=5).run(events)
    r2 = StressBacktestEngine(_buy_every_bar_stages(), model, SYMBOL, seed=5).run(events)
    r3 = StressBacktestEngine(_buy_every_bar_stages(), model, SYMBOL, seed=9).run(events)

    assert r1.state_hash == r2.state_hash
    assert [f.fill_id for f in r1.fills] == [f.fill_id for f in r2.fills]
    assert 0 < len(r1.fills) < len(events)
    assert any(r.reason is StressRejectionReason.STRESS_REJECTED for r in r1.rejected_intents)
    assert r1.state_hash != r3.state_hash or r1.fills != r3.fills


def test_stress_slippage_multiplier_worsens_execution_price_vs_baseline():
    baseline_model = ExecutionModelConfig(
        version="BASE",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("20"),
        determinism=DeterminismClass.EXACT,
    )
    stress_model = StressExecutionModelConfig(
        version="STRESS",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("20"),
        determinism=DeterminismClass.EXACT,
        stress_slippage_multiplier=Decimal("3"),
    )
    event = _event(0, "100")
    baseline_result = BacktestEngine(_buy_every_bar_stages(), baseline_model, SYMBOL).run([event])
    stress_result = StressBacktestEngine(_buy_every_bar_stages(), stress_model, SYMBOL).run([event])

    baseline_price = baseline_result.fills[0].price
    stress_price = stress_result.fills[0].price
    # both are BUYs: worse execution means paying MORE, i.e. a higher fill price
    assert stress_price > baseline_price
    assert stress_result.fills[0].slippage > baseline_result.fills[0].slippage


def test_base_rejection_reasons_pass_through_unchanged():
    model = StressExecutionModelConfig(
        version="S-SYM",
        mode=SimulationMode.STRESS,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        stress_slippage_multiplier=Decimal("2"),
    )

    def intent_fn(event, risk_decision):
        return OrderIntent(
            intent_id="WRONG-SYM",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="S-SYM",
            symbol="ETHUSDT",
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    stages = BacktestStageFunctions(
        feature_fn=lambda event: None,
        regime_fn=lambda event, feature: None,
        prediction_fn=lambda event, feature, regime: None,
        signal_fn=lambda event, prediction: None,
        opportunity_fn=lambda event, signal, regime: None,
        portfolio_fn=lambda event, opportunity, qty: None,
        risk_fn=lambda event, decision, qty: None,
        intent_fn=intent_fn,
    )
    engine = StressBacktestEngine(stages, model, SYMBOL)
    result = engine.run([_event(0, "100")])
    assert result.fills == ()
    assert result.rejected_intents[0].reason is RejectionReason.SYMBOL_MISMATCH
