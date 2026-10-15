from __future__ import annotations

from datetime import timedelta
from hashlib import sha256

import pytest

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v360.readiness_evidence import REQUIRED_EVIDENCE_CLASSES
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393,
    ReviewDecisionV393,
    SignatureVerificationStateV393,
)
from trading_platform.v411.operational_evidence import OperationalEvidenceManifestAuthorityV411
from trading_platform.v412.external_review_bridge import (
    ExternalReviewBridgeAuthorityV412,
    ExternalReviewBridgeErrorV412,
)

NOW = 1_800_000_100_000


def h(v: str) -> str:
    return sha256(v.encode()).hexdigest()


def manifest():
    evidence = []
    for idx, cls in enumerate(REQUIRED_EVIDENCE_CLASSES):
        item = {
            "evidence_id": f"V412-E{idx}", "evidence_class": cls, "scope": "PRODUCTION",
            "source_kind": "EXTERNAL", "source_system": f"producer-{idx}",
            "source_ref": f"https://external.example/{cls.lower()}/{idx}", "content_hash": h(f"content:{idx}"),
            "observed_at_ms": NOW, "valid_from_ms": NOW - 1_000, "expires_at_ms": NOW + 100_000,
            "artifact_refs": [f"evidence://{cls.lower()}/{idx}"], "attestation_ref": f"attestation://{cls.lower()}/{idx}",
        }
        if cls == "LIVE_VENUE": item.update(environment_id="TESTNET", session_ref="session://1", mutation_ref="mutation://1", reconciliation_ref="recon://1")
        elif cls == "NETWORK_SEGMENTATION": item.update(environment_id="PRODUCTION", policy_ref="policy://1", isolation_test_ref="isolation://1")
        elif cls == "SECRET_STORE": item.update(environment_id="PRODUCTION", vault_ref="vault://1", rotation_ref="rotation://1", revocation_ref="revocation://1")
        elif cls == "BACKUP_RESTORE": item.update(environment_id="PRODUCTION", backup_ref="backup://1", restore_ref="restore://1", rpo_rto_ref="rpo-rto://1")
        elif cls == "DISASTER_RECOVERY": item.update(environment_id="PRODUCTION", dr_exercise_ref="dr://1", failover_ref="failover://1", failback_ref="failback://1", recovery_proof_ref="recovery://1")
        elif cls == "SECURITY_REVIEW": item.update(assessment_ref="security://1", scope_ref="scope://1", findings_ref="findings://1")
        elif cls == "MONITORING": item.update(environment_id="PRODUCTION", monitoring_ref="monitor://1", page_ref="page://1", on_call_ref="oncall://1")
        elif cls == "ROLLBACK": item.update(environment_id="PRODUCTION", rollback_ref="rollback://1", reconciliation_ref="recon://1", recovery_proof_ref="recovery://1")
        elif cls == "INDEPENDENT_REVIEW": item.update(review_ref="review://1", reviewer_id="reviewer-external", subject_coverage_ref="coverage://1")
        evidence.append(item)
    out = {
        "protocol_version": "V4.11-OPERATIONAL-EVIDENCE-1", "package_id": "PKG-V412-1",
        "scope": "PRODUCTION", "created_at_ms": NOW, "source_system": "external-evidence-orchestrator",
        "evidence": evidence,
    }
    body = dict(out)
    body.pop("manifest_hash", None)
    out["manifest_hash"] = sha256(canonical_json(body)).hexdigest()
    return out


def review_for(man):
    subject_ids = tuple([man["package_id"]] + [item["evidence_id"] for item in man["evidence"]])
    body = {
        "review_id": "REV412", "scope": "PRODUCTION", "subject_ids": list(subject_ids),
        "reviewer_id": "independent-reviewer", "reviewer_role": "external-assurance",
        "producer_ids": ["external-evidence-orchestrator"], "owner_ids": ["owner-412"], "approver_ids": ["approver-412"],
        "decision": ReviewDecisionV393.ACCEPT.value, "reviewed_at_ms": NOW, "expires_at_ms": NOW + 60_000,
        "source_system": "independent-review-system", "source_ref": "https://review.example/REV412",
        "signature_ref": "https://review.example/signature/REV412", "signature_hash": h("signature"),
        "signature_verification": SignatureVerificationStateV393.EXTERNALLY_VERIFIED.value,
    }
    from trading_platform.v393.external_review_authority import _hash
    review_hash = _hash(body)
    return ExternalReviewAttestationV393(
        review_id=body["review_id"], scope=body["scope"], subject_ids=subject_ids,
        reviewer_id=body["reviewer_id"], reviewer_role=body["reviewer_role"], producer_ids=tuple(body["producer_ids"]),
        owner_ids=tuple(body["owner_ids"]), approver_ids=tuple(body["approver_ids"]), decision=ReviewDecisionV393.ACCEPT,
        reviewed_at_ms=NOW, expires_at_ms=NOW + 60_000, source_system=body["source_system"],
        source_ref=body["source_ref"], signature_ref=body["signature_ref"], signature_hash=body["signature_hash"],
        signature_verification=SignatureVerificationStateV393.EXTERNALLY_VERIFIED, review_hash=review_hash,
    )


def test_manifest_is_only_admissible_for_review_bridge():
    decision = OperationalEvidenceManifestAuthorityV411(EventStore()).admit(manifest())
    assert decision.allowed
    assert decision.status == "READY_FOR_EXTERNAL_REVIEW"


