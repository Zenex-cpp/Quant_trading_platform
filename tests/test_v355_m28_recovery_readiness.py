from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest

from trading_platform.operations.readiness import OperationalReadiness
from trading_platform.state.enums import OperationalMode
from trading_platform.v21.event_store import EventStore
from trading_platform.v324.recovery_proof import RecoveryProofLedger, RecoveryProofInvalid
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v355.recovery_readiness import (
    RecoveryReadinessAuthorityConflict,
    RecoveryReadinessAuthorityError,
    RecoveryReadinessAuthorityExpired,
    RecoveryReadinessLedger,
)

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def ready():
    return OperationalReadiness(*([True] * 19))


def proof(ledger: RecoveryProofLedger, *, proof_id="rp1", state_fp="state-1"):
    return ledger.record(
        proof_id=proof_id,
        recovery_id="recovery-1",
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True,
        invariants_pass=True,
        no_unresolved_critical_issue=True,
        guards_pass=True,
        state_fingerprint=state_fp,
        reconciliation_fingerprint="recon-1",
        invariants_fingerprint="inv-1",
        guards_fingerprint="guard-1",
        issued_at_ms=1,
        store=ledger.store,
    )


def test_canary_live_require_durable_readiness(tmp_path: Path):
    store = EventStore(str(tmp_path / "m28.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    auth = RecoveryReadinessLedger(store).authorize(
        authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
        proof_ledger=rp, proof_id=p.proof_id, now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
    )
    assert auth.proof_id == p.proof_id
    assert auth.target_mode is OperationalMode.LIVE


def test_missing_proof_blocks_readiness_authority(tmp_path: Path):
    store = EventStore(str(tmp_path / "m28.db"))
    rp = RecoveryProofLedger(store)
    with pytest.raises(RecoveryReadinessAuthorityError, match="RECOVERY_PROOF_REQUIRED"):
        RecoveryReadinessLedger(store).authorize(
            authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
            proof_ledger=rp, proof_id="missing", now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
        )


def test_state_change_invalidates_readiness(tmp_path: Path):
    store = EventStore(str(tmp_path / "m28.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    ledger = RecoveryReadinessLedger(store)
    ledger.authorize(
        authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.CANARY,
        proof_ledger=rp, proof_id=p.proof_id, now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
    )
    with pytest.raises(RecoveryReadinessAuthorityConflict, match="STATE_FINGERPRINT"):
        ledger.assert_valid("rr1", readiness=ready(), target_mode=OperationalMode.CANARY, proof_ledger=rp, now=NOW, current_state_fingerprint="state-2")


def test_expired_proof_cannot_create_readiness(tmp_path: Path):
    store = EventStore(str(tmp_path / "m28.db"))
    rp = RecoveryProofLedger(store)
    rp.record(
        proof_id="rp1", recovery_id="recovery-1", valid_from=NOW - timedelta(minutes=10), expires_at=NOW - timedelta(seconds=1),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint="state-1", reconciliation_fingerprint="r", invariants_fingerprint="i", guards_fingerprint="g", issued_at_ms=1, store=store,
    )
    with pytest.raises(RecoveryReadinessAuthorityError, match="RECOVERY_PROOF_REQUIRED"):
        RecoveryReadinessLedger(store).authorize(
            authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
            proof_ledger=rp, proof_id="rp1", now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
        )


def test_restart_preserves_readiness_authority(tmp_path: Path):
    db = tmp_path / "m28.db"
    store = EventStore(str(db))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    rr = RecoveryReadinessLedger(store).authorize(
        authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
        proof_ledger=rp, proof_id=p.proof_id, now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
    )
    restored = RecoveryReadinessLedger(EventStore(str(db))).assert_valid(
        rr.authorization_id, readiness=None, target_mode=OperationalMode.LIVE,
        proof_ledger=RecoveryProofLedger(EventStore(str(db))), now=NOW + timedelta(seconds=1), current_state_fingerprint="state-1",
    )
    assert restored.fingerprint == rr.fingerprint


def test_retry_is_idempotent_even_with_new_audit_timestamp(tmp_path: Path):
    store = EventStore(str(tmp_path / "m28.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    ledger = RecoveryReadinessLedger(store)
    first = ledger.authorize(
        authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
        proof_ledger=rp, proof_id=p.proof_id, now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
    )
    second = ledger.authorize(
        authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
        proof_ledger=rp, proof_id=p.proof_id, now=NOW, current_state_fingerprint="state-1", recorded_at_ms=99,
    )
    assert second == first


def test_tampered_readiness_chain_blocks_reuse(tmp_path: Path):
    store = EventStore(str(tmp_path / "m28.db"))
    rp = RecoveryProofLedger(store)
    p = proof(rp)
    ledger = RecoveryReadinessLedger(store)
    ledger.authorize(
        authorization_id="rr1", readiness=ready(), target_mode=OperationalMode.LIVE,
        proof_ledger=rp, proof_id=p.proof_id, now=NOW, current_state_fingerprint="state-1", recorded_at_ms=2,
    )
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ("{}", "recovery-readiness:authorize:rr1"))
    with pytest.raises(RecoveryReadinessAuthorityError, match="EVENT_CHAIN"):
        ledger.get("rr1")
