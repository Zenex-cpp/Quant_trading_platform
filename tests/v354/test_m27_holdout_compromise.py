from __future__ import annotations
from datetime import datetime, timezone, timedelta
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.data.holdout import HoldoutAccessContext, HoldoutPolicy, Workflow, HoldoutVault, HoldoutCapabilityInvalid
from trading_platform.v329.dependency_authority import DependencyInvalidationBlocked
from trading_platform.v354.holdout_compromise import HoldoutCompromiseAuthorityBlocked
from trading_platform.evidence.graph import Evidence, EvidenceDependencyGraph, EvidenceState

NOW_MS = 1_000


def ctx(store: EventStore) -> HoldoutAccessContext:
    return HoldoutAccessContext.build(
        store=store,
        graph=EvidenceDependencyGraph(),
        evidence_index={
            "EV-OLD": Evidence(
                "EV-OLD", "RESEARCH", EvidenceState.VALID, "1", "2026-09-25",
                ("H1",), ("H1",), "M", {}, (None, None), "HASH-OLD", "research",
            )
        },
        gate_dependencies={"G1": ("EV-OLD",)},
        candidates={"C1": ("G1",)},
        promotions={"P1": ("C1",)},
    )


def test_improper_holdout_access_compromises_holdout_and_invalidates_dependents():
    store = EventStore(); context = ctx(store); policy = HoldoutPolicy("H1", holdout_version="1", content_hash="HASH-H1")
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_ACCESS_FORBIDDEN"):
        policy.authorize(Workflow.TUNING, context=context, access_id="A1", actor="research", attempted_at_ms=NOW_MS)
    assert context.compromise_authority.get_compromise("H1") is not None
    with pytest.raises(DependencyInvalidationBlocked, match="DEPENDENCY_INVALIDATION_ACTIVE"):
        context.dependency_ledger.assert_evidence_usable("EV-OLD")
    rec = context.dependency_ledger.get("holdout-access-violation:A1")
    assert rec is not None
    assert "EV-OLD" in rec.invalidated_evidence
    assert store.get("holdout-evidence-invalidated:holdout-access-violation:A1:EV-OLD") is not None


def test_preissued_capability_cannot_open_after_compromise():
    store = EventStore(); context = ctx(store)
    policy = HoldoutPolicy("H1", holdout_version="1", content_hash="HASH-H1")
    cap = policy.issue_capability(Workflow.FINAL_EVALUATION, context=context, capability_id="C1", actor="validator", issued_at_ms=10, ttl_ms=10_000)
    vault = HoldoutVault(holdout_id="H1", rows=(1, 2), context=context, policy=policy)
    with pytest.raises(PermissionError):
        policy.authorize(Workflow.TUNING, context=context, access_id="A2", actor="research", attempted_at_ms=NOW_MS)
    with pytest.raises(HoldoutCapabilityInvalid, match="FINAL_HOLDOUT_COMPROMISED"):
        vault.open(capability=cap, actor="validator", now_ms=20)


def test_compromised_holdout_cannot_issue_new_capability():
    store = EventStore(); context = ctx(store); policy = HoldoutPolicy("H1", holdout_version="1", content_hash="HASH-H1")
    with pytest.raises(PermissionError):
        policy.authorize(Workflow.TUNING, context=context, access_id="A3", actor="research", attempted_at_ms=NOW_MS)
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_COMPROMISED"):
        policy.issue_capability(Workflow.FINAL_EVALUATION, context=context, capability_id="C3", actor="validator", issued_at_ms=20)


