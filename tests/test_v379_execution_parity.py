from datetime import datetime, timezone
from decimal import Decimal

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.realtime.orderbook import OrderBookSnapshot
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass
from trading_platform.v378 import BinanceVenueExecutionModelConfig, VenueMarketEvent
from trading_platform.v373.backtest_engine import MarketEvent
from trading_platform.v379.execution_parity import (
    AdapterObservation,
    AdapterStatus,
    BinanceTestnetOrderAdapter,
    BinanceTestnetPublicProbe,
    ExecutionParityHarness,
    LiveShadowExecutionAdapter,
    TestnetMutationGate,
)

SYMBOL = "BTCUSDT"
TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _event(offset: int, close: str = "100") -> VenueMarketEvent:
    p = Decimal(close)
    return VenueMarketEvent(
        market=MarketEvent(offset, TS, SYMBOL, p, p, p, p, Decimal("10")),
        book=OrderBookSnapshot(
            last_update_id=100 + offset,
            bids=((Decimal("99"), Decimal("10")),),
            asks=((Decimal("101"), Decimal("10")),),
        ),
    )


def _stages(*, broken_risk: bool = False) -> BacktestStageFunctions:
    def feature(e):
        return {"close": e.close}

    def regime(e, f):
        return "TREND"

    def prediction(e, f, r):
        return {"expected": f["close"]}

    def signal(e, p):
        return True

    def opportunity(e, s, r):
        return {"score": Decimal("1")}

    def portfolio(e, o, q):
        return {"qty": Decimal("1")}

    def risk(e, p, q):
        if broken_risk:
            return {"allowed": False, "qty": Decimal("0")}
        return {"allowed": True, "qty": Decimal("1")}

    def intent(e, r):
        return OrderIntent(
            intent_id=f"I-{e.event_offset}",
            decision_id="D1",
            portfolio_decision_id="P1",
            risk_decision_id="R1",
            strategy_id="S1",
            model_id="M1",
            execution_version="V379",
            symbol=SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=Decimal("1"),
            order_type=OrderType.MARKET,
            window=ValidWindow(TS, datetime(2030, 1, 1, tzinfo=timezone.utc)),
        )

    return BacktestStageFunctions(feature, regime, prediction, signal, opportunity, portfolio, risk, intent)


def _model():
    return BinanceVenueExecutionModelConfig(version="V379-EXEC", symbol=SYMBOL)


def test_execution_parity_is_non_vacuous_and_tracks_intents():
    adapter = LiveShadowExecutionAdapter()
    comparison, result = ExecutionParityHarness().run(
        stages=_stages(), execution_model=_model(), symbol=SYMBOL,
        venue_events=[_event(0), _event(1)], adapter=adapter,
    )
    assert comparison.passed
    assert comparison.compared_intents == 2
    assert comparison.intent_mismatch_offsets == ()
    assert adapter.observed_intents == ["I-0", "I-1"]
    assert result.event_count == 2


def test_adapter_scripted_observation_is_captured():
    observation = AdapterObservation(
        intent_id="I-0", client_order_id="cid-1", status=AdapterStatus.FILLED,
        exchange_order_id="77", executed_quantity=Decimal("1"), average_price=Decimal("100"),
        raw_hash="raw", source="TESTNET_FAKE",
    )
    adapter = LiveShadowExecutionAdapter({"I-0": observation})
    comparison, _ = ExecutionParityHarness().run(
        stages=_stages(), execution_model=_model(), symbol=SYMBOL,
        venue_events=[_event(0)], adapter=adapter,
    )
    assert comparison.passed


def test_testnet_mutation_gate_is_fail_closed_by_default():
    intent = _stages().intent_fn(_event(0).market, {"allowed": True, "qty": Decimal("1")})
    with pytest.raises(PermissionError, match="TESTNET_MUTATION_NOT_EXPLICITLY_APPROVED"):
        TestnetMutationGate().authorize(intent=intent, reference_price=Decimal("100"))


def test_testnet_mutation_gate_applies_hard_notional_ceiling():
    intent = _stages().intent_fn(_event(0).market, {"allowed": True, "qty": Decimal("1")})
    gate = TestnetMutationGate(mutation_enabled=True, operator_approval=True, max_notional=Decimal("99"))
    with pytest.raises(PermissionError, match="TESTNET_NOTIONAL_LIMIT_EXCEEDED"):
        gate.authorize(intent=intent, reference_price=Decimal("100"))


