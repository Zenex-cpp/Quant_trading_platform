from trading_platform.v21.event_store import EventStore
from trading_platform.v360.readiness_evidence import (
    REQUIRED_EVIDENCE_CLASSES,
    EvidenceResult,
    EvidenceSourceKind,
    EvidenceState,
    ProductionReadinessAssessor,
    ReadinessEvidenceInvalid,
    ReadinessEvidenceLedger,
)

NOW = 1_800_000_000_000


def _submit(ledger, evidence_id, cls, source_ref=None):
    return ledger.submit(
        evidence_id=evidence_id,
        evidence_class=cls,
        scope="PRODUCTION",
        result=EvidenceResult.PASS,
        observed_at_ms=NOW,
        valid_from_ms=NOW - 1000,
        expires_at_ms=NOW + 100000,
        source_system="external",
        source_ref=source_ref or f"evidence://external/{evidence_id}",
        content_hash=(evidence_id * 64)[:64],
        submitted_at_ms=NOW,
        source_kind=EvidenceSourceKind.EXTERNAL,
    )


def test_submitted_is_not_verified():
    store = EventStore()
    ledger = ReadinessEvidenceLedger(store)
    item = _submit(ledger, "E1", "MONITORING")
    assert item.state is EvidenceState.SUBMITTED
    assessment = ProductionReadinessAssessor(ledger).assess(assessment_id="A1", scope="PRODUCTION", now_ms=NOW)
    assert not assessment.production_ready
    assert "MONITORING" in assessment.missing


def test_verified_external_evidence_counts():
    store = EventStore()
    ledger = ReadinessEvidenceLedger(store)
    _submit(ledger, "E1", "MONITORING")
    item = ledger.verify(evidence_id="E1", reviewer_id="REV1", review_ref="review://1", verified_at_ms=NOW)
    assert item.state is EvidenceState.VERIFIED
    assert ledger.verified_current(evidence_class="MONITORING", scope="PRODUCTION", now_ms=NOW).evidence_id == "E1"


def test_synthetic_evidence_cannot_be_verified():
    store = EventStore()
    ledger = ReadinessEvidenceLedger(store)
    _submit(ledger, "E1", "MONITORING", source_ref="demo:synthetic")
    try:
        ledger.verify(evidence_id="E1", reviewer_id="REV1", review_ref="review://1", verified_at_ms=NOW)
        assert False
    except ReadinessEvidenceInvalid as exc:
        assert "SYNTHETIC_READINESS_EVIDENCE_FORBIDDEN" in str(exc)


def test_expired_verified_evidence_does_not_count():
    store = EventStore()
    ledger = ReadinessEvidenceLedger(store)
    ledger.submit(
        evidence_id="E1", evidence_class="MONITORING", scope="PRODUCTION", result=EvidenceResult.PASS,
        observed_at_ms=NOW, valid_from_ms=NOW - 1000, expires_at_ms=NOW + 10,
        source_system="external", source_ref="evidence://external/E1", content_hash="a" * 64, submitted_at_ms=NOW, source_kind=EvidenceSourceKind.EXTERNAL,
    )
    ledger.verify(evidence_id="E1", reviewer_id="REV1", review_ref="review://1", verified_at_ms=NOW)
    assert ledger.verified_current(evidence_class="MONITORING", scope="PRODUCTION", now_ms=NOW + 11) is None


def test_reopened_store_preserves_verified_state(tmp_path):
    path = str(tmp_path / "evidence.sqlite")
    store = EventStore(path)
    ledger = ReadinessEvidenceLedger(store)
    _submit(ledger, "E1", "MONITORING")
    ledger.verify(evidence_id="E1", reviewer_id="REV1", review_ref="review://1", verified_at_ms=NOW)
    reopened = ReadinessEvidenceLedger(EventStore(path))
    assert reopened.get("E1").state is EvidenceState.VERIFIED


def test_all_required_classes_are_needed():
    store = EventStore()
    ledger = ReadinessEvidenceLedger(store)
    for i, cls in enumerate(REQUIRED_EVIDENCE_CLASSES[:-1]):
        eid = f"E{i}"
        _submit(ledger, eid, cls)
        ledger.verify(evidence_id=eid, reviewer_id="REV", review_ref=f"review://{i}", verified_at_ms=NOW)
    assessment = ProductionReadinessAssessor(ledger).assess(assessment_id="A1", scope="PRODUCTION", now_ms=NOW)
    assert not assessment.production_ready
    assert assessment.missing == (REQUIRED_EVIDENCE_CLASSES[-1],)
