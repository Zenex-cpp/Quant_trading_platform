from datetime import datetime, timezone, timedelta
from decimal import Decimal

from trading_platform.v30.truth import AxisSnapshot, ConfigurationStatus, TruthComponent, TruthStatus, build_truth
from trading_platform.v33.commit import CommitCoordinator
from trading_platform.v34.execution_bridge import ExecutionBridge, BridgeStatus
from trading_platform.v35.binance_execution import ExchangeOutcome, RuntimeCredentialValues, SubmitObservation, ExchangeUncertain
from trading_platform.v310.runtime_orchestrator import RuntimeCycleSnapshot, OrchestrationState
from trading_platform.v312.execution_runtime import ExecutionRuntimeIntegration
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, PositionState, Side
from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState
from trading_platform.v331 import PositionAuthorityLedger
from trading_platform.v332 import MarketDataAuthorityLedger
from trading_platform.v333 import CausalTTLAuthorityLedger
from tests.causal_helpers import causal_authority_for_intent
from trading_platform.core.ttl import ValidWindow
from trading_platform.portfolio.config import ConfigValue, Precedence
from trading_platform.v343.config_authority import ConfigurationAuthorityLedger
from tests.dispatch_support import risk_accounting_reservation_for, risk_decision_ledger_for
from trading_platform.v21.event_store import EventStore
from trading_platform.v321 import DurableDispatchAttemptLedger

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
BASE_MS = int(NOW.timestamp() * 1000)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth(configuration):
    return build_truth(observed_at_ns=int(NOW.timestamp() * 1_000_000_000), axes=AX,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),
        requested_risk=Decimal("100"), caps={k: Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")},
        configuration_status=ConfigurationStatus.RESOLVED,
        configuration_fingerprint=configuration.candidates_fingerprint,
        configuration_resolution_id=configuration.resolution_id)


def intent():
    return OrderIntent("I312","D312","P312","R312","S312","M312","E312","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,WIN,risk_reservation_id="RR312")



def position_authority():
    ledger = PositionAuthorityLedger()
    recon = ReconciliationResult(
        ReconciliationState.GREEN, ReconciliationDiff(),
        "rest-hash", "stream-hash", "REST_WS_MATCH",
    )
    ledger.record_reconciliation(
        symbol="BTCUSDT", local_quantity=Decimal("0"), exchange_quantity=Decimal("0"),
        reconciliation=recon, observed_at_ms=BASE_MS, ttl_ms=10_000,
        position_state=PositionState.FLAT,
    )
    return ledger


def market_authority():
    ledger = MarketDataAuthorityLedger()
    ledger.record_observation(
        symbol="BTCUSDT", feed_id="primary", event_time_ms=BASE_MS, receive_time_ms=BASE_MS,
        processing_time_ms=BASE_MS, max_age_ms=10000, source="test", sequence_number=1,
    )
    return ledger

def payload():
    return {"intent_id":"I312","decision_id":"D312","risk_decision_id":"R312","portfolio_decision_id":"P312","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E312"}


def config_values():
    return (ConfigValue("runtime_configuration", "cfg-v1", Precedence.RUNTIME, "runtime", "1"),)


def configuration_authority(*, values=None, resolution_id="runtime-config-1", expires_at=None):
    values = tuple(values or config_values())
    ledger = ConfigurationAuthorityLedger()
    record, _ = ledger.record(
        resolution_id=resolution_id,
        config_name="runtime_configuration",
        values=values,
        valid_from=NOW - timedelta(seconds=1),
        expires_at=expires_at or NOW + timedelta(minutes=5),
        recorded_at_ms=BASE_MS,
        operator="test",
    )
    return ledger, record, values


def bridge(configuration):
    cc = CommitCoordinator()
    t = truth(configuration)
    cap = cc.capabilities.issue(truth=t, requested_risk=Decimal("10"), decision_id="D312", intent_payload=payload(), expires_at=NOW + timedelta(seconds=30))
    b = ExecutionBridge(commit=cc)
    obs = b.commit_intent(capability=cap, intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    assert obs.status is BridgeStatus.COMMITTED
    return b


def runtime_inputs():
    ledger, record, values = configuration_authority()
    return bridge(record), ledger, record, values


def risk_authority(b, *, expires_at_ms=None):
    return risk_decision_ledger_for(
        b, intent(), now_ms=BASE_MS,
        expires_at_ms=expires_at_ms if expires_at_ms is not None else BASE_MS + 60_000,
    )


class FakeGateway:
    def __init__(self, behavior): self.behavior, self.calls = behavior, []
    def submit(self, order, *, credentials):
        self.calls.append(order)
        return self.behavior(order, credentials)


class FakeOrchestrator:
    def __init__(self):
        self.allowed = True
    def snapshot(self, now):
        return RuntimeCycleSnapshot(OrchestrationState.ACTIVE if self.allowed else OrchestrationState.BLOCKED, "ACTIVE", "OPEN", True, self.allowed, False, not self.allowed, "TEST", 0, "OK" if self.allowed else "BLOCKED")


def test_true_path_uses_committed_bridge_request_and_testnet_gateway(tmp_path):
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    accounting, reservation_gate = risk_accounting_reservation_for(
        b, intent(), now_ms=BASE_MS, directory=tmp_path,
    )
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX312"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()), risk_decision_ledger=risk_authority(b), accounting_authority=accounting, risk_reservation_gate=reservation_gate, dispatch_attempt_ledger=DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db"))), configuration_authority=config)
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id, configuration_values=values)
    assert res.submitted is True and res.exchange_uncertain is False
    assert res.receipt is not None and res.receipt.exchange_order_id == "EX312"
    assert len(g.calls) == 1


