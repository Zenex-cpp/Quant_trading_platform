from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v21.event_store import EventStore
from trading_platform.v25.health import EvidenceFreshness, HealthState, assess_health
from trading_platform.v30.truth import AxisSnapshot, CanonicalAction, ConfigurationStatus, TruthComponent, TruthStatus, build_truth
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionConflict, RiskDecisionRecord, RiskSystemState
from trading_platform.v351 import (
    ModelHealthRiskError,
    assert_model_health_monotone,
    bind_model_health_to_risk,
)


AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth():
    comps = tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK", (f"E-{n}",)) for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger"))
    caps = {k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")}
    return build_truth(
        observed_at_ns=1,
        axes=AXES,
        components=comps,
        requested_risk=Decimal("100"),
        caps=caps,
        decision_fresh=True,
        configuration_status=ConfigurationStatus.RESOLVED,
    )


def assessment(*, assessment_id: str = "H-M24", state: HealthState = HealthState.HEALTHY, fresh: bool = True, drift: bool = False, quality: bool = True):
    return assess_health(
        assessment_id=assessment_id,
        now_ns=10,
        evidence=EvidenceFreshness("EV-M24", captured_at_ns=1, ttl_ns=100, verified=True) if fresh else EvidenceFreshness("EV-M24", captured_at_ns=1, ttl_ns=1, verified=True),
        drift_critical=drift,
        quality_ok=quality,
        stream_healthy=state is not HealthState.BLOCKED,
    ) if state in {HealthState.HEALTHY, HealthState.DEGRADED} else type("BlockedAssessment", (), {
        "assessment_id": assessment_id,
        "state": state,
        "evidence_fresh": fresh,
        "drift_critical": drift,
        "quality_ok": quality,
        "reason": "BLOCKED",
    })()


def decision(*, allowed="50", model_health=None, model_health_factor=None, model_health_max=None, assessment_id=None, state=None, fresh=None, drift=None, quality=None):
    return RiskDecisionRecord(
        decision_id="D-MH",
        action=RiskDecisionAction.ALLOW,
        risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("100"),
        allowed_exposure=Decimal(allowed),
        active_limits={"order": Decimal("100")},
        multipliers={"model_health": Decimal("1")},
        rejection_reason=None,
        reservation_id="RR-MH",
        intent_id="I-MH",
        created_at_ms=100,
        valid_from_ms=100,
        expires_at_ms=200,
        configuration_version="cfg1",
        risk_state_version="risk1",
        portfolio_version="port1",
        position_version="pos1",
        provenance_id="prov1",
        truth_hash="TH-MH",
        input_fingerprint="input-mh",
        model_health=None if model_health is None else Decimal(model_health),
        model_health_max=None if model_health_max is None else Decimal(model_health_max),
        model_health_risk_factor=None if model_health_factor is None else Decimal(model_health_factor),
        model_health_method=None if model_health is None else "CONSERVATIVE_LINEAR",
        model_health_method_version=None if model_health is None else "1",
        model_health_assessment_id=assessment_id,
        model_health_state=state,
        model_health_evidence_fresh=fresh,
        model_health_drift_critical=drift,
        model_health_quality_ok=quality,
    )


def test_model_health_binding_is_conservative_and_monotone():
    a_good = assessment()
    good = bind_model_health_to_risk(model_health=Decimal("0.9"), baseline_risk=Decimal("100"), assessment=a_good, assessment_id="H-M24")
    bad = bind_model_health_to_risk(model_health=Decimal("0.2"), baseline_risk=Decimal("100"), assessment=a_good, assessment_id="H-M24")
    assert good.allowed_risk == Decimal("90.0")
    assert bad.allowed_risk == Decimal("20.0")
    assert_model_health_monotone(higher_health=good.model_health, higher_allowed_risk=good.allowed_risk, lower_health=bad.model_health, lower_allowed_risk=bad.allowed_risk)


def test_runtime_authority_blocks_worse_model_health_from_increasing_risk():
    a = assessment()
    good = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("50"), decision_id="MH-GOOD", model_health=Decimal("0.9"), model_health_assessment=a, model_health_assessment_id="H-M24")
    bad = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("50"), decision_id="MH-BAD", model_health=Decimal("0.2"), model_health_assessment=a, model_health_assessment_id="H-M24")
    assert good.status is AuthorityStatus.AUTHORIZED
    assert bad.status is AuthorityStatus.DENIED
    assert bad.reason == "RISK_EXCEEDS_MODEL_HEALTH_ADJUSTED_RISK"
    assert good.model_health_risk_factor == Decimal("0.9")
    assert bad.model_health_risk_factor == Decimal("0.2")


