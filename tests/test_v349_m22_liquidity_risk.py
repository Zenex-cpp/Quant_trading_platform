from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.portfolio.capacity import assert_capacity_monotone, estimate_capacity
from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v21.event_store import EventStore
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, CanonicalAction, ConfigurationStatus, TruthStatus, build_truth
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionConflict, RiskDecisionRecord, RiskSystemState
from trading_platform.v349 import (
    LiquidityRiskError,
    assert_liquidity_monotone,
    bind_liquidity_to_risk,
)


def truth():
    axes = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
    components = tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK", (f"E-{n}",)) for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    caps = {k: Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}
    return build_truth(
        observed_at_ns=1, axes=axes, components=components,
        requested_risk=Decimal("100"), caps=caps, decision_fresh=True,
        configuration_status=ConfigurationStatus.RESOLVED,
    )


def decision(*, allowed="100", liquidity=None, liquidity_factor=None, liquidity_max=None, liquidity_floor="0", liquidity_method=None, liquidity_method_version=None, uncertainty=None, uncertainty_factor=None):
    return RiskDecisionRecord(
        decision_id="D-LIQ",
        action=RiskDecisionAction.ALLOW,
        risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("100"),
        allowed_exposure=Decimal(allowed),
        active_limits={"order": Decimal("100")},
        multipliers={"liquidity": Decimal("1")},
        rejection_reason=None,
        reservation_id="RR-LIQ",
        intent_id="I-LIQ",
        created_at_ms=100,
        valid_from_ms=100,
        expires_at_ms=200,
        configuration_version="cfg1",
        risk_state_version="risk1",
        portfolio_version="port1",
        position_version="pos1",
        provenance_id="prov1",
        truth_hash="TH-LIQ",
        input_fingerprint="input-liq",
        uncertainty=None if uncertainty is None else Decimal(uncertainty),
        uncertainty_max=None if uncertainty is None else Decimal("1"),
        uncertainty_floor=Decimal("0"),
        uncertainty_risk_factor=None if uncertainty_factor is None else Decimal(uncertainty_factor),
        uncertainty_method=None if uncertainty is None else "CONSERVATIVE_LINEAR",
        uncertainty_method_version=None if uncertainty is None else "1",
        liquidity_stress=None if liquidity is None else Decimal(liquidity),
        liquidity_max=None if liquidity_max is None else Decimal(liquidity_max),
        liquidity_floor=Decimal(liquidity_floor),
        liquidity_risk_factor=None if liquidity_factor is None else Decimal(liquidity_factor),
        liquidity_method=liquidity_method,
        liquidity_method_version=liquidity_method_version,
    )


def test_liquidity_binding_is_conservative_and_monotone():
    low = bind_liquidity_to_risk(liquidity_stress=Decimal("0.2"), baseline_risk=Decimal("100"))
    high = bind_liquidity_to_risk(liquidity_stress=Decimal("0.8"), baseline_risk=Decimal("100"))
    assert low.allowed_risk == Decimal("80.0")
    assert high.allowed_risk == Decimal("20.0")
    assert_liquidity_monotone(
        lower_liquidity_stress=low.liquidity_stress,
        lower_allowed_risk=low.allowed_risk,
        higher_liquidity_stress=high.liquidity_stress,
        higher_allowed_risk=high.allowed_risk,
    )


def test_runtime_authority_blocks_requested_risk_above_liquidity_cap():
    authority = RuntimeAuthority()
    allowed = authority.evaluate(
        truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20"), decision_id="A1",
        liquidity_stress=Decimal("0.8"),
    )
    assert allowed.status is AuthorityStatus.AUTHORIZED
    denied = authority.evaluate(
        truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20.01"), decision_id="A2",
        liquidity_stress=Decimal("0.8"),
    )
    assert denied.status is AuthorityStatus.DENIED
    assert denied.reason == "RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK"


def test_runtime_uses_tightest_uncertainty_and_liquidity_cap():
    decision = RuntimeAuthority().evaluate(
        truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20"), decision_id="A3",
        uncertainty=Decimal("0.5"), liquidity_stress=Decimal("0.8"),
    )
    assert decision.status is AuthorityStatus.AUTHORIZED
    assert decision.uncertainty_risk_factor == Decimal("0.5")
    assert decision.liquidity_risk_factor == Decimal("0.2")
    denied = RuntimeAuthority().evaluate(
        truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("20.01"), decision_id="A4",
        uncertainty=Decimal("0.5"), liquidity_stress=Decimal("0.8"),
    )
    assert denied.reason == "RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK"


def test_durable_risk_decision_rejects_allowed_exposure_above_liquidity_cap(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "risk.db")))
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_LIQUIDITY_CAP"):
        ledger.record(decision(allowed="21", liquidity="0.8", liquidity_factor="0.2", liquidity_max="1", liquidity_method="CONSERVATIVE_LINEAR", liquidity_method_version="1"))


def test_durable_risk_decision_is_restart_safe_and_stale_liquidity_blocks(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    d = decision(allowed="20", liquidity="0.8", liquidity_factor="0.2", liquidity_max="1", liquidity_method="CONSERVATIVE_LINEAR", liquidity_method_version="1")
    ledger.record(d)
    restored = DurableRiskDecisionLedger(EventStore(path)).get("D-LIQ")
    assert restored == d
    snap = DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
        decision_id="D-LIQ", now_ms=150, intent_id="I-LIQ", reservation_id="RR-LIQ",
        requested_exposure=Decimal("20"), truth_hash="TH-LIQ", liquidity_stress=Decimal("0.8"),
    )
    assert snap.liquidity_stress == Decimal("0.8")
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_LIQUIDITY_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-LIQ", now_ms=150, intent_id="I-LIQ", reservation_id="RR-LIQ",
            requested_exposure=Decimal("20"), truth_hash="TH-LIQ", liquidity_stress=Decimal("0.9"),
        )


def test_adjusted_risk_derives_liquidity_factor_and_rejects_upward_override():
    assert adjusted_risk(Decimal("100"), liquidity_stress=Decimal("0.8")) == Decimal("20.0")
    with pytest.raises(ValueError, match="LIQUIDITY_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("100"), liquidity_stress=Decimal("0.8"), liquidity_factor=Decimal("0.5"))
    with pytest.raises(LiquidityRiskError, match="LIQUIDITY_FACTOR_MUST_BE_NONINCREASING"):
        adjusted_risk(Decimal("100"), liquidity_factor=Decimal("1.1"))


def test_capacity_cannot_increase_when_liquidity_capacity_worsens():
    good = estimate_capacity(adv_notional=Decimal("1000"), max_participation=Decimal("0.10"), impact_budget_bps=Decimal("10"), impact_per_participation_bps=Decimal("100"))
    worse = estimate_capacity(adv_notional=Decimal("1000"), max_participation=Decimal("0.05"), impact_budget_bps=Decimal("10"), impact_per_participation_bps=Decimal("100"))
    assert worse.capacity_notional <= good.capacity_notional
    assert_capacity_monotone(lower_liquidity_capacity=good.capacity_notional, higher_liquidity_stress_capacity=worse.capacity_notional)


def test_unregistered_liquidity_method_fails_closed():
    with pytest.raises(LiquidityRiskError, match="LIQUIDITY_METHOD_NOT_REGISTERED"):
        bind_liquidity_to_risk(liquidity_stress=Decimal("0.5"), baseline_risk=Decimal("10"), method="UNKNOWN", method_version="1")
