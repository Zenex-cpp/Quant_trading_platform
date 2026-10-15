from decimal import Decimal
from pathlib import Path
import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v318 import (
    DurableRiskDecisionLedger,
    RiskDecisionAction,
    RiskDecisionConflict,
    RiskDecisionRecord,
    RiskDecisionReplayError,
    RiskSystemState,
)


def decision(*, did="D1", intent="I1", reservation="RR1", truth="TH1", valid_from=100, expires=200):
    return RiskDecisionRecord(
        decision_id=did,
        action=RiskDecisionAction.ALLOW,
        risk_state=RiskSystemState.NORMAL,
        requested_exposure=Decimal("3"),
        allowed_exposure=Decimal("3"),
        active_limits={"order": Decimal("3"), "portfolio": Decimal("10")},
        multipliers={"uncertainty": Decimal("1"), "liquidity": Decimal("1")},
        rejection_reason=None,
        reservation_id=reservation,
        intent_id=intent,
        created_at_ms=valid_from,
        valid_from_ms=valid_from,
        expires_at_ms=expires,
        configuration_version="cfg1",
        risk_state_version="risk1",
        portfolio_version="port1",
        position_version="pos1",
        provenance_id="prov1",
        truth_hash=truth,
        input_fingerprint="input1",
    )


def test_record_is_restart_safe_and_idempotent(tmp_path: Path):
    path = str(tmp_path / "decision.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    d = decision()
    assert ledger.record(d) == d
    assert ledger.record(d) == d
    restored = DurableRiskDecisionLedger(EventStore(path)).get("D1")
    assert restored == d


def test_conflicting_reuse_is_rejected(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "decision.db")))
    ledger.record(decision())
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_ID_PAYLOAD_CONFLICT"):
        ledger.record(decision(truth="OTHER"))


def test_ttl_and_identity_gate(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "decision.db")))
    ledger.record(decision())
    snap = ledger.assert_valid_for_new_risk(
        decision_id="D1", now_ms=150, intent_id="I1", reservation_id="RR1",
        requested_exposure=Decimal("3"), truth_hash="TH1",
    )
    assert snap.decision_id == "D1"
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_EXPIRED_OR_NOT_YET_VALID"):
        ledger.assert_valid_for_new_risk(
            decision_id="D1", now_ms=200, intent_id="I1", reservation_id="RR1",
            requested_exposure=Decimal("3"), truth_hash="TH1",
        )


def test_truth_and_version_staleness_fail_closed(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "decision.db")))
    ledger.record(decision())
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_TRUTH_HASH_STALE"):
        ledger.assert_valid_for_new_risk(
            decision_id="D1", now_ms=150, intent_id="I1", reservation_id="RR1",
            requested_exposure=Decimal("3"), truth_hash="STALE",
        )
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_POSITION_VERSION_MISMATCH"):
        ledger.assert_valid_for_new_risk(
            decision_id="D1", now_ms=150, intent_id="I1", reservation_id="RR1",
            requested_exposure=Decimal("3"), truth_hash="TH1", position_version="changed",
        )


def test_non_allow_decision_cannot_authorize_new_risk(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "decision.db")))
    d = decision()
    d = RiskDecisionRecord(**{**d.__dict__, "action": RiskDecisionAction.REJECT, "allowed_exposure": Decimal("0"), "rejection_reason": "NO_CAPACITY"})
    ledger.record(d)
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_ACTION_DENIED:REJECT"):
        ledger.assert_valid_for_new_risk(
            decision_id="D1", now_ms=150, intent_id="I1", reservation_id="RR1",
            requested_exposure=Decimal("0"), truth_hash="TH1",
        )


def test_corrupted_chain_fails_closed(tmp_path: Path):
    path = str(tmp_path / "decision.db")
    store = EventStore(path)
    ledger = DurableRiskDecisionLedger(store)
    ledger.record(decision())
    tamper_event_store(store, "UPDATE events SET payload_json='{}' WHERE event_id='risk-decision:record:D1'")
    with pytest.raises(RiskDecisionReplayError, match="RISK_DECISION_EVENT_CHAIN_INVALID"):
        ledger.restore()


def test_uncertainty_bound_rejects_allowed_exposure_above_conservative_cap(tmp_path: Path):
    ledger = DurableRiskDecisionLedger(EventStore(str(tmp_path / "decision.db")))
    d = decision()
    d = RiskDecisionRecord(**{**d.__dict__,
        "requested_exposure": Decimal("100"),
        "allowed_exposure": Decimal("60"),
        "uncertainty": Decimal("0.8"),
        "uncertainty_max": Decimal("1"),
        "uncertainty_floor": Decimal("0"),
        "uncertainty_risk_factor": Decimal("0.2"),
        "uncertainty_method": "CONSERVATIVE_LINEAR",
        "uncertainty_method_version": "1",
    })
    with pytest.raises(ValueError, match="RISK_ALLOWED_EXCEEDS_UNCERTAINTY_CAP"):
        ledger.record(d)


def test_uncertainty_bound_is_restart_safe_and_stale_uncertainty_blocks(tmp_path: Path):
    path = str(tmp_path / "decision.db")
    ledger = DurableRiskDecisionLedger(EventStore(path))
    d = decision()
    d = RiskDecisionRecord(**{**d.__dict__,
        "requested_exposure": Decimal("100"),
        "allowed_exposure": Decimal("20"),
        "uncertainty": Decimal("0.8"),
        "uncertainty_max": Decimal("1"),
        "uncertainty_floor": Decimal("0"),
        "uncertainty_risk_factor": Decimal("0.2"),
        "uncertainty_method": "CONSERVATIVE_LINEAR",
        "uncertainty_method_version": "1",
    })
    ledger.record(d)
    restored = DurableRiskDecisionLedger(EventStore(path)).get("D1")
    assert restored == d
    snap = DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
        decision_id="D1", now_ms=150, intent_id="I1", reservation_id="RR1",
        requested_exposure=Decimal("20"), truth_hash="TH1", uncertainty=Decimal("0.8"),
    )
    assert snap.uncertainty == Decimal("0.8")
    with pytest.raises(RiskDecisionConflict, match="RISK_DECISION_UNCERTAINTY_STALE"):
        DurableRiskDecisionLedger(EventStore(path)).assert_valid_for_new_risk(
            decision_id="D1", now_ms=150, intent_id="I1", reservation_id="RR1",
            requested_exposure=Decimal("20"), truth_hash="TH1", uncertainty=Decimal("0.9"),
        )
