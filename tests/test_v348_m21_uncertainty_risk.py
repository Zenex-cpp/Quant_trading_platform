from decimal import Decimal
from datetime import datetime, timezone, timedelta
import pytest
from trading_platform.model.uncertainty import conservative_risk_factor
from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v348.uncertainty_risk_authority import (
    UncertaintyRiskError,
    assert_uncertainty_monotone,
    bind_uncertainty_to_risk,
    conservative_risk_factor_decimal,
)
from trading_platform.v31.authority import RuntimeAuthority, AuthorityStatus
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth, CanonicalAction
from trading_platform.model.contracts import Prediction
from trading_platform.v348.uncertainty_assessment import UncertaintyAssessment
from tests._m21_calibration_helpers import synthetic_calibration_report

AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")

NOW=datetime(2026,9,25,tzinfo=timezone.utc)
NOW_NS=int(NOW.timestamp()*1_000_000_000)


def uncertainty_assessment(value="0.5", calibration_state="CALIBRATED", prediction_id=None):
    probability=float(value)
    prediction=Prediction(
        prediction_id=prediction_id or f"P-{value}-{calibration_state}", model_id="M21-SYNTHETIC",
        model_version="1", timestamp=NOW, feature_version="F1", target_version="T1",
        prediction=probability, probability=probability, expected_return=None, expected_risk=probability,
        uncertainty=probability, calibration_state=calibration_state, valid_from=NOW,
        expires_at=NOW+timedelta(minutes=5), artifact_hash="a"*64,
    )
    report = None if calibration_state == "UNKNOWN" else synthetic_calibration_report()
    return UncertaintyAssessment.from_prediction(prediction, calibration_report=report)


def truth(assessment=None):
    names=("health","provenance","governance","reconciliation","accounting","ledger")
    evidence={name:(f"E-{name}",) for name in names}
    if assessment is not None:
        names=(*names,"model_output")
        evidence["model_output"]=(assessment.source_evidence_id,assessment.source_fingerprint)
    comps=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK", evidence[n]) for n in names)
    caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}
    return build_truth(observed_at_ns=NOW_NS, axes=AXES, components=comps, requested_risk=Decimal("100"), caps=caps)

def test_decimal_uncertainty_factor_is_nonincreasing():
    assert conservative_risk_factor_decimal(Decimal("0.1")) >= conservative_risk_factor_decimal(Decimal("0.8"))
    assert conservative_risk_factor(0.1) >= conservative_risk_factor(0.8)

def test_binding_caps_allowed_risk():
    b=bind_uncertainty_to_risk(uncertainty=Decimal("0.8"), baseline_risk=Decimal("100"))
    assert b.risk_factor == Decimal("0.2")
    assert b.allowed_risk == Decimal("20.0")

def test_pairwise_monotonicity_higher_uncertainty_cannot_raise_risk():
    low=bind_uncertainty_to_risk(uncertainty=Decimal("0.2"), baseline_risk=Decimal("100"))
    high=bind_uncertainty_to_risk(uncertainty=Decimal("0.7"), baseline_risk=Decimal("100"))
    assert_uncertainty_monotone(lower_uncertainty=low.uncertainty, lower_allowed_risk=low.allowed_risk,
                                higher_uncertainty=high.uncertainty, higher_allowed_risk=high.allowed_risk)

def test_monotonicity_rejects_increasing_risk():
    with pytest.raises(UncertaintyRiskError, match="RISK_MONOTONICITY_BREACH_UNCERTAINTY"):
        assert_uncertainty_monotone(lower_uncertainty=Decimal("0.2"), lower_allowed_risk=Decimal("20"),
                                    higher_uncertainty=Decimal("0.8"), higher_allowed_risk=Decimal("21"))

def test_arbitrary_uncertainty_factor_above_one_rejected():
    with pytest.raises(UncertaintyRiskError, match="UNCERTAINTY_FACTOR_MUST_BE_NONINCREASING"):
        adjusted_risk(Decimal("10"), uncertainty_factor=Decimal("1.1"))

def test_adjusted_risk_derives_uncertainty_factor():
    assert adjusted_risk(Decimal("100"), uncertainty=Decimal("0.75")) == Decimal("25.00")
    assert adjusted_risk(Decimal("100"), uncertainty=Decimal("0.75")) < adjusted_risk(Decimal("100"), uncertainty=Decimal("0.25"))

def test_runtime_trade_higher_uncertainty_tightens_live_cap():
    runtime=RuntimeAuthority()
    low_assessment=uncertainty_assessment("0.2")
    high_assessment=uncertainty_assessment("0.8")
    low=runtime.evaluate(truth=truth(low_assessment), action=CanonicalAction.TRADE, requested_risk=Decimal("60"), decision_id="LOW",
                         uncertainty_assessment=low_assessment)
    high=runtime.evaluate(truth=truth(high_assessment), action=CanonicalAction.TRADE, requested_risk=Decimal("60"), decision_id="HIGH",
                          uncertainty_assessment=high_assessment)
    assert low.status is AuthorityStatus.AUTHORIZED
    assert high.status is AuthorityStatus.DENIED
    assert high.reason == "RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK"

