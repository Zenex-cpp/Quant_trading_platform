from __future__ import annotations

from hashlib import sha256

import pytest

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v360.readiness_evidence import REQUIRED_EVIDENCE_CLASSES
from trading_platform.v411.operational_evidence import (
    OperationalEvidenceManifestAuthorityV411,
    OperationalEvidenceManifestErrorV411,
)

NOW = 1_800_000_000_000


def _hash(payload):
    body = dict(payload)
    body.pop("manifest_hash", None)
    return sha256(canonical_json(body)).hexdigest()


def _manifest():
    evidence = []
    for idx, cls in enumerate(REQUIRED_EVIDENCE_CLASSES):
        entry = {
            "evidence_id": f"V411-E{idx}",
            "evidence_class": cls,
            "scope": "PRODUCTION",
            "source_kind": "EXTERNAL",
            "source_system": f"external-system-{idx}",
            "source_ref": f"https://external.example/{cls.lower()}/{idx}",
            "content_hash": "a" * 64,
            "observed_at_ms": NOW,
            "valid_from_ms": NOW - 1000,
            "expires_at_ms": NOW + 100_000,
            "artifact_refs": [f"evidence://{cls.lower()}/{idx}/primary"],
            "attestation_ref": f"attestation://{cls.lower()}/{idx}",
        }
        if cls == "LIVE_VENUE":
            entry.update(environment_id="TESTNET", session_ref="session://1", mutation_ref="mutation://1", reconciliation_ref="recon://1")
        elif cls == "NETWORK_SEGMENTATION":
            entry.update(environment_id="PRODUCTION", policy_ref="policy://1", isolation_test_ref="isolation://1")
        elif cls == "SECRET_STORE":
            entry.update(environment_id="PRODUCTION", vault_ref="vault://1", rotation_ref="rotation://1", revocation_ref="revocation://1")
        elif cls == "BACKUP_RESTORE":
            entry.update(environment_id="PRODUCTION", backup_ref="backup://1", restore_ref="restore://1", rpo_rto_ref="rpo-rto://1")
        elif cls == "DISASTER_RECOVERY":
            entry.update(environment_id="PRODUCTION", dr_exercise_ref="dr://1", failover_ref="failover://1", failback_ref="failback://1", recovery_proof_ref="recovery://1")
        elif cls == "SECURITY_REVIEW":
            entry.update(assessment_ref="security://1", scope_ref="scope://1", findings_ref="findings://1")
        elif cls == "MONITORING":
            entry.update(environment_id="PRODUCTION", monitoring_ref="monitor://1", page_ref="page://1", on_call_ref="oncall://1")
        elif cls == "ROLLBACK":
            entry.update(environment_id="PRODUCTION", rollback_ref="rollback://1", reconciliation_ref="recon://1", recovery_proof_ref="recovery://1")
        elif cls == "INDEPENDENT_REVIEW":
            entry.update(review_ref="review://1", reviewer_id="independent-reviewer", subject_coverage_ref="coverage://1")
        evidence.append(entry)
    manifest = {
        "protocol_version": "V4.11-OPERATIONAL-EVIDENCE-1",
        "package_id": "PKG-V411-1",
        "scope": "PRODUCTION",
        "created_at_ms": NOW,
        "source_system": "external-evidence-orchestrator",
        "evidence": evidence,
    }
    manifest["manifest_hash"] = _hash(manifest)
    return manifest


def test_complete_manifest_is_admissible_but_not_verified():
    decision = OperationalEvidenceManifestAuthorityV411(EventStore()).admit(_manifest())
    assert decision.allowed
    assert decision.status == "READY_FOR_EXTERNAL_REVIEW"
    assert decision.externally_admissible


def test_all_nine_required_classes_are_required():
    manifest = _manifest()
    manifest["evidence"] = manifest["evidence"][:-1]
    manifest["manifest_hash"] = _hash(manifest)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="REQUIRED_EVIDENCE_CLASS_MISSING"):
        OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest)


def test_each_item_must_be_external():
    manifest = _manifest()
    manifest["evidence"][0]["source_kind"] = "INTERNAL"
    manifest["manifest_hash"] = _hash(manifest)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="EXTERNAL_EVIDENCE_REQUIRED"):
        OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest)


def test_synthetic_source_is_blocked():
    manifest = _manifest()
    manifest["evidence"][0]["source_ref"] = "synthetic:fixture"
    manifest["manifest_hash"] = _hash(manifest)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="NON_EXTERNAL_SOURCE_FORBIDDEN"):
        OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest)


def test_missing_class_specific_field_is_blocked():
    manifest = _manifest()
    del manifest["evidence"][0]["mutation_ref"]
    manifest["manifest_hash"] = _hash(manifest)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="PROTOCOL_FIELDS_MISSING:LIVE_VENUE"):
        OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest)


def test_manifest_hash_is_bound_and_tamper_fails():
    manifest = _manifest()
    authority = OperationalEvidenceManifestAuthorityV411(EventStore())
    authority.admit(manifest)
    tampered = dict(manifest)
    tampered["evidence"] = [dict(item) for item in manifest["evidence"]]
    tampered["evidence"][0]["mutation_ref"] = "mutation://tampered"
    tampered["manifest_hash"] = manifest["manifest_hash"]
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="MANIFEST_HASH_MISMATCH"):
        authority.revalidate(tampered)


def test_same_package_cannot_be_rebound_to_new_manifest():
    authority = OperationalEvidenceManifestAuthorityV411(EventStore())
    manifest = _manifest()
    authority.admit(manifest)
    changed = dict(manifest)
    changed["created_at_ms"] += 1
    changed["manifest_hash"] = _hash(changed)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="MANIFEST_ID_CONFLICT"):
        authority.admit(changed)


def test_sensitive_payload_is_rejected():
    manifest = _manifest()
    manifest["evidence"][0]["raw_secret"] = "do-not-store"
    manifest["manifest_hash"] = _hash(manifest)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="SENSITIVE_FIELD_FORBIDDEN"):
        OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest)


def test_time_window_and_hash_are_checked():
    manifest = _manifest()
    manifest["evidence"][0]["observed_at_ms"] = NOW + 200_000
    manifest["manifest_hash"] = _hash(manifest)
    with pytest.raises(OperationalEvidenceManifestErrorV411, match="EVIDENCE_TIME_WINDOW_INVALID"):
        OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest)
