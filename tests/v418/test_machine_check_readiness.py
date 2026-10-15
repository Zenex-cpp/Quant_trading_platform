from __future__ import annotations

import base64
import copy
import json
from dataclasses import replace
from hashlib import sha256

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import canonical_json, compute_package_hash
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393,
    ExternalReviewAuthorityLedgerV393,
    ReviewDecisionV393,
    SignatureVerificationStateV393,
)
from trading_platform.v394.cryptographic_attestation import (
    KeyStatusV394,
    SignatureAlgorithmV394,
    SignedReviewEnvelopeV394,
    TrustAnchorAttestationStateV394,
    TrustAnchorV394,
)
from trading_platform.v395.trust_anchor_attestation import (
    ExternalTrustAnchorAttestationV395,
    RevocationDrillEvidenceV395,
    ReviewerKeyStatusV395,
    ReviewerTrustAnchorV395,
    TrustAnchorAttestationAuthorityV395,
    TrustRegistrySnapshotV395,
)
from trading_platform.v413.crypto_review import PromotionCryptoReviewAuthorityV413
from trading_platform.v417.production_readiness_compliance import (
    MANDATORY_REQUIREMENTS_V417,
    ProductionReadinessComplianceAuthorityV417,
)
from trading_platform.v418.machine_check_readiness import (
    MANDATORY_MACHINE_CHECKS_V418,
    MachineCheckReadinessAuthorityV418,
    MachineCheckReadinessErrorV418,
)

NOW = 1_800_100_000_000
BUNDLE = "BUNDLE-418"
COMPLIANCE_ID = "COMPLIANCE-418-READY"
REVIEW_ID = "REVIEW-418-M1-M30"


def _v417_matrix(*, verified: bool) -> list[dict[str, str]]:
    return [
        {
            "requirement_id": rid,
            "requirement_text": text,
            "priority": "CRITICAL",
            "implementation_status": "VERIFIED" if verified else "TESTED",
            "code_reference": f"src/{rid}",
            "schema_reference": f"schemas/{rid}.csv",
            "test_reference": f"tests/{rid}.py",
            "evidence_reference": f"evidence://{rid}",
            "owner": "governance",
            "unresolved_gap": "" if verified else "external operational proof remains open",
        }
        for rid, text in MANDATORY_REQUIREMENTS_V417
    ]


def _prepare_compliance(store: EventStore, *, verified: bool) -> None:
    store.append(
        event_id="operational-readiness-convergence-v416:CONV-418",
        occurred_at_ms=NOW - 10,
        event_type="OPERATIONAL_READINESS_CONVERGED_V416",
        aggregate_id=BUNDLE,
        payload={"status": "VERIFIED", "bundle_id": BUNDLE, "activation_flag": "NOT_SET"},
    )
    decision = ProductionReadinessComplianceAuthorityV417(store).evaluate(
        decision_id=COMPLIANCE_ID,
        convergence_id="CONV-418",
        matrix=_v417_matrix(verified=verified),
        now_ms=NOW - 9,
    )
    assert decision.status == ("VERIFIED" if verified else "BLOCKED")


def _machine_matrix(*, verified: bool, review_id: str = REVIEW_ID) -> list[dict[str, str]]:
    return [
        {
            "machine_check_id": check_id,
            "requirement_text": text,
            "priority": "CRITICAL",
            "implementation_status": "VERIFIED" if verified else "TESTED",
            "code_reference": f"src/{check_id}",
            "schema_reference": f"schemas/{check_id}.json",
            "test_reference": f"tests/{check_id}.py",
            "evidence_reference": f"evidence://{check_id}",
            "review_reference": review_id if verified else "",
            "owner": "governance",
            "unresolved_gap": "" if verified else "independent review and external evidence are not verified",
        }
        for check_id, text in MANDATORY_MACHINE_CHECKS_V418
    ]


def _row_hash(row: dict[str, str]) -> str:
    raw = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    return sha256(raw).hexdigest()


