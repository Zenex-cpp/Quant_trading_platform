from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.risk.monotonicity import adjusted_risk
from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, CanonicalAction, ConfigurationStatus, build_truth
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v318 import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionRecord, RiskSystemState
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v356 import (
    RiskBudgetMonotonicityGuard,
    RiskBudgetStateSnapshot,
    RiskStateMonotonicityError,
    RiskStateRecoveryEventLedger,
    RiskStateRecoveryEventRecord,
    conservative_state_risk_factor,
    state_severity,
)

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth(state: RiskSystemState = RiskSystemState.NORMAL):
    comps = tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger"))
    caps = {k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")}
    return build_truth(
        observed_at_ns=int(NOW.timestamp() * 1_000_000_000),
        axes=AX,
        components=comps,
        requested_risk=Decimal("100"),
        caps=caps,
        decision_fresh=True,
        configuration_status=ConfigurationStatus.RESOLVED,
        risk_state=state.value,
    )


def snapshot(state, remaining, new_risk, maximum, truth_hash="TH", observed=100):
    return RiskBudgetStateSnapshot(
        risk_state=state,
        remaining_budget=Decimal(str(remaining)),
        available_new_risk=Decimal(str(new_risk)),
        maximum_exposure=Decimal(str(maximum)),
        state_version="risk-state-v1",
        truth_hash=truth_hash,
        observed_at_ms=observed,
    )


def recovery_proof(store: EventStore, state_fp: str):
    ledger = RecoveryProofLedger(store)
    return ledger.record(
        proof_id="RP-M29",
        recovery_id="REC-M29",
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True,
        invariants_pass=True,
        no_unresolved_critical_issue=True,
        guards_pass=True,
        state_fingerprint=state_fp,
        reconciliation_fingerprint="recon-m29",
        invariants_fingerprint="inv-m29",
        guards_fingerprint="guards-m29",
        issued_at_ms=int(NOW.timestamp() * 1000),
        store=store,
    )


def recovery_event(store, state_fp="STATE-M29"):
    proof_ledger = RecoveryProofLedger(store)
    proof = recovery_proof(store, state_fp)
    ledger = RiskStateRecoveryEventLedger(store)
    record = RiskStateRecoveryEventRecord(
        recovery_event_id="RE-M29",
        previous_state=RiskSystemState.EMERGENCY,
        current_state=RiskSystemState.RECOVERY,
        recovery_proof_id=proof.proof_id,
        recovery_proof_fingerprint=proof.fingerprint,
        state_fingerprint=state_fp,
        validated=True,
        audited=True,
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=15),
        recorded_at_ms=int(NOW.timestamp() * 1000),
        allowed_remaining_budget=Decimal("25"),
        allowed_available_new_risk=Decimal("20"),
        allowed_maximum_exposure=Decimal("25"),
    )
    return ledger.record(record, proof_ledger=proof_ledger, now=NOW + timedelta(seconds=1), current_state_fingerprint=state_fp)


def test_state_severity_and_factor_are_conservative():
    assert state_severity(RiskSystemState.NORMAL) < state_severity(RiskSystemState.ELEVATED)
    assert state_severity(RiskSystemState.ELEVATED) < state_severity(RiskSystemState.RESTRICTED)
    assert state_severity(RiskSystemState.RESTRICTED) < state_severity(RiskSystemState.FROZEN)
    assert state_severity(RiskSystemState.FROZEN) < state_severity(RiskSystemState.EMERGENCY)
    assert state_severity(RiskSystemState.EMERGENCY) < state_severity(RiskSystemState.RECOVERY)
    assert conservative_state_risk_factor(RiskSystemState.NORMAL) == Decimal("1")
    assert conservative_state_risk_factor(RiskSystemState.ELEVATED) == Decimal("0.75")
    assert conservative_state_risk_factor(RiskSystemState.RESTRICTED) == Decimal("0.50")
    assert conservative_state_risk_factor(RiskSystemState.RECOVERY) == Decimal("0")


def test_adjusted_risk_state_factor_is_conservative():
    assert adjusted_risk(Decimal("100"), state_risk_factor=Decimal("0.75")) == Decimal("75.00")
    with pytest.raises(Exception, match="RISK_STATE_FACTOR_MUST_BE_NONINCREASING"):
        adjusted_risk(Decimal("100"), state_risk_factor=Decimal("1.1"))


def test_runtime_authority_tightens_worse_risk_state():
    normal = RuntimeAuthority().evaluate(
        truth=truth(RiskSystemState.NORMAL), action=CanonicalAction.TRADE,
        requested_risk=Decimal("80"), decision_id="STATE-NORMAL",
    )
    elevated = RuntimeAuthority().evaluate(
        truth=truth(RiskSystemState.ELEVATED), action=CanonicalAction.TRADE,
        requested_risk=Decimal("80"), decision_id="STATE-ELEVATED",
    )
    assert normal.status is AuthorityStatus.AUTHORIZED
    assert elevated.status is AuthorityStatus.DENIED
    assert elevated.reason == "RISK_EXCEEDS_RISK_STATE_ADJUSTED_RISK"
    assert elevated.risk_state == RiskSystemState.ELEVATED.value
    assert elevated.risk_state_risk_factor == Decimal("0.75")


