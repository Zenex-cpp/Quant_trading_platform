from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.realtime.orderbook import OrderBookSnapshot
from trading_platform.v373.backtest_engine import BacktestStageFunctions, MarketEvent
from trading_platform.v378 import BinanceVenueExecutionModelConfig, VenueMarketEvent
from trading_platform.v379 import (
    AdapterObservation,
    AdapterStatus,
    ExecutionParityHarness,
    LiveShadowExecutionAdapter,
    BinanceTestnetOrderAdapter,
    BinanceTestnetPublicProbe,
    TestnetMutationGate,
)

ROOT = Path(__file__).resolve().parent
SYMBOL = "BTCUSDT"
TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def market(offset: int, close: str = "100") -> MarketEvent:
    p = Decimal(close)
    return MarketEvent(offset, TS, SYMBOL, p, p, p, p, Decimal("10"))


def venue_event(offset: int, close: str = "100") -> VenueMarketEvent:
    return VenueMarketEvent(
        market=market(offset, close),
        book=OrderBookSnapshot(
            last_update_id=100 + offset,
            bids=((Decimal("99"), Decimal("10")),),
            asks=((Decimal("101"), Decimal("10")),),
        ),
    )


def stages() -> BacktestStageFunctions:
    def feature(e): return {"close": e.close}
    def regime(e, f): return "TREND"
    def prediction(e, f, r): return {"expected": f["close"]}
    def signal(e, p): return True
    def opportunity(e, s, r): return {"score": Decimal("1")}
    def portfolio(e, o, q): return {"qty": Decimal("1")}
    def risk(e, p, q): return {"allowed": True, "qty": Decimal("1")}
    def intent(e, r):
        return OrderIntent(
            intent_id=f"I-{e.event_offset}", decision_id="D1", portfolio_decision_id="P1",
            risk_decision_id="R1", strategy_id="S1", model_id="M1", execution_version="V379",
            symbol=SYMBOL, side=Side.BUY, action=OrderAction.OPEN, quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            window=ValidWindow(TS, datetime(2030, 1, 1, tzinfo=timezone.utc)),
        )
    return BacktestStageFunctions(feature, regime, prediction, signal, opportunity, portfolio, risk, intent)


def main() -> None:
    events = [venue_event(0), venue_event(1, "101")]
    adapter = LiveShadowExecutionAdapter({
        "I-0": AdapterObservation("I-0", "cid-0", AdapterStatus.FILLED, "SIM-0", Decimal("1"), Decimal("101"), "raw-0", "SHADOW_SCRIPTED"),
        "I-1": AdapterObservation("I-1", "cid-1", AdapterStatus.ACKNOWLEDGED, None, Decimal("0"), None, "raw-1", "SHADOW_SCRIPTED"),
    })
    comparison, backtest = ExecutionParityHarness().run(
        stages=stages(), execution_model=BinanceVenueExecutionModelConfig(version="V379-EXEC", symbol=SYMBOL),
        symbol=SYMBOL, venue_events=events, adapter=adapter,
    )
    adapter_contract_pass = False
    adapter_contract_error = None
    try:
        from trading_platform.v35.binance_execution import BinanceTestnetExecutionConfig, BinanceTestnetExecutionGateway
        class _ContractGateway(BinanceTestnetExecutionGateway):
            def __init__(self):
                super().__init__(BinanceTestnetExecutionConfig())
        contract_adapter = BinanceTestnetOrderAdapter(
            _ContractGateway(),
            TestnetMutationGate(mutation_enabled=True, operator_approval=True, max_notional=Decimal("200")),
        )
        sample_intent = stages().intent_fn(market(0), {"allowed": True, "qty": Decimal("1")})
        request = contract_adapter.to_order_request(sample_intent, now=TS)
        adapter_contract_pass = (
            request.symbol == SYMBOL
            and request.order_type is OrderType.MARKET
            and request.quantity == Decimal("1")
            and request.client_order_id.startswith("tp-")
        )
    except Exception as exc:
        adapter_contract_error = type(exc).__name__ + ":" + str(exc)

    payload = {
        "artifact_type": "EXECUTION_SEAM_PARITY_EVIDENCE",
        "schema_version": "V379_EXECUTION_SEAM_PARITY_1",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "status": comparison.status,
        "checks": {
            "decision_trace_parity": comparison.decision.passed,
            "decision_trace_event_count": comparison.decision.compared_events,
            "intent_mismatch_offsets": list(comparison.intent_mismatch_offsets),
            "compared_intents": comparison.compared_intents,
            "adapter_observation_hash_equals_expected": comparison.adapter_observation_hash == comparison.expected_adapter_observation_hash,
            "testnet_market_order_request_contract": adapter_contract_pass,
            "testnet_market_order_request_contract_error": adapter_contract_error,
            "backtest_state_hash": comparison.backtest_state_hash,
            "shadow_adapter_state_hash": comparison.shadow_adapter_state_hash,
            "backtest_event_count": backtest.event_count,
        },
        "evidence_boundary": [
            "Shared decision-stage parity is proven for the tested venue-event set.",
            "Execution-adapter seam normalization is proven with injected observations.",
            "No real order was submitted by this evidence runner.",
            "Testnet public connectivity remains a separate read-only probe.",
            "This artifact does not prove production exchange matching or latency parity.",
        ],
        "production_ready": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    out = ROOT / "V379_EXECUTION_PARITY_EVIDENCE.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if comparison.status != "PASS":
        raise SystemExit("V379 parity evidence failed")
    print(out)
    print(payload["evidence_hash"])

    try:
        probe = BinanceTestnetPublicProbe().run(symbol=SYMBOL)
        probe_payload = {
            "artifact_type": "BINANCE_TESTNET_PUBLIC_PROBE",
            "status": "PASS" if probe.passed else "FAIL",
            "endpoint": probe.endpoint,
            "symbol": SYMBOL,
            "server_time_ms": probe.server_time_ms,
            "symbol_present": probe.symbol_present,
            "symbol_status": probe.symbol_status,
            "response_hash": probe.response_hash,
            "retrieved_at": probe.retrieved_at,
            "network_policy": probe.network_policy,
            "mutation": "NONE",
        }
    except Exception as exc:
        probe_payload = {
            "artifact_type": "BINANCE_TESTNET_PUBLIC_PROBE",
            "status": "NOT_VERIFIED",
            "endpoint": "https://testnet.binancefuture.com",
            "symbol": SYMBOL,
            "error": type(exc).__name__ + ":" + str(exc),
            "mutation": "NONE",
        }
    (ROOT / "V379_TESTNET_PUBLIC_PROBE.json").write_text(json.dumps(probe_payload, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
