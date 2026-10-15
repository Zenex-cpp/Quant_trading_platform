from decimal import Decimal
from datetime import datetime, timezone
import pytest

from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side
from trading_platform.core.ttl import ValidWindow
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus
from trading_platform.v36.user_execution import BinanceExecutionCorrelation, parse_order_trade_update
from trading_platform.execution.lifecycle import OrderExecutionState

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
WINDOW = ValidWindow(NOW, NOW.replace(second=1))


def intent():
    return OrderIntent(
        intent_id="intent-1", decision_id="d1", portfolio_decision_id="p1", risk_decision_id="r1",
        strategy_id="s1", model_id="m1", execution_version="v36", symbol="BTCUSDT", side=Side.BUY,
        action=OrderAction.OPEN, quantity=Decimal("0.002"), order_type=OrderType.MARKET, window=WINDOW,
    )


def payload(status="NEW", execution="NEW", order_id=77, client_id="cid-1", trade_id=0, last_qty="0", last_price="0", cum="0"):
    return {
        "e": "ORDER_TRADE_UPDATE", "E": 1000, "T": 999,
        "o": {
            "s": "BTCUSDT", "c": client_id, "i": order_id,
            "x": execution, "X": status, "t": trade_id,
            "l": last_qty, "L": last_price, "z": cum, "n": "0.0001", "N": "USDT", "T": 1000,
        },
    }


def commit_stub():
    raise NotImplementedError


def setup_bridge(monkeypatch):
    bridge = ExecutionBridge()
    c = BinanceExecutionCorrelation(bridge)
    c.register(intent=intent(), client_order_id="cid-1")
    bridge._requests["intent-1"] = type("Req", (), {"order_request_id": "or-1", "client_order_id": "cid-1", "symbol": "BTCUSDT"})()
    bridge._lifecycles["intent-1"] = __import__("trading_platform.execution.lifecycle", fromlist=["OrderLifecycle"]).OrderLifecycle()
    bridge._lifecycles["intent-1"].apply(OrderExecutionState.SUBMITTED, event_id="seed", idempotency_key="seed")
    return bridge, c


def test_parser_extracts_binance_order_trade_fields():
    u = parse_order_trade_update(payload(status="PARTIALLY_FILLED", execution="TRADE", trade_id=9, last_qty="0.001", last_price="100000", cum="0.001"))
    assert u.client_order_id == "cid-1"
    assert u.exchange_order_id == "77"
    assert u.trade_id == "9"
    assert u.last_fill_quantity == Decimal("0.001")
    assert u.last_fill_price == Decimal("100000")
    assert u.is_trade


def test_event_correlates_by_client_then_binds_exchange_id():
    bridge, c = setup_bridge(None)
    r = c.observe(payload(status="NEW", execution="NEW", order_id=77))
    assert r.correlated and r.intent_id == "intent-1"
    assert c.correlate(client_order_id=None, exchange_order_id="77") == "intent-1"
    assert bridge._lifecycles["intent-1"].state is OrderExecutionState.ACKNOWLEDGED


def test_trade_update_creates_fill_and_duplicate_does_not_double_count():
    bridge, c = setup_bridge(None)
    p = payload(status="FILLED", execution="TRADE", order_id=77, trade_id=9, last_qty="0.001", last_price="100000", cum="0.001")
    r1 = c.observe(p)
    r2 = c.observe(p)
    assert r1.fill_id == "binance-trade:77:9"
    assert r2.duplicate
    assert bridge.fill_ledger.total_quantity("or-1") == Decimal("0.001")


def test_conflicting_client_and_exchange_correlation_fails_closed():
    bridge, c = setup_bridge(None)
    c.register(intent=OrderIntent("intent-2","d2","p2","r2","s2","m2","v36","BTCUSDT",Side.SELL,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WINDOW), client_order_id="cid-2")
    c.bind_exchange_order(intent_id="intent-2", exchange_order_id="88")
    c.bind_exchange_order(intent_id="intent-1", exchange_order_id="77")
    with pytest.raises(ValueError, match="ORDER_CORRELATION_CONFLICT"):
        c.correlate(client_order_id="cid-2", exchange_order_id="77")


def test_unknown_event_isolated_for_reconciliation():
    bridge, c = setup_bridge(None)
    r = c.observe(payload(status="NEW", execution="NEW", order_id=999, client_id="unknown-client"))
    assert not r.correlated
    assert r.status is BridgeStatus.RECONCILIATION_REQUIRED