def _review_package(
    bundle_id: str,
    *,
    include_all: bool = True,
    matrix: list[dict[str, str]] | None = None,
) -> dict:
    package_id = MachineCheckReadinessAuthorityV418.expected_review_package_id(bundle_id)
    matrix = matrix if matrix is not None else _machine_matrix(verified=True)
    by_id = {row["machine_check_id"]: row for row in matrix}
    checks = MANDATORY_MACHINE_CHECKS_V418 if include_all else MANDATORY_MACHINE_CHECKS_V418[:-1]
    evidence = []
    for check_id, _ in checks:
        evidence.append({
            "evidence_id": check_id,
            "evidence_class": "INDEPENDENT_REVIEW",
            "scope": "PRODUCTION",
            "result": "PASS",
            "observed_at_ms": NOW - 500,
            "valid_from_ms": NOW - 1_000,
            "expires_at_ms": NOW + 100_000,
            "source_system": "machine-check-test-evidence-store",
            "source_ref": f"evidence://machine-check/{check_id}",
            "content_hash": _row_hash(by_id[check_id]),
            "source_kind": "EXTERNAL",
        })
    package = {
        "package_id": package_id,
        "scope": "PRODUCTION",
        "created_at_ms": NOW - 500,
        "source_system": "machine-check-review-package-store",
        "evidence": evidence,
    }
    package["package_hash"] = compute_package_hash(package)
    return package


def _review(bundle_id: str = BUNDLE, *, expires_at_ms: int = NOW + 50_000) -> ExternalReviewAttestationV393:
    package_id = MachineCheckReadinessAuthorityV418.expected_review_package_id(bundle_id)
    candidate = ExternalReviewAttestationV393(
        review_id=REVIEW_ID,
        scope="PRODUCTION",
        subject_ids=tuple([package_id, bundle_id] + [check_id for check_id, _ in MANDATORY_MACHINE_CHECKS_V418]),
        reviewer_id="independent-reviewer-418",
        reviewer_role="INDEPENDENT_REVIEWER",
        producer_ids=("machine-check-review-package-store", "machine-check-test-evidence-store"),
        owner_ids=("platform-owner-418",),
        approver_ids=("production-approver-418",),
        decision=ReviewDecisionV393.ACCEPT,
        reviewed_at_ms=NOW - 100,
        expires_at_ms=expires_at_ms,
        source_system="independent-review-system-418",
        source_ref="review://machine-checks/418",
        signature_ref="signature://machine-checks/418",
        signature_hash="a" * 64,
        signature_verification=SignatureVerificationStateV393.EXTERNALLY_VERIFIED,
        review_hash="",
    )
    return ExternalReviewAttestationV393(**{**candidate.__dict__, "review_hash": candidate.computed_review_hash()})