def test_runtime_uncertainty_metadata_is_bound_to_decision():
    assessment=uncertainty_assessment("0.4")
    d=RuntimeAuthority().evaluate(truth=truth(assessment), action=CanonicalAction.TRADE, requested_risk=Decimal("10"), decision_id="META",
                                  uncertainty_assessment=assessment, uncertainty_method="CONSERVATIVE_LINEAR", uncertainty_method_version="1")
    assert d.authorized
    assert d.uncertainty == Decimal("0.4")
    assert d.uncertainty_risk_factor == Decimal("0.6")
    assert d.uncertainty_method == "CONSERVATIVE_LINEAR"
    assert d.uncertainty_method_version == "1"


def test_runtime_poor_or_unknown_calibration_caps_risk():
    assessment=uncertainty_assessment("0.1", "UNKNOWN")
    decision=RuntimeAuthority().evaluate(
        truth=truth(assessment), action=CanonicalAction.TRADE, requested_risk=Decimal("30"),
        decision_id="UNKNOWN-CALIBRATION", uncertainty_assessment=assessment,
    )
    assert not decision.authorized
    assert decision.reason == "RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK"


def test_runtime_rejects_unbound_uncertainty_scalar():
    decision=RuntimeAuthority().evaluate(
        truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"),
        decision_id="UNBOUND-UNCERTAINTY", uncertainty=Decimal("0.1"),
    )
    assert not decision.authorized
    assert decision.reason == "UNCERTAINTY_SOURCE_BINDING_REQUIRED"


def test_runtime_requires_exact_model_artifact_and_assessment_fingerprint():
    expected=uncertainty_assessment("0.4", prediction_id="P-EXPECTED")
    changed=uncertainty_assessment("0.4", prediction_id="P-CHANGED")
    decision=RuntimeAuthority().evaluate(
        truth=truth(expected), action=CanonicalAction.TRADE, requested_risk=Decimal("1"),
        decision_id="CHANGED-UNCERTAINTY-SOURCE", uncertainty_assessment=changed,
    )
    assert not decision.authorized
    assert decision.reason == "UNCERTAINTY_ASSESSMENT_SOURCE_BINDING_REQUIRED"


def test_uncertainty_assessment_payload_recomputes_and_rejects_tampering():
    assessment=uncertainty_assessment("0.4")
    payload={**assessment.payload(), "source_fingerprint": assessment.source_fingerprint}
    assert UncertaintyAssessment.from_payload(payload) == assessment
    payload["uncertainty"]="0.9"
    with pytest.raises(ValueError, match="INVALID_UNCERTAINTY_ASSESSMENT_PAYLOAD"):
        UncertaintyAssessment.from_payload(payload)


def test_calibration_state_requires_a_bound_empirical_report():
    prediction = Prediction(
        prediction_id="P-CALIBRATION-EVIDENCE", model_id="M21-SYNTHETIC", model_version="1",
        timestamp=NOW, feature_version="F1", target_version="T1", prediction=0.8,
        probability=0.8, expected_return=None, expected_risk=0.2, uncertainty=0.2,
        calibration_state="CALIBRATED", valid_from=NOW, expires_at=NOW+timedelta(minutes=1),
        artifact_hash="c"*64,
    )
    unsigned = UncertaintyAssessment.from_prediction(prediction)
    report = synthetic_calibration_report("CURRENT-30", "REFERENCE-30")
    evidenced = UncertaintyAssessment.from_prediction(prediction, calibration_report=report)
    assert unsigned.calibration_state == "UNKNOWN"
    assert unsigned.calibration_risk_cap == Decimal("0.25")
    assert evidenced.calibration_state == "CALIBRATED"
    assert evidenced.calibration_report_fingerprint == report.fingerprint
    assert evidenced.calibration_source_id == "CURRENT-30"
    assert evidenced.calibration_reference_source_id == "REFERENCE-30"
    assert evidenced.source_fingerprint != unsigned.source_fingerprint
    assert evidenced.is_valid()
    assert UncertaintyAssessment.from_payload(evidenced.payload()) == evidenced

