from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v373.backtest_engine import (
    BacktestStageFunctions,
    DeterminismClass,
    ExecutionModelConfig,
    MarketEvent,
    SimulationMode,
)
from trading_platform.v375.decision_parity import (
    LiveDecisionEngine,
    capture_backtest_decision_trace,
    compare_decision_traces,
)


SYMBOL = "BTCUSDT"


def event(offset: int, close: str) -> MarketEvent:
    price = Decimal(close)
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


def window() -> ValidWindow:
    return ValidWindow(
        valid_from=datetime(2020, 1, 1, tzinfo=timezone.utc),
        expires_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )


def stages(*, broken_risk: bool = False) -> BacktestStageFunctions:
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
            window=window(),
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


def model() -> ExecutionModelConfig:
    return ExecutionModelConfig(
        version="PARITY-EVIDENCE",
        mode=SimulationMode.REALISTIC,
        fee_bps=Decimal("0"),
        slippage_bps=Decimal("0"),
        determinism=DeterminismClass.EXACT,
    )


def main() -> int:
    events = [event(i, str(100 + i)) for i in range(4)]
    bt_trace, bt_result = capture_backtest_decision_trace(stages(), model(), SYMBOL, events)

    live = LiveDecisionEngine(stages()).run(events, bt_trace.position_quantities)
    parity = compare_decision_traces(bt_trace, live.trace)

    mutated_live = LiveDecisionEngine(stages(broken_risk=True)).run(
        events, bt_trace.position_quantities
    )
    mutation_check = compare_decision_traces(bt_trace, mutated_live.trace)

    evidence = {
        "artifact_type": "DECISION_STAGE_PARITY_EVIDENCE",
        "schema_version": "V375_DECISION_STAGE_PARITY_1",
        "source_kind": "INTERNAL",
        "scope": "APPLICATION_BACKTEST_LIVE_SHADOW_DECISION_STAGE",
        "status": "PASS" if parity.passed and not mutation_check.passed else "FAIL",
        "production_ready": False,
        "checks": [
            {
                "check": "shared_decision_stage_trace",
                "pass": parity.passed,
                "event_count": parity.compared_events,
                "backtest_trace_hash": parity.backtest_hash,
                "live_trace_hash": parity.live_hash,
                "mismatch_offsets": list(parity.mismatch_offsets),
            },
            {
                "check": "deliberate_stage_mutation_is_detected",
                "pass": not mutation_check.passed and len(mutation_check.mismatch_offsets) == len(events),
                "mutation_mismatch_offsets": list(mutation_check.mismatch_offsets),
            },
            {
                "check": "backtest_replay_completed",
                "pass": bt_result.event_count == len(events),
                "state_hash": bt_result.state_hash,
            },
        ],
        "evidence_boundary": [
            "Proves the shared decision-stage seam only.",
            "Does not prove live market-data transport parity.",
            "Does not prove execution, accounting, reconciliation, latency, or operational shadow parity.",
            "Does not establish production readiness.",
        ],
    }
    payload = json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
    import hashlib
    evidence["evidence_hash"] = hashlib.sha256(payload).hexdigest()
    out = Path(__file__).resolve().parents[0] / "V375_DECISION_PARITY_EVIDENCE.json"
    out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(out)
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
