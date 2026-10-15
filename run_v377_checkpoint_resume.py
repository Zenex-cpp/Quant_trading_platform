from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass, MarketEvent, SimulationMode
from trading_platform.v376.partial_fill_execution import PartialFillExecutionModelConfig
from trading_platform.v377.checkpoint_resume import CheckpointedPartialFillBacktestEngine, SNAPSHOT_VERSION

SYMBOL = "BTCUSDT"


def event(offset: int) -> MarketEvent:
    price = Decimal("100")
    return MarketEvent(
        event_offset=offset,
        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=offset),
        symbol=SYMBOL,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=Decimal("10"),
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
            intent_id="INTENT-V377", decision_id="D377", portfolio_decision_id="P377",
            risk_decision_id="R377", strategy_id="S377", model_id="M377",
            execution_version="PF-1", symbol=SYMBOL, side=Side.BUY,
            action=OrderAction.OPEN, quantity=Decimal("5"), order_type=OrderType.MARKET,
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


def model():
    return PartialFillExecutionModelConfig(
        version="PF-1", mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"), slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT, participation_rate=Decimal("0.2"),
    )


if __name__ == "__main__":
    events = [event(i) for i in range(4)]
    engine = CheckpointedPartialFillBacktestEngine(stages(), model(), SYMBOL)
    full = engine.run(events)
    prefix, cp = engine.run_to_checkpoint(events, checkpoint_after_event_offset=1, checkpoint_id="CP-V377-EVIDENCE")
    resumed = engine.resume(events[2:], cp)
    payload = {
        "evidence_version": "V377_CHECKPOINT_RESUME_EVIDENCE_1",
        "snapshot_version": SNAPSHOT_VERSION,
        "checkpoint_id": cp.checkpoint_id,
        "checkpoint_state_hash": cp.state_hash,
        "checkpoint_verified": cp.verify(),
        "checkpoint_event_offset": cp.event_offset,
        "resume_next_event_offset": cp.next_event_offset,
        "prefix_state_hash": prefix.state_hash,
        "full_state_hash": full.state_hash,
        "resumed_state_hash": resumed.state_hash,
        "resumed_matches_full": resumed.state_hash == full.state_hash,
        "fills": [str(f.quantity) for f in resumed.fills],
        "open_orders": [(k, str(v)) for k, v in resumed.open_orders],
        "production_ready": False,
    }
    Path("V377_CHECKPOINT_RESUME_EVIDENCE.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