def test_testnet_public_probe_rejects_non_testnet_host():
    with pytest.raises(PermissionError, match="NETWORK_POLICY_DENIED"):
        BinanceTestnetPublicProbe(base_url="https://fapi.binance.com")


def test_deliberate_live_stage_mutation_is_detected():
    from trading_platform.v375.decision_parity import capture_backtest_decision_trace, compare_decision_traces, LiveDecisionEngine
    events = [_event(0), _event(1)]
    # Use the current backtest trace as the immutable comparison target.
    collector, _ = capture_backtest_decision_trace(
        _stages(),
        __import__("trading_platform.v373.backtest_engine", fromlist=["ExecutionModelConfig"]).ExecutionModelConfig(
            version="M", mode=__import__("trading_platform.v373.backtest_engine", fromlist=["SimulationMode"]).SimulationMode.REALISTIC,
            fee_bps=Decimal("0"), slippage_bps=Decimal("0"),
            determinism=__import__("trading_platform.v373.backtest_engine", fromlist=["DeterminismClass"]).DeterminismClass.EXACT,
        ),
        SYMBOL, [e.market for e in events],
    )
    live = LiveDecisionEngine(_stages(broken_risk=True)).run(
        [e.market for e in events], collector.position_quantities,
    )
    comparison = compare_decision_traces(collector, live.trace)
    assert not comparison.passed
    assert comparison.mismatch_offsets == (0, 1)


def test_testnet_order_adapter_market_mapping_is_deterministic():
    from trading_platform.v35.binance_execution import BinanceTestnetExecutionGateway, BinanceTestnetExecutionConfig
    from trading_platform.v35.binance_execution import RuntimeCredentialValues
    class FakeGateway(BinanceTestnetExecutionGateway):
        def __init__(self):
            super().__init__(BinanceTestnetExecutionConfig())
            self.requests = []
        def submit(self, order, *, credentials):
            self.requests.append(order)
            return __import__("trading_platform.v35.binance_execution", fromlist=["SubmitObservation"]).SubmitObservation(
                __import__("trading_platform.v35.binance_execution", fromlist=["ExchangeOutcome"]).ExchangeOutcome.ACKNOWLEDGED,
                order.client_order_id, "77", raw={"status": "NEW", "orderId": 77, "clientOrderId": order.client_order_id}
            )
    gateway = FakeGateway()
    adapter = BinanceTestnetOrderAdapter(gateway, TestnetMutationGate(mutation_enabled=True, operator_approval=True, max_notional=Decimal("200")))
    intent = _stages().intent_fn(_event(0).market, {"allowed": True, "qty": Decimal("1")})
    result = adapter.submit(intent, credentials=RuntimeCredentialValues("k", b"s"), now=TS, reference_price=Decimal("100"))
    assert result.outcome.value == "ACKNOWLEDGED"
    assert gateway.requests[0].client_order_id == "tp-" + __import__("hashlib").sha256(intent.intent_id.encode()).hexdigest()[:24]
    assert gateway.requests[0].order_type is OrderType.MARKET


def test_testnet_order_adapter_limit_is_fail_closed_until_request_contract_is_extended():
    from trading_platform.v35.binance_execution import BinanceTestnetExecutionGateway, BinanceTestnetExecutionConfig, RuntimeCredentialValues
    class FakeGateway(BinanceTestnetExecutionGateway):
        def __init__(self):
            super().__init__(BinanceTestnetExecutionConfig())
    adapter = BinanceTestnetOrderAdapter(FakeGateway(), TestnetMutationGate(mutation_enabled=True, operator_approval=True, max_notional=Decimal("200")))
    base = _stages().intent_fn(_event(0).market, {"allowed": True, "qty": Decimal("1")})
    limit_intent = OrderIntent(**{**base.__dict__, "order_type": OrderType.LIMIT, "price": Decimal("100")})
    with pytest.raises(ValueError, match="LIMIT_ORDER_ADAPTER_NOT_SUPPORTED"):
        adapter.to_order_request(limit_intent, now=TS)
