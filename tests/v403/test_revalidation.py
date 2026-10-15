from __future__ import annotations

import base64
from datetime import datetime, timezone, timedelta
from hashlib import sha256

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v395.trust_anchor_attestation import ReviewerKeyStatusV395, ReviewerTrustAnchorV395
from trading_platform.v403.revalidation import (
    ExternalReadinessRevalidationAuthorityV403,
    ReadinessRevalidationWitnessV403,
    RevalidationStatusV403,
)


def _anchor(private: Ed25519PrivateKey, key_id="reviewer-v403"):
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


def _sign_witness(private, **kwargs):
    body = dict(kwargs)
    import json
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    signature = private.sign(canonical)
    return ReadinessRevalidationWitnessV403(
        **body,
        signature_b64=base64.b64encode(signature).decode(),
        signature_hash=sha256(signature).hexdigest(),
    )


def _store():
    s = EventStore()
    e1 = s.append(event_id="e1", occurred_at_ms=1000, event_type="READINESS_A", aggregate_id="b1", payload={"status":"VERIFIED"}).event
    e2 = s.append(event_id="e2", occurred_at_ms=1001, event_type="READINESS_B", aggregate_id="b1", payload={"status":"VERIFIED"}).event
    return s, e1, e2


def test_accepts_signed_revalidation_with_immutable_event_hashes():
    store, e1, e2 = _store()
    private = Ed25519PrivateKey.generate()
    witness = _sign_witness(
        private,
        witness_id="w1", scope="PRODUCTION_CRITICAL", bundle_id="b1", evidence_snapshot_id="s1",
        release_artifact_hash="a"*64, checked_event_hashes=(("e1", e1.event_hash),("e2", e2.event_hash)),
        review_evidence_ref="audit://revalidation/w1", reviewer_id="rev", operator_id="op",
        reviewer_key_id="reviewer-v403", checked_at_ms=2000, expires_at_ms=4000, decision="ACCEPT",
    )
    decision = ExternalReadinessRevalidationAuthorityV403(store).admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3000)
    assert decision.allowed is True
    assert decision.status is RevalidationStatusV403.REVALIDATED


def test_rejects_event_hash_mismatch():
    store, e1, _ = _store()
    private = Ed25519PrivateKey.generate()
    witness = _sign_witness(
        private,
        witness_id="w2", scope="PRODUCTION_CRITICAL", bundle_id="b1", evidence_snapshot_id="s1",
        release_artifact_hash="a"*64, checked_event_hashes=(("e1", "0"*64),),
        review_evidence_ref="audit://revalidation/w2", reviewer_id="rev", operator_id="op",
        reviewer_key_id="reviewer-v403", checked_at_ms=2000, expires_at_ms=4000, decision="ACCEPT",
    )
    decision = ExternalReadinessRevalidationAuthorityV403(store).admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3000)
    assert decision.allowed is False
    assert "HASH_MISMATCH" in decision.reason


def test_rejects_expired_witness():
    store, e1, _ = _store()
    private = Ed25519PrivateKey.generate()
    witness = _sign_witness(
        private,
        witness_id="w3", scope="PRODUCTION_CRITICAL", bundle_id="b1", evidence_snapshot_id="s1",
        release_artifact_hash="a"*64, checked_event_hashes=(("e1", e1.event_hash),),
        review_evidence_ref="audit://revalidation/w3", reviewer_id="rev", operator_id="op",
        reviewer_key_id="reviewer-v403", checked_at_ms=2000, expires_at_ms=4000, decision="ACCEPT",
    )
    decision = ExternalReadinessRevalidationAuthorityV403(store).admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=4000)
    assert decision.allowed is False
    assert decision.status is RevalidationStatusV403.EXPIRED


def test_rejects_synthetic_review_reference():
    store, e1, _ = _store()
    private = Ed25519PrivateKey.generate()
    witness = _sign_witness(
        private,
        witness_id="w4", scope="PRODUCTION_CRITICAL", bundle_id="b1", evidence_snapshot_id="s1",
        release_artifact_hash="a"*64, checked_event_hashes=(("e1", e1.event_hash),),
        review_evidence_ref="synthetic:review", reviewer_id="rev", operator_id="op",
        reviewer_key_id="reviewer-v403", checked_at_ms=2000, expires_at_ms=4000, decision="ACCEPT",
    )
    decision = ExternalReadinessRevalidationAuthorityV403(store).admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3000)
    assert decision.allowed is False
    assert "REFERENCE_INVALID" in decision.reason


def test_assert_fresh_blocks_after_expiry():
    store, e1, _ = _store()
    private = Ed25519PrivateKey.generate()
    witness = _sign_witness(
        private,
        witness_id="w5", scope="PRODUCTION_CRITICAL", bundle_id="b1", evidence_snapshot_id="s1",
        release_artifact_hash="a"*64, checked_event_hashes=(("e1", e1.event_hash),),
        review_evidence_ref="audit://revalidation/w5", reviewer_id="rev", operator_id="op",
        reviewer_key_id="reviewer-v403", checked_at_ms=2000, expires_at_ms=4000, decision="ACCEPT",
    )
    authority = ExternalReadinessRevalidationAuthorityV403(store)
    assert authority.admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3000).allowed
    authority.assert_fresh("w5", now_ms=3999)
    try:
        authority.assert_fresh("w5", now_ms=4000)
    except ValueError as exc:
        assert str(exc) == "REVALIDATION_WITNESS_EXPIRED"
    else:
        raise AssertionError("expected expiry block")


def test_idempotent_revalidation_event():
    store, e1, _ = _store()
    private = Ed25519PrivateKey.generate()
    witness = _sign_witness(
        private,
        witness_id="w6", scope="PRODUCTION_CRITICAL", bundle_id="b1", evidence_snapshot_id="s1",
        release_artifact_hash="a"*64, checked_event_hashes=(("e1", e1.event_hash),),
        review_evidence_ref="audit://revalidation/w6", reviewer_id="rev", operator_id="op",
        reviewer_key_id="reviewer-v403", checked_at_ms=2000, expires_at_ms=4000, decision="ACCEPT",
    )
    authority = ExternalReadinessRevalidationAuthorityV403(store)
    d1 = authority.admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3000)
    d2 = authority.admit(witness=witness, reviewer_anchor=_anchor(private), now_ms=3001)
    assert d1.allowed and d2.allowed
    assert d1.status is d2.status is RevalidationStatusV403.REVALIDATED
    assert authority.verify_chain()
