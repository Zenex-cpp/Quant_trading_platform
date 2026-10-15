from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from tests._m13_helpers import green_reconciliation
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m19_helpers import authorize_promotion_bundle
from tests._m18_helpers import authorize_evidence_snapshot
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from tests._m19_helpers import authorize_promotion_bundle
from tests._m18_helpers import authorize_evidence_snapshot
from trading_platform.v326.transition_authority import DeploymentStateTransitionAuthority, StateTransitionAuthorityLedger
from trading_platform.v325.deployment_activation import DeploymentActivationLedger
from trading_platform.v324.recovery_proof import RecoveryProofLedger
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentPhase, DeploymentRequest, DeploymentState, DeploymentAuditChain
from trading_platform.v28.deployment_authority import ActivationCapabilityError
from trading_platform.v328.durable_transition import (
    DurableFinalActivationAuthority,
    DurableTransitionExecutionConflict,
    DurableTransitionExecutionInvalid,
    DurableTransitionExecutionLedger,
)
from tests.v326.test_transition_authority import NOW, approval, bundle, gates, readiness, truth, promotion_fp
from trading_platform.promotion.contracts import ModelRole, ScopeCheck, DeploymentState as RuntimeDeploymentState
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.state.enums import OperationalMode
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger


def setup_case(tmp_path: Path):
    store = EventStore(str(tmp_path / 'ledger.db'))
    proof_ledger = RecoveryProofLedger(store)
    proof = proof_ledger.record(
        proof_id='rp1', recovery_id='recovery-1', valid_from=NOW - timedelta(minutes=1), expires_at=NOW + timedelta(minutes=30),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint='state-1', reconciliation_fingerprint='recon-1', invariants_fingerprint='inv-1', guards_fingerprint='guard-1',
        issued_at_ms=1000, store=store,
    )
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, RuntimeDeploymentState.ACTIVE, 'HEALTHY', True)
    recon = green_reconciliation(store, now=NOW)
    compat = authorize_compatibility(store, bundle())
    integrity = authorize_artifact_integrity(store, bundle())
    promotion_bundle = authorize_promotion_bundle(store, bundle(), now=NOW)
    authorize_evidence_snapshot(store, bundle(), now=NOW)
    activation, _ = DeploymentActivationLedger.authorize(
        deployment_id='D1', bundle=bundle(), approval=approval(), gates=gates(), scope=ScopeCheck(True, 'ok'),
        evidence_valid=True, compatibility_valid=True, artifacts_integrity=True, readiness=readiness(), target_mode=OperationalMode.CANARY,
        proof_ledger=proof_ledger, proof_id=proof.proof_id, current_state_fingerprint='state-1', truth=truth(),
        requested_risk=Decimal('10'), canary_exposure=Decimal('100'), runtime_state=runtime,
        rollout_policy=RolloutPolicy(Decimal('10'), Decimal('100')), operator='operator', decision_id='DDEC1',
        now=NOW, recorded_at_ms=2000, store=store, reconciliation_authorization_id=recon.authorization_id,
        compatibility_authorization_id=compat.authorization_id,
        artifact_integrity_authorization_id=integrity.authorization_id,
        promotion_bundle_authorization_id=promotion_bundle.authorization_id,
    )
    request = DeploymentRequest('D1', bundle(), approval(), gates(), ScopeCheck(True, 'ok'), True, True, True, 'operator', Decimal('10'), Decimal('100'), runtime, compat.authorization_id, integrity.authorization_id, promotion_bundle.authorization_id)
    orch = DeploymentOrchestrator(policy=RolloutPolicy(Decimal('10'), Decimal('100')), dependency_authority=DependencyInvalidationLedger(store))
    state = orch.start_canary(orch.stage(orch.prepare(request, now=NOW, now_ns=1), now_ns=2), now_ns=3)
    state_auth = DeploymentStateTransitionAuthority(
        activation_ledger=DeploymentActivationLedger(store), proof_ledger=proof_ledger, transition_ledger=StateTransitionAuthorityLedger(store)
    )
    ledger = DurableTransitionExecutionLedger(store)
    durable = DurableFinalActivationAuthority(state_auth, ledger)
    return store, proof_ledger, state, orch, durable, ledger, state_auth


def test_executed_event_is_separate_and_restart_replayable(tmp_path: Path):
    store, _, state, orch, durable, ledger, _ = setup_case(tmp_path)
    result = durable.execute(
        state, now=NOW + timedelta(seconds=1), now_ns=4,
        current_state_fingerprint='state-1', current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator='operator', decision_id='TDEC1', transition_id='T1', orchestrator=orch,
    )
    assert result.phase is DeploymentPhase.ACTIVATED
    execution = ledger.get('T1')
    assert execution is not None
    assert execution.target_phase is DeploymentPhase.ACTIVATED
    assert any(e.event_type == 'DEPLOYMENT_STATE_TRANSITION_EXECUTED' for e in store.iter_events())

    restored_ledger = DurableTransitionExecutionLedger(EventStore(str(tmp_path / 'ledger.db')))
    replayed = restored_ledger.restore(state, restored_ledger.get('T1'))
    assert replayed.phase is DeploymentPhase.ACTIVATED
    assert replayed.chain.head_hash == execution.event_hash


