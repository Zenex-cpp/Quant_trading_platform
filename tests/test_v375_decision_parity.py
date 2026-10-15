from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.core.ttl import ValidWindow
from trading_platform.v373.backtest_engine import (
    BacktestStageFunctions,
    DeterminismClass,
    ExecutionModelConfig,
    MarketEvent,
    SimulationMode,
)
from trading_platform.v375.decision_parity import (
    LiveDecisionEngine,
    ParityInputError,
    capture_backtest_decision_trace,
    compare_decision_traces,
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


def _stages(*, broken_risk: bool = False) -> BacktestStageFunctions:
    def feature(event):
        return {"close": event.close, "volume": event.volume}

    def regime(event, feature):
        return "TREND" if feature["close"] >= Decimal("100") else "MEAN_REVERT"

    def prediction(event, feature, regime):
        return {"expected": feature["close"], "regime": regime}

    def signal(event, prediction):
        return prediction["regime"] == "TREND"

    def opportunity(event, signal, regime):
        return {"score": Decimal("1") if signal else Decimal("0"), "regime": regime}

    def portfolio(event, opportunity, qty):
        return {"qty": Decimal("1") if opportunity["score"] > 0 else Decimal("0"), "position_before": qty}

    def risk(event, decision, qty):
        if broken_risk:
            return {"allowed": False, "qty": Decimal("0"), "position_before": qty}
        return {"allowed": decision["qty"] > 0, "qty": decision["qty"], "position_before": qty}

    def intent(event, risk_decision):
        if not risk_decision["allowed"]:
            return None
        return OrderIntent(
            intent_id=f"I-{event.event_offset}",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="PARITY",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=risk_decision["qty"],
            order_type=OrderType.MARKET,
            window=_wide_window(),
        )

    return BacktestStageFunctions(
        feature_fn=feature,
        regime_fn=regime,
        prediction_fn=prediction,
        signal_fn=signal,
        opportunity_fn=opportunity,
        portfolio_fn=portfolio,
        risk_fn=risk,
        intent_fn=intent,
    )


def _model() -> ExecutionModelConfig:
    return ExecutionModelConfig(
        version="PARITY-BASE",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
    )


def test_same_stages_same_events_and_position_state_are_machine_comparable():
    events = [_event(i, str(100 + i)) for i in range(4)]

    backtest_trace, backtest_result = capture_backtest_decision_trace(
        _stages(),
        _model(),
        SYMBOL,
        events,
    )
    live_result = LiveDecisionEngine(_stages()).run(
        events,
        backtest_trace.position_quantities,
    )

    comparison = compare_decision_traces(backtest_trace, live_result.trace)

    assert comparison.passed
    assert comparison.compared_events == 4
    assert comparison.mismatch_offsets == ()
    assert comparison.backtest_hash == comparison.live_hash
    assert backtest_result.event_count == 4


def test_parity_trace_has_deterministic_hash():
    events = [_event(i, str(100 + i)) for i in range(3)]
    trace_a, _ = capture_backtest_decision_trace(_stages(), _model(), SYMBOL, events)
    trace_b, _ = capture_backtest_decision_trace(_stages(), _model(), SYMBOL, events)
    assert trace_a.state_hash == trace_b.state_hash


def test_live_stage_change_is_detected_as_parity_failure():
    events = [_event(i, str(100 + i)) for i in range(3)]
    backtest_trace, _ = capture_backtest_decision_trace(_stages(), _model(), SYMBOL, events)
    live_result = LiveDecisionEngine(_stages(broken_risk=True)).run(
        events,
        backtest_trace.position_quantities,
    )
    comparison = compare_decision_traces(backtest_trace, live_result.trace)
    assert not comparison.passed
    assert comparison.mismatch_offsets == (0, 1, 2)


def test_live_runner_rejects_position_length_mismatch():
    events = [_event(0, "100"), _event(1, "101")]
    with pytest.raises(ParityInputError):
        LiveDecisionEngine(_stages()).run(events, [Decimal("0")])


def test_live_runner_rejects_out_of_order_events():
    events = [_event(1, "101"), _event(0, "100")]
    with pytest.raises(ParityInputError, match="OUT_OF_ORDER_LIVE_EVENT"):
        LiveDecisionEngine(_stages()).run(events, [Decimal("0"), Decimal("0")])


def test_live_runner_has_no_execution_side_effects():
    events = [_event(0, "100"), _event(1, "101")]
    result = LiveDecisionEngine(_stages()).run(events, [Decimal("0"), Decimal("1")])
    assert len(result.intents) == 2
    assert all(intent is not None for intent in result.intents)
