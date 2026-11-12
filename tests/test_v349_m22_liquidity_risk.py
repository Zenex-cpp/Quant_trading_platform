from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
from trading_platform.portfolio.capacity import assert_capacity_monotone, estimate_capacity
from trading_platform.realtime.orderbook import OrderBookSnapshot
from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, CanonicalAction, ConfigurationStatus, TruthComponent, TruthStatus, build_truth
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v31.router import ExecutionRouter
from trading_platform.v311.dispatch_guard import DispatchGuardDenied, assert_final_dispatch_authorities
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionConflict, RiskDecisionRecord, RiskSystemState
from trading_platform.v332.market_authority import MarketDataAuthorityLedger
from trading_platform.v349 import (
    LiquidityAssessment,
    LiquidityAssessmentError,
    LiquidityRiskError,
    assert_liquidity_monotone,
    bind_liquidity_to_risk,
)
from trading_platform.model.contracts import Prediction
from trading_platform.v348 import UncertaintyAssessment
from tests._m21_calibration_helpers import synthetic_calibration_report
from trading_platform.v32.capability import CapabilityAuthority, CapabilityError


AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
CAPS = {k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")}


def book(*, quantity_scale: str = "1", spread: str = "0.02", last_update_id: int = 41) -> OrderBookSnapshot:
    scale = Decimal(quantity_scale)
    half_spread = Decimal(spread) / Decimal("2")
    mid = Decimal("100")
    return OrderBookSnapshot(
        last_update_id=last_update_id,
        bids=((mid - half_spread, Decimal("10") * scale), (mid - half_spread - Decimal("0.01"), Decimal("20") * scale)),
        asks=((mid + half_spread, Decimal("10") * scale), (mid + half_spread + Decimal("0.01"), Decimal("20") * scale)),
    )


def market_record(*, sequence_number: int = 41, source: str = "synthetic-l2"):
    ledger = MarketDataAuthorityLedger(EventStore())
    record = ledger.record_observation(
        symbol="BTCUSDT", feed_id="primary", event_time_ms=100,
        receive_time_ms=100, processing_time_ms=100, max_age_ms=1_000,
        source=source, sequence_number=sequence_number,
    )
    return ledger, record


def assessment(
    *, quantity: str = "1", quantity_scale: str = "1", spread: str = "0.02",
    max_spread_bps: str = "100", max_impact_bps: str = "100",
    source: str = "synthetic-l2", source_evidence_id: str | None = None,
):
    _, record = market_record(source=source)
    return LiquidityAssessment.assess(
        symbol="BTCUSDT", source_evidence_id=source_evidence_id or record.fingerprint,
        verified=True, side="BUY", requested_quantity=Decimal(quantity),
        snapshot=book(quantity_scale=quantity_scale, spread=spread),
        observed_at_ns=record.processing_time_ms * 1_000_000, ttl_ns=1_000_000_000,
        depth_levels=2, max_spread_bps=Decimal(max_spread_bps), max_impact_bps=Decimal(max_impact_bps),
    )


def uncertainty_source(value="0.5"):
    now=datetime.fromtimestamp(0.1, tz=timezone.utc)
    prediction=Prediction(
        prediction_id=f"P-M22-{value}", model_id="M-SYNTHETIC", model_version="1",
        timestamp=now, feature_version="F1", target_version="T1", prediction=float(value),
        probability=float(value), expected_return=None, expected_risk=float(value), uncertainty=float(value),
        calibration_state="CALIBRATED", valid_from=now, expires_at=now+timedelta(seconds=60), artifact_hash="b"*64,
    )
    return UncertaintyAssessment.from_prediction(prediction, calibration_report=synthetic_calibration_report())


def truth(liquidity: LiquidityAssessment | None = None, *, bind_source: bool = True, uncertainty=None):
    names = ("health", "provenance", "governance", "reconciliation", "accounting", "ledger", "market_data")
    if uncertainty is not None:
        names=(*names,"model_output")
    components = tuple(
        TruthComponent(
            name, TruthStatus.VERIFIED, "OK",
            (uncertainty.source_evidence_id, uncertainty.source_fingerprint)
            if name == "model_output" and uncertainty is not None
            else (liquidity.source_evidence_id, liquidity.source_fingerprint)
            if name == "market_data" and liquidity is not None and bind_source
            else (liquidity.source_evidence_id,)
            if name == "market_data" and liquidity is not None
            else (f"E-{name}",),
        )
        for name in names
    )
    return build_truth(
        observed_at_ns=100_000_000, axes=AXES, components=components,
        requested_risk=Decimal("100"), caps=CAPS, decision_fresh=True,
        configuration_status=ConfigurationStatus.RESOLVED,
    )


def decision(*, allowed="100", liquidity: LiquidityAssessment | None = None):
    stress = None if liquidity is None else liquidity.liquidity_stress
    return RiskDecisionRecord(
        decision_id="D-LIQ", action=RiskDecisionAction.ALLOW, risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("100"), allowed_exposure=Decimal(allowed),
        active_limits={"order": Decimal("100")}, multipliers={"liquidity": Decimal("1")},
        rejection_reason=None, reservation_id="RR-LIQ", intent_id="I-LIQ",
        created_at_ms=100, valid_from_ms=100, expires_at_ms=2_000,
        configuration_version="cfg1", risk_state_version="risk1", portfolio_version="port1",
        position_version="pos1", provenance_id="prov1", truth_hash="TH-LIQ", input_fingerprint="input-liq",
        liquidity_stress=stress, liquidity_max=None if liquidity is None else Decimal("1"),
        liquidity_floor=Decimal("0"),
        liquidity_risk_factor=None if liquidity is None else Decimal("1") - stress,
        liquidity_method=None if liquidity is None else "CONSERVATIVE_LINEAR",
        liquidity_method_version=None if liquidity is None else "1",
        liquidity_assessment=liquidity,
    )


def test_orderbook_assessment_measures_depth_spread_impact_and_replays_exactly():
    assessed = assessment(quantity="10", max_spread_bps="2.5", max_impact_bps="10")
    assert assessed.spread_bps == Decimal("2")
    assert assessed.side_depth_notional > assessed.executed_notional
    assert assessed.execution_vwap >= assessed.mid_price
    assert assessed.market_impact_bps >= 0
    assert assessed.liquidity_stress == Decimal("0.8")
    assert assessed.is_valid()
    restored = LiquidityAssessment.from_payload({**assessed.payload(), "source_fingerprint": assessed.source_fingerprint})
    assert restored == assessed
    with pytest.raises(LiquidityAssessmentError, match="PAYLOAD"):
        LiquidityAssessment.from_payload({**assessed.payload(), "liquidity_stress": "0.1"})


def test_worse_depth_or_wider_spread_cannot_reduce_liquidity_stress():
    deep = assessment(quantity="10", max_spread_bps="100", max_impact_bps="100")
    shallow = assessment(quantity="10", quantity_scale="0.5", max_spread_bps="100", max_impact_bps="100")
    wide = assessment(quantity="10", spread="0.10", max_spread_bps="100", max_impact_bps="100")
    assert shallow.depth_utilization > deep.depth_utilization
    assert shallow.liquidity_stress >= deep.liquidity_stress
    assert wide.spread_bps > deep.spread_bps
    assert wide.liquidity_stress >= deep.liquidity_stress
    deep_binding = bind_liquidity_to_risk(
        liquidity_stress=deep.liquidity_stress, baseline_risk=Decimal("100"),
        assessment=deep, now_ns=100_000_000,
    )
    shallow_binding = bind_liquidity_to_risk(
        liquidity_stress=shallow.liquidity_stress, baseline_risk=Decimal("100"),
        assessment=shallow, now_ns=100_000_000,
    )
    assert shallow_binding.allowed_risk <= deep_binding.allowed_risk
    assert_liquidity_monotone(
        lower_liquidity_stress=deep.liquidity_stress, lower_allowed_risk=deep_binding.allowed_risk,
        higher_liquidity_stress=shallow.liquidity_stress, higher_allowed_risk=shallow_binding.allowed_risk,
    )


def test_insufficient_visible_depth_and_unverified_source_fail_closed():
    with pytest.raises(LiquidityAssessmentError, match="DEPTH_INSUFFICIENT"):
        LiquidityAssessment.assess(
            symbol="BTCUSDT", source_evidence_id="E", verified=True, side="BUY",
            requested_quantity=Decimal("100"), snapshot=book(), observed_at_ns=100,
            ttl_ns=10, depth_levels=2, max_spread_bps=Decimal("10"), max_impact_bps=Decimal("10"),
        )
    with pytest.raises(LiquidityAssessmentError, match="IDENTITY_REQUIRED"):
        LiquidityAssessment.assess(
            symbol="BTCUSDT", source_evidence_id="E", verified=False, side="BUY",
            requested_quantity=Decimal("1"), snapshot=book(), observed_at_ns=100,
            ttl_ns=10, depth_levels=2, max_spread_bps=Decimal("10"), max_impact_bps=Decimal("10"),
        )


def test_liquidity_binding_is_conservative_and_requires_fresh_source_time():
    low = bind_liquidity_to_risk(liquidity_stress=Decimal("0.2"), baseline_risk=Decimal("100"))
    high = bind_liquidity_to_risk(liquidity_stress=Decimal("0.8"), baseline_risk=Decimal("100"))
    assert low.allowed_risk == Decimal("80.0")
    assert high.allowed_risk == Decimal("20.0")
    with pytest.raises(LiquidityRiskError, match="VALIDATION_TIME_REQUIRED"):
        bind_liquidity_to_risk(
            liquidity_stress=Decimal("0.8"), baseline_risk=Decimal("100"),
            assessment=assessment(quantity="10", max_spread_bps="2.5"),
        )


def test_runtime_requires_market_bound_assessment_and_enforces_stress_cap():
    liquid = assessment(quantity="10", max_spread_bps="2.5")
    authority = RuntimeAuthority()
    allowed = authority.evaluate(
        truth=truth(liquid), action=CanonicalAction.TRADE, requested_risk=Decimal("20"),
        decision_id="A1", liquidity_assessment=liquid,
    )
    denied = authority.evaluate(
        truth=truth(liquid), action=CanonicalAction.TRADE, requested_risk=Decimal("20.01"),
        decision_id="A2", liquidity_assessment=liquid,
    )
    assert allowed.status is AuthorityStatus.AUTHORIZED
    assert allowed.liquidity_stress == Decimal("0.8")
    assert allowed.liquidity_risk_factor == Decimal("0.2")
    assert allowed.liquidity_source_fingerprint == liquid.source_fingerprint
    assert denied.status is AuthorityStatus.DENIED
    assert denied.reason == "RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK"


def test_runtime_rejects_scalar_or_unbound_market_liquidity():
    raw = RuntimeAuthority().evaluate(
        truth=truth(), action=CanonicalAction.TRADE, requested_risk=Decimal("1"),
        decision_id="A-RAW", liquidity_stress=Decimal("0.1"),
    )
    assert raw.status is AuthorityStatus.DENIED
    assert raw.reason == "LIQUIDITY_SOURCE_BINDING_REQUIRED"
    assessed = assessment()
    unbound = RuntimeAuthority().evaluate(
        truth=truth(assessed, bind_source=False), action=CanonicalAction.TRADE,
        requested_risk=Decimal("1"), decision_id="A-UNBOUND", liquidity_assessment=assessed,
    )
    assert unbound.status is AuthorityStatus.DENIED
    assert unbound.reason == "LIQUIDITY_ASSESSMENT_SOURCE_BINDING_REQUIRED"


def test_runtime_uses_tightest_uncertainty_and_orderbook_liquidity_cap():
    assessed = assessment(quantity="10", max_spread_bps="2.5")
    uncertainty = uncertainty_source()
    decision = RuntimeAuthority().evaluate(
        truth=truth(assessed, uncertainty=uncertainty), action=CanonicalAction.TRADE, requested_risk=Decimal("20"),
        decision_id="A3", uncertainty_assessment=uncertainty, liquidity_assessment=assessed,
    )
    assert decision.status is AuthorityStatus.AUTHORIZED
    assert decision.uncertainty_risk_factor == Decimal("0.5")
    assert decision.liquidity_risk_factor == Decimal("0.2")
    denied = RuntimeAuthority().evaluate(
        truth=truth(assessed, uncertainty=uncertainty), action=CanonicalAction.TRADE, requested_risk=Decimal("20.01"),
        decision_id="A4", uncertainty_assessment=uncertainty, liquidity_assessment=assessed,
    )
    assert denied.reason == "RISK_EXCEEDS_LIQUIDITY_ADJUSTED_RISK"


def test_durable_decision_requires_liquidity_source_and_rejects_over_cap(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "risk.db")))
    assessed = assessment(quantity="10", max_spread_bps="2.5")
    with pytest.raises(ValueError, match="LIQUIDITY_SOURCE_PROVENANCE_REQUIRED"):
        ledger.record(decision(allowed="20", liquidity=None).__class__(
            **{**decision(allowed="20", liquidity=None).__dict__,
               "liquidity_stress": assessed.liquidity_stress,
               "liquidity_max": Decimal("1"),
               "liquidity_risk_factor": Decimal("0.2"),
               "liquidity_method": "CONSERVATIVE_LINEAR",
               "liquidity_method_version": "1"}
        ))
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_LIQUIDITY_CAP"):
        ledger.record(decision(allowed="21", liquidity=assessed))


