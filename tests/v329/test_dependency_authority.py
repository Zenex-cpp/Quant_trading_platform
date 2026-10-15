from __future__ import annotations

from pathlib import Path

import pytest

from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph, EvidenceGraphNode, EvidenceState
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from tests._m14_helpers import authorize_compatibility
from tests._m15_helpers import authorize_artifact_integrity
from trading_platform.promotion.contracts import DeploymentState
from trading_platform.v329.dependency_authority import (
    DependencyInvalidationBlocked,
    DependencyInvalidationConflict,
    DependencyInvalidationLedger,
    DependencyRevalidationConflict,
    InvalidationState,
)


def graph() -> EvidenceDependencyGraph:
    g = EvidenceDependencyGraph()
    for node in (
        EvidenceGraphNode("D", "DATASET", "1", ()),
        EvidenceGraphNode("F", "FEATURE", "1", ("D",)),
        EvidenceGraphNode("X", "EXPERIMENT", "1", ("F",)),
        EvidenceGraphNode("M", "MODEL", "1", ("X",)),
        EvidenceGraphNode("S", "STRATEGY", "1", ("M",)),
    ):
        g.add(node)
    return g


def evidence_index() -> dict[str, Evidence]:
    return {
        "EV-M": Evidence(
            "EV-M", "MODEL", EvidenceState.VALID, "1", "2026-09-23T00:00:00+00:00",
            ("M",), ("M",), "meth-1", {"instrument": "BTCUSDT"}, (None, None), "h-m", "research",
        ),
        "EV-S": Evidence(
            "EV-S", "STRATEGY", EvidenceState.VALID, "1", "2026-09-23T00:00:00+00:00",
            ("S",), ("S",), "meth-1", {"instrument": "BTCUSDT"}, (None, None), "h-s", "research",
        ),
    }


def test_dependency_change_is_durable_and_idempotent(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    ledger = DependencyInvalidationLedger(store)
    kwargs = dict(
        incident_id="INC-1",
        changed_dependency="D",
        graph=graph(),
        evidence_index=evidence_index(),
        gate_dependencies={"G1": ("M",), "G2": ("S",)},
        candidates={"C1": ("G1",)},
        promotions={"P1": ("C1",)},
        reason="DATASET_CORRUPTION",
        recorded_at_ms=1000,
    )
    first, created = ledger.invalidate(**kwargs)
    second, duplicate = ledger.invalidate(**kwargs)
    assert created is True
    assert duplicate is False
    assert first.fingerprint == second.fingerprint
    assert ledger.get("INC-1").state is InvalidationState.ACTIVE
    with pytest.raises(DependencyInvalidationBlocked):
        ledger.assert_clear(("G1",))
    assert ledger.store.verify_chain()


def test_active_blast_radius_blocks_gate_evidence_candidate_and_promotion(tmp_path: Path):
    ledger = DependencyInvalidationLedger(EventStore(str(tmp_path / "events.db")))
    ledger.invalidate(
        incident_id="INC-2", changed_dependency="D", graph=graph(),
        evidence_index=evidence_index(), gate_dependencies={"G1": ("M",)},
        candidates={"C1": ("G1",)}, promotions={"P1": ("C1",)},
        reason="HOLDOUT_CONTAMINATION", recorded_at_ms=1001,
    )
    assert ledger.blocked_dependencies(("EV-M", "G1", "C1", "P1")) == ("C1", "EV-M", "G1", "P1")
    with pytest.raises(DependencyInvalidationBlocked):
        ledger.assert_evidence_usable("EV-M")
    with pytest.raises(DependencyInvalidationBlocked):
        ledger.assert_gate_reusable("G1")
    with pytest.raises(DependencyInvalidationBlocked):
        ledger.assert_promotion_usable("P1")


def test_revalidation_closes_incident_and_is_durable(tmp_path: Path):
    path = tmp_path / "events.db"
    store = EventStore(str(path))
    ledger = DependencyInvalidationLedger(store)
    ledger.invalidate(
        incident_id="INC-3", changed_dependency="D", graph=graph(),
        evidence_index=evidence_index(), gate_dependencies={"G1": ("M",)},
        candidates={"C1": ("G1",)}, promotions={"P1": ("C1",)},
        reason="BACKTEST_BUG", recorded_at_ms=1002,
    )
    with pytest.raises(DependencyInvalidationBlocked):
        ledger.assert_clear(("P1",))
    record, created = ledger.revalidate(
        incident_id="INC-3", revalidation_id="REV-3", validation_fingerprint="NEW-SNAPSHOT",
        evidence_refs=("EV-M",), gate_refs=("G1",), reviewer="reviewer", validated_at_ms=1003,
    )
    assert created is True
    assert record.state is InvalidationState.REVALIDATED
    assert ledger.get("INC-3").state is InvalidationState.REVALIDATED
    ledger.assert_clear(("EV-M", "G1", "C1", "P1"))

    restored = DependencyInvalidationLedger(EventStore(str(path)))
    assert restored.get("INC-3").state is InvalidationState.REVALIDATED
    restored.assert_clear(("P1",))


def test_revalidation_requires_existing_incident(tmp_path: Path):
    ledger = DependencyInvalidationLedger(EventStore(str(tmp_path / "events.db")))
    with pytest.raises(DependencyRevalidationConflict) as exc_info:
        ledger.revalidate(
            incident_id="MISSING", revalidation_id="REV-1", validation_fingerprint="X",
            evidence_refs=(), gate_refs=(), reviewer="reviewer", validated_at_ms=1,
        )
    assert str(exc_info.value) == "INVALIDATION_NOT_FOUND"


def test_conflicting_idempotent_invalidation_is_blocked(tmp_path: Path):
    ledger = DependencyInvalidationLedger(EventStore(str(tmp_path / "events.db")))
    base = dict(
        incident_id="INC-4", changed_dependency="D", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={"G1": ("M",)}, candidates={}, promotions={},
        reason="DATASET_CORRUPTION", recorded_at_ms=1004,
    )
    ledger.invalidate(**base)
    with pytest.raises(DependencyInvalidationConflict, match="INVALIDATION_ID_CONFLICT"):
        ledger.invalidate(**{**base, "reason": "DIFFERENT_ROOT_CAUSE"})


def test_corrupted_invalidation_chain_fails_closed(tmp_path: Path):
    store = EventStore(str(tmp_path / "events.db"))
    ledger = DependencyInvalidationLedger(store)
    ledger.invalidate(
        incident_id="INC-5", changed_dependency="D", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={}, candidates={}, promotions={}, reason="CORRUPTION", recorded_at_ms=1005,
    )
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ("{}", "evidence-invalidation:INC-5"))
    with pytest.raises(Exception, match="EVENT_CHAIN_INVALID"):
        ledger.active_incidents()


