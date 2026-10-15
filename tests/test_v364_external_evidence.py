from trading_platform.v21.event_store import EventStore
from trading_platform.v360.readiness_evidence import (
    EvidenceResult, EvidenceSourceKind, EvidenceState, ReadinessEvidenceInvalid, ReadinessEvidenceLedger,
)
from trading_platform.v361.evidence_package import compute_package_hash, EvidencePackageImporter
from trading_platform.v364.external_evidence import ExternalEvidencePackageImporter, ExternalEvidencePackageInvalid

NOW = 1_800_000_000_000


def _submit(ledger, *, source_kind=EvidenceSourceKind.EXTERNAL):
    return ledger.submit(
        evidence_id="E-EXT-1", evidence_class="MONITORING", scope="PRODUCTION",
        result=EvidenceResult.PASS, observed_at_ms=NOW, valid_from_ms=NOW - 1_000,
        expires_at_ms=NOW + 100_000, source_system="monitoring-prod",
        source_ref="evidence://monitoring/run-64", content_hash="a" * 64,
        submitted_at_ms=NOW, source_kind=source_kind,
    )


def test_internal_source_cannot_be_verified():
    ledger = ReadinessEvidenceLedger(EventStore())
    _submit(ledger, source_kind=EvidenceSourceKind.INTERNAL)
    try:
        ledger.verify(evidence_id="E-EXT-1", reviewer_id="REV", review_ref="review://64", verified_at_ms=NOW)
        assert False
    except ReadinessEvidenceInvalid as exc:
        assert "EXTERNAL_READINESS_EVIDENCE_REQUIRED" in str(exc)


def test_external_source_can_be_verified():
    ledger = ReadinessEvidenceLedger(EventStore())
    _submit(ledger)
    item = ledger.verify(evidence_id="E-EXT-1", reviewer_id="REV", review_ref="review://64", verified_at_ms=NOW)
    assert item.state is EvidenceState.VERIFIED
    assert item.source_kind is EvidenceSourceKind.EXTERNAL


def _package(kind="EXTERNAL"):
    p={
        "package_id":"PKG64", "scope":"PRODUCTION", "created_at_ms":NOW,
        "source_system":"external-evidence-store", "evidence":[{
            "evidence_id":"E64", "evidence_class":"MONITORING", "scope":"PRODUCTION",
            "result":"PASS", "observed_at_ms":NOW, "valid_from_ms":NOW-1000,
            "expires_at_ms":NOW+100000, "source_system":"monitoring-prod",
            "source_ref":"evidence://monitoring/run-64", "source_kind":kind,
            "content_hash":"b"*64,
        }],
    }
    p["package_hash"]=compute_package_hash(p)
    return p


def test_v364_import_requires_explicit_external_provenance():
    try:
        ExternalEvidencePackageImporter(EventStore()).import_package(_package("UNKNOWN"))
        assert False
    except ExternalEvidencePackageInvalid as exc:
        assert "EXTERNAL_EVIDENCE_REQUIRED" in str(exc)


def test_v364_import_persists_external_provenance():
    store=EventStore()
    ExternalEvidencePackageImporter(store).import_package(_package("EXTERNAL"))
    item=ReadinessEvidenceLedger(store).get("E64")
    assert item.source_kind is EvidenceSourceKind.EXTERNAL
    assert item.state is EvidenceState.SUBMITTED


def test_legacy_v361_import_is_non_verifiable_without_provenance():
    package=_package()
    package["evidence"][0].pop("source_kind")
    package["package_hash"]=compute_package_hash(package)
    store=EventStore()
    EvidencePackageImporter(store).import_package(package)
    item=ReadinessEvidenceLedger(store).get("E64")
    assert item.source_kind is EvidenceSourceKind.UNKNOWN
    try:
        ReadinessEvidenceLedger(store).verify(evidence_id="E64", reviewer_id="REV", review_ref="review://legacy", verified_at_ms=NOW)
        assert False
    except ReadinessEvidenceInvalid as exc:
        assert "EXTERNAL_READINESS_EVIDENCE_REQUIRED" in str(exc)