def test_runtime_requires_fresh_verified_model_health_source():
    stale = assessment(fresh=False)
    decision = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="MH-STALE", model_health=Decimal("0.9"), model_health_assessment=stale, model_health_assessment_id="H-M24")
    assert decision.status is AuthorityStatus.DENIED
    assert decision.reason.startswith("MODEL_HEALTH_RISK_BLOCKED:MODEL_HEALTH_EVIDENCE_STALE")


def test_runtime_requires_assessment_id_and_exact_source_binding():
    a = assessment()
    missing = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="MH-MISS", model_health=Decimal("0.9"), model_health_assessment=a)
    mismatch = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"), decision_id="MH-MISM", model_health=Decimal("0.9"), model_health_assessment=a, model_health_assessment_id="OTHER")
    assert missing.reason == "MODEL_HEALTH_SOURCE_BINDING_REQUIRED"
    assert "MODEL_HEALTH_ASSESSMENT_ID_MISMATCH" in mismatch.reason


def test_adjusted_risk_derives_model_health_factor_and_rejects_upward_override():
    assert adjusted_risk(Decimal("100"), model_health=Decimal("0.2")) == Decimal("20.0")
    with pytest.raises(ValueError, match="MODEL_HEALTH_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("100"), model_health=Decimal("0.2"), model_health_factor=Decimal("0.8"))
    with pytest.raises(ModelHealthRiskError, match="MODEL_HEALTH_FACTOR_MUST_BE_NONINCREASING"):
        adjusted_risk(Decimal("100"), model_health_factor=Decimal("1.1"))


def test_durable_decision_rejects_budget_above_model_health_cap():
    ledger = DurableRiskDecisionLedger(EventStore())
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_MODEL_HEALTH_CAP"):
        ledger.record(decision(allowed="21", model_health="0.2", model_health_factor="0.2", model_health_max="1", assessment_id="H-M24", state="HEALTHY", fresh=True, drift=False, quality=True))


def test_durable_decision_restart_safe_and_health_stale_blocks(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    d = decision(allowed="20", model_health="0.2", model_health_factor="0.2", model_health_max="1", assessment_id="H-M24", state="HEALTHY", fresh=True, drift=False, quality=True)
    ledger.record(d)
    restored = DurableRiskDecisionLedger(EventStore(path)).get("D-MH")
    assert restored == d
    snap = DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
        decision_id="D-MH", now_ms=150, intent_id="I-MH", reservation_id="RR-MH", requested_exposure=Decimal("20"), truth_hash="TH-MH", model_health=Decimal("0.2"), model_health_assessment_id="H-M24",
    )
    assert snap.model_health == Decimal("0.2")
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_MODEL_HEALTH_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-MH", now_ms=150, intent_id="I-MH", reservation_id="RR-MH", requested_exposure=Decimal("20"), truth_hash="TH-MH", model_health=Decimal("0.1"), model_health_assessment_id="H-M24",
        )
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_MODEL_HEALTH_ASSESSMENT_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-MH", now_ms=150, intent_id="I-MH", reservation_id="RR-MH", requested_exposure=Decimal("20"), truth_hash="TH-MH", model_health=Decimal("0.2"), model_health_assessment_id="H-OTHER",
        )


