from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from trading_platform.operations.readiness import OperationalReadiness
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v324.recovery_proof import (
    RecoveryProofConflict,
    RecoveryProofExpired,
    RecoveryProofInvalid,
    RecoveryProofLedger,
    RecoveryProofStatus,
    require_live_readiness,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def record(ledger: RecoveryProofLedger, *, proof_id="rp1", state_fp="state-1", expires=5):
    return ledger.record(
        proof_id=proof_id,
        recovery_id="recovery-1",
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=expires),
        state_reconciled=True,
        invariants_pass=True,
        no_unresolved_critical_issue=True,
        guards_pass=True,
        state_fingerprint=state_fp,
        reconciliation_fingerprint="recon-1",
        invariants_fingerprint="inv-1",
        guards_fingerprint="guards-1",
        issued_at_ms=int(NOW.timestamp() * 1000),
        store=ledger.store,
    )


def ready() -> OperationalReadiness:
    return OperationalReadiness(*([True] * 19))


def test_verified_proof_is_durable_and_bound_to_current_state(tmp_path: Path):
    db = tmp_path / "recovery.db"
    first = RecoveryProofLedger(EventStore(str(db)))
    proof = record(first)
    assert proof.status is RecoveryProofStatus.VERIFIED
    assert first.assert_valid("rp1", now=NOW + timedelta(seconds=1), current_state_fingerprint="state-1") == proof

    second = RecoveryProofLedger(EventStore(str(db)))
    restored = second.get("rp1")
    assert restored == proof
    assert second.restore()["rp1"] == proof


def test_failed_predicate_cannot_be_recorded(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    with pytest.raises(RecoveryProofInvalid, match="PREDICATES_NOT_VERIFIED"):
        ledger.record(
            proof_id="bad",
            recovery_id="recovery-1",
            valid_from=NOW,
            expires_at=NOW + timedelta(minutes=5),
            state_reconciled=True,
            invariants_pass=False,
            no_unresolved_critical_issue=True,
            guards_pass=True,
            state_fingerprint="state-1",
            reconciliation_fingerprint="recon-1",
            invariants_fingerprint="inv-1",
            guards_fingerprint="guards-1",
            issued_at_ms=1,
            store=ledger.store,
        )


def test_expired_proof_is_rejected(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    record(ledger, expires=1)
    with pytest.raises(RecoveryProofExpired, match="RECOVERY_PROOF_EXPIRED"):
        ledger.assert_valid("rp1", now=NOW + timedelta(minutes=1), current_state_fingerprint="state-1")


def test_changed_state_fingerprint_fails_closed(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    record(ledger)
    with pytest.raises(RecoveryProofConflict, match="STATE_FINGERPRINT_MISMATCH"):
        ledger.assert_valid("rp1", now=NOW + timedelta(seconds=1), current_state_fingerprint="state-2")


def test_corrupt_chain_blocks_recovery_gate(tmp_path: Path):
    db = tmp_path / "r.db"
    ledger = RecoveryProofLedger(EventStore(str(db)))
    record(ledger)
    store = EventStore(str(db))
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}', 'recovery-proof:record:rp1'))
    with pytest.raises(RecoveryProofInvalid, match="EVENT_CHAIN_INVALID"):
        RecoveryProofLedger(EventStore(str(db))).assert_valid("rp1", now=NOW, current_state_fingerprint="state-1")


def test_live_readiness_requires_durable_recovery_proof(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    with pytest.raises(PermissionError, match="RECOVERY_PROOF_REQUIRED"):
        require_live_readiness(
            ready(),
            target_mode=OperationalMode.LIVE,
            proof_ledger=ledger,
            proof_id=None,
            now=NOW,
            current_state_fingerprint="state-1",
        )


def test_live_readiness_accepts_verified_current_proof(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    proof = record(ledger)
    assert require_live_readiness(
        ready(),
        target_mode=OperationalMode.LIVE,
        proof_ledger=ledger,
        proof_id=proof.proof_id,
        now=NOW + timedelta(seconds=1),
        current_state_fingerprint="state-1",
    ) == proof


def test_non_operational_mode_does_not_require_recovery_proof(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    assert require_live_readiness(
        ready(),
        target_mode=OperationalMode.SHADOW,
        proof_ledger=ledger,
        proof_id=None,
        now=NOW,
        current_state_fingerprint="state-1",
    ) is None


def test_closing_only_does_not_require_recovery_proof(tmp_path: Path):
    ledger = RecoveryProofLedger(EventStore(str(tmp_path / "r.db")))
    assert require_live_readiness(
        ready(),
        target_mode=OperationalMode.CLOSING_ONLY,
        proof_ledger=ledger,
        proof_id=None,
        now=NOW,
        current_state_fingerprint="state-1",
    ) is None