def test_runtime_without_persistent_side_effect_store_fails_closed():
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "MUST-NOT-SEND"))
    rt = ExecutionRuntimeIntegration(
        orchestrator=o, bridge=b, gateway=g,
        position_authority=position_authority(), market_data_authority=market_authority(),
        causal_ttl_authority=causal_authority_for_intent(intent()), risk_decision_ledger=risk_authority(b),
        configuration_authority=config,
    )

    res = rt.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(),
        configuration_resolution_id=resolution.resolution_id, configuration_values=values,
    )

    assert res.submitted is False
    assert res.reason == "SIDE_EFFECT_LEDGER_NOT_PERSISTENT"
    assert g.calls == []


def test_transport_uncertainty_marks_unknown_and_requires_reconciliation(tmp_path):
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    accounting, reservation_gate = risk_accounting_reservation_for(
        b, intent(), now_ms=BASE_MS, directory=tmp_path,
    )
    def uncertain(order, credentials): raise ExchangeUncertain("SUBMIT_OUTCOME_UNKNOWN")
    g = FakeGateway(uncertain)
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()), risk_decision_ledger=risk_authority(b), accounting_authority=accounting, risk_reservation_gate=reservation_gate, dispatch_attempt_ledger=DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db"))), configuration_authority=config)
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id, configuration_values=values)
    assert res.exchange_uncertain is True and res.recovery_required is True
    assert b._lifecycles[intent().intent_id].state.value == "UNKNOWN"


def test_permission_lost_after_network_dispatch_is_not_reported_as_clean_cycle(tmp_path):
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    accounting, reservation_gate = risk_accounting_reservation_for(
        b, intent(), now_ms=BASE_MS, directory=tmp_path,
    )
    def behavior(order, credentials):
        o.allowed = False
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX312-RACE")
    g = FakeGateway(behavior)
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()), risk_decision_ledger=risk_authority(b), accounting_authority=accounting, risk_reservation_gate=reservation_gate, dispatch_attempt_ledger=DurableDispatchAttemptLedger(EventStore(str(tmp_path / "attempt.db"))), configuration_authority=config)
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id, configuration_values=values)
    assert res.submitted is True
    assert res.recovery_required is True
    assert res.reason == "PERMISSION_LOST_DURING_CYCLE"


def test_blocked_runtime_makes_zero_exchange_calls():
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator(); o.allowed = False
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "NEVER"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), causal_ttl_authority=causal_authority_for_intent(intent()), configuration_authority=config)
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id, configuration_values=values)
    assert not res.submitted and not g.calls


def test_missing_causal_ttl_authority_blocks_before_gateway():
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "NEVER"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, position_authority=position_authority(), market_data_authority=market_authority(), risk_decision_ledger=risk_authority(b), configuration_authority=config)
    res = rt.dispatch(intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id, configuration_values=values)
    assert res.submitted is False
    assert "CAUSAL_TTL_DENIED:CAUSAL_TTL_INTENT_NOT_FOUND" in res.reason
    assert g.calls == []