def test_runtime_uncertainty_configuration_conflict_fails_closed():
    with pytest.raises(ValueError, match="UNCERTAINTY_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("10"), uncertainty=Decimal("0.5"), uncertainty_factor=Decimal("0.2"))


def test_execution_router_enforces_uncertainty_cap_before_order_request():
    from datetime import datetime, timezone, timedelta
    from trading_platform.v31.router import ExecutionRouter
    from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
    from trading_platform.core.ttl import ValidWindow
    now=NOW
    window=ValidWindow(now-timedelta(seconds=1), now+timedelta(minutes=5))
    intent=OrderIntent("I-M21","D","P","R","S","M","E","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,window)
    assessment=uncertainty_assessment("0.8")
    with pytest.raises(PermissionError, match="RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK"):
        ExecutionRouter().route(intent=intent, truth=truth(assessment), now=now, position_state=PositionState.FLAT,
                                 market_window=window, upstream_windows=[window], risk_valid=True,
                                 requested_risk=Decimal("60"), decision_id="M21-ROUTE", uncertainty_assessment=assessment)


def test_trade_capability_identity_changes_with_uncertainty():
    from datetime import datetime, timezone, timedelta
    from trading_platform.v32.capability import CapabilityAuthority
    now=NOW
    payload={"intent_id":"I1","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001"}
    ca=CapabilityAuthority()
    low_assessment=uncertainty_assessment("0.2")
    high_assessment=uncertainty_assessment("0.8")
    low=ca.issue(truth=truth(low_assessment), requested_risk=Decimal("10"), decision_id="M21-CAP", intent_payload=payload,
                 expires_at=now+timedelta(seconds=10), uncertainty_assessment=low_assessment)
    high=ca.issue(truth=truth(high_assessment), requested_risk=Decimal("10"), decision_id="M21-CAP", intent_payload=payload,
                  expires_at=now+timedelta(seconds=10), uncertainty_assessment=high_assessment)
    assert low.capability_id != high.capability_id
    assert low.authority.input_fingerprint != high.authority.input_fingerprint


def test_capability_revalidates_source_bound_uncertainty_and_ttl():
    from trading_platform.v32.capability import CapabilityAuthority, CapabilityError
    ca=CapabilityAuthority()
    payload={"intent_id":"I-UNCERTAINTY","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001"}
    assessment=uncertainty_assessment("0.2")
    capability=ca.issue(
        truth=truth(assessment), requested_risk=Decimal("10"), decision_id="M21-CAP-REVALIDATE",
        intent_payload=payload, expires_at=NOW+timedelta(seconds=10), uncertainty_assessment=assessment,
    )
    with pytest.raises(CapabilityError, match="UNCERTAINTY_REVALIDATION_REQUIRED"):
        ca.validate(capability, now=NOW+timedelta(seconds=1), truth=truth(assessment), intent_payload=payload)
    ca.validate(
        capability, now=NOW+timedelta(seconds=1), truth=truth(assessment), intent_payload=payload,
        uncertainty_assessment=assessment,
    )
    changed=uncertainty_assessment("0.2", prediction_id="P-NEW-SOURCE")
    with pytest.raises(CapabilityError, match="UNCERTAINTY_SOURCE_CHANGED"):
        ca.validate(
            capability, now=NOW+timedelta(seconds=1), truth=truth(assessment), intent_payload=payload,
            uncertainty_assessment=changed,
        )


def test_final_dispatch_revalidates_the_same_uncertainty_assessment():
    from trading_platform.core.ttl import ValidWindow
    from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
    from trading_platform.v311.dispatch_guard import assert_final_dispatch_authorities
    from trading_platform.v332.market_authority import MarketDataAuthorityLedger
    from trading_platform.v21.event_store import EventStore

    now_ms=int(NOW.timestamp()*1000)
    window=ValidWindow(NOW-timedelta(seconds=1), NOW+timedelta(minutes=1))
    intent=OrderIntent(
        "I-M21-DISPATCH", "D-M21-DISPATCH", "P-M21", "R-M21", "S-M21", "M-M21", "E-M21",
        "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, window,
    )
    market=MarketDataAuthorityLedger(EventStore())
    market.record_observation(
        symbol="BTCUSDT", feed_id="primary", event_time_ms=now_ms, receive_time_ms=now_ms,
        processing_time_ms=now_ms, max_age_ms=60_000, source="synthetic-dispatch-feed",
    )
    source=uncertainty_assessment("0.2")

    class RiskLedger:
        def __init__(self):
            self.assessment=None
        def assert_valid_for_new_risk(self, **kwargs):
            self.assessment=kwargs["uncertainty_assessment"]

    class PositionAuthority:
        def assert_orderable(self, **kwargs):
            return None

    class CausalTTLAuthority:
        def assert_intent_chain_valid(self, **kwargs):
            return None

    ledger=RiskLedger()
    assert_final_dispatch_authorities(
        intent=intent, now_ms=now_ms, request_deadline=window.expires_at,
        requested_exposure=Decimal("10"), truth_hash="TH-M21",
        risk_decision_ledger=ledger, position_authority=PositionAuthority(),
        market_data_authority=market, causal_ttl_authority=CausalTTLAuthority(),
        uncertainty_assessment=source,
    )
    assert ledger.assessment == source


def test_unregistered_uncertainty_method_fails_closed():
    from trading_platform.v348.uncertainty_risk_authority import bind_uncertainty_to_risk
    with pytest.raises(UncertaintyRiskError, match="UNCERTAINTY_METHOD_NOT_REGISTERED"):
        bind_uncertainty_to_risk(uncertainty=Decimal("0.5"), baseline_risk=Decimal("10"), method="CUSTOM", method_version="99")
