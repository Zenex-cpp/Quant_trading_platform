from datetime import datetime, timezone
import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v333 import (
    CausalArtifactState,
    CausalArtifactType,
    CausalTTLAuthorityLedger,
    CausalTTLConflict,
)

BASE = int(datetime(2026, 9, 23, tzinfo=timezone.utc).timestamp() * 1000)
EX = BASE + 60_000


def build_chain(ledger: CausalTTLAuthorityLedger, *, intent_expires=EX, upstream_expires=None, state_overrides=None):
    upstream_expires = upstream_expires or EX
    state_overrides = state_overrides or {}
    ids = {
        "prediction": "PRED-333",
        "signal": "SIG-333",
        "opportunity": "OPP-333",
        "portfolio": "PORT-333",
        "risk": "RISK-333",
        "intent": "INTENT-333",
    }
    ledger.record_artifact(artifact_id=ids["prediction"], artifact_type=CausalArtifactType.PREDICTION,
                           version="v1", state=state_overrides.get("prediction", CausalArtifactState.VALID),
                           valid_from_ms=BASE, expires_at_ms=upstream_expires, recorded_at_ms=BASE)
    ledger.record_artifact(artifact_id=ids["signal"], artifact_type=CausalArtifactType.SIGNAL,
                           version="v1", state=state_overrides.get("signal", CausalArtifactState.VALID),
                           valid_from_ms=BASE, expires_at_ms=upstream_expires, dependencies=(ids["prediction"],), recorded_at_ms=BASE)
    ledger.record_artifact(artifact_id=ids["opportunity"], artifact_type=CausalArtifactType.OPPORTUNITY,
                           version="v1", state=state_overrides.get("opportunity", CausalArtifactState.VALID),
                           valid_from_ms=BASE, expires_at_ms=upstream_expires, dependencies=(ids["signal"],), recorded_at_ms=BASE)
    ledger.record_artifact(artifact_id=ids["portfolio"], artifact_type=CausalArtifactType.PORTFOLIO_DECISION,
                           version="v1", state=state_overrides.get("portfolio", CausalArtifactState.ACTIVE),
                           valid_from_ms=BASE, expires_at_ms=upstream_expires, dependencies=(ids["opportunity"],), recorded_at_ms=BASE)
    ledger.record_artifact(artifact_id=ids["risk"], artifact_type=CausalArtifactType.RISK_DECISION,
                           version="v1", state=state_overrides.get("risk", CausalArtifactState.APPROVED),
                           valid_from_ms=BASE, expires_at_ms=upstream_expires, dependencies=(ids["portfolio"],), recorded_at_ms=BASE)
    ledger.record_artifact(artifact_id=ids["intent"], artifact_type=CausalArtifactType.ORDER_INTENT,
                           version="v1", state=state_overrides.get("intent", CausalArtifactState.ACTIVE),
                           valid_from_ms=BASE, expires_at_ms=intent_expires, dependencies=(ids["risk"],), recorded_at_ms=BASE)
    return ids


def test_complete_chain_authorizes():
    ledger = CausalTTLAuthorityLedger()
    ids = build_chain(ledger)
    root = ledger.assert_intent_chain_valid(intent_id=ids["intent"], now_ms=BASE + 10_000, expected_valid_from_ms=BASE, expected_expires_at_ms=EX)
    assert root.artifact_type is CausalArtifactType.ORDER_INTENT


def test_downstream_cannot_be_recorded_beyond_expired_prediction():
    ledger = CausalTTLAuthorityLedger()
    ledger.record_artifact(artifact_id="PRED-333", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                           valid_from_ms=BASE, expires_at_ms=BASE + 5_000, recorded_at_ms=BASE)
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_UPSTREAM_EXPIRED|CAUSAL_TTL_DOWNSTREAM_OUTLIVES_UPSTREAM"):
        ledger.record_artifact(artifact_id="SIG-333", artifact_type=CausalArtifactType.SIGNAL, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=BASE + 10_000, dependencies=("PRED-333",), recorded_at_ms=BASE)


