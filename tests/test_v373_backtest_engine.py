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
    OutOfOrderEventError,
    RejectionReason,
    SimulationMode,
)

SYMBOL = "BTCUSDT"


def _event(offset: int, close: str, minute: int = 0) -> MarketEvent:
    price = Decimal(close)
    return MarketEvent(
        event_offset=offset,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=minute),
        symbol=SYMBOL,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("10"),
    )


def _wide_window() -> ValidWindow:
    return ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def _idealized_model() -> ExecutionModelConfig:
    return ExecutionModelConfig(
        version="EM-1",
        mode=SimulationMode.IDEALIZED,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
    )


def _no_intent_stages() -> BacktestStageFunctions:
    return BacktestStageFunctions(
        feature_fn=lambda event: None,
        regime_fn=lambda event, feature: None,
        prediction_fn=lambda event, feature, regime: None,
        signal_fn=lambda event, prediction: None,
        opportunity_fn=lambda event, signal, regime: None,
        portfolio_fn=lambda event, opportunity, qty: None,
        risk_fn=lambda event, decision, qty: None,
        intent_fn=lambda event, risk_decision: None,
    )


def _buy_once_at_offset(target_offset: int, quantity: str = "1") -> BacktestStageFunctions:
    stages = _no_intent_stages()

    def intent_fn(event, risk_decision):
        if event.event_offset != target_offset:
            return None
        return OrderIntent(
            intent_id=f"INTENT-{event.event_offset}",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="EM-1",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal(quantity),
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    return BacktestStageFunctions(
        feature_fn=stages.feature_fn,
        regime_fn=stages.regime_fn,
        prediction_fn=stages.prediction_fn,
        signal_fn=stages.signal_fn,
        opportunity_fn=stages.opportunity_fn,
        portfolio_fn=stages.portfolio_fn,
        risk_fn=stages.risk_fn,
        intent_fn=intent_fn,
    )


def test_no_intents_produces_flat_result():
    engine = BacktestEngine(_no_intent_stages(), _idealized_model(), SYMBOL)
    events = [_event(0, "100"), _event(1, "101"), _event(2, "99")]
    result = engine.run(events)
    assert result.fills == ()
    assert result.final_quantity == Decimal("0")
    assert result.final_equity == Decimal("0")
    assert result.event_count == 3


def test_buy_then_hold_tracks_mark_to_market_equity():
    engine = BacktestEngine(_buy_once_at_offset(0), _idealized_model(), SYMBOL)
    events = [_event(0, "100"), _event(1, "110")]
    result = engine.run(events)
    assert len(result.fills) == 1
    assert result.final_quantity == Decimal("1")
    # bought 1 @ 100 (no fee/slippage), marked at 110 on the last bar:
    # cash = -100, equity = cash + qty*close = -100 + 110 = 10
    assert result.final_equity == Decimal("10")


def test_fee_and_slippage_reduce_equity():
    model = ExecutionModelConfig(
        version="EM-2",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("10"),       # 0.10%
        slippage_bps=Decimal("5"),   # 0.05%
        determinism=DeterminismClass.EXACT,
    )
    engine = BacktestEngine(_buy_once_at_offset(0), model, SYMBOL)
    result = engine.run([_event(0, "100")])
    fill = result.fills[0]
    assert fill.price == Decimal("100") * (Decimal("1") + Decimal("5") / Decimal("10000"))
    assert fill.fee > Decimal("0")
    # equity immediately after: cash reflects price paid + fee, marked at same close
    assert result.final_equity < Decimal("0")


def test_latency_offset_delays_fill_to_later_bar_price():
    model = ExecutionModelConfig(
        version="EM-3",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        latency_offsets=2,
    )
    engine = BacktestEngine(_buy_once_at_offset(0), model, SYMBOL)
    events = [_event(0, "100"), _event(1, "105"), _event(2, "120"), _event(3, "130")]
    result = engine.run(events)
    assert len(result.fills) == 1
    # signal generated at offset 0 but latency=2 -> fills at the first event
    # whose offset >= 0+2, i.e. offset 2, at that bar's close (120), not 100.
    assert result.fills[0].price == Decimal("120")


def test_out_of_order_events_are_rejected():
    engine = BacktestEngine(_no_intent_stages(), _idealized_model(), SYMBOL)
    with pytest.raises(OutOfOrderEventError):
        engine.run([_event(1, "100"), _event(0, "99")])


def test_expired_intent_is_rejected_not_filled():
    stages = _no_intent_stages()
    expired_window = ValidWindow(
        valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )

    def intent_fn(event, risk_decision):
        return OrderIntent(
            intent_id="EXPIRED-1",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="EM-1",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            window=expired_window,
        )

    stages = BacktestStageFunctions(
        feature_fn=stages.feature_fn,
        regime_fn=stages.regime_fn,
        prediction_fn=stages.prediction_fn,
        signal_fn=stages.signal_fn,
        opportunity_fn=stages.opportunity_fn,
        portfolio_fn=stages.portfolio_fn,
        risk_fn=stages.risk_fn,
        intent_fn=intent_fn,
    )
    engine = BacktestEngine(stages, _idealized_model(), SYMBOL)
    result = engine.run([_event(0, "100")])
    assert result.fills == ()
    assert len(result.rejected_intents) == 1
    assert result.rejected_intents[0].reason is RejectionReason.WINDOW_EXPIRED_OR_NOT_YET_VALID


def test_symbol_mismatch_is_rejected():
    stages = _no_intent_stages()

    def intent_fn(event, risk_decision):
        return OrderIntent(
            intent_id="WRONG-SYM",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="EM-1",
            symbol="ETHUSDT",
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    stages = BacktestStageFunctions(
        feature_fn=stages.feature_fn,
        regime_fn=stages.regime_fn,
        prediction_fn=stages.prediction_fn,
        signal_fn=stages.signal_fn,
        opportunity_fn=stages.opportunity_fn,
        portfolio_fn=stages.portfolio_fn,
        risk_fn=stages.risk_fn,
        intent_fn=intent_fn,
    )
    engine = BacktestEngine(stages, _idealized_model(), SYMBOL)
    result = engine.run([_event(0, "100")])
    assert result.fills == ()
    assert result.rejected_intents[0].reason is RejectionReason.SYMBOL_MISMATCH


def test_same_inputs_produce_identical_state_hash_twice():
    events = [_event(0, "100"), _event(1, "105"), _event(2, "95"), _event(3, "110")]
    r1 = BacktestEngine(_buy_once_at_offset(1), _idealized_model(), SYMBOL).run(events)
    r2 = BacktestEngine(_buy_once_at_offset(1), _idealized_model(), SYMBOL).run(events)
    assert r1.state_hash == r2.state_hash
    assert r1.final_equity == r2.final_equity
    assert r1.fills == r2.fills


def test_stochastic_fill_probability_is_seeded_and_reproducible():
    model = ExecutionModelConfig(
        version="EM-4",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.STOCHASTIC_BUT_SEEDED,
        fill_probability=Decimal("0.5"),
    )
    events = [_event(i, "100") for i in range(20)]

    def stages_buy_every_bar() -> BacktestStageFunctions:
        base = _no_intent_stages()

        def intent_fn(event, risk_decision):
            return OrderIntent(
                intent_id=f"I-{event.event_offset}",
                decision_id="D1",
                portfolio_decision_id="P1",
                risk_decision_id="R1",
                strategy_id="S1",
                model_id="M1",
                execution_version="EM-4",
                symbol=SYMBOL,
                side=Side.BUY,
                action=OrderAction.OPEN,
                quantity=Decimal("1"),
                order_type=OrderType.MARKET,
                window=_wide_window(),
            )

        return BacktestStageFunctions(
            feature_fn=base.feature_fn,
            regime_fn=base.regime_fn,
            prediction_fn=base.prediction_fn,
            signal_fn=base.signal_fn,
            opportunity_fn=base.opportunity_fn,
            portfolio_fn=base.portfolio_fn,
            risk_fn=base.risk_fn,
            intent_fn=intent_fn,
        )

    r1 = BacktestEngine(stages_buy_every_bar(), model, SYMBOL, seed=42).run(events)
    r2 = BacktestEngine(stages_buy_every_bar(), model, SYMBOL, seed=42).run(events)
    r3 = BacktestEngine(stages_buy_every_bar(), model, SYMBOL, seed=43).run(events)

    assert 0 < len(r1.fills) < len(events)  # some fill, some miss -- not deterministically all-or-nothing
    assert r1.state_hash == r2.state_hash  # same seed -> identical outcome
    assert [f.fill_id for f in r1.fills] == [f.fill_id for f in r2.fills]
    assert r1.state_hash != r3.state_hash or r1.fills != r3.fills  # different seed is free to differ


def test_execution_model_rejects_invalid_parameters():
    with pytest.raises(ValueError):
        ExecutionModelConfig(
            version="X",
            mode=SimulationMode.IDEALIZED,
            fee_bps=Decimal("-1"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,
        )
    with pytest.raises(ValueError):
        ExecutionModelConfig(
            version="X",
            mode=SimulationMode.IDEALIZED,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,
            fill_probability=Decimal("0.5"),  # mismatched determinism class
        )
    with pytest.raises(ValueError):
        ExecutionModelConfig(
            version="",
            mode=SimulationMode.IDEALIZED,
            fee_bps=Decimal("0"),
            slippage_bps=Decimal("0"),
            determinism=DeterminismClass.EXACT,
        )


def test_non_finite_market_event_is_rejected():
    with pytest.raises(ValueError):
        _event(0, "nan")
