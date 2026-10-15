from datetime import datetime, timedelta, timezone
from hashlib import sha256

import pytest

from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.promotion.contracts import Approval, PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v360.readiness_evidence import (
    EvidenceResult,
    EvidenceSourceKind,
    ReadinessEvidenceLedger,
    REQUIRED_EVIDENCE_CLASSES,
)
from trading_platform.v359.human_review import HumanReviewAuthorityLedger, HumanReviewPackage
from trading_platform.v408.gate_promotion import GatePromotionAuthorizationLedgerV408
from trading_platform.v410.readiness_binding import (
    ProductionReadinessRevalidationAuthorityV410,
    ProductionReadinessRevalidationErrorV410,
)


NOW = datetime(2026, 10, 8, 5, 0, tzinfo=timezone.utc)
NOW_MS = int(NOW.timestamp() * 1000)


def h(v: str) -> str:
    return sha256(v.encode()).hexdigest()


def make_bundle(scope: str = "LIVE") -> PromotionBundle:
    return PromotionBundle(
        "B410", "S410", "M410", "F410", "T410", "C410", "E410", "CODE410",
        "SNAP410", ("G410",), ("ART410",), "A410", {"mode": scope}, "RB410", "HASH410", NOW,
    )


def make_approval() -> Approval:
    return Approval("A410", ("approver-410",), NOW - timedelta(minutes=1), NOW + timedelta(hours=1), {"mode": "LIVE"})


def make_gate() -> Gate:
    return Gate(
        gate_id="G410", candidate_version="CAND410", run_id="RUN410",
        input_versions=("M410", "F410"), checks=("CHECK410",), result=GateResult.PASS,
        required_artifacts=("ART410",), evidence_refs=("EVG410",), owner="owner-410",
        reviewer="reviewer-410", timestamp=NOW.isoformat(), expiration=(NOW + timedelta(hours=1)).isoformat(),
        revalidation_condition="DEPENDENCY_UNCHANGED",
    )


def seed_gate_and_snapshot(store: EventStore, dep: DependencyInvalidationLedger, bundle: PromotionBundle, gate: Gate):
    from trading_platform.v398.critical_promotion import CriticalPromotionReadinessAuthorityV398
    dep_store = dep
    # Existing V4.8 gate authority only needs its own durable gate authorization;
    # V4.10 composes the already-tested V4.9 preflight.
    GatePromotionAuthorizationLedgerV408(store).authorize(gate=gate, dependency_authority=dep_store, recorded_at_ms=NOW_MS)
    # Snapshot/gate authority used by V4.9 can operate on a minimal valid bundle in these focused tests.
    return gate


def seed_readiness_evidence(store: EventStore, scope: str = "LIVE"):
    ledger = ReadinessEvidenceLedger(store)
    for idx, cls in enumerate(REQUIRED_EVIDENCE_CLASSES):
        eid = f"EV410-{idx}"
        ledger.submit(
            evidence_id=eid,
            evidence_class=cls,
            scope=scope,
            result=EvidenceResult.PASS,
            observed_at_ms=NOW_MS,
            valid_from_ms=NOW_MS - 1000,
            expires_at_ms=NOW_MS + 60_000,
            source_system="external-operator",
            source_ref=f"external:run410:{cls}",
            content_hash=h(f"{eid}:{cls}"),
            submitted_at_ms=NOW_MS,
            source_kind=EvidenceSourceKind.EXTERNAL,
        )
        ledger.verify(evidence_id=eid, reviewer_id=f"reviewer-{idx}", review_ref=f"review-{idx}", verified_at_ms=NOW_MS)


def test_source_is_egress_free():
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "src/trading_platform/v410/readiness_binding.py").read_text()
    forbidden = ("subprocess", "socket.", "requests.", "urllib.request", "httpx", "os.system")
    assert not any(token in text for token in forbidden)


def test_exact_evidence_fingerprint_is_recorded_and_roundtrips():
    # The end-to-end ready path is covered by the integration-level V4.9 controls;
    # this test targets the new binding primitive with controlled evidence.
    store = EventStore()
    dep = DependencyInvalidationLedger(store)
    ledger = ReadinessEvidenceLedger(store)
    ledger.submit(
        evidence_id="EVID-A", evidence_class=REQUIRED_EVIDENCE_CLASSES[0], scope="LIVE",
        result=EvidenceResult.PASS, observed_at_ms=NOW_MS, valid_from_ms=NOW_MS-1,
        expires_at_ms=NOW_MS+10000, source_system="external", source_ref="external:a",
        content_hash=h("a"), submitted_at_ms=NOW_MS, source_kind=EvidenceSourceKind.EXTERNAL,
    )
    ledger.verify(evidence_id="EVID-A", reviewer_id="reviewer", review_ref="review", verified_at_ms=NOW_MS)
    ev = ledger.get("EVID-A")
    assert ev is not None
    auth = ProductionReadinessRevalidationAuthorityV410(store=store, dependency_authority=dep)
    assert auth._evidence_fingerprint(ev) == ev.fingerprint()