def test_runtime_allows_recovery_event_exception_within_audited_ceiling(tmp_path: Path):
    state_fp = truth(RiskSystemState.RECOVERY).state_hash
    store = EventStore(str(tmp_path / "m29.db"))
    event = recovery_event(store, state_fp=state_fp)
    decision = RuntimeAuthority().evaluate(
        truth=truth(RiskSystemState.RECOVERY), action=CanonicalAction.TRADE,
        requested_risk=Decimal("20"), decision_id="STATE-RECOVERY", recovery_event=event,
    )
    assert decision.status is AuthorityStatus.AUTHORIZED
    assert decision.recovery_event_id == "RE-M29"
    assert decision.risk_state_risk_factor == Decimal("0.25")
    too_high = RuntimeAuthority().evaluate(
        truth=truth(RiskSystemState.RECOVERY), action=CanonicalAction.TRADE,
        requested_risk=Decimal("26"), decision_id="STATE-RECOVERY-HIGH", recovery_event=event,
    )
    assert too_high.status is AuthorityStatus.DENIED
    assert too_high.reason == "RISK_EXCEEDS_RISK_STATE_ADJUSTED_RISK"


def test_budget_outputs_cannot_increase_when_state_worsens_without_recovery():
    previous = snapshot(RiskSystemState.NORMAL, 50, 50, 50)
    current = snapshot(RiskSystemState.ELEVATED, 51, 51, 51)
    with pytest.raises(RiskStateMonotonicityError, match="RISK_STATE_WORSENED_WITHOUT_RECOVERY_EVENT"):
        RiskBudgetMonotonicityGuard.assert_monotone(previous=previous, current=current)


def test_budget_outputs_may_remain_equal_or_decrease_when_state_worsens():
    previous = snapshot(RiskSystemState.NORMAL, 50, 50, 50)
    current = snapshot(RiskSystemState.ELEVATED, 50, 49, 40)
    RiskBudgetMonotonicityGuard.assert_monotone(previous=previous, current=current)


def test_recovery_event_allows_state_worsening_increase_only_with_audited_event(tmp_path: Path):
    store = EventStore(str(tmp_path / "recovery.db"))
    event = recovery_event(store)
    previous = snapshot(RiskSystemState.EMERGENCY, 0, 0, 0, truth_hash="STATE-M29")
    current = snapshot(RiskSystemState.RECOVERY, 20, 20, 20, truth_hash="STATE-M29")
    RiskBudgetMonotonicityGuard.assert_monotone(previous=previous, current=current, recovery_event=event)


def test_recovery_event_ceiling_is_enforced():
    class Fake:
        validated = True
        audited = True
        current_state = RiskSystemState.RECOVERY
        allowed_remaining_budget = Decimal("25")
        allowed_available_new_risk = Decimal("20")
        allowed_maximum_exposure = Decimal("20")
        def assert_allows(self, *, current, now=None):
            if current.maximum_exposure > self.allowed_maximum_exposure:
                raise RiskStateMonotonicityError("RECOVERY_EVENT_MAXIMUM_EXPOSURE_EXCEEDED")
    previous = snapshot(RiskSystemState.EMERGENCY, 0, 0, 0)
    current = snapshot(RiskSystemState.RECOVERY, 21, 21, 21)
    with pytest.raises(RiskStateMonotonicityError, match="RECOVERY_EVENT_MAXIMUM_EXPOSURE_EXCEEDED"):
        RiskBudgetMonotonicityGuard.assert_monotone(previous=previous, current=current, recovery_event=Fake())


def test_durable_risk_decision_state_cap_is_enforced():
    ledger = DurableRiskDecisionLedger(EventStore())
    base = dict(
        decision_id="D-M29", action=RiskDecisionAction.ALLOW, risk_state=RiskSystemState.ELEVATED,
        requested_exposure=Decimal("100"), active_limits={"order": Decimal("100")}, multipliers={"state": Decimal("0.75")},
        rejection_reason=None, reservation_id="RR-M29", intent_id="I-M29", created_at_ms=100, valid_from_ms=100, expires_at_ms=200,
        configuration_version="cfg1", risk_state_version="risk1", portfolio_version="port1", position_version="pos1",
        provenance_id="prov1", truth_hash="TH-M29", input_fingerprint="fp", risk_state_factor=Decimal("0.75"), recovery_event_id=None,
    )
    ok = RiskDecisionRecord(allowed_exposure=Decimal("75"), **base)
    assert ledger.record(ok) == ok
    bad = RiskDecisionRecord(allowed_exposure=Decimal("76"), **{**base, "decision_id": "D-M29-BAD"})
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_RISK_STATE_CAP"):
        ledger.record(bad)


def test_recovery_event_is_restart_safe_and_proof_bound(tmp_path: Path):
    path = str(tmp_path / "recover.db")
    store = EventStore(path)
    event = recovery_event(store, state_fp="FP-M29")
    restored = RiskStateRecoveryEventLedger(EventStore(path)).get(event.recovery_event_id)
    assert restored == event
    assert restored.recovery_proof_fingerprint == event.recovery_proof_fingerprint


def test_recovery_event_requires_matching_current_state_fingerprint(tmp_path: Path):
    store = EventStore(str(tmp_path / "recover.db"))
    proof_ledger = RecoveryProofLedger(store)
    proof = recovery_proof(store, "FP-M29")
    record = RiskStateRecoveryEventRecord(
        recovery_event_id="RE-M29-BAD",
        previous_state=RiskSystemState.EMERGENCY,
        current_state=RiskSystemState.RECOVERY,
        recovery_proof_id=proof.proof_id,
        recovery_proof_fingerprint=proof.fingerprint,
        state_fingerprint="OTHER",
        validated=True,
        audited=True,
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=15),
        recorded_at_ms=int(NOW.timestamp() * 1000),
        allowed_remaining_budget=Decimal("25"),
        allowed_available_new_risk=Decimal("20"),
        allowed_maximum_exposure=Decimal("25"),
    )
    with pytest.raises(Exception, match="RECOVERY_EVENT_STATE_FINGERPRINT_STALE"):
        RiskStateRecoveryEventLedger(store).record(record, proof_ledger=proof_ledger, now=NOW + timedelta(seconds=1), current_state_fingerprint="FP-M29")
