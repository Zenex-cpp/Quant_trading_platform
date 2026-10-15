import copy
from trading_platform.v21.event_store import EventStore
from trading_platform.v360.readiness_evidence import EvidenceState
from trading_platform.v361.evidence_package import (
    EvidencePackageImporter,
    EvidencePackageInvalid,
    compute_package_hash,
)

NOW = 1_800_000_000_000


def _package():
    p = {
        "package_id": "PKG1",
        "scope": "PRODUCTION",
        "created_at_ms": NOW,
        "source_system": "external-evidence-store",
        "evidence": [{
            "evidence_id": "E1",
            "evidence_class": "MONITORING",
            "scope": "PRODUCTION",
            "result": "PASS",
            "observed_at_ms": NOW,
            "valid_from_ms": NOW - 1000,
            "expires_at_ms": NOW + 100000,
            "source_system": "monitoring-prod",
            "source_ref": "evidence://monitoring/run-1",
            "content_hash": "a" * 64,
        }],
    }
    p["package_hash"] = compute_package_hash(p)
    return p


def test_import_is_atomic_and_only_submits():
    store = EventStore()
    imported = EvidencePackageImporter(store).import_package(_package())
    assert imported.package_id == "PKG1"
    assert EvidencePackageImporter(store).package_was_imported("PKG1")
    assert EvidencePackageImporter(store).ledger.get("E1").state is EvidenceState.SUBMITTED


def test_import_does_not_make_production_ready():
    store = EventStore()
    EvidencePackageImporter(store).import_package(_package())
    ledger = EvidencePackageImporter(store).ledger
    assert ledger.verified_current(evidence_class="MONITORING", scope="PRODUCTION", now_ms=NOW) is None


def test_bad_package_hash_rejected():
    p = _package(); p["package_hash"] = "0" * 64
    try:
        EvidencePackageImporter(EventStore()).import_package(p)
        assert False
    except EvidencePackageInvalid as exc:
        assert "PACKAGE_HASH_MISMATCH" in str(exc)


def test_synthetic_source_rejected():
    p = _package(); p["evidence"][0]["source_ref"] = "synthetic:test"; p["package_hash"] = compute_package_hash(p)
    try:
        EvidencePackageImporter(EventStore()).import_package(p)
        assert False
    except EvidencePackageInvalid as exc:
        assert "SYNTHETIC_EVIDENCE_SOURCE_FORBIDDEN" in str(exc)


def test_sensitive_fields_rejected():
    p = _package(); p["evidence"][0]["api_key"] = "secret"; p["package_hash"] = compute_package_hash(p)
    try:
        EvidencePackageImporter(EventStore()).import_package(p)
        assert False
    except EvidencePackageInvalid as exc:
        assert "SENSITIVE_FIELD_FORBIDDEN" in str(exc)


def test_restart_preserves_import(tmp_path):
    path = str(tmp_path / "evidence.sqlite")
    store = EventStore(path)
    EvidencePackageImporter(store).import_package(_package())
    reopened = EvidencePackageImporter(EventStore(path))
    assert reopened.package_was_imported("PKG1")
    assert reopened.ledger.get("E1").state is EvidenceState.SUBMITTED
