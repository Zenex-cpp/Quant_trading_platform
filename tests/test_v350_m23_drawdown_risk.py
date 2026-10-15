from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, CanonicalAction, ConfigurationStatus, build_truth
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionConflict, RiskDecisionRecord, RiskSystemState
from trading_platform.v350 import DrawdownRiskError, assert_drawdown_monotone, bind_drawdown_to_risk

AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")

def truth():
    comps = tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK", (f"E-{n}",)) for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    caps = {k: Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}
    return build_truth(observed_at_ns=1, axes=AXES, components=comps, requested_risk=Decimal("100"), caps=caps, decision_fresh=True, configuration_status=ConfigurationStatus.RESOLVED)

def decision(*, allowed="50", drawdown=None, drawdown_factor=None, drawdown_max=None):
    return RiskDecisionRecord(
        decision_id="D-DD", action=RiskDecisionAction.ALLOW, risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("100"), allowed_exposure=Decimal(allowed),
        active_limits={"order": Decimal("100")}, multipliers={"drawdown": Decimal("1")},
        rejection_reason=None, reservation_id="RR-DD", intent_id="I-DD", created_at_ms=100, valid_from_ms=100, expires_at_ms=200,
        configuration_version="cfg1", risk_state_version="risk1", portfolio_version="port1", position_version="pos1",
        provenance_id="prov1", truth_hash="TH-DD", input_fingerprint="input-dd",
        drawdown=None if drawdown is None else Decimal(drawdown), drawdown_max=None if drawdown_max is None else Decimal(drawdown_max),
        drawdown_risk_factor=None if drawdown_factor is None else Decimal(drawdown_factor),
        drawdown_method=None if drawdown is None else "CONSERVATIVE_LINEAR", drawdown_method_version=None if drawdown is None else "1",
    )

def test_drawdown_binding_is_conservative_and_monotone():
    low = bind_drawdown_to_risk(drawdown=Decimal("0.2"), baseline_risk=Decimal("100"))
    high = bind_drawdown_to_risk(drawdown=Decimal("0.8"), baseline_risk=Decimal("100"))
    assert low.allowed_risk == Decimal("80.0")
    assert high.allowed_risk == Decimal("20.0")
    assert_drawdown_monotone(lower_drawdown=low.drawdown, lower_allowed_risk=low.allowed_risk, higher_drawdown=high.drawdown, higher_allowed_risk=high.allowed_risk)

def test_higher_drawdown_cannot_raise_runtime_risk_budget():
    low = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("80"), decision_id="DD-LOW", drawdown=Decimal("0.2"))
    high = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("80"), decision_id="DD-HIGH", drawdown=Decimal("0.8"))
    assert low.status is AuthorityStatus.AUTHORIZED
    assert high.status is AuthorityStatus.DENIED
    assert high.reason == "RISK_EXCEEDS_DRAWDOWN_ADJUSTED_RISK"
    assert low.drawdown_risk_factor == Decimal("0.8")
    assert high.drawdown_risk_factor == Decimal("0.2")

def test_adjusted_risk_derives_drawdown_factor_and_rejects_upward_override():
    assert adjusted_risk(Decimal("100"), drawdown=Decimal("0.8")) == Decimal("20.0")
    with pytest.raises(ValueError, match="DRAWDOWN_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("100"), drawdown=Decimal("0.8"), drawdown_factor=Decimal("0.5"))
    with pytest.raises(DrawdownRiskError, match="DRAWDOWN_FACTOR_MUST_BE_NONINCREASING"):
        adjusted_risk(Decimal("100"), drawdown_factor=Decimal("1.1"))

def test_durable_decision_rejects_budget_above_drawdown_cap():
    ledger = DurableRiskDecisionLedger(EventStore())
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_DRAWDOWN_CAP"):
        ledger.record(decision(allowed="21", drawdown="0.8", drawdown_factor="0.2", drawdown_max="1"))

def test_durable_decision_restart_safe_and_drawdown_stale_blocks(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    d = decision(allowed="20", drawdown="0.8", drawdown_factor="0.2", drawdown_max="1")
    ledger.record(d)
    restored = DurableRiskDecisionLedger(EventStore(path)).get("D-DD")
    assert restored == d
    snap = DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
        decision_id="D-DD", now_ms=150, intent_id="I-DD", reservation_id="RR-DD", requested_exposure=Decimal("20"), truth_hash="TH-DD", drawdown=Decimal("0.8")
    )
    assert snap.drawdown == Decimal("0.8")
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_DRAWDOWN_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-DD", now_ms=150, intent_id="I-DD", reservation_id="RR-DD", requested_exposure=Decimal("20"), truth_hash="TH-DD", drawdown=Decimal("0.9")
        )

