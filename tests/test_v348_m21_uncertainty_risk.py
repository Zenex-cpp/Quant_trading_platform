from decimal import Decimal
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

AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")

def truth():
    comps=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK", (f"E-{n}",)) for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}
    return build_truth(observed_at_ns=1, axes=AXES, components=comps, requested_risk=Decimal("100"), caps=caps)

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
    low=runtime.evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("60"), decision_id="LOW",
                         uncertainty=Decimal("0.2"))
    high=runtime.evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("60"), decision_id="HIGH",
                          uncertainty=Decimal("0.8"))
    assert low.status is AuthorityStatus.AUTHORIZED
    assert high.status is AuthorityStatus.DENIED
    assert high.reason == "RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK"

def test_runtime_uncertainty_metadata_is_bound_to_decision():
    d=RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("10"), decision_id="META",
                                  uncertainty=Decimal("0.4"), uncertainty_method="CONSERVATIVE_LINEAR", uncertainty_method_version="1")
    assert d.authorized
    assert d.uncertainty == Decimal("0.4")
    assert d.uncertainty_risk_factor == Decimal("0.6")
    assert d.uncertainty_method == "CONSERVATIVE_LINEAR"
    assert d.uncertainty_method_version == "1"

def test_runtime_uncertainty_configuration_conflict_fails_closed():
    with pytest.raises(ValueError, match="UNCERTAINTY_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("10"), uncertainty=Decimal("0.5"), uncertainty_factor=Decimal("0.2"))


def test_execution_router_enforces_uncertainty_cap_before_order_request():
    from datetime import datetime, timezone, timedelta
    from trading_platform.v31.router import ExecutionRouter
    from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
    from trading_platform.core.ttl import ValidWindow
    now=datetime(2026,9,25,tzinfo=timezone.utc)
    window=ValidWindow(now-timedelta(seconds=1), now+timedelta(minutes=5))
    intent=OrderIntent("I-M21","D","P","R","S","M","E","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.001"),OrderType.MARKET,window)
    with pytest.raises(PermissionError, match="RISK_EXCEEDS_UNCERTAINTY_ADJUSTED_RISK"):
        ExecutionRouter().route(intent=intent, truth=truth(), now=now, position_state=PositionState.FLAT,
                                 market_window=window, upstream_windows=[window], risk_valid=True,
                                 requested_risk=Decimal("60"), decision_id="M21-ROUTE", uncertainty=Decimal("0.8"))


def test_trade_capability_identity_changes_with_uncertainty():
    from datetime import datetime, timezone, timedelta
    from trading_platform.v32.capability import CapabilityAuthority
    now=datetime(2026,9,25,tzinfo=timezone.utc)
    payload={"intent_id":"I1","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001"}
    ca=CapabilityAuthority()
    low=ca.issue(truth=truth(), requested_risk=Decimal("10"), decision_id="M21-CAP", intent_payload=payload,
                 expires_at=now+timedelta(seconds=10), uncertainty=Decimal("0.2"))
    high=ca.issue(truth=truth(), requested_risk=Decimal("10"), decision_id="M21-CAP", intent_payload=payload,
                  expires_at=now+timedelta(seconds=10), uncertainty=Decimal("0.8"))
    assert low.capability_id != high.capability_id
    assert low.authority.input_fingerprint != high.authority.input_fingerprint


def test_unregistered_uncertainty_method_fails_closed():
    from trading_platform.v348.uncertainty_risk_authority import bind_uncertainty_to_risk
    with pytest.raises(UncertaintyRiskError, match="UNCERTAINTY_METHOD_NOT_REGISTERED"):
        bind_uncertainty_to_risk(uncertainty=Decimal("0.5"), baseline_risk=Decimal("10"), method="CUSTOM", method_version="99")
