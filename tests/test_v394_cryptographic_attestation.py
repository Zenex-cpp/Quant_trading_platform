import base64
from dataclasses import replace

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import compute_package_hash
from trading_platform.v393.external_review_authority import (
    ExternalReviewAttestationV393,
    ReviewDecisionV393,
    SignatureVerificationStateV393,
)
from trading_platform.v394.cryptographic_attestation import (
    CryptoVerificationStateV394,
    CryptographicAttestationAuthorityV394,
    KeyStatusV394,
    SignatureAlgorithmV394,
    SignedReviewEnvelopeV394,
    TrustAnchorAttestationStateV394,
    TrustAnchorV394,
)

NOW = 1_800_000_000_000


def _package():
    package = {
        "package_id": "PKG394",
        "scope": "PRODUCTION",
        "created_at_ms": NOW,
        "source_system": "external-evidence-store",
        "evidence": [{
            "evidence_id": "E394-1", "evidence_class": "MONITORING", "scope": "PRODUCTION",
            "result": "PASS", "observed_at_ms": NOW, "valid_from_ms": NOW - 1_000,
            "expires_at_ms": NOW + 100_000, "source_system": "monitoring-prod",
            "source_ref": "evidence://monitoring/394", "source_kind": "EXTERNAL", "content_hash": "a" * 64,
        }],
    }
    package["package_hash"] = compute_package_hash(package)
    return package


def _review():
    base = dict(
        review_id="REV394-1", scope="PRODUCTION", subject_ids=("PKG394", "E394-1"),
        reviewer_id="independent-reviewer", reviewer_role="INDEPENDENT_REVIEWER",
        producer_ids=("external-evidence-store", "monitoring-prod"), owner_ids=("platform-owner",),
        approver_ids=("promotion-approver",), decision=ReviewDecisionV393.ACCEPT,
        reviewed_at_ms=NOW, expires_at_ms=NOW + 86_400_000,
        source_system="independent-review-system", source_ref="review://394/REV394-1",
        signature_ref="signature://394/REV394-1", signature_hash="b" * 64,
        signature_verification=SignatureVerificationStateV393.EXTERNALLY_VERIFIED, review_hash="",
    )
    provisional = ExternalReviewAttestationV393(**base)
    base["review_hash"] = provisional.computed_review_hash()
    return ExternalReviewAttestationV393(**base)


def _anchor(private_key, *, status=KeyStatusV394.ACTIVE, scope="PRODUCTION", attested=TrustAnchorAttestationStateV394.ATTESTED):
    raw = private_key.public_key().public_bytes_raw()
    import hashlib
    return TrustAnchorV394(
        key_id="review-key-394", algorithm=SignatureAlgorithmV394.ED25519,
        public_key_b64=base64.b64encode(raw).decode(), valid_from_ms=NOW - 1_000,
        expires_at_ms=NOW + 86_400_000, status=status,
        allowed_scopes=(scope,), registry_version="trust-registry-v394", key_fingerprint=hashlib.sha256(raw).hexdigest(),
    ), attested


def _envelope(private_key, package, review, anchor, attested=TrustAnchorAttestationStateV394.ATTESTED):
    draft = SignedReviewEnvelopeV394(
        envelope_id="ENV394-1", package_id=package["package_id"], package_hash=package["package_hash"],
        review_id=review.review_id, review_hash=review.review_hash, scope=review.scope,
        key_id=anchor.key_id, algorithm=SignatureAlgorithmV394.ED25519, signature_b64="",
        signature_hash="", trust_registry_version=anchor.registry_version, trust_anchor_attestation=attested,
    )
    signature = private_key.sign(draft.signing_bytes())
    import hashlib
    return replace(draft, signature_b64=base64.b64encode(signature).decode(), signature_hash=hashlib.sha256(signature).hexdigest())


def test_real_ed25519_signature_verification():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    assert decision.allowed
    assert decision.verification is CryptoVerificationStateV394.VERIFIED
    assert decision.evidence_status.startswith("CRYPTOGRAPHICALLY_VERIFIED")


def test_tampered_payload_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    tampered = replace(envelope, package_hash="0" * 64)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=tampered, trust_anchor=anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "SIGNED_HASH_BINDING_MISMATCH"


def test_wrong_key_is_rejected():
    signer = Ed25519PrivateKey.generate()
    wrong = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(wrong)
    envelope = _envelope(signer, package, review, anchor, attested)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "SIGNATURE_INVALID"


def test_expired_key_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    expired = replace(anchor, expires_at_ms=NOW)
    envelope = _envelope(private_key, package, review, expired, attested)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=expired, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "TRUST_ANCHOR_EXPIRED"


def test_revoked_key_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key, status=KeyStatusV394.REVOKED)
    envelope = _envelope(private_key, package, review, anchor, attested)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "TRUST_ANCHOR_REVOKED"


def test_unattested_trust_anchor_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, _ = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, TrustAnchorAttestationStateV394.UNATTESTED)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "TRUST_ANCHOR_ATTESTATION_REQUIRED"


def test_scope_mismatch_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key, scope="TESTNET")
    envelope = _envelope(private_key, package, review, anchor, attested)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "TRUST_ANCHOR_SCOPE_NOT_ALLOWED"


def test_fingerprint_mismatch_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    bad_anchor = replace(anchor, key_fingerprint="0" * 64)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=envelope, trust_anchor=bad_anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "TRUST_ANCHOR_FINGERPRINT_MISMATCH"


def test_signature_hash_mismatch_is_rejected():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    bad = replace(envelope, signature_hash="0" * 64)
    decision = CryptographicAttestationAuthorityV394(EventStore()).verify(package=package, review=review, envelope=bad, trust_anchor=anchor, now_ms=NOW + 1)
    assert not decision.allowed and decision.reason == "SIGNATURE_HASH_MISMATCH"


def test_restart_preserves_verification(tmp_path):
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    path = str(tmp_path / "crypto.sqlite")
    first = CryptographicAttestationAuthorityV394(EventStore(path)).verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    assert first.allowed
    reopened = CryptographicAttestationAuthorityV394(EventStore(path))
    assert reopened.get(envelope.envelope_id) is not None
    assert reopened.verify_chain()


def test_duplicate_verification_is_idempotent():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    authority = CryptographicAttestationAuthorityV394(EventStore())
    first = authority.verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 1)
    second = authority.verify(package=package, review=review, envelope=envelope, trust_anchor=anchor, now_ms=NOW + 2)
    assert first.allowed and second.allowed
    assert authority.get(envelope.envelope_id) is not None
    assert authority.verify_chain()


def test_safe_payload_excludes_signature_material():
    private_key = Ed25519PrivateKey.generate()
    package, review = _package(), _review()
    anchor, attested = _anchor(private_key)
    envelope = _envelope(private_key, package, review, anchor, attested)
    payload = envelope.safe_payload()
    assert "signature_b64" not in payload
    assert "private_key" not in str(payload).lower()
