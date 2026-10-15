from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import compute_package_hash
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393,
    ExternalReviewAuthorityLedgerV393,
    ReviewDecisionV393,
    SignatureVerificationStateV393,
)

NOW = 1_800_000_000_000


def _package():
    package = {
        "package_id": "PKG393",
        "scope": "PRODUCTION",
        "created_at_ms": NOW,
        "source_system": "external-evidence-store",
        "evidence": [
            {
                "evidence_id": "E393-1",
                "evidence_class": "MONITORING",
                "scope": "PRODUCTION",
                "result": "PASS",
                "observed_at_ms": NOW,
                "valid_from_ms": NOW - 1_000,
                "expires_at_ms": NOW + 100_000,
                "source_system": "monitoring-prod",
                "source_ref": "evidence://monitoring/393",
                "source_kind": "EXTERNAL",
                "content_hash": "a" * 64,
            },
        ],
    }
    package["package_hash"] = compute_package_hash(package)
    return package


def _review(**overrides):
    base = dict(
        review_id="REV393-1",
        scope="PRODUCTION",
        subject_ids=("PKG393", "E393-1"),
        reviewer_id="independent-reviewer",
        reviewer_role="INDEPENDENT_REVIEWER",
        producer_ids=("external-evidence-store", "monitoring-prod"),
        owner_ids=("platform-owner",),
        approver_ids=("promotion-approver",),
        decision=ReviewDecisionV393.ACCEPT,
        reviewed_at_ms=NOW,
        expires_at_ms=NOW + 86_400_000,
        source_system="independent-review-system",
        source_ref="review://393/REV393-1",
        signature_ref="signature://393/REV393-1",
        signature_hash="b" * 64,
        signature_verification=SignatureVerificationStateV393.EXTERNALLY_VERIFIED,
        review_hash="",
    )
    base.update(overrides)
    candidate = ExternalReviewAttestationV393(**base)
    return ExternalReviewAttestationV393(**{**base, "review_hash": candidate.computed_review_hash()})


def test_accepts_external_evidence_with_independent_review():
    ledger = ExternalReviewAuthorityLedgerV393(EventStore())
    decision = ledger.admit(package=_package(), review=_review(), now_ms=NOW + 1)
    assert decision.allowed
    assert decision.reason == "EXTERNAL_REVIEW_ACCEPTED"
    assert ledger.verify_chain()


def test_reviewer_cannot_equal_evidence_producer():
    review = _review(reviewer_id="monitoring-prod")
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "INDEPENDENT_REVIEWER_CONFLICT" or "REVIEWER_SAME_AS_EVIDENCE_PRODUCER" in decision.reason


def test_reviewer_cannot_equal_approver():
    review = _review(reviewer_id="promotion-approver")
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "INDEPENDENT_REVIEWER_CONFLICT"


def test_unverified_signature_is_blocked():
    review = _review(signature_verification=SignatureVerificationStateV393.UNVERIFIED)
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "EXTERNAL_SIGNATURE_VERIFICATION_REQUIRED"


def test_review_expiry_is_blocked():
    review = _review(expires_at_ms=NOW + 1)
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 2)
    assert not decision.allowed
    assert decision.reason == "REVIEW_EXPIRED"


def test_subject_coverage_is_required():
    review = _review(subject_ids=("PKG393",))
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "REVIEW_SUBJECT_COVERAGE_INCOMPLETE"


def test_internal_evidence_is_blocked():
    package = _package()
    package["evidence"][0]["source_kind"] = "INTERNAL"
    package["package_hash"] = compute_package_hash(package)
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=package, review=_review(), now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "EXTERNAL_EVIDENCE_REQUIRED"


def test_synthetic_review_source_is_blocked():
    review = _review(source_ref="synthetic:review")
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "SYNTHETIC_REVIEW_SOURCE_FORBIDDEN"


def test_review_hash_tamper_is_blocked():
    review = _review()
    review = ExternalReviewAttestationV393(**{**review.__dict__, "review_hash": "0" * 64})
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "REVIEW_HASH_MISMATCH"


def test_idempotent_re_admission_returns_same_audit_record():
    store = EventStore()
    ledger = ExternalReviewAuthorityLedgerV393(store)
    review = _review()
    first = ledger.admit(package=_package(), review=review, now_ms=NOW + 1)
    second = ledger.admit(package=_package(), review=review, now_ms=NOW + 2)
    assert first.allowed and second.allowed
    assert first.review_hash == second.review_hash
    assert ledger.get(review.review_id) is not None
    assert ledger.verify_chain()


def test_restart_preserves_acceptance(tmp_path):
    path = str(tmp_path / "review.sqlite")
    review = _review()
    first = ExternalReviewAuthorityLedgerV393(EventStore(path)).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert first.allowed
    reopened = ExternalReviewAuthorityLedgerV393(EventStore(path))
    assert reopened.get(review.review_id) is not None
    assert reopened.verify_chain()


def test_safe_payload_contains_no_secret_material():
    review = _review()
    payload = review.safe_payload()
    assert all("secret" not in str(key).lower() for key in payload)


def test_review_source_cannot_equal_package_source():
    review = _review(source_system="external-evidence-store")
    decision = ExternalReviewAuthorityLedgerV393(EventStore()).admit(package=_package(), review=review, now_ms=NOW + 1)
    assert not decision.allowed
    assert decision.reason == "REVIEW_SOURCE_INDEPENDENCE_CONFLICT"
