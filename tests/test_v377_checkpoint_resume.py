from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass, MarketEvent, SimulationMode
from trading_platform.v376.partial_fill_execution import PartialFillExecutionModelConfig
from trading_platform.v377.checkpoint_resume import (
    CheckpointResumeError,
    CheckpointedPartialFillBacktestEngine,
    InMemoryCheckpointStore,
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


def stages() -> BacktestStageFunctions:
    window = ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )

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
            quantity=Decimal("5"),
            order_type=OrderType.MARKET,
            window=window,
        )

    return BacktestStageFunctions(
        feature_fn=lambda event: {"close": str(event.close)},
        regime_fn=lambda event, feature: "NORMAL",
        prediction_fn=lambda event, feature, regime: Decimal("0.5"),
        signal_fn=lambda event, prediction: "LONG",
        opportunity_fn=lambda event, signal, regime: "OPEN",
        portfolio_fn=lambda event, opportunity, qty: qty,
        risk_fn=lambda event, decision, qty: "ALLOW",
        intent_fn=intent_fn,
    )


def model() -> PartialFillExecutionModelConfig:
    return PartialFillExecutionModelConfig(
        version="PF-1",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        participation_rate=Decimal("0.2"),
    )


def test_checkpoint_resume_matches_full_replay_exactly():
    events = [event(i) for i in range(4)]
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL)

    full = engine.run(events)
    prefix, checkpoint = engine.run_to_checkpoint(
        events,
        checkpoint_after_event_offset=1,
        checkpoint_id="CP-1",
    )
    resumed = engine.resume(events[2:], checkpoint)

    assert prefix.fills[-1].quantity == Decimal("2")
    assert checkpoint.verify() is True
    assert resumed.state_hash == full.state_hash
    assert resumed.fills == full.fills
    assert resumed.rejected_intents == full.rejected_intents
    assert resumed.equity_curve == full.equity_curve
    assert resumed.final_quantity == full.final_quantity
    assert resumed.open_orders == full.open_orders


def test_checkpoint_restores_pending_order_and_fill_index_without_replaying_prefix():
    events = [event(0), event(1), event(2)]
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL)
    _, checkpoint = engine.run_to_checkpoint(
        events,
        checkpoint_after_event_offset=1,
        checkpoint_id="CP-PENDING",
    )

    payload = checkpoint.payload()
    assert payload["pending"][0]["remaining_quantity"] == "1.0"
    assert payload["pending"][0]["fill_index"] == 2
    resumed = engine.resume(events[2:], checkpoint)
    assert resumed.fills[-1].quantity == Decimal("1.0")
    assert resumed.open_orders == ()


def test_tampered_checkpoint_fails_closed():
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL)
    _, checkpoint = engine.run_to_checkpoint(
        [event(0), event(1)],
        checkpoint_after_event_offset=0,
        checkpoint_id="CP-TAMPER",
    )
    tampered = type(checkpoint)(
        **{
            **checkpoint.__dict__,
            "snapshot_json": checkpoint.snapshot_json.replace('"cash":"-200.0"', '"cash":"-201.0"'),
        }
    )
    assert tampered.verify() is False
    with pytest.raises(CheckpointResumeError, match="CHECKPOINT_INVALID"):
        engine.resume([event(1)], tampered)


def test_checkpoint_store_rejects_id_reuse():
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL)
    _, checkpoint = engine.run_to_checkpoint(
        [event(0), event(1)],
        checkpoint_after_event_offset=0,
        checkpoint_id="CP-IMMUTABLE",
    )
    store = InMemoryCheckpointStore()
    store.put(checkpoint)
    with pytest.raises(CheckpointResumeError, match="CHECKPOINT_IMMUTABLE_ID_REUSE"):
        store.put(checkpoint)


def test_resume_requires_exact_event_boundary():
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL)
    _, checkpoint = engine.run_to_checkpoint(
        [event(0), event(1), event(2)],
        checkpoint_after_event_offset=0,
        checkpoint_id="CP-BOUNDARY",
    )
    with pytest.raises(CheckpointResumeError, match="CHECKPOINT_EVENT_BOUNDARY_MISMATCH"):
        engine.resume([event(2)], checkpoint)


def test_resume_rejects_execution_model_or_seed_mismatch():
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL, seed=7)
    _, checkpoint = engine.run_to_checkpoint(
        [event(0), event(1)],
        checkpoint_after_event_offset=0,
        checkpoint_id="CP-COMPAT",
    )
    other = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL, seed=8)
    with pytest.raises(CheckpointResumeError, match="CHECKPOINT_SEED_MISMATCH"):
        other.resume([event(1)], checkpoint)