def _crypto_review_gate(store: EventStore, package: dict, review: ExternalReviewAttestationV393) -> str:
    # The review signature is bound cryptographically to the exact package/review
    # hashes, and the signing key is referenced through a V3.95-accepted registry.
    review_private = Ed25519PrivateKey.generate()
    review_public = review_private.public_key().public_bytes_raw()
    review_fp = sha256(review_public).hexdigest()
    registry_version = "trust-registry-v418"
    anchor = TrustAnchorV394(
        "machine-check-review-key-418", SignatureAlgorithmV394.ED25519,
        base64.b64encode(review_public).decode(), NOW - 5_000, NOW + 500_000,
        KeyStatusV394.ACTIVE, ("PRODUCTION",), registry_version, review_fp,
    )
    snapshot_draft = TrustRegistrySnapshotV395(registry_version, (anchor,), "")
    snapshot = replace(snapshot_draft, registry_hash=snapshot_draft.computed_hash())

    attestation_private = Ed25519PrivateKey.generate()
    attestation_public = attestation_private.public_key().public_bytes_raw()
    reviewer_anchor = ReviewerTrustAnchorV395(
        reviewer_key_id="trust-registry-reviewer-key-418",
        public_key_b64=base64.b64encode(attestation_public).decode(),
        valid_from_ms=NOW - 5_000,
        expires_at_ms=NOW + 500_000,
        status=ReviewerKeyStatusV395.ACTIVE,
        allowed_scopes=("PRODUCTION",),
        fingerprint=sha256(attestation_public).hexdigest(),
    )
    drill = RevocationDrillEvidenceV395(
        drill_id="revocation-drill-418", target_key_id=anchor.key_id,
        executed_at_ms=NOW - 1_000, passed=True, revoked_anchor_blocked=True,
        evidence_ref="ops://trust-anchor/revocation-drill/418",
    )
    attestation_draft = ExternalTrustAnchorAttestationV395(
        attestation_id=f"TRUST-ANCHOR-{review.review_id}",
        scope="PRODUCTION", registry_version=registry_version,
        registry_hash=snapshot.registry_hash, anchor_fingerprints=snapshot.fingerprint_set,
        custodian_id="trust-custodian-418",
        custody_evidence_ref="ops://trust-anchor/custody/418",
        ceremony_evidence_ref="ops://trust-anchor/ceremony/418",
        revocation_drill=drill, reviewer_id="trust-registry-reviewer-418",
        reviewer_key_id=reviewer_anchor.reviewer_key_id,
        reviewed_at_ms=NOW - 100, expires_at_ms=NOW + 100_000,
        signature_b64="", signature_hash="0" * 64,
    )
    attestation_signature = attestation_private.sign(canonical_json(attestation_draft.body_for_hash()))
    attestation = replace(
        attestation_draft,
        signature_b64=base64.b64encode(attestation_signature).decode(),
        signature_hash=sha256(attestation_signature).hexdigest(),
    )
    attestation_decision = TrustAnchorAttestationAuthorityV395(store).intake(
        snapshot=snapshot, attestation=attestation, reviewer_anchor=reviewer_anchor, now_ms=NOW,
    )
    assert attestation_decision.allowed, attestation_decision.reason

    envelope_draft = SignedReviewEnvelopeV394(
        f"ENVELOPE-418-{review.review_id}", str(package["package_id"]),
        str(package["package_hash"]), review.review_id, review.review_hash, review.scope,
        anchor.key_id, SignatureAlgorithmV394.ED25519, "", "", registry_version,
        TrustAnchorAttestationStateV394.ATTESTED,
    )
    envelope_signature = review_private.sign(envelope_draft.signing_bytes())
    envelope = replace(
        envelope_draft,
        signature_b64=base64.b64encode(envelope_signature).decode(),
        signature_hash=sha256(envelope_signature).hexdigest(),
    )
    decision = PromotionCryptoReviewAuthorityV413(store).verify(
        package=package, review=review, envelope=envelope, trust_anchor=anchor,
        trust_anchor_attestation_id=attestation.attestation_id, now_ms=NOW,
    )
    assert decision.allowed and decision.status == "VERIFIED", decision.reason
    return decision.gate_id


def _crypto_gate_id(review: ExternalReviewAttestationV393) -> str:
    return f"promotion-crypto-review-v413:ENVELOPE-418-{review.review_id}"


def _admit_review(
    store: EventStore,
    *,
    include_all: bool = True,
    review: ExternalReviewAttestationV393 | None = None,
    matrix: list[dict[str, str]] | None = None,
) -> tuple[ExternalReviewAttestationV393, dict]:
    review = review or _review()
    bundle_id = str(review.subject_ids[1])
    package = _review_package(bundle_id, include_all=include_all, matrix=matrix)
    decision = ExternalReviewAuthorityLedgerV393(store).admit(package=package, review=review, now_ms=NOW)
    assert decision.allowed, decision.reason
    _crypto_review_gate(store, package, review)
    return review, package


def test_all_thirty_machine_checks_can_be_verified_only_with_same_bundle_and_durable_review():
    store = EventStore()
    _prepare_compliance(store, verified=True)
    review, package = _admit_review(store)
    authority = MachineCheckReadinessAuthorityV418(store)
    decision = authority.evaluate(
        decision_id="DECISION-418-VALID",
        compliance_decision_id=COMPLIANCE_ID,
        matrix=_machine_matrix(verified=True),
        review=review,
        now_ms=NOW,
        review_package=package,
        crypto_review_gate_id=_crypto_gate_id(review),
    )
    assert len(MANDATORY_MACHINE_CHECKS_V418) == 30
    assert decision.allowed and decision.status == "VERIFIED"
    assert decision.bundle_id == BUNDLE
    assert decision.blocking_machine_check_ids == ()
    authority.assert_valid("DECISION-418-VALID")
    event = authority.get("DECISION-418-VALID")
    assert event.payload["production_ready"] is False
    assert event.payload["activation_flag"] == "NOT_SET"