class FakeGateway:
    def __init__(self, query_raw):
        self.query_raw = query_raw
        self.calls = []
    def submit(self, req, *, credentials):
        self.calls.append("POST")
        from trading_platform.v35.binance_execution import ExchangeUncertain
        raise ExchangeUncertain("SUBMIT_OUTCOME_UNKNOWN")
    def query(self, *, symbol, client_order_id, credentials):
        self.calls.append(("GET", symbol, client_order_id))
        from trading_platform.v35.binance_execution import SubmitObservation, ExchangeOutcome
        status = self.query_raw["status"]
        outcome = {"NEW": ExchangeOutcome.ACKNOWLEDGED, "CANCELED": ExchangeOutcome.CANCELLED, "REJECTED": ExchangeOutcome.REJECTED, "EXPIRED": ExchangeOutcome.REJECTED, "FILLED": ExchangeOutcome.ACKNOWLEDGED}.get(status, ExchangeOutcome.UNKNOWN)
        return SubmitObservation(outcome, client_order_id, str(self.query_raw["orderId"]), raw=self.query_raw)
    @staticmethod
    def lifecycle_target(obs):
        from trading_platform.v35.binance_execution import BinanceTestnetExecutionGateway
        return BinanceTestnetExecutionGateway.lifecycle_target(obs)


def test_ambiguous_submit_uses_one_post_then_one_query_without_retry():
    bridge, c = setup_bridge(None)
    g = FakeGateway({"status": "NEW", "orderId": 77, "executedQty": "0"})
    from trading_platform.v35.binance_execution import RuntimeCredentialValues
    r = c.submit_and_reconcile(intent=intent(), client_order_id="cid-1", gateway=g,
                                credentials=RuntimeCredentialValues("k", b"s"), exchange_submit=g.submit)
    assert g.calls == ["POST", ("GET", "BTCUSDT", "cid-1")]
    assert r.status is BridgeStatus.OBSERVED
    assert bridge._lifecycles["intent-1"].state is OrderExecutionState.ACKNOWLEDGED


def test_rest_filled_without_stream_fill_stays_unknown():
    bridge, c = setup_bridge(None)
    g = FakeGateway({"status": "FILLED", "orderId": 77, "executedQty": "0.001"})
    from trading_platform.v35.binance_execution import RuntimeCredentialValues
    c.register(intent=intent(), client_order_id="cid-1")
    bridge.mark_unknown("intent-1", exchange_order_id="77", client_order_id="cid-1")
    r = c.reconcile_unknown(intent_id="intent-1", gateway=g, credentials=RuntimeCredentialValues("k", b"s"))
    assert r.reason == "RECONCILIATION_VERIFIED"
    assert bridge._lifecycles["intent-1"].state is OrderExecutionState.UNKNOWN


