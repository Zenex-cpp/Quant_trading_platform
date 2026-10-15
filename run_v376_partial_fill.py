from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass, MarketEvent, SimulationMode
from trading_platform.v376.partial_fill_execution import PartialFillBacktestEngine, PartialFillExecutionModelConfig

SYMBOL = "BTCUSDT"


def event(offset: int, volume: str = "10") -> MarketEvent:
    price = Decimal("100") + Decimal(offset)
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
    def intent_fn(event, risk_decision):
        if event.event_offset != 0:
            return None
        return OrderIntent(
            intent_id="EVIDENCE-1",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="PF-EVIDENCE",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal("5"),
            order_type=OrderType.MARKET,
            window=ValidWindow(
                valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
                expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
            ),
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


def model() -> PartialFillExecutionModelConfig:
    return PartialFillExecutionModelConfig(
        version="PF-EVIDENCE",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
        participation_rate=Decimal("0.2"),
    )


def main() -> int:
    events = [event(0), event(1), event(2)]
    r1 = PartialFillBacktestEngine(stages(), model(), SYMBOL).run(events)
    r2 = PartialFillBacktestEngine(stages(), model(), SYMBOL).run(events)
    total = sum((fill.quantity for fill in r1.fills), Decimal("0"))
    checks = [
        {
            "check": "liquidity_constrained_partial_fill",
            "fill_quantities": [str(fill.quantity) for fill in r1.fills],
            "requested_quantity": "5",
            "total_filled": str(total),
            "pass": [fill.quantity for fill in r1.fills] == [Decimal("2"), Decimal("2"), Decimal("1")]
            and total == Decimal("5"),
        },
        {
            "check": "no_overfill",
            "requested_quantity": "5",
            "filled_quantity": str(total),
            "open_orders": [[intent_id, str(quantity)] for intent_id, quantity in r1.open_orders],
            "pass": total <= Decimal("5") and r1.open_orders == (),
        },
        {
            "check": "deterministic_replay",
            "run_1_hash": r1.state_hash,
            "run_2_hash": r2.state_hash,
            "pass": r1.state_hash == r2.state_hash,
        },
    ]
    report = {
        "artifact_type": "PARTIAL_FILL_EXECUTION_EVIDENCE",
        "schema_version": "V376_PARTIAL_FILL_EXECUTION_1",
        "source_kind": "INTERNAL",
        "scope": "APPLICATION_BACKTEST_REALISTIC_PARTIAL_FILL",
        "status": "PASS" if all(item["pass"] for item in checks) else "FAIL",
        "production_ready": False,
        "checks": checks,
        "evidence_boundary": [
            "Proves deterministic partial-fill mechanics against a configurable participation rate.",
            "Does not prove order-book depth, queue position, maker/taker semantics, or venue matching behavior.",
            "Participation rate is an explicit simulation assumption, not market-calibrated evidence.",
            "Does not close platform-wide STRESS mode enforcement or full backtest/live operational parity.",
        ],
    }
    payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    report["evidence_hash"] = hashlib.sha256(payload).hexdigest()
    out = Path(__file__).resolve().parent / "V376_PARTIAL_FILL_EXECUTION_EVIDENCE.json"
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
