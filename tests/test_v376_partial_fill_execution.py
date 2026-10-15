from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass, MarketEvent, SimulationMode
from trading_platform.v376.partial_fill_execution import (
    PartialFillBacktestEngine,
    PartialFillExecutionModelConfig,
    PartialFillRejectionReason,
)

SYMBOL = "BTCUSDT"


def event(offset: int, close: str = "100", volume: str = "10") -> MarketEvent:
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


def window(expires: datetime | None = None) -> ValidWindow:
    return ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=expires or datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def stages(quantity: str = "5", intent_window: ValidWindow | None = None) -> BacktestStageFunctions:
    def intent_fn(event, risk_decision):
        if event.event_offset != 0:
            return None
        return OrderIntent(
            intent_id="INTENT-1",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="PF-1",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal(quantity),
            order_type=OrderType.MARKET,
            window=intent_window or window(),
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


def model(rate: str = "0.2", probability: str = "1") -> PartialFillExecutionModelConfig:
    determinism = DeterminismClass.EXACT if probability == "1" else DeterminismClass.STOCHASTIC_BUT_SEEDED
    return PartialFillExecutionModelConfig(
        version="PF-1",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=determinism,
        participation_rate=Decimal(rate),
        fill_probability=Decimal(probability),
    )


def test_order_is_filled_across_multiple_bars_without_overfill():
    result = PartialFillBacktestEngine(stages("5"), model("0.2"), SYMBOL).run(
        [event(0), event(1), event(2)]
    )
    assert [fill.quantity for fill in result.fills] == [Decimal("2"), Decimal("2"), Decimal("1")]
    assert sum((fill.quantity for fill in result.fills), Decimal("0")) == Decimal("5")
    assert result.open_orders == ()
    assert result.final_quantity == Decimal("5")


def test_remainder_stays_open_when_data_ends():
    result = PartialFillBacktestEngine(stages("5"), model("0.2"), SYMBOL).run([event(0)])
    assert [fill.quantity for fill in result.fills] == [Decimal("2")]
    assert result.open_orders == (("INTENT-1", Decimal("3")),)
    assert result.final_quantity == Decimal("2")


def test_remaining_quantity_expires_without_silent_fill():
    expiry = datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
    result = PartialFillBacktestEngine(stages("5", window(expiry)), model("0.2"), SYMBOL).run(
        [event(0), event(1), event(2), event(3)]
    )
    assert [fill.quantity for fill in result.fills] == [Decimal("2"), Decimal("2")]
    assert result.open_orders == ()
    assert len(result.rejected_intents) == 1
    assert result.rejected_intents[0].reason is PartialFillRejectionReason.WINDOW_EXPIRED


def test_seeded_partial_fill_probability_is_reproducible():
    events = [event(i) for i in range(20)]
    r1 = PartialFillBacktestEngine(stages("5"), model("0.5", "0.6"), SYMBOL, seed=41).run(events)
    r2 = PartialFillBacktestEngine(stages("5"), model("0.5", "0.6"), SYMBOL, seed=41).run(events)
    assert r1.state_hash == r2.state_hash
    assert r1.fills == r2.fills
    assert r1.open_orders == r2.open_orders


def test_invalid_participation_rate_is_rejected():
    with pytest.raises(ValueError, match="INVALID_PARTICIPATION_RATE"):
        model("0")
    with pytest.raises(ValueError, match="INVALID_PARTICIPATION_RATE"):
        model("1.1")


def test_partial_fill_engine_requires_its_own_model_type():
    from trading_platform.v373.backtest_engine import DeterminismClass, ExecutionModelConfig

    plain = ExecutionModelConfig(
        version="X",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
    )
    with pytest.raises(ValueError, match="PARTIAL_FILL_ENGINE_REQUIRES_PARTIAL_FILL_EXECUTION_MODEL"):
        PartialFillBacktestEngine(stages(), plain, SYMBOL)


def test_partial_fill_engine_rejects_stress_mode_without_stress_contract():
    with pytest.raises(ValueError, match="PARTIAL_FILL_EXECUTION_MODE_UNSUPPORTED_FOR_STRESS"):
        PartialFillExecutionModelConfig(
            version="PF-STRESS",
            mode=SimulationMode.STRESS,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,
            participation_rate=Decimal("0.2"),
        )
