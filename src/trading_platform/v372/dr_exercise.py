from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path
from typing import Callable

from trading_platform.ops.backup_restore import BackupPolicy, BackupRestoreService, BackupRestoreError
from trading_platform.v21.event_store import EventStore
from trading_platform.v21.ledger import EventSourcedLedger, LedgerState
from trading_platform.v23.recovery import GapRecoveryCoordinator, RecoveryState, RestSnapshot, state_hash, state_payload


class DRExerciseError(RuntimeError):
    """Application-level disaster-recovery drill failure."""


class DRPhase(str, Enum):
    PREPARE = "PREPARE"
    DISASTER_DECLARED = "DISASTER_DECLARED"
    RESTORE = "RESTORE"
    REPLAY = "REPLAY"
    VERIFY = "VERIFY"
    RECOVERED = "RECOVERED"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class DRResult:
    recovery_id: str
    phase: DRPhase
    evidence_class: str
    event_chain_verified: bool
    snapshot_verified: bool
    replay_verified: bool
    invariants_pass: bool
    no_unresolved_critical_issue: bool
    guards_pass: bool
    trading_allowed: bool
    rpo_seconds: float
    rto_seconds: float
    expected_state_hash: str
    recovered_state_hash: str
    expected_event_chain_hash: str
    recovered_event_chain_hash: str
    reason: str

    @property
    def recovery_verified(self) -> bool:
        return (
            self.phase is DRPhase.RECOVERED
            and self.event_chain_verified
            and self.snapshot_verified
            and self.replay_verified
            and self.invariants_pass
            and self.no_unresolved_critical_issue
            and self.guards_pass
            and self.trading_allowed
        )

    def as_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["phase"] = self.phase.value
        data["recovery_verified"] = self.recovery_verified
        return data


