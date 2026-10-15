from __future__ import annotations

import base64
from hashlib import sha256
import json

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v395.trust_anchor_attestation import ReviewerKeyStatusV395, ReviewerTrustAnchorV395
from trading_platform.v403.revalidation import ExternalReadinessRevalidationAuthorityV403, ReadinessRevalidationWitnessV403
from trading_platform.v404.revocation import ExternalReadinessRevocationAuthorityV404, ReadinessRevocationV404, RevalidationStatusV404


def _anchor(private: Ed25519PrivateKey, key_id="reviewer-v404"):
    raw = private.public_key().public_bytes_raw()
    return ReviewerTrustAnchorV395(
        reviewer_key_id=key_id,
        public_key_b64=base64.b64encode(raw).decode(),
        valid_from_ms=0,
        expires_at_ms=9_999_999_999_999,
        status=ReviewerKeyStatusV395.ACTIVE,
        allowed_scopes=("PRODUCTION_CRITICAL",),
        fingerprint=sha256(raw).hexdigest(),
    )


def _witness(private: Ed25519PrivateKey, store: EventStore):
    e = store.append(event_id="e1", occurred_at_ms=1000, event_type="READINESS_A", aggregate_id="b1", payload={"status":"VERIFIED"}).event
    body = {
        "witness_id":"w1", "scope":"PRODUCTION_CRITICAL", "bundle_id":"b1", "evidence_snapshot_id":"s1",
        "release_artifact_hash":"a"*64, "checked_event_hashes":(("e1", e.event_hash),),
        "review_evidence_ref":"audit://revalidation/w1", "reviewer_id":"rev", "operator_id":"op",
        "reviewer_key_id":"reviewer-v404", "checked_at_ms":2000, "expires_at_ms":4000, "decision":"ACCEPT",
    }
    canonical = json.dumps({
        "witness_id": body["witness_id"], "scope": body["scope"], "bundle_id": body["bundle_id"],
        "evidence_snapshot_id": body["evidence_snapshot_id"], "release_artifact_hash": body["release_artifact_hash"],
        "checked_event_hashes": [list(x) for x in body["checked_event_hashes"]],
        "review_evidence_ref": body["review_evidence_ref"], "reviewer_id": body["reviewer_id"],
        "operator_id": body["operator_id"], "reviewer_key_id": body["reviewer_key_id"],
        "checked_at_ms": body["checked_at_ms"], "expires_at_ms": body["expires_at_ms"], "decision":"ACCEPT",
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    signature = private.sign(canonical)
    witness = ReadinessRevalidationWitnessV403(
        **body, signature_b64=base64.b64encode(signature).decode(), signature_hash=sha256(signature).hexdigest()
    )
    ExternalReadinessRevalidationAuthorityV403(store).admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3000)
    return witness


def _revocation(private: Ed25519PrivateKey, witness, store: EventStore):
    accepted = store.get(f"external-readiness-revalidation:{witness.witness_id}:accepted")
    fingerprint = str(accepted.payload["witness_fingerprint"])
    body = {
        "revocation_id":"r1", "scope":"PRODUCTION_CRITICAL", "witness_id":"w1", "witness_fingerprint":fingerprint,
        "bundle_id":"b1", "evidence_snapshot_id":"s1", "release_artifact_hash":"a"*64,
        "reason_code":"SECURITY_EVIDENCE_INVALIDATED", "reviewer_id":"rev2", "operator_id":"op", "reviewer_key_id":"reviewer-v404",
        "revoked_at_ms":3200, "decision":"REVOKE",
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    signature = private.sign(canonical)
    return ReadinessRevocationV404(
        **body, signature_b64=base64.b64encode(signature).decode(), signature_hash=sha256(signature).hexdigest()
    )


def test_revocation_blocks_future_use():
    store = EventStore()
    private = Ed25519PrivateKey.generate()
    witness = _witness(private, store)
    authority = ExternalReadinessRevocationAuthorityV404(store)
    revocation = _revocation(private, witness, store)
    allowed, status, reason = authority.revoke(revocation=revocation, reviewer_anchor=_anchor(private), now_ms=3300)
    assert allowed and status is RevalidationStatusV404.REVOKED
    assert reason == "EXTERNAL_READINESS_REVALIDATION_REVOKED"
    try:
        authority.assert_usable(witness_id="w1", now_ms=3300)
    except ValueError as exc:
        assert str(exc) == "REVALIDATION_WITNESS_REVOKED"
    else:
        raise AssertionError("expected revocation block")


def test_revocation_is_idempotent():
    store = EventStore()
    private = Ed25519PrivateKey.generate()
    witness = _witness(private, store)
    authority = ExternalReadinessRevocationAuthorityV404(store)
    revocation = _revocation(private, witness, store)
    first = authority.revoke(revocation=revocation, reviewer_anchor=_anchor(private), now_ms=3300)
    second = authority.revoke(revocation=revocation, reviewer_anchor=_anchor(private), now_ms=3301)
    assert first == second
    assert authority.verify_chain()


def test_status_distinguishes_expired_and_revoked():
    store = EventStore()
    private = Ed25519PrivateKey.generate()
    witness = _witness(private, store)
    authority = ExternalReadinessRevocationAuthorityV404(store)
    assert authority.status("w1", now_ms=3999) is RevalidationStatusV404.REVALIDATED
    assert authority.status("w1", now_ms=4000) is RevalidationStatusV404.EXPIRED
    revocation = _revocation(private, witness, store)
    authority.revoke(revocation=revocation, reviewer_anchor=_anchor(private), now_ms=3300)
    assert authority.status("w1", now_ms=3999) is RevalidationStatusV404.REVOKED


def test_rejects_fingerprint_or_bundle_mismatch():
    store = EventStore()
    private = Ed25519PrivateKey.generate()
    witness = _witness(private, store)
    authority = ExternalReadinessRevocationAuthorityV404(store)
    revocation = _revocation(private, witness, store)
    bad = ReadinessRevocationV404(**{**revocation.__dict__, "bundle_id":"other"})
    # Re-sign mutated body so the signature itself is not the reason for rejection.
    canonical = json.dumps(bad.body_for_hash(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    sig = private.sign(canonical)
    bad = ReadinessRevocationV404(**{**bad.__dict__, "signature_b64":base64.b64encode(sig).decode(), "signature_hash":sha256(sig).hexdigest()})
    allowed, status, reason = authority.revoke(revocation=bad, reviewer_anchor=_anchor(private), now_ms=3300)
    assert not allowed
    assert status is RevalidationStatusV404.REJECTED
    assert reason == "REVOCATION_BUNDLE_MISMATCH"
