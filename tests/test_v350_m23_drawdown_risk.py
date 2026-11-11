from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, CanonicalAction, ConfigurationStatus, build_truth
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionConflict, RiskDecisionRecord, RiskSystemState
from trading_platform.v24.accounting import AccountingSnapshot, AccountingTruth, CashComponents, PnLView
from trading_platform.v350 import DrawdownHistoryError, DrawdownHistoryLedger, DrawdownRiskError, assert_drawdown_monotone, bind_drawdown_to_risk


AXES = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def equity_snapshot(timestamp_ns: int, equity: str) -> AccountingSnapshot:
    return AccountingSnapshot(
        timestamp_ns=timestamp_ns,
        equity=Decimal(equity),
        cash=CashComponents(),
        pnl=PnLView(),
        source=AccountingTruth.RECONSTRUCTED,
    )


def history(equities: tuple[str, ...], *, start_ns: int = 99_000_000, portfolio_id: str = "P-M23"):
    ledger = DrawdownHistoryLedger(EventStore())
    snapshot_ids = []
    for index, equity in enumerate(equities):
        snapshot_id = f"S-{index}"
        snapshot = equity_snapshot(start_ns + index * 1_000_000, equity)
        if index == 0:
            ledger.initialize(
                portfolio_id=portfolio_id,
                history_evidence_id="SYNTHETIC-TEST-HISTORY-EVIDENCE",
                verified=True,
                opening_snapshot_id=snapshot_id,
                opening_snapshot=snapshot,
            )
        else:
            ledger.observe(portfolio_id=portfolio_id, snapshot_id=snapshot_id, snapshot=snapshot)
        snapshot_ids.append(snapshot_id)
    return ledger, tuple(snapshot_ids)


def assessment_for(
    equities: tuple[str, ...], *, current_index: int | None = None,
    start_ns: int = 99_000_000, ttl_ns: int = 60_000_000,
    portfolio_id: str = "P-M23",
):
    ledger, snapshot_ids = history(equities, start_ns=start_ns, portfolio_id=portfolio_id)
    index = len(snapshot_ids) - 1 if current_index is None else current_index
    current_ns = start_ns + index * 1_000_000
    return ledger.assess(
        portfolio_id=portfolio_id,
        now_ns=current_ns,
        ttl_ns=ttl_ns,
        snapshot_id=snapshot_ids[index],
    )


