from __future__ import annotations

from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v406.gate_revalidation import GateDispositionV406, GateRevalidationAuthorityV406
from trading_platform.evidence.graph import EvidenceDependencyGraph, EvidenceGraphNode, Evidence, EvidenceState


def _gate(run_id: str = "run-1") -> Gate:
    return Gate(
        gate_id="gate-1", candidate_version="candidate-1", run_id=run_id,
        input_versions=("witness-1",), checks=("CHECK",), result=GateResult.PASS,
        required_artifacts=("artifact-1",), evidence_refs=("evidence-1",),
        owner="owner", reviewer="reviewer", timestamp="2026-10-07T00:00:00Z",
        expiration=None, revalidation_condition="DEPENDENCIES_UNCHANGED",
    )


def _impact(ledger: DependencyInvalidationLedger) -> None:
    graph = EvidenceDependencyGraph([
        EvidenceGraphNode("witness-1", "WITNESS", "1", ()),
        EvidenceGraphNode("evidence-1", "EVIDENCE", "1", ("witness-1",)),
        EvidenceGraphNode("artifact-1", "ARTIFACT", "1", ("evidence-1",)),
        EvidenceGraphNode("gate-1", "GATE", "1", ("artifact-1",)),
    ])
    evidence = {
        "evidence-1": Evidence(
            "evidence-1", "READINESS", EvidenceState.VALID, "1", "2026-10-07T00:00:00Z",
            (), ("witness-1",), "m1", {"environment": "PRODUCTION"}, (None, None), "a" * 64, "owner"
        )
    }
    return ledger.invalidate(
        incident_id="incident-1", changed_dependency="witness-1", graph=graph,
        evidence_index=evidence, gate_dependencies={"gate-1": ("artifact-1",)},
        candidates={"candidate-1": ("gate-1",)}, promotions={"promotion-1": ("candidate-1",)},
        reason="TEST_REVOCATION", recorded_at_ms=20,
    )


def test_gate_is_current_before_invalidation():
    store = EventStore()
    authority = GateRevalidationAuthorityV406(store=store)
    decision = authority.evaluate(gate=_gate(), dependency_checkpoint=store.latest_sequence(), now_ms=10)
    assert decision.allowed
    assert decision.disposition is GateDispositionV406.CURRENT
    assert store.verify_chain()


def test_gate_is_invalidated_after_dependency_change():
    store = EventStore()
    ledger = DependencyInvalidationLedger(store)
    authority = GateRevalidationAuthorityV406(store=store, dependency_authority=ledger)
    checkpoint = store.latest_sequence()
    _impact(ledger)
    decision = authority.evaluate(gate=_gate(), dependency_checkpoint=checkpoint, now_ms=30)
    assert not decision.allowed
    assert decision.disposition is GateDispositionV406.INVALIDATED
    assert "DEPENDENCY_INVALIDATION" in decision.reason


def test_revalidation_does_not_resurrect_old_gate():
    store = EventStore()
    ledger = DependencyInvalidationLedger(store)
    authority = GateRevalidationAuthorityV406(store=store, dependency_authority=ledger)
    checkpoint = store.latest_sequence()
    record, _ = _impact(ledger)
    ledger.revalidate(
        incident_id=record.incident_id, revalidation_id="reval-1", validation_fingerprint=record.fingerprint,
        evidence_refs=("evidence-1",), gate_refs=("gate-1",), reviewer="reviewer", validated_at_ms=30,
    )
    # The exact old checkpoint must still fail closed for the old gate.
    decision = authority.evaluate(gate=_gate(), dependency_checkpoint=checkpoint, now_ms=40)
    assert not decision.allowed
    assert decision.disposition is GateDispositionV406.INVALIDATED


def test_fresh_gate_checkpoint_is_reusable_after_revalidation():
    store = EventStore()
    ledger = DependencyInvalidationLedger(store)
    authority = GateRevalidationAuthorityV406(store=store, dependency_authority=ledger)
    record, _ = _impact(ledger)
    ledger.revalidate(
        incident_id=record.incident_id, revalidation_id="reval-1", validation_fingerprint=record.fingerprint,
        evidence_refs=("evidence-1",), gate_refs=("gate-1",), reviewer="reviewer", validated_at_ms=30,
    )
    checkpoint = store.latest_sequence()
    decision = authority.evaluate(gate=_gate("run-2"), dependency_checkpoint=checkpoint, now_ms=40)
    assert decision.allowed
    assert decision.disposition is GateDispositionV406.CURRENT


def test_decision_is_idempotent():
    store = EventStore()
    authority = GateRevalidationAuthorityV406(store=store)
    gate = _gate()
    checkpoint = store.latest_sequence()
    first = authority.evaluate(gate=gate, dependency_checkpoint=checkpoint, now_ms=10)
    second = authority.evaluate(gate=gate, dependency_checkpoint=checkpoint, now_ms=10)
    assert first == second
    assert len([e for e in store.iter_events() if e.event_type == authority.DECISION_EVENT]) == 1
