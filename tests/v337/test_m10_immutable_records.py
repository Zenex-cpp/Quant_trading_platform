import sqlite3

import pytest

from trading_platform.v17.evidence import DurableEvidenceStore, EvidenceArtifact
from trading_platform.v21.event_store import EventStore
from trading_platform.v22.checkpoint import CheckpointStore
from trading_platform.v337.immutable_records import ImmutableRecordAuthority, ImmutableRecordError
from trading_platform.v21.ledger import LedgerState
from decimal import Decimal
from pathlib import Path


def test_immutable_authority_never_updates_in_place_and_requires_audit():
    a = ImmutableRecordAuthority()
    first = a.create(record_id="r-v1", payload={"value": 1}, audit_id="audit-1", created_at_ms=1)
    second = a.supersede(
        previous_record_id="r-v1",
        new_record_id="r-v2",
        payload={"value": 2},
        audit_id="audit-2",
        created_at_ms=2,
    )
    assert first.version == 1
    assert second.version == 2
    assert second.supersedes_record_id == first.record_id
    assert a.assert_chain_valid("r-v2").payload == {"value": 2}
    assert a.store.get("immutable:audit:audit-2") is not None


def test_same_record_update_is_rejected():
    a = ImmutableRecordAuthority()
    a.create(record_id="r-v1", payload={"value": 1}, audit_id="audit-1", created_at_ms=1)
    with pytest.raises(ImmutableRecordError, match="IMMUTABLE_RECORD_UPDATE_FORBIDDEN"):
        a.supersede(
            previous_record_id="r-v1",
            new_record_id="r-v1",
            payload={"value": 2},
            audit_id="audit-2",
            created_at_ms=2,
        )


def test_event_store_blocks_raw_update_and_delete():
    store = EventStore()
    store.append(event_id="e1", occurred_at_ms=1, event_type="T", aggregate_id="a", payload={"x": 1})
    with pytest.raises(sqlite3.DatabaseError, match="IMMUTABLE_RECORD_UPDATE_FORBIDDEN"):
        store._db.execute("UPDATE events SET payload_json=? WHERE event_id='e1'", ('{}',))
    store._db.rollback()
    with pytest.raises(sqlite3.DatabaseError, match="IMMUTABLE_RECORD_DELETE_FORBIDDEN"):
        store._db.execute("DELETE FROM events WHERE event_id='e1'")
    store._db.rollback()
    assert store.verify_chain()


def test_checkpoint_blocks_raw_update(tmp_path: Path):
    store = EventStore(str(tmp_path / "ledger.db"))
    cp = CheckpointStore(store)
    state = LedgerState(Decimal("10"), (), ())
    cp.create("cp-1", state, event_sequence=0, created_at_ms=1)
    with pytest.raises(sqlite3.DatabaseError, match="IMMUTABLE_RECORD_UPDATE_FORBIDDEN"):
        store._db.execute("UPDATE checkpoints SET state_hash='x' WHERE checkpoint_id='cp-1'")
    store._db.rollback()
    assert cp.get("cp-1") is not None


def test_evidence_blocks_raw_update(tmp_path: Path):
    store = DurableEvidenceStore(tmp_path / "evidence.db")
    art = EvidenceArtifact(
        evidence_id="ev-1", scenario_id="s", status="PASS", environment="TESTNET",
        started_at="1", completed_at="2", correlation_id="c", operator_id="o", endpoint="e",
        request_hash=None, response_hash=None, pre_snapshot_hash=None, post_snapshot_hash=None,
        reconciliation="GREEN", observations=(), references=()
    )
    store.append(art)
    with sqlite3.connect(store.path) as db:
        with pytest.raises(sqlite3.DatabaseError, match="IMMUTABLE_RECORD_UPDATE_FORBIDDEN"):
            db.execute("UPDATE evidence SET status='TAMPERED' WHERE evidence_id='ev-1'")


def test_supersede_is_atomic_when_audit_id_collides():
    a = ImmutableRecordAuthority()
    a.create(record_id="r-v1", payload={"value": 1}, audit_id="audit-1", created_at_ms=1)
    a.store.append(
        event_id="immutable:audit:audit-2",
        occurred_at_ms=2,
        event_type="OTHER_AUDIT",
        aggregate_id="other",
        payload={"x": 1},
    )
    with pytest.raises(RuntimeError, match="EVENT_APPEND_PARTIAL_BATCH"):
        a.supersede(
            previous_record_id="r-v1",
            new_record_id="r-v2",
            payload={"value": 2},
            audit_id="audit-2",
            created_at_ms=3,
        )
    assert a.get("r-v2") is None