def test_blocked_upstream_compliance_cannot_be_overridden_by_machine_check_review():
    store = EventStore()
    _prepare_compliance(store, verified=False)
    review, package = _admit_review(store)
    d = MachineCheckReadinessAuthorityV418(store).evaluate(
        decision_id="DECISION-418-UPSTREAM-BLOCKED",
        compliance_decision_id=COMPLIANCE_ID,
        matrix=_machine_matrix(verified=True),
        review=review,
        now_ms=NOW,
        review_package=package,
        crypto_review_gate_id=_crypto_gate_id(review),
    )
    assert not d.allowed and d.status == "BLOCKED"
    assert "UPSTREAM_COMPLIANCE_NOT_VERIFIED" in d.blocking_reasons


def test_missing_external_review_blocks_all_checks():
    store = EventStore()
    _prepare_compliance(store, verified=True)
    d = MachineCheckReadinessAuthorityV418(store).evaluate(
        decision_id="DECISION-418-NO-REVIEW",
        compliance_decision_id=COMPLIANCE_ID,
        matrix=_machine_matrix(verified=True),
        review=None,
        now_ms=NOW,
    )
    assert not d.allowed and d.status == "BLOCKED"
    assert "INDEPENDENT_M1_M30_REVIEW_REQUIRED" in d.blocking_reasons
    with pytest.raises(MachineCheckReadinessErrorV418, match="MACHINE_CHECK_DECISION_NOT_VERIFIED"):
        MachineCheckReadinessAuthorityV418(store).assert_valid("DECISION-418-NO-REVIEW")


def test_missing_mandatory_machine_check_is_rejected():
    store = EventStore(); _prepare_compliance(store, verified=True); review, package = _admit_review(store)
    rows = _machine_matrix(verified=True)[:-1]
    with pytest.raises(MachineCheckReadinessErrorV418, match="MANDATORY_MACHINE_CHECKS_MISSING:M30"):
        MachineCheckReadinessAuthorityV418(store).evaluate(
            decision_id="DECISION-418-MISSING", compliance_decision_id=COMPLIANCE_ID,
            matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
        )


def test_duplicate_machine_check_is_rejected():
    store = EventStore(); _prepare_compliance(store, verified=True); review, package = _admit_review(store)
    rows = _machine_matrix(verified=True); rows.append(copy.deepcopy(rows[0]))
    with pytest.raises(MachineCheckReadinessErrorV418, match="MACHINE_CHECK_DUPLICATE:M1"):
        MachineCheckReadinessAuthorityV418(store).evaluate(
            decision_id="DECISION-418-DUP", compliance_decision_id=COMPLIANCE_ID,
            matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
        )


def test_verified_status_without_refs_review_or_gap_closure_is_blocked():
    store = EventStore(); _prepare_compliance(store, verified=True)
    rows = _machine_matrix(verified=True)
    review, package = _admit_review(store, matrix=rows)
    rows[0]["test_reference"] = ""
    d = MachineCheckReadinessAuthorityV418(store).evaluate(
        decision_id="DECISION-418-MISSING-REF", compliance_decision_id=COMPLIANCE_ID,
        matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
    )
    assert not d.allowed and "M1" in d.blocking_machine_check_ids


def test_external_review_must_cover_all_thirty_evidence_ids():
    store = EventStore(); _prepare_compliance(store, verified=True)
    review, package = _admit_review(store, include_all=False)
    d = MachineCheckReadinessAuthorityV418(store).evaluate(
        decision_id="DECISION-418-REVIEW-GAP", compliance_decision_id=COMPLIANCE_ID,
        matrix=_machine_matrix(verified=True), review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
    )
    assert not d.allowed and "MACHINE_CHECK_REVIEW_EVIDENCE_COVERAGE_INCOMPLETE:M30" in d.blocking_reasons