def test_replacement_holdout_requires_durable_registration():
    store = EventStore(); context = ctx(store); old = HoldoutPolicy("H1", holdout_version="1", content_hash="HASH-H1")
    with pytest.raises(PermissionError):
        old.authorize(Workflow.TUNING, context=context, access_id="A4", actor="research", attempted_at_ms=NOW_MS)
    new = HoldoutPolicy("H2", holdout_version="2", content_hash="HASH-H2", replacement_of="H1")
    with pytest.raises(PermissionError, match="HOLDOUT_REPLACEMENT_NOT_REGISTERED"):
        new.issue_capability(Workflow.FINAL_EVALUATION, context=context, capability_id="C4", actor="validator", issued_at_ms=20)
    context.compromise_authority.register_replacement(
        replacement_id="R1", compromised_holdout_id="H1", new_holdout_id="H2",
        new_holdout_version="2", new_content_hash="HASH-H2", reviewer="reviewer",
        registered_at_ms=30, dependency_authority=context.dependency_ledger,
    )
    cap = new.issue_capability(Workflow.FINAL_EVALUATION, context=context, capability_id="C5", actor="validator", issued_at_ms=40)
    assert cap.holdout_id == "H2"


def test_revalidation_after_holdout_compromise_requires_new_evidence():
    store = EventStore(); context = ctx(store); old = HoldoutPolicy("H1", holdout_version="1", content_hash="HASH-H1")
    with pytest.raises(PermissionError):
        old.authorize(Workflow.TUNING, context=context, access_id="A5", actor="research", attempted_at_ms=NOW_MS)
    replacement = context.compromise_authority.register_replacement(
        replacement_id="R2", compromised_holdout_id="H1", new_holdout_id="H2", new_holdout_version="2",
        new_content_hash="HASH-H2", reviewer="reviewer", registered_at_ms=30, dependency_authority=context.dependency_ledger,
    )
    with pytest.raises(Exception, match="REVALIDATION_REQUIRES_NEW_EVIDENCE"):
        context.compromise_authority.revalidate_after_replacement(
            incident_id="holdout-access-violation:A5", revalidation_id="REV-1", validation_fingerprint="FP",
            replacement=replacement, new_evidence_refs=("EV-OLD",), new_gate_refs=("G1",), reviewer="reviewer",
            validated_at_ms=50, dependency_authority=context.dependency_ledger,
        )
    assert context.dependency_ledger.get("holdout-access-violation:A5").state.value == "ACTIVE"


def test_old_evidence_never_becomes_snapshot_input_after_holdout_recovery(tmp_path):
    from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger, EvidenceSnapshotAuthorityInvalid
    from trading_platform.evidence.snapshot import build_snapshot
    store = EventStore(); context = ctx(store); old = HoldoutPolicy("H1", holdout_version="1", content_hash="HASH-H1")
    with pytest.raises(PermissionError):
        old.authorize(Workflow.TUNING, context=context, access_id="A6", actor="research", attempted_at_ms=NOW_MS)
    replacement = context.compromise_authority.register_replacement(
        replacement_id="R3", compromised_holdout_id="H1", new_holdout_id="H2", new_holdout_version="2",
        new_content_hash="HASH-H2", reviewer="reviewer", registered_at_ms=30, dependency_authority=context.dependency_ledger,
    )
    context.compromise_authority.revalidate_after_replacement(
        incident_id="holdout-access-violation:A6", revalidation_id="REV-6", validation_fingerprint="NEW-HOLDOUT-REVALIDATION",
        replacement=replacement, new_evidence_refs=("EV-NEW",), new_gate_refs=("G2",), reviewer="reviewer",
        validated_at_ms=40, dependency_authority=context.dependency_ledger,
    )
    snap = build_snapshot(snapshot_id="S-OLD", evidence_ids=("EV-OLD",), metrics={}, gates=("G1",), dependencies=("EV-OLD",),
                          versions=("1",), hashes=("H",), methodology=("M",), approvals=("A",), scope={})
    with pytest.raises(EvidenceSnapshotAuthorityInvalid, match="FINAL_HOLDOUT_CONTAMINATED_EVIDENCE"):
        EvidenceSnapshotAuthorityLedger(store).authorize(
            snapshot=snap, promotion_id="P1", bundle_id="B1", model_version="M1",
            valid_from=datetime(2026,9,25,tzinfo=timezone.utc), expires_at=datetime(2026,9,26,tzinfo=timezone.utc),
            reviewer="reviewer", recorded_at_ms=60, dependency_authority=context.dependency_ledger,
        )