def test_final_deployment_activation_blocks_active_dependency_invalidation(tmp_path: Path):
    from datetime import datetime, timedelta, timezone
    from decimal import Decimal
    from trading_platform.operations.readiness import OperationalReadiness
    from trading_platform.promotion.contracts import Approval, GateSummary, ModelRole, PromotionBundle, ScopeCheck
    from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
    from trading_platform.state.enums import OperationalMode
    from trading_platform.v324.recovery_proof import RecoveryProofLedger
    from trading_platform.v325.deployment_activation import DeploymentActivationLedger, ActivationInvalid
    from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth

    now = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)
    store = EventStore(str(tmp_path / "activation.db"))
    rp = RecoveryProofLedger(store)
    proof = rp.record(
        proof_id="rp1", recovery_id="r1", valid_from=now - timedelta(minutes=1), expires_at=now + timedelta(minutes=30),
        state_reconciled=True, invariants_pass=True, no_unresolved_critical_issue=True, guards_pass=True,
        state_fingerprint="state-1", reconciliation_fingerprint="recon", invariants_fingerprint="inv", guards_fingerprint="guard",
        issued_at_ms=1, store=store,
    )
    bundle = PromotionBundle("B1", "S1", "M1", "F1", "T1", "C1", "E1", "CODE1", "SNAP1", ("G1",), ("H1",), "A1", {"mode":"CANARY"}, "RB", "HASH", now)
    approval = Approval("A1", ("operator",), now - timedelta(minutes=2), now + timedelta(minutes=30), {})
    gates = GateSummary(("G1",), ("G1",), ())
    truth = build_truth(
        observed_at_ns=1,
        axes=AxisSnapshot("APPROVED", "CANARY", "HEALTHY", "APPROVED", "ACTIVE", "CHALLENGER"),
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger")),
        requested_risk=Decimal("10"), caps={k:Decimal("100") for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")},
    )
    inv = DependencyInvalidationLedger(store)
    compat = authorize_compatibility(store, bundle, authorization_id="COMPAT-INVALID")
    integrity = authorize_artifact_integrity(store, bundle, authorization_id="INTEGRITY-INVALID")
    inv.invalidate(
        incident_id="INC-LIVE", changed_dependency="D", graph=graph(), evidence_index=evidence_index(),
        gate_dependencies={"G1": ("M",)}, candidates={"C1": ("G1",)}, promotions={"B1": ("C1",)},
        reason="HOLDOUT_CONTAMINATION", recorded_at_ms=2,
    )
    with pytest.raises(ActivationInvalid, match="DEPENDENCY_INVALIDATION_BLOCKED"):
        DeploymentActivationLedger.authorize(
            deployment_id="D-INVALID", bundle=bundle, approval=approval, gates=gates, scope=ScopeCheck(True, "ok"),
            evidence_valid=True, compatibility_valid=True, artifacts_integrity=True,
            readiness=OperationalReadiness(*([True] * 19)), target_mode=OperationalMode.CANARY, proof_ledger=rp, proof_id=proof.proof_id,
            current_state_fingerprint="state-1", truth=truth, requested_risk=Decimal("10"), canary_exposure=Decimal("10"),
            runtime_state=RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True),
            rollout_policy=RolloutPolicy(Decimal("10"), Decimal("100")), operator="operator", decision_id="DEC", now=now,
            recorded_at_ms=3, store=store, compatibility_authorization_id=compat.authorization_id,
            artifact_integrity_authorization_id=integrity.authorization_id,
        )