def test_combined_uncertainty_liquidity_drawdown_uses_tightest_cap():
    low = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20"), decision_id="DD-COMB-1", uncertainty=Decimal("0.5"), liquidity_stress=Decimal("0.8"), drawdown=Decimal("0.3"))
    assert low.status is AuthorityStatus.AUTHORIZED
    assert low.uncertainty_risk_factor == Decimal("0.5")
    assert low.liquidity_risk_factor == Decimal("0.2")
    assert low.drawdown_risk_factor == Decimal("0.7")
    denied = RuntimeAuthority().evaluate(truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20.01"), decision_id="DD-COMB-2", uncertainty=Decimal("0.5"), liquidity_stress=Decimal("0.8"), drawdown=Decimal("0.3"))
    assert denied.status is AuthorityStatus.DENIED
    assert denied.reason == "RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK"

def test_unregistered_drawdown_method_fails_closed():
    with pytest.raises(DrawdownRiskError, match="DRAWDOWN_METHOD_NOT_REGISTERED"):
        bind_drawdown_to_risk(drawdown=Decimal("0.5"), baseline_risk=Decimal("10"), method="UNKNOWN", method_version="1")

def test_monotonicity_rejects_risk_increase_with_worse_drawdown():
    with pytest.raises(DrawdownRiskError, match="RISK_MONOTONICITY_BREACH_DRAWDOWN"):
        assert_drawdown_monotone(lower_drawdown=Decimal("0.2"), lower_allowed_risk=Decimal("20"), higher_drawdown=Decimal("0.8"), higher_allowed_risk=Decimal("21"))

def test_drawdown_off_preserves_baseline_and_on_tightens():
    assert adjusted_risk(Decimal("100")) == Decimal("100")
    assert adjusted_risk(Decimal("100"), drawdown=Decimal("0")) == Decimal("100")
    assert adjusted_risk(Decimal("100"), drawdown=Decimal("0.5")) == Decimal("50.0")


def test_execution_router_enforces_drawdown_cap_before_order_request():
    from datetime import datetime, timezone, timedelta
    from trading_platform.v31.router import ExecutionRouter
    from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
    from trading_platform.core.ttl import ValidWindow
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    window = ValidWindow(now - timedelta(seconds=1), now + timedelta(minutes=5))
    intent = OrderIntent("I-M23", "D", "P", "R", "S", "M", "E", "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, window)
    with pytest.raises(PermissionError, match="RISK_EXCEEDS_DRAWDOWN_ADJUSTED_RISK"):
        ExecutionRouter().route(
            intent=intent, truth=truth(), now=now, position_state=PositionState.FLAT,
            market_window=window, upstream_windows=[window], risk_valid=True,
            requested_risk=Decimal("60"), decision_id="M23-ROUTE", drawdown=Decimal("0.8"),
        )


def test_trade_capability_identity_changes_with_drawdown():
    from datetime import datetime, timezone, timedelta
    from trading_platform.v32.capability import CapabilityAuthority
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    payload = {"intent_id":"I-DD-CAP","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001"}
    ca = CapabilityAuthority()
    low = ca.issue(truth=truth(), requested_risk=Decimal("10"), decision_id="M23-CAP", intent_payload=payload,
                   expires_at=now + timedelta(seconds=10), drawdown=Decimal("0.2"))
    high = ca.issue(truth=truth(), requested_risk=Decimal("10"), decision_id="M23-CAP", intent_payload=payload,
                    expires_at=now + timedelta(seconds=10), drawdown=Decimal("0.8"))
    assert low.capability_id != high.capability_id
    assert low.authority.input_fingerprint != high.authority.input_fingerprint
