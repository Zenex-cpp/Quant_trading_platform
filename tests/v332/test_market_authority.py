from decimal import Decimal
import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v332 import (
    MarketDataAuthorityConflict,
    MarketDataAuthorityLedger,
    MarketDataAuthorityState,
)


def record(ledger, **kwargs):
    return ledger.record_observation(
        symbol=kwargs.get("symbol", "BTCUSDT"),
        feed_id=kwargs.get("feed_id", "primary"),
        event_time_ms=kwargs.get("event_time_ms", 1_000),
        receive_time_ms=kwargs.get("receive_time_ms", 1_050),
        processing_time_ms=kwargs.get("processing_time_ms", 1_100),
        max_age_ms=kwargs.get("max_age_ms", 1_000),
        source=kwargs.get("source", "test-feed"),
        sequence_number=kwargs.get("sequence_number", 1),
    )


def test_fresh_market_data_is_orderable():
    ledger = MarketDataAuthorityLedger()
    rec = record(ledger)
    assert rec.authority_state is MarketDataAuthorityState.VERIFIED
    assert ledger.assert_fresh(symbol="BTCUSDT", now_ms=1_500).event_time_ms == 1_000


def test_stale_market_data_blocks():
    ledger = MarketDataAuthorityLedger()
    record(ledger)
    with pytest.raises(MarketDataAuthorityConflict, match="MARKET_DATA_STALE"):
        ledger.assert_fresh(symbol="BTCUSDT", now_ms=2_000)


def test_missing_market_data_fails_closed():
    ledger = MarketDataAuthorityLedger()
    with pytest.raises(MarketDataAuthorityConflict, match="MARKET_DATA_AUTHORITY_MISSING"):
        ledger.assert_fresh(symbol="ETHUSDT", now_ms=1_500)


def test_future_record_is_not_yet_valid():
    ledger = MarketDataAuthorityLedger()
    record(ledger, event_time_ms=2_000, receive_time_ms=2_050, processing_time_ms=2_100)
    with pytest.raises(MarketDataAuthorityConflict, match="MARKET_DATA_AUTHORITY_NOT_YET_VALID"):
        ledger.assert_fresh(symbol="BTCUSDT", now_ms=2_000)


def test_invalid_temporal_order_is_rejected():
    ledger = MarketDataAuthorityLedger()
    with pytest.raises(ValueError, match="MARKET_RECEIVE_BEFORE_EVENT_TIME"):
        record(ledger, event_time_ms=2_000, receive_time_ms=1_999)
    with pytest.raises(ValueError, match="MARKET_PROCESSING_BEFORE_RECEIVE_TIME"):
        record(ledger, event_time_ms=1_000, receive_time_ms=1_050, processing_time_ms=1_049)


def test_restart_reconstructs_market_authority():
    store = EventStore()
    ledger = MarketDataAuthorityLedger(store)
    record(ledger)
    reloaded = MarketDataAuthorityLedger(store)
    assert reloaded.assert_fresh(symbol="BTCUSDT", now_ms=1_500).feed_id == "primary"


def test_corrupted_market_authority_chain_blocks():
    store = EventStore()
    ledger = MarketDataAuthorityLedger(store)
    record(ledger)
    tamper_event_store(store, "UPDATE events SET event_hash='corrupted' WHERE sequence=1")
    with pytest.raises(MarketDataAuthorityConflict, match="MARKET_DATA_AUTHORITY_CHAIN_INVALID"):
        ledger.assert_fresh(symbol="BTCUSDT", now_ms=1_500)


def test_duplicate_observation_is_idempotent():
    store = EventStore()
    ledger = MarketDataAuthorityLedger(store)
    a = record(ledger)
    b = record(ledger)
    assert a.fingerprint == b.fingerprint
    assert store.latest_sequence() == 1


def test_processing_after_expiry_creates_expired_authority():
    ledger = MarketDataAuthorityLedger()
    rec = record(ledger, processing_time_ms=2_500)
    assert rec.authority_state is MarketDataAuthorityState.EXPIRED
    with pytest.raises(MarketDataAuthorityConflict, match="MARKET_DATA_STALE"):
        ledger.assert_fresh(symbol="BTCUSDT", now_ms=2_500)

def test_runtime_integration_blocks_stale_market_before_gateway(tmp_path):
    from datetime import datetime, timezone, timedelta
    from decimal import Decimal
    from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
    from trading_platform.v33.commit import CommitCoordinator
    from trading_platform.v34.execution_bridge import ExecutionBridge
    from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation
    from trading_platform.v310.runtime_orchestrator import OrchestrationState, RuntimeCycleSnapshot
    from trading_platform.v312.execution_runtime import ExecutionRuntimeIntegration
    from trading_platform.v331 import PositionAuthorityLedger
    from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, PositionState, Side
    from trading_platform.core.ttl import ValidWindow
    from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState

    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    win = ValidWindow(now - timedelta(seconds=1), now + timedelta(minutes=5))
    axes = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
    truth = build_truth(observed_at_ns=1, axes=axes,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),
        requested_risk=Decimal("100"), caps={k: Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")})
    intent = OrderIntent("IM4","DM4","PM4","RM4","SM4","MM4","EM4","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,win)
    payload = {"intent_id":"IM4","decision_id":"DM4","risk_decision_id":"RM4","portfolio_decision_id":"PM4","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"EM4"}
    cc = CommitCoordinator()
    cap = cc.capabilities.issue(truth=truth, requested_risk=Decimal("1"), decision_id="DM4", intent_payload=payload, expires_at=now + timedelta(minutes=1))
    bridge = ExecutionBridge(commit=cc)
    bridge.commit_intent(capability=cap, intent=intent, truth=truth, now=now, position_state=PositionState.FLAT,
                         market_window=win, upstream_windows=[win], risk_valid=True)

    pos = PositionAuthorityLedger()
    pos.record_reconciliation(symbol="BTCUSDT", local_quantity=Decimal("0"), exchange_quantity=Decimal("0"),
                              reconciliation=ReconciliationResult(ReconciliationState.GREEN, ReconciliationDiff(), "r", "s", "REST_WS_MATCH"),
                              observed_at_ms=1000, ttl_ms=10000, position_state=PositionState.FLAT)
    market = MarketDataAuthorityLedger()
    market.record_observation(symbol="BTCUSDT", feed_id="primary", event_time_ms=0, receive_time_ms=0, processing_time_ms=0,
                              max_age_ms=100, source="test-feed", sequence_number=1)

    class O:
        def snapshot(self, now_epoch):
            return RuntimeCycleSnapshot(OrchestrationState.ACTIVE, "ACTIVE", "OPEN", True, True, False, False, "TEST", 0, "OK")

    class G:
        def __init__(self): self.calls = []
        def submit(self, order, *, credentials):
            self.calls.append(order)
            return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX-M4")

    gateway = G()
    runtime = ExecutionRuntimeIntegration(orchestrator=O(), bridge=bridge, gateway=gateway,
                                          position_authority=pos, market_data_authority=market)
    result = runtime.dispatch(intent=intent, credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=1.0)
    assert result.submitted is False
    assert "MARKET_DATA_AUTHORITY_DENIED:MARKET_DATA_STALE" in result.reason
    assert gateway.calls == []