def test_durable_risk_decision_replays_and_revalidates_exact_liquidity_source(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    assessed = assessment(quantity="10", max_spread_bps="2.5")
    record = decision(allowed="20", liquidity=assessed)
    ledger.record(record)
    reopened = DurableRiskDecisionLedger(EventStore(path))
    assert reopened.get("D-LIQ") == record
    gate = reopened.assert_valid_for_new_risk(
        decision_id="D-LIQ", now_ms=150, intent_id="I-LIQ", reservation_id="RR-LIQ",
        requested_exposure=Decimal("20"), truth_hash="TH-LIQ",
        liquidity_stress=assessed.liquidity_stress, liquidity_assessment=assessed,
    )
    assert gate.liquidity_source_fingerprint == assessed.source_fingerprint
    changed = assessment(quantity="10", max_spread_bps="2.5", source="other-feed")
    with pytest.raises(RiskDecisionConflict, match="LIQUIDITY_SOURCE_STALE"):
        reopened.assert_valid_for_new_risk(
            decision_id="D-LIQ", now_ms=150, intent_id="I-LIQ", reservation_id="RR-LIQ",
            requested_exposure=Decimal("20"), truth_hash="TH-LIQ",
            liquidity_stress=changed.liquidity_stress, liquidity_assessment=changed,
        )
    with pytest.raises(RiskDecisionConflict, match="LIQUIDITY_SOURCE_EXPIRED"):
        reopened.assert_valid_for_new_risk(
            decision_id="D-LIQ", now_ms=1_100, intent_id="I-LIQ", reservation_id="RR-LIQ",
            requested_exposure=Decimal("20"), truth_hash="TH-LIQ",
            liquidity_stress=assessed.liquidity_stress, liquidity_assessment=assessed,
        )


def test_execution_router_binds_exact_order_quantity_and_orderbook_source():
    assessed = assessment(quantity="10", max_spread_bps="100")
    now = datetime.fromtimestamp(0.15, tz=timezone.utc)
    window = ValidWindow(now - timedelta(milliseconds=50), now + timedelta(seconds=1))
    intent = OrderIntent(
        "I-ROUTE", "D-ROUTE", "P", "R", "S", "M", "E", "BTCUSDT", Side.BUY,
        OrderAction.OPEN, Decimal("10"), OrderType.MARKET, window,
    )
    out = ExecutionRouter().route(
        intent=intent, truth=truth(assessed), now=now, position_state=PositionState.FLAT,
        market_window=window, upstream_windows=[window], risk_valid=True,
        requested_risk=Decimal("10"), decision_id="ROUTE", liquidity_assessment=assessed,
    )
    assert out.authority.liquidity_source_fingerprint == assessed.source_fingerprint
    wrong_order = assessment(quantity="9", max_spread_bps="100")
    with pytest.raises(PermissionError, match="LIQUIDITY_INTENT_MISMATCH"):
        ExecutionRouter().route(
            intent=intent, truth=truth(wrong_order), now=now, position_state=PositionState.FLAT,
            market_window=window, upstream_windows=[window], risk_valid=True,
            requested_risk=Decimal("10"), decision_id="ROUTE-WRONG", liquidity_assessment=wrong_order,
        )


def test_capability_binds_liquidity_assessment_and_fails_when_stale():
    assessed = assessment(quantity="10", max_spread_bps="100")
    now = datetime.fromtimestamp(0.15, tz=timezone.utc)
    payload = {"intent_id": "I-CAP", "symbol": "BTCUSDT", "side": "BUY", "quantity": "10"}
    authority = CapabilityAuthority()
    capability = authority.issue(
        truth=truth(assessed), requested_risk=Decimal("10"), decision_id="CAP-LIQ",
        intent_payload=payload, expires_at=now + timedelta(seconds=2), liquidity_assessment=assessed,
    )
    assert capability.authority.liquidity_assessment_id == assessed.assessment_id
    with pytest.raises(CapabilityError, match="LIQUIDITY_SOURCE_EXPIRED"):
        authority.validate(
            capability, now=now + timedelta(seconds=1), truth=truth(assessed),
            intent_payload=payload, liquidity_assessment=assessed,
        )


def test_final_dispatch_checks_liquidity_against_fresh_market_record():
    market, market_evidence = market_record()
    assessed = assessment(source_evidence_id=market_evidence.fingerprint)
    now = datetime.fromtimestamp(0.15, tz=timezone.utc)
    window = ValidWindow(now - timedelta(milliseconds=50), now + timedelta(seconds=1))
    intent = OrderIntent(
        "I-DISPATCH-LIQ", "D-DISPATCH-LIQ", "P", "R", "S", "M", "E", "BTCUSDT",
        Side.BUY, OrderAction.OPEN, Decimal("1"), OrderType.MARKET, window,
    )

    class PositionAuthority:
        def assert_orderable(self, **kwargs):
            return None

    class RiskLedger:
        def __init__(self):
            self.assessments = []

        def assert_valid_for_new_risk(self, **kwargs):
            self.assessments.append(kwargs["liquidity_assessment"])

    class CausalTTLAuthority:
        def assert_intent_chain_valid(self, **kwargs):
            return None

    risk_ledger = RiskLedger()
    checks = dict(
        intent=intent, now_ms=150, request_deadline=window.expires_at,
        requested_exposure=Decimal("1"), truth_hash="TH-LIQ",
        risk_decision_ledger=risk_ledger, position_authority=PositionAuthority(),
        market_data_authority=market, causal_ttl_authority=CausalTTLAuthority(),
    )
    assert_final_dispatch_authorities(**checks, liquidity_assessment=assessed)
    assert risk_ledger.assessments == [assessed]

    other_source = assessment(quantity="1", source="other-feed")
    with pytest.raises(DispatchGuardDenied, match="LIQUIDITY_MARKET_EVIDENCE_MISMATCH"):
        assert_final_dispatch_authorities(**checks, liquidity_assessment=other_source)
    assert risk_ledger.assessments == [assessed, other_source]


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