class DisasterRecoveryExercise:
    """Deterministic application-level crash/restart/restore drill.

    This proves only application recovery semantics. It does not prove infrastructure DR,
    cross-region durability, production RPO/RTO, or external operational readiness.
    """

    EVIDENCE_CLASS = "INTERNAL_TEST_EVIDENCE"
    SNAPSHOT_FILE = "recovery_snapshot.json"
    STATE_FILE = "expected_state.json"
    DB_FILE = "events.db"

    def __init__(self, *, now_ns: Callable[[], int] | None = None) -> None:
        self._now_ns = now_ns or __import__("time").time_ns

    @staticmethod
    def _sha256(data: bytes) -> str:
        return sha256(data).hexdigest()

    @staticmethod
    def _state_to_json(state: LedgerState) -> dict[str, object]:
        return state_payload(state)

    @staticmethod
    def _state_from_json(payload: dict[str, object]) -> LedgerState:
        from decimal import Decimal
        from trading_platform.v21.ledger import PositionState
        positions = tuple(
            PositionState(
                symbol=str(row["symbol"]),
                quantity=Decimal(str(row["quantity"])),
                avg_entry_price=Decimal(str(row["avg_entry_price"])),
                realized_pnl=Decimal(str(row["realized_pnl"])),
                fees=Decimal(str(row["fees"])),
            )
            for row in payload.get("positions", [])
        )
        return LedgerState(cash=Decimal(str(payload.get("cash", "0"))), positions=positions)

    @staticmethod
    def _latest_event_hash(store: EventStore) -> str:
        latest = None
        for event in store.iter_events():
            latest = event
        return latest.event_hash if latest else "GENESIS"

    def run(
        self,
        *,
        workspace: Path,
        recovery_id: str = "DR72-001",
        backup_id: str = "B372-001",
    ) -> DRResult:
        workspace = workspace.resolve()
        if workspace.exists():
            for child in workspace.iterdir():
                if child.is_dir():
                    for p in sorted(child.rglob("*"), reverse=True):
                        if p.is_file() or p.is_symlink():
                            p.unlink()
                    child.rmdir()
                else:
                    child.unlink()
        workspace.mkdir(parents=True, exist_ok=True)

        live = workspace / "live"
        backup_archive = workspace / "backup.tar.gz"
        restored = workspace / "restored"
        live.mkdir()

        db = live / self.DB_FILE
        store = EventStore(str(db))
        store.append(
            event_id="dr72-e1",
            occurred_at_ms=1_000,
            event_type=EventSourcedLedger.CASH_ADJUSTMENT,
            aggregate_id="ACCOUNT",
            payload={"amount": "1000"},
        )
        checkpoint_ledger = EventSourcedLedger()
        checkpoint_state = checkpoint_ledger.rebuild(store)
        snapshot = RestSnapshot.from_state(
            snapshot_id="snap-1",
            captured_at_ms=1_100,
            last_event_sequence=store.latest_sequence(),
            state=checkpoint_state,
        )

        store.append(
            event_id="dr72-e2",
            occurred_at_ms=1_200,
            event_type=EventSourcedLedger.FILL,
            aggregate_id="BTCUSDT",
            payload={"side": "BUY", "quantity": "0.01", "price": "50000"},
        )
        expected_ledger = EventSourcedLedger()
        expected_state = expected_ledger.rebuild(store)
        expected_state_hash = state_hash(expected_state)
        expected_chain_hash = self._latest_event_hash(store)
        latest_event_time_ns = 2_000_000_000

        (live / self.SNAPSHOT_FILE).write_text(
            json.dumps(
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "captured_at_ms": snapshot.captured_at_ms,
                    "last_event_sequence": snapshot.last_event_sequence,
                    "state": state_payload(snapshot.state),
                    "source_hash": snapshot.source_hash,
                    "evidence_class": self.EVIDENCE_CLASS,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        (live / self.STATE_FILE).write_text(
            json.dumps(
                {"state": self._state_to_json(expected_state), "state_hash": expected_state_hash, "evidence_class": self.EVIDENCE_CLASS},
                sort_keys=True,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )

        service = BackupRestoreService(now_ns=self._now_ns)
        policy = BackupPolicy(
            source_root=live,
            include_prefixes=(self.DB_FILE, self.SNAPSHOT_FILE, self.STATE_FILE),
            destination=backup_archive,
            rpo_seconds=10,
            rto_seconds=10,
        )
        try:
            # Durable cutover boundary: checkpoint WAL and close the live writer before snapshot.
            store._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            store._db.close()
            backup_record = service.create_backup(
                policy=policy,
                latest_event_time_ns=latest_event_time_ns,
                backup_id=backup_id,
            )
        except BackupRestoreError as exc:
            raise DRExerciseError(str(exc)) from exc

        # Disaster declaration: live state is unavailable and must not be used for replay.
        for path in live.iterdir():
            path.unlink()
        live.rmdir()

        phase = DRPhase.DISASTER_DECLARED
        try:
            restored_record, rto = service.restore(archive_path=backup_archive, destination_root=restored)
            phase = DRPhase.RESTORE
        except BackupRestoreError as exc:
            raise DRExerciseError(f"RESTORE_FAILED:{exc}") from exc

        restored_db = restored / self.DB_FILE
        restored_store = EventStore(str(restored_db))
        event_chain_verified = restored_store.verify_chain()
        expected_event_chain_hash = expected_chain_hash
        recovered_event_chain_hash = self._latest_event_hash(restored_store)
        if not event_chain_verified:
            return DRResult(
                recovery_id=recovery_id,
                phase=DRPhase.BLOCKED,
                evidence_class=self.EVIDENCE_CLASS,
                event_chain_verified=False,
                snapshot_verified=False,
                replay_verified=False,
                invariants_pass=False,
                no_unresolved_critical_issue=False,
                guards_pass=False,
                trading_allowed=False,
                rpo_seconds=backup_record.rpo_age_seconds,
                rto_seconds=rto,
                expected_state_hash=expected_state_hash,
                recovered_state_hash="",
                expected_event_chain_hash=expected_event_chain_hash,
                recovered_event_chain_hash=recovered_event_chain_hash,
                reason="EVENT_CHAIN_INVALID",
            )

        raw_snapshot = json.loads((restored / self.SNAPSHOT_FILE).read_text(encoding="utf-8"))
        raw_expected = json.loads((restored / self.STATE_FILE).read_text(encoding="utf-8"))
        recovered_snapshot = RestSnapshot(
            snapshot_id=str(raw_snapshot["snapshot_id"]),
            captured_at_ms=int(raw_snapshot["captured_at_ms"]),
            last_event_sequence=int(raw_snapshot["last_event_sequence"]),
            state=self._state_from_json(dict(raw_snapshot["state"])),
            source_hash=str(raw_snapshot["source_hash"]),
        )
        snapshot_verified = recovered_snapshot.verify() and raw_snapshot.get("evidence_class") == self.EVIDENCE_CLASS
        expected_from_backup = self._state_from_json(dict(raw_expected["state"]))
        if not snapshot_verified:
            return self._blocked(
                recovery_id, backup_record.rpo_age_seconds, rto, expected_state_hash,
                recovered_event_chain_hash, expected_event_chain_hash, "REST_SNAPSHOT_INVALID",
            )

        phase = DRPhase.REPLAY
        coordinator = GapRecoveryCoordinator(restored_store)
        result = coordinator.recover(
            recovery_id=recovery_id,
            snapshot=recovered_snapshot,
            target_state=expected_from_backup,
            require_chain=True,
        )
        replay_verified = result.state is RecoveryState.VERIFIED and result.trading_allowed
        recovered_state_hash = result.state_hash
        if not replay_verified:
            return self._blocked(
                recovery_id, backup_record.rpo_age_seconds, rto, expected_state_hash,
                recovered_event_chain_hash, expected_event_chain_hash, f"RECOVERY_BLOCKED:{result.reason}",
                recovered_state_hash=recovered_state_hash,
                snapshot_verified=snapshot_verified,
                event_chain_verified=event_chain_verified,
            )

        phase = DRPhase.VERIFY
        invariants_pass = recovered_state_hash == expected_state_hash
        no_unresolved_critical_issue = event_chain_verified and snapshot_verified and replay_verified
        guards_pass = invariants_pass and no_unresolved_critical_issue and rto <= 10
        trading_allowed = guards_pass
        final_phase = DRPhase.RECOVERED if trading_allowed else DRPhase.BLOCKED
        reason = "DISASTER_RECOVERY_RESTORE_REPLAY_VERIFIED" if trading_allowed else "RECOVERY_GUARD_FAILED"
        if final_phase is DRPhase.RECOVERED:
            phase = DRPhase.RECOVERED
        return DRResult(
            recovery_id=recovery_id,
            phase=final_phase,
            evidence_class=self.EVIDENCE_CLASS,
            event_chain_verified=event_chain_verified,
            snapshot_verified=snapshot_verified,
            replay_verified=replay_verified,
            invariants_pass=invariants_pass,
            no_unresolved_critical_issue=no_unresolved_critical_issue,
            guards_pass=guards_pass,
            trading_allowed=trading_allowed,
            rpo_seconds=backup_record.rpo_age_seconds,
            rto_seconds=rto,
            expected_state_hash=expected_state_hash,
            recovered_state_hash=recovered_state_hash,
            expected_event_chain_hash=expected_event_chain_hash,
            recovered_event_chain_hash=recovered_event_chain_hash,
            reason=reason,
        )

    @staticmethod
    def _blocked(
        recovery_id: str,
        rpo: float,
        rto: float,
        expected_state_hash: str,
        recovered_event_chain_hash: str,
        expected_event_chain_hash: str,
        reason: str,
        *,
        recovered_state_hash: str = "",
        snapshot_verified: bool = False,
        event_chain_verified: bool = False,
    ) -> DRResult:
        return DRResult(
            recovery_id=recovery_id,
            phase=DRPhase.BLOCKED,
            evidence_class=DisasterRecoveryExercise.EVIDENCE_CLASS,
            event_chain_verified=event_chain_verified,
            snapshot_verified=snapshot_verified,
            replay_verified=False,
            invariants_pass=False,
            no_unresolved_critical_issue=False,
            guards_pass=False,
            trading_allowed=False,
            rpo_seconds=rpo,
            rto_seconds=rto,
            expected_state_hash=expected_state_hash,
            recovered_state_hash=recovered_state_hash,
            expected_event_chain_hash=expected_event_chain_hash,
            recovered_event_chain_hash=recovered_event_chain_hash,
            reason=reason,
        )