def truth(*, assessment=None, bind_history: bool = True):
    evidence_ids = (
        (assessment.current_snapshot_hash, assessment.history_fingerprint)
        if assessment is not None and bind_history
        else (assessment.current_snapshot_hash,)
        if assessment is not None
        else ("E-accounting",)
    )
    comps = tuple(
        TruthComponent(n, TruthStatus.VERIFIED, "OK", evidence_ids if n == "accounting" else (f"E-{n}",))
        for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger")
    )
    caps = {k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")}
    observed_at_ns = assessment.observed_at_ns if assessment is not None else 1
    return build_truth(
        observed_at_ns=observed_at_ns, axes=AXES, components=comps,
        requested_risk=Decimal("100"), caps=caps, decision_fresh=True,
        configuration_status=ConfigurationStatus.RESOLVED,
    )


def decision(*, allowed="50", assessment=None, drawdown_factor=None):
    return RiskDecisionRecord(
        decision_id="D-DD", action=RiskDecisionAction.ALLOW, risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("100"), allowed_exposure=Decimal(allowed),
        active_limits={"order": Decimal("100")}, multipliers={"drawdown": Decimal("1")},
        rejection_reason=None, reservation_id="RR-DD", intent_id="I-DD",
        created_at_ms=100, valid_from_ms=100, expires_at_ms=200,
        configuration_version="cfg1", risk_state_version="risk1", portfolio_version="port1", position_version="pos1",
        provenance_id="prov1", truth_hash="TH-DD", input_fingerprint="input-dd",
        drawdown=None if assessment is None else assessment.drawdown,
        drawdown_max=None if assessment is None else Decimal("1"),
        drawdown_risk_factor=None if drawdown_factor is None else Decimal(drawdown_factor),
        drawdown_method=None if assessment is None else "CONSERVATIVE_LINEAR",
        drawdown_method_version=None if assessment is None else "1",
        drawdown_assessment=assessment,
    )


def test_drawdown_history_replays_peak_and_computes_current_fraction(tmp_path: Path):
    path = str(tmp_path / "drawdown.db")
    ledger = DrawdownHistoryLedger(EventStore(path))
    ledger.initialize(
        portfolio_id="P1", history_evidence_id="TEST-HISTORY-SIGNOFF", verified=True,
        opening_snapshot_id="S1", opening_snapshot=equity_snapshot(100, "100"),
    )
    ledger.observe(portfolio_id="P1", snapshot_id="S2", snapshot=equity_snapshot(200, "75"))
    ledger.observe(portfolio_id="P1", snapshot_id="S3", snapshot=equity_snapshot(300, "120"))
    before_new_high = DrawdownHistoryLedger(EventStore(path)).assess(
        portfolio_id="P1", now_ns=200, ttl_ns=100, snapshot_id="S2",
    )
    at_new_high = DrawdownHistoryLedger(EventStore(path)).assess(
        portfolio_id="P1", now_ns=300, ttl_ns=100, snapshot_id="S3",
    )
    assert before_new_high.peak_equity == Decimal("100")
    assert before_new_high.drawdown == Decimal("0.25")
    assert at_new_high.peak_equity == Decimal("120")
    assert at_new_high.drawdown == Decimal("0")
    assert DrawdownHistoryLedger(EventStore(path)).assess(
        portfolio_id="P1", now_ns=301, ttl_ns=100,
    ).source_fingerprint == at_new_high.source_fingerprint


def test_drawdown_history_requires_fresh_monotone_durable_snapshots():
    ledger = DrawdownHistoryLedger(EventStore())
    ledger.initialize(
        portfolio_id="P1", history_evidence_id="TEST-HISTORY-SIGNOFF", verified=True,
        opening_snapshot_id="S1", opening_snapshot=equity_snapshot(100, "100"),
    )
    with pytest.raises(DrawdownHistoryError, match="TIME_NOT_INCREASING"):
        ledger.observe(portfolio_id="P1", snapshot_id="S2", snapshot=equity_snapshot(100, "90"))
    with pytest.raises(DrawdownHistoryError, match="EXPIRED"):
        ledger.assess(portfolio_id="P1", now_ns=111, ttl_ns=10)


def test_drawdown_history_requires_explicit_verified_bootstrap():
    ledger = DrawdownHistoryLedger(EventStore())
    snapshot = equity_snapshot(100, "100")
    with pytest.raises(DrawdownHistoryError, match="INITIALIZATION_REQUIRED"):
        ledger.observe(portfolio_id="P1", snapshot_id="S1", snapshot=snapshot)
    with pytest.raises(DrawdownHistoryError, match="INITIALIZATION_REQUIRED"):
        ledger.assess(portfolio_id="P1", now_ns=100, ttl_ns=10)
    with pytest.raises(DrawdownHistoryError, match="EVIDENCE_REQUIRED"):
        ledger.initialize(
            portfolio_id="P1", history_evidence_id="", verified=True,
            opening_snapshot_id="S1", opening_snapshot=snapshot,
        )
    with pytest.raises(DrawdownHistoryError, match="EVIDENCE_REQUIRED"):
        ledger.initialize(
            portfolio_id="P1", history_evidence_id="TEST-SIGNOFF", verified=False,
            opening_snapshot_id="S1", opening_snapshot=snapshot,
        )
    assert ledger.initialize(
        portfolio_id="P1", history_evidence_id="TEST-SIGNOFF", verified=True,
        opening_snapshot_id="S1", opening_snapshot=snapshot,
    ) is True
    assert ledger.initialize(
        portfolio_id="P1", history_evidence_id="TEST-SIGNOFF", verified=True,
        opening_snapshot_id="S1", opening_snapshot=snapshot,
    ) is False
    assessed = ledger.assess(portfolio_id="P1", now_ns=100, ttl_ns=10)
    assert assessed.history_evidence_id == "TEST-SIGNOFF"


def test_drawdown_history_observation_replay_is_idempotent_and_conflicts_fail_closed():
    ledger = DrawdownHistoryLedger(EventStore())
    ledger.initialize(
        portfolio_id="P1", history_evidence_id="TEST-SIGNOFF", verified=True,
        opening_snapshot_id="S0", opening_snapshot=equity_snapshot(100, "100"),
    )
    snapshot = equity_snapshot(200, "90")
    assert ledger.observe(portfolio_id="P1", snapshot_id="S1", snapshot=snapshot) is True
    assert ledger.observe(portfolio_id="P1", snapshot_id="S1", snapshot=snapshot) is False
    with pytest.raises(DrawdownHistoryError, match="SNAPSHOT_ID_CONFLICT"):
        ledger.observe(portfolio_id="P1", snapshot_id="S1", snapshot=equity_snapshot(200, "80"))


def test_drawdown_binding_is_conservative_and_monotone():
    low = bind_drawdown_to_risk(drawdown=Decimal("0.2"), baseline_risk=Decimal("100"))
    high = bind_drawdown_to_risk(drawdown=Decimal("0.8"), baseline_risk=Decimal("100"))
    assert low.allowed_risk == Decimal("80.0")
    assert high.allowed_risk == Decimal("20.0")
    assert_drawdown_monotone(lower_drawdown=low.drawdown, lower_allowed_risk=low.allowed_risk, higher_drawdown=high.drawdown, higher_allowed_risk=high.allowed_risk)
    assessment = assessment_for(("100", "80"))
    with pytest.raises(DrawdownRiskError, match="VALIDATION_TIME_REQUIRED"):
        bind_drawdown_to_risk(drawdown=assessment.drawdown, baseline_risk=Decimal("100"), assessment=assessment)


def test_higher_drawdown_cannot_raise_runtime_risk_budget_and_requires_source_binding():
    low_assessment = assessment_for(("100", "80"))
    high_assessment = assessment_for(("100", "20"))
    low = RuntimeAuthority().evaluate(
        truth=truth(assessment=low_assessment), action=CanonicalAction.TRADE,
        requested_risk=Decimal("80"), decision_id="DD-LOW", drawdown_assessment=low_assessment,
    )
    high = RuntimeAuthority().evaluate(
        truth=truth(assessment=high_assessment), action=CanonicalAction.TRADE,
        requested_risk=Decimal("80"), decision_id="DD-HIGH", drawdown_assessment=high_assessment,
    )
    assert low.status is AuthorityStatus.AUTHORIZED
    assert high.status is AuthorityStatus.DENIED
    assert high.reason == "RISK_EXCEEDS_DRAWDOWN_ADJUSTED_RISK"
    assert low.drawdown_risk_factor == Decimal("0.8")
    assert high.drawdown_risk_factor == Decimal("0.2")
    raw = RuntimeAuthority().evaluate(
        truth=truth(), action=CanonicalAction.TRADE,
        requested_risk=Decimal("1"), decision_id="DD-RAW", drawdown=Decimal("0.1"),
    )
    assert raw.status is AuthorityStatus.DENIED
    assert raw.reason == "DRAWDOWN_SOURCE_BINDING_REQUIRED"


def test_runtime_requires_accounting_truth_to_bind_current_drawdown_snapshot():
    assessment = assessment_for(("100", "70"))
    unbound_truth = truth()
    decision = RuntimeAuthority().evaluate(
        truth=unbound_truth, action=CanonicalAction.TRADE, requested_risk=Decimal("1"),
        decision_id="DD-UNBOUND", drawdown_assessment=assessment,
    )
    assert decision.status is AuthorityStatus.DENIED
    assert decision.reason == "DRAWDOWN_ACCOUNTING_SOURCE_BINDING_REQUIRED"


def test_runtime_requires_accounting_truth_to_bind_complete_drawdown_history():
    assessment = assessment_for(("100", "70"))
    decision = RuntimeAuthority().evaluate(
        truth=truth(assessment=assessment, bind_history=False), action=CanonicalAction.TRADE,
        requested_risk=Decimal("1"), decision_id="DD-UNBOUND-HISTORY", drawdown_assessment=assessment,
    )
    assert decision.status is AuthorityStatus.DENIED
    assert decision.reason == "DRAWDOWN_HISTORY_SOURCE_BINDING_REQUIRED"


def test_adjusted_risk_derives_drawdown_factor_and_rejects_upward_override():
    assert adjusted_risk(Decimal("100"), drawdown=Decimal("0.8")) == Decimal("20.0")
    with pytest.raises(ValueError, match="DRAWDOWN_FACTOR_CONFLICT"):
        adjusted_risk(Decimal("100"), drawdown=Decimal("0.8"), drawdown_factor=Decimal("0.5"))
    with pytest.raises(DrawdownRiskError, match="DRAWDOWN_FACTOR_MUST_BE_NONINCREASING"):
        adjusted_risk(Decimal("100"), drawdown_factor=Decimal("1.1"))


def test_durable_decision_rejects_budget_above_dynamic_drawdown_cap():
    ledger = DurableRiskDecisionLedger(EventStore())
    assessment = assessment_for(("100", "20"))
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_DRAWDOWN_CAP"):
        ledger.record(decision(allowed="21", assessment=assessment, drawdown_factor="0.2"))


def test_durable_decision_replays_and_revalidates_dynamic_drawdown_source(tmp_path: Path):
    path = str(tmp_path / "risk.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    assessment = assessment_for(("100", "20"))
    d = decision(allowed="20", assessment=assessment, drawdown_factor="0.2")
    ledger.record(d)
    restored = DurableRiskDecisionLedger(EventStore(path)).get("D-DD")
    assert restored == d
    snap = DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
        decision_id="D-DD", now_ms=150, intent_id="I-DD", reservation_id="RR-DD",
        requested_exposure=Decimal("20"), truth_hash="TH-DD", drawdown=assessment.drawdown,
        drawdown_assessment=assessment,
    )
    assert snap.drawdown == Decimal("0.8")
    assert snap.drawdown_source_fingerprint == assessment.source_fingerprint
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_DRAWDOWN_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-DD", now_ms=150, intent_id="I-DD", reservation_id="RR-DD",
            requested_exposure=Decimal("20"), truth_hash="TH-DD", drawdown=Decimal("0.9"),
            drawdown_assessment=assessment,
        )
    changed_source = assessment_for(("100", "20"), portfolio_id="P-OTHER")
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_DRAWDOWN_SOURCE_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-DD", now_ms=150, intent_id="I-DD", reservation_id="RR-DD",
            requested_exposure=Decimal("20"), truth_hash="TH-DD", drawdown=changed_source.drawdown,
            drawdown_assessment=changed_source,
        )
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_DRAWDOWN_SOURCE_EXPIRED"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D-DD", now_ms=161, intent_id="I-DD", reservation_id="RR-DD",
            requested_exposure=Decimal("20"), truth_hash="TH-DD", drawdown=assessment.drawdown,
            drawdown_assessment=assessment,
        )


