from pathlib import Path

import pytest

from trading_platform.ops.backup_restore import (
    BackupPolicy,
    BackupRestoreError,
    BackupRestoreService,
)


def test_backup_restore_drill_records_integrity_and_rpo_rto(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "state.json").write_text('{"state":"READY"}', encoding="utf-8")
    (root / "evidence.txt").write_text("immutable-evidence", encoding="utf-8")
    archive = tmp_path / "backup.tar.gz"
    restored = tmp_path / "restored"
    clock = iter([2_000_000_000_000, 2_000_000_000_100, 2_000_000_000_200])
    service = BackupRestoreService(now_ns=lambda: next(clock))
    policy = BackupPolicy(
        source_root=root,
        include_prefixes=("state.json", "evidence.txt"),
        destination=archive,
        rpo_seconds=10,
        rto_seconds=10,
    )
    record = service.create_backup(
        policy=policy,
        latest_event_time_ns=1_999_999_999_000,
        backup_id="B367-001",
    )
    assert record.file_count == 2
    assert record.evidence_class == "INTERNAL_TEST_EVIDENCE"
    restored_record, elapsed = service.restore(archive_path=archive, destination_root=restored)
    assert restored_record.manifest_hash == record.manifest_hash
    assert elapsed == pytest.approx(0.0000001)
    assert (restored / "state.json").read_text() == '{"state":"READY"}'
    assert (restored / "evidence.txt").read_text() == "immutable-evidence"


def test_backup_rejects_secret_like_paths(tmp_path: Path):
    root = tmp_path / "source"
    (root / "secrets").mkdir(parents=True)
    (root / "secrets" / "prod_secret.txt").write_text("do-not-backup")
    policy = BackupPolicy(
        source_root=root,
        include_prefixes=("secrets",),
        destination=tmp_path / "backup.tar.gz",
        rpo_seconds=10,
        rto_seconds=10,
    )
    with pytest.raises(BackupRestoreError, match="BACKUP_SECRET_LIKE_PATH_FORBIDDEN"):
        BackupRestoreService(now_ns=lambda: 1_000).create_backup(
            policy=policy,
            latest_event_time_ns=900,
            backup_id="B367-SECRET",
        )


def test_restore_rejects_non_empty_destination(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "state.json").write_text("state")
    archive = tmp_path / "backup.tar.gz"
    policy = BackupPolicy(root, ("state.json",), archive, 10, 10)
    service = BackupRestoreService(now_ns=lambda: 1_000)
    service.create_backup(policy=policy, latest_event_time_ns=900, backup_id="B367-002")
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "preexisting").write_text("x")
    with pytest.raises(BackupRestoreError, match="RESTORE_DESTINATION_NOT_EMPTY"):
        service.restore(archive_path=archive, destination_root=restored)


def test_rpo_and_rto_are_fail_closed(tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "state.json").write_text("state")
    policy = BackupPolicy(root, ("state.json",), tmp_path / "backup.tar.gz", 1, 1)
    with pytest.raises(BackupRestoreError, match="RPO_TARGET_BREACHED"):
        BackupRestoreService(now_ns=lambda: 10_000_000_000).create_backup(
            policy=policy,
            latest_event_time_ns=8_000_000_000,
            backup_id="B367-RPO",
        )