def test_invalidated_middle_artifact_blocks_downstream_record():
    ledger = CausalTTLAuthorityLedger()
    ledger.record_artifact(artifact_id="PRED-333", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                           valid_from_ms=BASE, expires_at_ms=EX, recorded_at_ms=BASE)
    ledger.record_artifact(artifact_id="SIG-333", artifact_type=CausalArtifactType.SIGNAL, version="v1", state=CausalArtifactState.INVALIDATED,
                           valid_from_ms=BASE, expires_at_ms=EX, dependencies=("PRED-333",), recorded_at_ms=BASE)
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_UPSTREAM_INVALID:SIG-333"):
        ledger.record_artifact(artifact_id="OPP-333", artifact_type=CausalArtifactType.OPPORTUNITY, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=EX, dependencies=("SIG-333",), recorded_at_ms=BASE)


def test_downstream_cannot_outlive_upstream():
    ledger = CausalTTLAuthorityLedger()
    ledger.record_artifact(artifact_id="P", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                           valid_from_ms=BASE, expires_at_ms=BASE + 5_000, recorded_at_ms=BASE)
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_DOWNSTREAM_OUTLIVES_UPSTREAM"):
        ledger.record_artifact(artifact_id="S", artifact_type=CausalArtifactType.SIGNAL, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=BASE + 10_000, dependencies=("P",), recorded_at_ms=BASE)


def test_missing_dependency_blocks_record():
    ledger = CausalTTLAuthorityLedger()
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_UPSTREAM_NOT_FOUND"):
        ledger.record_artifact(artifact_id="S", artifact_type=CausalArtifactType.SIGNAL, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=EX, dependencies=("MISSING",), recorded_at_ms=BASE)


def test_wrong_dependency_type_blocks_record():
    ledger = CausalTTLAuthorityLedger()
    ledger.record_artifact(artifact_id="X", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                           valid_from_ms=BASE, expires_at_ms=EX, recorded_at_ms=BASE)
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_REQUIRED_DEPENDENCY_TYPE_MISSING"):
        ledger.record_artifact(artifact_id="R", artifact_type=CausalArtifactType.RISK_DECISION, version="v1", state=CausalArtifactState.APPROVED,
                               valid_from_ms=BASE, expires_at_ms=EX, dependencies=("X",), recorded_at_ms=BASE)


def test_root_prediction_rejects_dependencies():
    ledger = CausalTTLAuthorityLedger()
    with pytest.raises(ValueError, match="CAUSAL_TTL_ROOT_DEPENDENCY_NOT_ALLOWED"):
        ledger.record_artifact(artifact_id="P", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=EX, dependencies=("X",), recorded_at_ms=BASE)


def test_restart_reconstructs_chain():
    store = EventStore()
    ledger = CausalTTLAuthorityLedger(store)
    ids = build_chain(ledger)
    restored = CausalTTLAuthorityLedger(store)
    assert restored.assert_intent_chain_valid(intent_id=ids["intent"], now_ms=BASE + 1_000).artifact_id == ids["intent"]


def test_corrupted_chain_fails_closed():
    store = EventStore()
    ledger = CausalTTLAuthorityLedger(store)
    ids = build_chain(ledger)
    tamper_event_store(store, "UPDATE events SET event_hash='corrupted' WHERE sequence=1")
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_EVENT_CHAIN_INVALID"):
        ledger.assert_intent_chain_valid(intent_id=ids["intent"], now_ms=BASE + 1_000)


def test_duplicate_artifact_id_is_idempotent():
    store = EventStore()
    ledger = CausalTTLAuthorityLedger(store)
    a = ledger.record_artifact(artifact_id="P", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=EX, recorded_at_ms=BASE)
    b = ledger.record_artifact(artifact_id="P", artifact_type=CausalArtifactType.PREDICTION, version="v1", state=CausalArtifactState.VALID,
                               valid_from_ms=BASE, expires_at_ms=EX, recorded_at_ms=BASE)
    assert a.fingerprint == b.fingerprint
    assert store.latest_sequence() == 1


def test_intent_window_mismatch_blocks():
    ledger = CausalTTLAuthorityLedger()
    ids = build_chain(ledger)
    with pytest.raises(CausalTTLConflict, match="CAUSAL_TTL_INTENT_EXPIRES_AT_MISMATCH"):
        ledger.assert_intent_chain_valid(intent_id=ids["intent"], now_ms=BASE + 1_000, expected_valid_from_ms=BASE, expected_expires_at_ms=EX + 1)