def test_combined_uncertainty_liquidity_drawdown_uses_tightest_cap():
    assessment = assessment_for(("100", "70"))
    low = RuntimeAuthority().evaluate(
        truth=truth(assessment=assessment), action=CanonicalAction.TRADE,
        requested_risk=Decimal("20"), decision_id="DD-COMB-1",
        uncertainty=Decimal("0.5"), liquidity_stress=Decimal("0.8"),
        drawdown_assessment=assessment,
    )
    assert low.status is AuthorityStatus.AUTHORIZED
    assert low.uncertainty_risk_factor == Decimal("0.5")
    assert low.liquidity_risk_factor == Decimal("0.2")
    assert low.drawdown_risk_factor == Decimal("0.7")
    denied = RuntimeAuthority().evaluate(
        truth=truth(assessment=assessment), action=CanonicalAction.TRADE,
        requested_risk=Decimal("20.01"), decision_id="DD-COMB-2",
        uncertainty=Decimal("0.5"), liquidity_stress=Decimal("0.8"),
        drawdown_assessment=assessment,
    )
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


def test_execution_router_enforces_source_bound_drawdown_cap_before_order_request():
    from trading_platform.v31.router import ExecutionRouter
    from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side, PositionState
    from trading_platform.core.ttl import ValidWindow

    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    delta = now - datetime(1970, 1, 1, tzinfo=timezone.utc)
    now_ns = ((delta.days * 86400 + delta.seconds) * 1_000_000_000) + delta.microseconds * 1_000
    assessment = assessment_for(("100", "20"), start_ns=now_ns - 1_000_000)
    window = ValidWindow(now - timedelta(seconds=1), now + timedelta(minutes=5))
    intent = OrderIntent("I-M23", "D", "P", "R", "S", "M", "E", "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, window)
    with pytest.raises(PermissionError, match="RISK_EXCEEDS_DRAWDOWN_ADJUSTED_RISK"):
        ExecutionRouter().route(
            intent=intent, truth=truth(assessment=assessment), now=now, position_state=PositionState.FLAT,
            market_window=window, upstream_windows=[window], risk_valid=True,
            requested_risk=Decimal("60"), decision_id="M23-ROUTE", drawdown_assessment=assessment,
        )


def test_trade_capability_binds_and_revalidates_dynamic_drawdown_source():
    from trading_platform.v32.capability import CapabilityAuthority, CapabilityError

    now = datetime(2026, 9, 25, tzinfo=timezone.utc)
    delta = now - datetime(1970, 1, 1, tzinfo=timezone.utc)
    now_ns = ((delta.days * 86400 + delta.seconds) * 1_000_000_000) + delta.microseconds * 1_000
    low_assessment = assessment_for(("100", "80"), start_ns=now_ns - 1_000_000, ttl_ns=60_000_000_000)
    high_assessment = assessment_for(("100", "20"), start_ns=now_ns - 1_000_000, ttl_ns=60_000_000_000)
    payload = {"intent_id": "I-DD-CAP", "symbol": "BTCUSDT", "side": "BUY", "action": "OPEN", "quantity": "0.001"}
    ca = CapabilityAuthority()
    low = ca.issue(
        truth=truth(assessment=low_assessment), requested_risk=Decimal("10"), decision_id="M23-CAP",
        intent_payload=payload, expires_at=now + timedelta(seconds=120), drawdown_assessment=low_assessment,
    )
    high = ca.issue(
        truth=truth(assessment=high_assessment), requested_risk=Decimal("10"), decision_id="M23-CAP",
        intent_payload=payload, expires_at=now + timedelta(seconds=120), drawdown_assessment=high_assessment,
    )
    assert low.capability_id != high.capability_id
    assert low.authority.input_fingerprint != high.authority.input_fingerprint
    with pytest.raises(CapabilityError, match="DRAWDOWN_SOURCE_EXPIRED"):
        ca.validate(
            low, now=now + timedelta(seconds=61), truth=truth(assessment=low_assessment),
            intent_payload=payload, drawdown_assessment=low_assessment,
        )