def test_user_stream_closes_durable_unknown_attempt_before_bridge_mutation(tmp_path):
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger, DispatchAttemptState
    from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger

    bridge = ExecutionBridge()
    c = BinanceExecutionCorrelation(bridge, now_epoch=lambda: 2.0,
                                    dispatch_attempt_ledger=DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db"))))
    attempt_ledger = c.dispatch_attempt_ledger
    reconciliation = DurableDispatchReconciliationLedger(attempt_ledger.store, attempts=attempt_ledger)
    c.dispatch_reconciliation_ledger = reconciliation
    c.register(intent=intent(), client_order_id="cid-1")
    bridge._requests["intent-1"] = type("Req", (), {"order_request_id": "or-1", "client_order_id": "cid-1", "symbol": "BTCUSDT"})()
    bridge._lifecycles["intent-1"] = __import__("trading_platform.execution.lifecycle", fromlist=["OrderLifecycle"]).OrderLifecycle()
    bridge._lifecycles["intent-1"].apply(OrderExecutionState.SUBMITTED, event_id="seed", idempotency_key="seed")
    attempt_ledger.prepare(
        intent_id="intent-1", order_request_id="or-1", client_order_id="cid-1",
        request_fingerprint="rf", intent_fingerprint="if", idempotency_key="k", attempted_at_ms=1000,
    )
    attempt_ledger.observe(order_request_id="or-1", state=DispatchAttemptState.UNKNOWN,
                           exchange_order_id=None, outcome="UNKNOWN", reason="SUBMIT_EXCEPTION", observed_at_ms=1100)
    result = c.observe(payload(status="NEW", execution="NEW", order_id=77))
    assert result.correlated
    rec = reconciliation.get("or-1")
    assert rec is not None and rec.resolved_state is DispatchAttemptState.ACKNOWLEDGED
    assert attempt_ledger.get("or-1").state is DispatchAttemptState.UNKNOWN
    assert bridge._lifecycles["intent-1"].state is OrderExecutionState.ACKNOWLEDGED


def test_rest_reconciliation_closes_durable_unknown_attempt(tmp_path):
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger, DispatchAttemptState
    from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger

    bridge = ExecutionBridge()
    attempt_ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    reconciliation = DurableDispatchReconciliationLedger(attempt_ledger.store, attempts=attempt_ledger)
    c = BinanceExecutionCorrelation(bridge, now_epoch=lambda: 2.0,
                                    dispatch_attempt_ledger=attempt_ledger,
                                    dispatch_reconciliation_ledger=reconciliation)
    c.register(intent=intent(), client_order_id="cid-1")
    bridge._requests["intent-1"] = type("Req", (), {"order_request_id": "or-1", "client_order_id": "cid-1", "symbol": "BTCUSDT"})()
    bridge._lifecycles["intent-1"] = __import__("trading_platform.execution.lifecycle", fromlist=["OrderLifecycle"]).OrderLifecycle()
    bridge.mark_unknown("intent-1", exchange_order_id=None, client_order_id="cid-1")
    attempt_ledger.prepare(intent_id="intent-1", order_request_id="or-1", client_order_id="cid-1",
                          request_fingerprint="rf", intent_fingerprint="if", idempotency_key="k", attempted_at_ms=1000)
    attempt_ledger.observe(order_request_id="or-1", state=DispatchAttemptState.UNKNOWN,
                           exchange_order_id=None, outcome="UNKNOWN", reason="SUBMIT_EXCEPTION", observed_at_ms=1100)
    c.reconcile_unknown(intent_id="intent-1", gateway=FakeGateway({"status": "NEW", "orderId": 77, "executedQty": "0"}),
                        credentials=__import__("trading_platform.v35.binance_execution", fromlist=["RuntimeCredentialValues"]).RuntimeCredentialValues("k", b"s"))
    rec = reconciliation.get("or-1")
    assert rec is not None and rec.resolved_state is DispatchAttemptState.ACKNOWLEDGED


def test_rest_filled_closes_durable_attempt_when_fill_accounting_already_known(tmp_path):
    from trading_platform.v21.event_store import EventStore
    from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger, DispatchAttemptState
    from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger
    bridge = ExecutionBridge()
    attempt_ledger = DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db")))
    reconciliation = DurableDispatchReconciliationLedger(attempt_ledger.store, attempts=attempt_ledger)
    c = BinanceExecutionCorrelation(bridge, now_epoch=lambda: 2.0,
                                    dispatch_attempt_ledger=attempt_ledger,
                                    dispatch_reconciliation_ledger=reconciliation)
    c.register(intent=intent(), client_order_id="cid-1")
    bridge._requests["intent-1"] = type("Req", (), {"order_request_id": "or-1", "client_order_id": "cid-1", "symbol": "BTCUSDT"})()
    bridge.mark_unknown("intent-1", exchange_order_id=None, client_order_id="cid-1")
    attempt_ledger.prepare(intent_id="intent-1", order_request_id="or-1", client_order_id="cid-1",
                          request_fingerprint="rf", intent_fingerprint="if", idempotency_key="k", attempted_at_ms=1000)
    attempt_ledger.observe(order_request_id="or-1", state=DispatchAttemptState.UNKNOWN,
                           exchange_order_id=None, outcome="UNKNOWN", reason="SUBMIT_EXCEPTION", observed_at_ms=1100)
    # Seed accounting/fill quantity so the REST FILLED branch is allowed to close the case.
    from trading_platform.execution.models import Fill
    bridge.fill_ledger.apply(Fill("fill-1", "or-1", "77", Decimal("0.002"), Decimal("100000"), Decimal("0"), event_time=1200))
    c.reconcile_unknown(intent_id="intent-1", gateway=FakeGateway({"status": "FILLED", "orderId": 77, "executedQty": "0.002"}),
                        credentials=__import__("trading_platform.v35.binance_execution", fromlist=["RuntimeCredentialValues"]).RuntimeCredentialValues("k", b"s"))
    rec = reconciliation.get("or-1")
    assert rec is not None and rec.resolved_state is DispatchAttemptState.ACKNOWLEDGED