def test_expired_review_cannot_be_reused():
    store = EventStore(); _prepare_compliance(store, verified=True)
    review = _review(expires_at_ms=NOW + 10)
    package = _review_package(BUNDLE)
    decision = ExternalReviewAuthorityLedgerV393(store).admit(package=package, review=review, now_ms=NOW)
    assert decision.allowed
    _crypto_review_gate(store, package, review)
    d = MachineCheckReadinessAuthorityV418(store).evaluate(
        decision_id="DECISION-418-EXPIRED", compliance_decision_id=COMPLIANCE_ID,
        matrix=_machine_matrix(verified=True), review=review, now_ms=NOW + 11, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
    )
    assert not d.allowed
    assert any(item.startswith("EXTERNAL_REVIEW_INVALID:REVIEW_EXPIRED") for item in d.blocking_reasons)


def test_review_for_another_bundle_is_blocked():
    store = EventStore(); _prepare_compliance(store, verified=True)
    review = _review(bundle_id="OTHER-BUNDLE")
    package = _review_package("OTHER-BUNDLE")
    decision = ExternalReviewAuthorityLedgerV393(store).admit(package=package, review=review, now_ms=NOW)
    assert decision.allowed
    _crypto_review_gate(store, package, review)
    d = MachineCheckReadinessAuthorityV418(store).evaluate(
        decision_id="DECISION-418-OTHER-BUNDLE", compliance_decision_id=COMPLIANCE_ID,
        matrix=_machine_matrix(verified=True), review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
    )
    assert not d.allowed
    assert "MACHINE_CHECK_REVIEW_PACKAGE_MISMATCH" in d.blocking_reasons


def test_same_decision_id_cannot_be_reused_after_matrix_mutation():
    store = EventStore(); _prepare_compliance(store, verified=True); review, package = _admit_review(store)
    authority = MachineCheckReadinessAuthorityV418(store)
    rows = _machine_matrix(verified=True)
    authority.evaluate(decision_id="DECISION-418-IDEMP", compliance_decision_id=COMPLIANCE_ID,
                      matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review))
    rows[1]["unresolved_gap"] = "new gap"
    with pytest.raises(MachineCheckReadinessErrorV418, match="MACHINE_CHECK_DECISION_ID_CONFLICT"):
        authority.evaluate(decision_id="DECISION-418-IDEMP", compliance_decision_id=COMPLIANCE_ID,
                           matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review))


def test_missing_upstream_compliance_decision_is_rejected():
    with pytest.raises(MachineCheckReadinessErrorV418, match="UPSTREAM_COMPLIANCE_DECISION_REQUIRED"):
        MachineCheckReadinessAuthorityV418(EventStore()).evaluate(
            decision_id="DECISION-418-NO-UPSTREAM", compliance_decision_id="MISSING",
            matrix=_machine_matrix(verified=False), review=None, now_ms=NOW,
        )


def test_invalid_status_vocabulary_is_rejected():
    store = EventStore(); _prepare_compliance(store, verified=True); review, package = _admit_review(store)
    rows = _machine_matrix(verified=True); rows[0]["implementation_status"] = "PRODUCTION_READY"
    with pytest.raises(MachineCheckReadinessErrorV418, match="MACHINE_CHECK_STATUS_INVALID:M1"):
        MachineCheckReadinessAuthorityV418(store).evaluate(
            decision_id="DECISION-418-STATUS", compliance_decision_id=COMPLIANCE_ID,
            matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review),
        )


def test_identical_evaluation_is_idempotent():
    store = EventStore(); _prepare_compliance(store, verified=True); review, package = _admit_review(store)
    authority = MachineCheckReadinessAuthorityV418(store); rows = _machine_matrix(verified=True)
    first = authority.evaluate(decision_id="DECISION-418-REPEAT", compliance_decision_id=COMPLIANCE_ID,
                               matrix=rows, review=review, now_ms=NOW, review_package=package, crypto_review_gate_id=_crypto_gate_id(review))
    second = authority.evaluate(decision_id="DECISION-418-REPEAT", compliance_decision_id=COMPLIANCE_ID,
                                matrix=rows, review=review, now_ms=NOW + 1, review_package=package, crypto_review_gate_id=_crypto_gate_id(review))
    assert first == second
    assert store.get("machine-check-readiness-v418:DECISION-418-REPEAT") is not None