def test_capability_identity_changes_with_model_health_and_commit_rechecks_source():
    from datetime import datetime, timedelta, timezone
    from trading_platform.v32.capability import CapabilityAuthority, CapabilityError
    from trading_platform.v32.router import CommitRouter
    from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
    from trading_platform.core.ttl import ValidWindow
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    a = assessment()
    window = ValidWindow(now - timedelta(seconds=1), now + timedelta(minutes=5))
    intent = OrderIntent("I-MH-CAP", "D", "P", "R", "S", "M", "E", "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, window)
    payload = {
        "intent_id": intent.intent_id, "decision_id": intent.decision_id, "risk_decision_id": intent.risk_decision_id,
        "symbol": intent.symbol, "side": intent.side.value, "action": intent.action.value, "quantity": str(intent.quantity),
        "order_type": intent.order_type.value, "price": None, "execution_version": intent.execution_version,
    }
    ca = CapabilityAuthority()
    good = ca.issue(truth=truth(), requested_risk=Decimal("10"), decision_id="MHCAP", intent_payload=payload, expires_at=now + timedelta(seconds=10), model_health=Decimal("0.9"), model_health_assessment=a, model_health_assessment_id="H-M24")
    bad = ca.issue(truth=truth(), requested_risk=Decimal("10"), decision_id="MHCAP2", intent_payload=payload, expires_at=now + timedelta(seconds=10), model_health=Decimal("0.2"), model_health_assessment=a, model_health_assessment_id="H-M24")
    assert good.capability_id != bad.capability_id
    assert good.authority.input_fingerprint != bad.authority.input_fingerprint
    with pytest.raises(CapabilityError, match="MODEL_HEALTH_CHANGED"):
        CommitRouter().commit(
            capability=good, intent=intent, truth=truth(), now=now, position_state=PositionState.FLAT,
            market_window=window, upstream_windows=[window], risk_valid=True,
            model_health=Decimal("0.2"), model_health_assessment=a, model_health_assessment_id="H-M24",
        )



def test_unregistered_model_health_method_fails_closed():
    with pytest.raises(ModelHealthRiskError, match="MODEL_HEALTH_METHOD_NOT_REGISTERED"):
        bind_model_health_to_risk(model_health=Decimal("0.5"), baseline_risk=Decimal("10"), assessment=assessment(), assessment_id="H-M24", method="UNKNOWN", method_version="1")


def test_assessment_health_states_that_are_unknown_or_blocked_do_not_authorize_model_health_risk():
    from types import SimpleNamespace
    unknown = SimpleNamespace(assessment_id="H-M24", state=HealthState.UNKNOWN, evidence_fresh=True, drift_critical=False, quality_ok=True)
    blocked = SimpleNamespace(assessment_id="H-M24", state=HealthState.BLOCKED, evidence_fresh=True, drift_critical=False, quality_ok=True)
    with pytest.raises(ModelHealthRiskError, match="MODEL_HEALTH_STATE_NOT_APPLICABLE"):
        bind_model_health_to_risk(model_health=Decimal("0.8"), baseline_risk=Decimal("10"), assessment=unknown, assessment_id="H-M24")
    with pytest.raises(ModelHealthRiskError, match="MODEL_HEALTH_STATE_NOT_APPLICABLE"):
        bind_model_health_to_risk(model_health=Decimal("0.8"), baseline_risk=Decimal("10"), assessment=blocked, assessment_id="H-M24")


def test_model_health_off_preserves_baseline_and_zero_preserves_baseline():
    assert adjusted_risk(Decimal("100")) == Decimal("100")
    assert adjusted_risk(Decimal("100"), model_health=Decimal("1")) == Decimal("100")
    assert adjusted_risk(Decimal("100"), model_health=Decimal("0.5")) == Decimal("50.0")