def test_valid_external_review_bridges_and_verifies_all_evidence():
    store = EventStore(); m = manifest(); r = review_for(m); authority = ExternalReviewBridgeAuthorityV412(store)
    d = authority.assess(manifest=m, review=r, now_ms=NOW)
    assert d.externally_verified
    assert len(d.evidence_ids) == 9
    for eid in d.evidence_ids:
        ev = authority.evidence_ledger.get(eid)
        assert ev is not None and ev.state.value == "VERIFIED"
        assert ev.reviewer_id == r.reviewer_id
        assert ev.review_ref == r.review_id


def test_unverified_signature_is_blocked():
    store = EventStore(); m = manifest(); r = review_for(m)
    bad = ExternalReviewAttestationV393(**{**r.__dict__, "signature_verification": SignatureVerificationStateV393.UNVERIFIED})
    with pytest.raises(ExternalReviewBridgeErrorV412, match="EXTERNAL_REVIEW:EXTERNAL_SIGNATURE_VERIFICATION_REQUIRED"):
        ExternalReviewBridgeAuthorityV412(store).assess(manifest=m, review=bad, now_ms=NOW)


def test_review_scope_mismatch_is_blocked():
    m = manifest(); r = review_for(m)
    bad = ExternalReviewAttestationV393(**{**r.__dict__, "scope": "TESTNET"})
    with pytest.raises(ExternalReviewBridgeErrorV412, match="EXTERNAL_REVIEW:REVIEW_SCOPE_MISMATCH"):
        ExternalReviewBridgeAuthorityV412(EventStore()).assess(manifest=m, review=bad, now_ms=NOW)


def test_reviewer_cannot_equal_evidence_producer():
    m = manifest(); r = review_for(m)
    bad = ExternalReviewAttestationV393(**{**r.__dict__, "reviewer_id": "external-evidence-orchestrator"})
    from trading_platform.v393.external_review_authority import _hash
    body = bad.body_for_hash(); bad = ExternalReviewAttestationV393(**{**bad.__dict__, "review_hash": _hash(body)})
    with pytest.raises(ExternalReviewBridgeErrorV412, match="EXTERNAL_REVIEW:INDEPENDENT_REVIEWER_CONFLICT"):
        ExternalReviewBridgeAuthorityV412(EventStore()).assess(manifest=m, review=bad, now_ms=NOW)


def test_tampered_manifest_cannot_revalidate():
    store = EventStore(); m = manifest(); r = review_for(m); authority = ExternalReviewBridgeAuthorityV412(store)
    d = authority.assess(manifest=m, review=r, now_ms=NOW)
    tampered = {**m, "created_at_ms": NOW + 1_000}
    body = dict(tampered); body.pop("manifest_hash", None); tampered["manifest_hash"] = sha256(canonical_json(body)).hexdigest()
    with pytest.raises(ExternalReviewBridgeErrorV412, match="MANIFEST_ID_CONFLICT|MANIFEST_FINGERPRINT_CHANGED|BRIDGE"):
        authority.assert_verified(d.bridge_id, manifest=tampered, review=r, now_ms=NOW)


def test_review_fingerprint_change_blocks_revalidation():
    store = EventStore(); m = manifest(); r = review_for(m); authority = ExternalReviewBridgeAuthorityV412(store)
    d = authority.assess(manifest=m, review=r, now_ms=NOW)
    changed = ExternalReviewAttestationV393(**{**r.__dict__, "reviewed_at_ms": NOW + 1})
    from trading_platform.v393.external_review_authority import _hash
    changed = ExternalReviewAttestationV393(**{**changed.__dict__, "review_hash": _hash(changed.body_for_hash())})
    with pytest.raises(ExternalReviewBridgeErrorV412):
        authority.assert_verified(d.bridge_id, manifest=m, review=changed, now_ms=NOW)


def test_bridge_record_is_durable_and_idempotent():
    store = EventStore(); m = manifest(); r = review_for(m); authority = ExternalReviewBridgeAuthorityV412(store)
    first = authority.assess(manifest=m, review=r, now_ms=NOW)
    second = authority.assess(manifest=m, review=r, now_ms=NOW)
    assert first.bridge_id == second.bridge_id
    assert authority.get(first.bridge_id) is not None


def test_bridge_does_not_claim_production_ready():
    store = EventStore(); m = manifest(); r = review_for(m); authority = ExternalReviewBridgeAuthorityV412(store)
    d = authority.assess(manifest=m, review=r, now_ms=NOW)
    assert d.externally_verified
    assert not hasattr(d, "production_ready")


def test_source_contract_has_no_network_or_process_egress():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[2] / "src/trading_platform/v412/external_review_bridge.py").read_text()
    forbidden = ("subprocess", "socket.", "requests.", "urllib.request", "httpx", "os.system", "urlopen")
    assert not any(token in source for token in forbidden)


def test_exactly_nine_required_classes_are_bridged():
    store = EventStore(); m = manifest(); r = review_for(m); authority = ExternalReviewBridgeAuthorityV412(store)
    d = authority.assess(manifest=m, review=r, now_ms=NOW)
    assert set(d.evidence_ids) == set(REQUIRED_EVIDENCE_CLASSES) or len(d.evidence_ids) == len(REQUIRED_EVIDENCE_CLASSES)
