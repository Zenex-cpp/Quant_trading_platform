from decimal import Decimal
import pytest
from trading_platform.v30.truth import *

AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")

def comps(status=TruthStatus.VERIFIED):
    return tuple(TruthComponent(n, status, "OK", (f"E-{n}",)) for n in ("health","provenance","governance","reconciliation","accounting","ledger"))

def caps(x="100"):
    return {k: Decimal(x) for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}

def truth(**kw):
    d=dict(observed_at_ns=1,axes=AXES,components=comps(),requested_risk=Decimal("50"),caps=caps())
    d.update(kw)
    return build_truth(**d)

def test_verified_truth_allows_trade_and_deploy():
    t=truth(); assert t.status is TruthStatus.VERIFIED
    assert t.effective_risk == Decimal("50")
    assert t.trading_allowed and t.deployment_allowed
    assert t.action_allowed(CanonicalAction.TRADE)
    assert t.action_allowed(CanonicalAction.DEPLOY)

def test_blocked_truth_zeroes_risk():
    t=truth(components=comps(TruthStatus.BLOCKED))
    assert t.status is TruthStatus.BLOCKED
    assert t.effective_risk == 0
    assert not t.trading_allowed and not t.deployment_allowed

def test_unknown_truth_zeroes_risk_but_reconcile_remains_possible():
    t=truth(components=comps(TruthStatus.UNKNOWN))
    assert t.status is TruthStatus.UNKNOWN
    assert t.effective_risk == 0
    assert not t.action_allowed(CanonicalAction.TRADE)
    assert t.action_allowed(CanonicalAction.RECONCILE)

def test_degraded_truth_preserves_only_capped_risk():
    t=truth(components=comps(TruthStatus.DEGRADED), caps=caps("25"))
    assert t.status is TruthStatus.DEGRADED
    assert t.effective_risk == Decimal("25")
    assert not t.trading_allowed

def test_kill_switch_fail_closed():
    t=truth(kill_switch=True)
    assert t.status is TruthStatus.BLOCKED
    assert t.effective_risk == 0
    assert not t.action_allowed(CanonicalAction.TRADE)

def test_stale_decision_zeroes_risk():
    t=truth(decision_fresh=False)
    assert t.effective_risk == 0
    assert not t.trading_allowed

def test_risk_is_monotonic_when_cap_worsens():
    t=truth(caps=caps("100"))
    worse=truth(caps=caps("10"))
    assert worse.effective_risk <= t.effective_risk

def test_cap_binds_to_smallest_constraint():
    c=caps("100"); c["reconciliation_cap"]=Decimal("7")
    t=truth(caps=c)
    assert t.effective_risk == Decimal("7")

def test_truth_hash_deterministic():
    a=truth(); b=truth()
    assert a.state_hash == b.state_hash

def test_component_names_unique():
    with pytest.raises(ValueError, match="TRUTH_COMPONENT_DUPLICATE"):
        truth(components=(TruthComponent("health", TruthStatus.VERIFIED, "OK"), TruthComponent("health", TruthStatus.VERIFIED, "OK")))

def test_unknown_component_blocks_deployment():
    cs=list(comps()); cs[-1]=TruthComponent("ledger", TruthStatus.UNKNOWN, "MISSING", ()); t=truth(components=tuple(cs))
    assert not t.deployment_allowed