def test_missing_risk_decision_authority_blocks_final_runtime_dispatch():
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "MUST-NOT-SEND"))
    rt = ExecutionRuntimeIntegration(
        orchestrator=o, bridge=b, gateway=g,
        position_authority=position_authority(), market_data_authority=market_authority(),
        causal_ttl_authority=causal_authority_for_intent(intent()),
        configuration_authority=config,
    )
    result = rt.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"),
        now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id,
        configuration_values=values,
    )
    assert result.reason == "RISK_DECISION_LEDGER_REQUIRED"
    assert result.submitted is False and g.calls == []


def test_expired_risk_decision_blocks_final_runtime_dispatch():
    b, config, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "MUST-NOT-SEND"))
    rt = ExecutionRuntimeIntegration(
        orchestrator=o, bridge=b, gateway=g,
        position_authority=position_authority(), market_data_authority=market_authority(),
        causal_ttl_authority=causal_authority_for_intent(intent()),
        risk_decision_ledger=risk_authority(b, expires_at_ms=BASE_MS),
        configuration_authority=config,
    )
    result = rt.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"),
        now_epoch=NOW.timestamp(), configuration_resolution_id=resolution.resolution_id,
        configuration_values=values,
    )
    assert "RISK_DECISION_DENIED:RISK_DECISION_EXPIRED_OR_NOT_YET_VALID" in result.reason
    assert result.submitted is False and g.calls == []


def test_configuration_conflict_blocks_before_exchange_dispatch():
    b, ledger, _, _ = runtime_inputs(); o = FakeOrchestrator()
    conflict = (
        ConfigValue("runtime_configuration", "cfg-a", Precedence.RUNTIME, "runtime-a", "1"),
        ConfigValue("runtime_configuration", "cfg-b", Precedence.RUNTIME, "runtime-b", "1"),
    )
    conflict_record, _ = ledger.record(
        resolution_id="runtime-config-conflict",
        config_name="runtime_configuration",
        values=conflict,
        valid_from=NOW - timedelta(seconds=1),
        expires_at=NOW + timedelta(minutes=5),
        recorded_at_ms=BASE_MS + 1,
        operator="test",
    )
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "MUST-NOT-SEND"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, configuration_authority=ledger)
    res = rt.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(),
        configuration_resolution_id=conflict_record.resolution_id, configuration_values=conflict,
    )
    assert not res.submitted
    assert res.reason == "CONFIGURATION_AUTHORITY_DENIED:CONFIG_CONFLICT"
    assert g.calls == []


def test_dispatch_requires_configuration_authority_and_binding():
    b, ledger, resolution, values = runtime_inputs(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "MUST-NOT-SEND"))
    without_authority = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g)
    result = without_authority.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(),
        configuration_resolution_id=resolution.resolution_id, configuration_values=values,
    )
    assert result.reason == "CONFIGURATION_AUTHORITY_REQUIRED"
    with_authority = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, configuration_authority=ledger)
    result = with_authority.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(),
    )
    assert result.reason == "CONFIGURATION_RESOLUTION_BINDING_REQUIRED"
    assert g.calls == []


def test_stale_or_changed_configuration_cannot_dispatch():
    b, ledger, resolution, _ = runtime_inputs(); o = FakeOrchestrator()
    g = FakeGateway(lambda order, credentials: SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "MUST-NOT-SEND"))
    rt = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, configuration_authority=ledger)
    changed = (ConfigValue("runtime_configuration", "cfg-v2", Precedence.RUNTIME, "runtime", "2"),)
    result = rt.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(),
        configuration_resolution_id=resolution.resolution_id, configuration_values=changed,
    )
    assert "CONFIGURATION_FINGERPRINT_MISMATCH" in result.reason
    expired_ledger, expired, expired_values = configuration_authority(
        resolution_id="expired-config", expires_at=NOW,
    )
    expired_runtime = ExecutionRuntimeIntegration(orchestrator=o, bridge=b, gateway=g, configuration_authority=expired_ledger)
    result = expired_runtime.dispatch(
        intent=intent(), credentials=RuntimeCredentialValues("API", b"SECRET"), now_epoch=NOW.timestamp(),
        configuration_resolution_id=expired.resolution_id, configuration_values=expired_values,
    )
    assert "CONFIGURATION_RESOLUTION_EXPIRED" in result.reason
    assert g.calls == []