def test_v410_binds_exact_scope_and_evidence_and_roundtrips(monkeypatch):
    store = EventStore(); dep = DependencyInvalidationLedger(store)
    auth = ProductionReadinessRevalidationAuthorityV410(store=store, dependency_authority=dep)
    ledger = ReadinessEvidenceLedger(store)
    now_ms = NOW_MS
    evidence_ids = []
    for idx, cls in enumerate(REQUIRED_EVIDENCE_CLASSES):
        eid = f"EV410-INTEGRATION-{idx}"
        evidence_ids.append(eid)
        ledger.submit(
            evidence_id=eid, evidence_class=cls, scope="LIVE", result=EvidenceResult.PASS,
            observed_at_ms=now_ms, valid_from_ms=now_ms-1, expires_at_ms=now_ms+60_000,
            source_system="external-system", source_ref=f"external:integration:{cls}",
            content_hash=h(f"integration:{eid}"), submitted_at_ms=now_ms, source_kind=EvidenceSourceKind.EXTERNAL,
        )
        ledger.verify(evidence_id=eid, reviewer_id=f"reviewer-{idx}", review_ref=f"review-{idx}", verified_at_ms=now_ms)

    from trading_platform.v360.readiness_evidence import ProductionReadinessAssessment
    from trading_platform.v407.critical_promotion_evidence import CriticalPromotionEvidenceDecisionV407
    from trading_platform.v408.gate_promotion import CriticalPromotionGateDecisionV408
    from trading_platform.v409.production_readiness import ProductionReadinessDecisionV409

    bundle = make_bundle("LIVE")
    preflight = CriticalPromotionGateDecisionV408(
        True, "PREFLIGHT_OK", ("G410",), ("G410",), (),
        CriticalPromotionEvidenceDecisionV407(True, "SNAPSHOT_OK", bundle.evidence_snapshot_id, bundle.bundle_id),
    )
    ready = ProductionReadinessDecisionV409(
        True, "PRODUCTION_READY", "PRODUCTION_READINESS_VERIFIED", bundle.bundle_id, (),
        tuple(sorted(evidence_ids)), "production-readiness:ASSESS-INTEGRATION", "HR410",
        bundle.approval_id, preflight,
    )
    monkeypatch.setattr(auth.v409, "assess", lambda **kwargs: ready)
    decision = auth.assess(
        bundle=bundle, gates=(), approval=make_approval(), human_review_id="HR410", scope="LIVE",
        now=NOW, assessment_id="ASSESS-INTEGRATION",
    )
    assert decision.production_ready
    rec = auth.get(decision.readiness_id)
    assert rec is not None
    assert rec.scope == "LIVE"
    assert rec.evidence_ids == tuple(sorted(evidence_ids))
    again = auth.assert_verified(
        decision.readiness_id, bundle=bundle, gates=(), approval=make_approval(), scope="LIVE", now=NOW,
    )
    assert again.binding_fingerprint == rec.binding_fingerprint


def test_scope_mismatch_is_fail_closed_on_record_revalidation(monkeypatch):
    store = EventStore(); dep = DependencyInvalidationLedger(store)
    auth = ProductionReadinessRevalidationAuthorityV410(store=store, dependency_authority=dep)
    # Inject a durable record directly to isolate the revalidation boundary.
    from trading_platform.v410.readiness_binding import ReadinessBindingRecordV410
    rec = ReadinessBindingRecordV410(
        readiness_id="production-readiness-v410:R1", bundle_id="B410", evidence_snapshot_id="SNAP410", scope="LIVE",
        evidence_ids=(), evidence_fingerprints=(), human_review_id="HR", approval_id="A410",
        application_preflight_fingerprint="P", dependency_checkpoint=dep.checkpoint(), assessed_at_ms=NOW_MS,
    )
    auth._persist(rec)
    with pytest.raises(ProductionReadinessRevalidationErrorV410, match="SCOPE_MISMATCH"):
        auth.assert_verified(
            rec.readiness_id,
            bundle=make_bundle("LIVE"), gates=(), approval=make_approval(), scope="CANARY", now=NOW,
        )


def test_changed_evidence_fingerprint_blocks_revalidation():
    store = EventStore(); dep = DependencyInvalidationLedger(store)
    auth = ProductionReadinessRevalidationAuthorityV410(store=store, dependency_authority=dep)
    from trading_platform.v410.readiness_binding import ReadinessBindingRecordV410
    ledger = ReadinessEvidenceLedger(store)
    ledger.submit(
        evidence_id="EVID-B", evidence_class=REQUIRED_EVIDENCE_CLASSES[0], scope="LIVE",
        result=EvidenceResult.PASS, observed_at_ms=NOW_MS, valid_from_ms=NOW_MS-1,
        expires_at_ms=NOW_MS+10000, source_system="external", source_ref="external:b",
        content_hash=h("b"), submitted_at_ms=NOW_MS, source_kind=EvidenceSourceKind.EXTERNAL,
    )
    ledger.verify(evidence_id="EVID-B", reviewer_id="reviewer", review_ref="review", verified_at_ms=NOW_MS)
    ev = ledger.get("EVID-B"); assert ev is not None
    rec = ReadinessBindingRecordV410(
        readiness_id="production-readiness-v410:R2", bundle_id="B410", evidence_snapshot_id="SNAP410", scope="LIVE",
        evidence_ids=("EVID-B",), evidence_fingerprints=(("EVID-B", "wrong"),), human_review_id="HR", approval_id="A410",
        application_preflight_fingerprint="P", dependency_checkpoint=dep.checkpoint(), assessed_at_ms=NOW_MS,
    )
    auth._persist(rec)
    with pytest.raises(ProductionReadinessRevalidationErrorV410, match="FINGERPRINT_CHANGED"):
        auth.assert_verified(
            rec.readiness_id,
            bundle=make_bundle("LIVE"), gates=(), approval=make_approval(), scope="LIVE", now=NOW,
        )