def test_retry_after_commit_does_not_require_new_capability(tmp_path: Path):
    store, _, state, orch, durable, ledger, _ = setup_case(tmp_path)
    first = durable.execute(
        state, now=NOW + timedelta(seconds=1), now_ns=4,
        current_state_fingerprint='state-1', current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator='operator', decision_id='TDEC1', transition_id='T1', orchestrator=orch,
    )
    # The persisted EXECUTED record is sufficient for a retry using the original source state.
    before_events = len(tuple(store.iter_events()))
    second = durable.execute(
        state, now=NOW + timedelta(seconds=2), now_ns=5,
        current_state_fingerprint='state-1', current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator='operator', decision_id='TDEC1', transition_id='T1', orchestrator=orch,
    )
    assert second.chain.head_hash == first.chain.head_hash
    assert len(tuple(store.iter_events())) == before_events


def test_chain_binding_blocks_restore_on_wrong_source_state(tmp_path: Path):
    store, _, state, orch, durable, ledger, _ = setup_case(tmp_path)
    durable.execute(
        state, now=NOW + timedelta(seconds=1), now_ns=4,
        current_state_fingerprint='state-1', current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator='operator', decision_id='TDEC1', transition_id='T1', orchestrator=orch,
    )
    execution = ledger.get('T1')
    bad = DeploymentState(state.request, state.phase, state.allocated_risk, DeploymentAuditChain(), state.failure_reason)
    with pytest.raises(DurableTransitionExecutionConflict, match='CHAIN_HEAD'):
        ledger.restore(bad, execution)


def test_corrupted_executed_event_fails_closed(tmp_path: Path):
    store, _, state, orch, durable, ledger, _ = setup_case(tmp_path)
    durable.execute(
        state, now=NOW + timedelta(seconds=1), now_ns=4,
        current_state_fingerprint='state-1', current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator='operator', decision_id='TDEC1', transition_id='T1', orchestrator=orch,
    )
    tamper_event_store(store, 'UPDATE events SET payload_json=? WHERE event_id=?', ('{}', 'deployment-transition:execute:T1'))
    with pytest.raises(DurableTransitionExecutionInvalid, match='EVENT_CHAIN'):
        ledger.get('T1')


def test_crash_after_execution_event_is_replayable(monkeypatch, tmp_path: Path):
    store, _, state, orch, durable, ledger, _ = setup_case(tmp_path)
    original = __import__("trading_platform.v328.durable_transition", fromlist=["consume_activation_capability"]).consume_activation_capability

    def crash_after_durable_commit(_capability):
        raise RuntimeError("SIMULATED_POST_COMMIT_CRASH")

    monkeypatch.setattr("trading_platform.v328.durable_transition.consume_activation_capability", crash_after_durable_commit)
    with pytest.raises(RuntimeError, match="SIMULATED_POST_COMMIT_CRASH"):
        durable.execute(
            state, now=NOW + timedelta(seconds=1), now_ns=4,
            current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
            current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
            operator="operator", decision_id="TDEC1", transition_id="T1", orchestrator=orch,
        )
    assert ledger.get("T1") is not None

    monkeypatch.setattr("trading_platform.v328.durable_transition.consume_activation_capability", original)
    replayed = durable.execute(
        state, now=NOW + timedelta(seconds=2), now_ns=5,
        current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(),
        operator="operator", decision_id="TDEC1", transition_id="T1", orchestrator=orch,
    )
    assert replayed.phase is DeploymentPhase.ACTIVATED


def test_executed_event_requires_existing_authorization(tmp_path: Path):
    store, _, state, orch, durable, ledger, _ = setup_case(tmp_path)
    # Constructing a record manually cannot bypass the V3.26 authorization event.
    auth = durable.authority.authorize_final_activation(
        state, now=NOW, now_ns=4, current_state_fingerprint="state-1", current_truth_hash=truth().state_hash,
        current_promotion_fingerprint=promotion_fp(), current_approval=approval(), operator="operator", decision_id="TDEC1", transition_id="T1",
    )
    tamper_event_store(store, "DELETE FROM events WHERE event_id=?", ("deployment-transition:authorize:T1",))
    event = __import__("trading_platform.v28.deployment", fromlist=["DeploymentEvent"]).DeploymentEvent.build(
        sequence=1, event_type=__import__("trading_platform.v28.deployment", fromlist=["DeploymentEventType"]).DeploymentEventType.ACTIVATE,
        deployment_id="D1", actor="operator", from_phase=DeploymentPhase.CANARY, to_phase=DeploymentPhase.ACTIVATED,
        risk_before=Decimal("10"), risk_after=Decimal("10"), reason="ACTIVATED_AFTER_CANARY", timestamp_ns=4, previous_hash=state.chain.head_hash,
    )
    from trading_platform.v328.durable_transition import TransitionExecutionRecord
    record = TransitionExecutionRecord(
        transition_id="T1", deployment_id="D1", authorization_fingerprint=auth.fingerprint, source_phase=DeploymentPhase.CANARY,
        target_phase=DeploymentPhase.ACTIVATED, source_chain_head=state.chain.head_hash, event_sequence=1, event_type=event.event_type,
        actor="operator", risk_before=Decimal("10"), risk_after=Decimal("10"), reason=event.reason, timestamp_ns=4, event_hash=event.event_hash, committed_at_ms=4,
    )
    with pytest.raises(DurableTransitionExecutionInvalid, match="AUTHORIZATION_NOT_FOUND"):
        ledger.record(record)
