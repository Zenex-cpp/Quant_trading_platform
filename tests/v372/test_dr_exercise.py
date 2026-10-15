from pathlib import Path

from trading_platform.v372.dr_exercise import DRPhase, DisasterRecoveryExercise


def test_application_disaster_recovery_crash_restore_replay(tmp_path: Path):
    clock = iter([2_000_000_100, 2_000_000_200, 2_000_000_300])
    result = DisasterRecoveryExercise(now_ns=lambda: next(clock)).run(workspace=tmp_path / "dr")
    assert result.phase is DRPhase.RECOVERED
    assert result.evidence_class == "INTERNAL_TEST_EVIDENCE"
    assert result.event_chain_verified
    assert result.snapshot_verified
    assert result.replay_verified
    assert result.invariants_pass
    assert result.no_unresolved_critical_issue
    assert result.guards_pass
    assert result.trading_allowed
    assert result.recovery_verified
    assert result.expected_state_hash == result.recovered_state_hash
    assert result.expected_event_chain_hash == result.recovered_event_chain_hash
    assert result.rpo_seconds >= 0
    assert result.rto_seconds <= 10


def test_disaster_recovery_is_fail_closed_on_rto_breach(tmp_path: Path):
    from trading_platform.ops.backup_restore import BackupRestoreError, BackupPolicy, BackupRestoreService

    root = tmp_path / "source"
    root.mkdir()
    (root / "state.json").write_text("state", encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"
    policy = BackupPolicy(root, ("state.json",), archive, 10, 0)
    clock = iter([1_000_000_000, 1_000_000_001, 1_000_000_002])
    service = BackupRestoreService(now_ns=lambda: next(clock))
    service.create_backup(policy=policy, latest_event_time_ns=999_999_999, backup_id="B372-RTO")
    try:
        service.restore(archive_path=archive, destination_root=tmp_path / "restored")
    except BackupRestoreError as exc:
        assert str(exc) == "RTO_TARGET_BREACHED"
    else:
        raise AssertionError("RTO breach was not fail-closed")
