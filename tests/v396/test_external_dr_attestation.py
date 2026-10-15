from __future__ import annotations

import base64
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v396.dr_attestation import (
    DRAttestationStatusV396,
    DRPolicySnapshotV396,
    ExternalDRAttestationAuthorityV396,
    ExternalDRAttestationV396,
)
from trading_platform.v361.evidence_package import canonical_json
from trading_platform.v395.trust_anchor_attestation import ReviewerKeyStatusV395, ReviewerTrustAnchorV395
from trading_platform.v21.event_store import EventStore
import hashlib


def _keypair():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    key_id = "reviewer-dr-396"
    anchor = ReviewerTrustAnchorV395(
        reviewer_key_id=key_id,
        public_key_b64=base64.b64encode(public).decode(),
        valid_from_ms=100,
        expires_at_ms=100_000,
        status=ReviewerKeyStatusV395.ACTIVE,
        allowed_scopes=("PRODUCTION_DR_READINESS",),
        fingerprint=hashlib.sha256(public).hexdigest(),
    )
    return private, anchor


def _policy():
    p = DRPolicySnapshotV396("DR-POLICY-396", "PRODUCTION_DR_READINESS", 30, 120, "")
    return DRPolicySnapshotV396(p.policy_version, p.scope, p.required_rpo_seconds, p.required_rto_seconds, p.computed_hash())


def _attestation(private, policy, **overrides):
    body = dict(
        attestation_id="DR-ATTEST-396-001",
        scope=policy.scope,
        policy_version=policy.policy_version,
        policy_hash=policy.policy_hash,
        backup_artifact_hash="a" * 64,
        restore_evidence_hash="b" * 64,
        observed_rpo_seconds=10,
        observed_rto_seconds=60,
        failover_evidence_ref="ops://dr/failover/2026-10-07",
        failback_evidence_ref="ops://dr/failback/2026-10-07",
        recovery_proof_ref="ops://dr/recovery-proof/2026-10-07",
        recovery_state_reconciled=True,
        recovery_invariants_pass=True,
        no_unresolved_critical_issue=True,
        recovery_guards_pass=True,
        operator_id="operator-1",
        custodian_id="custodian-1",
        reviewer_id="reviewer-1",
        reviewer_key_id="reviewer-dr-396",
        attested_at_ms=1_000,
        expires_at_ms=10_000,
        signature_b64="",
        signature_hash="",
    )
    body.update(overrides)
    unsigned = ExternalDRAttestationV396(**body)
    sig = private.sign(canonical_json(unsigned.body_for_hash()))
    return ExternalDRAttestationV396(
        **{**body, "signature_b64": base64.b64encode(sig).decode(), "signature_hash": hashlib.sha256(sig).hexdigest()}
    )


def test_accepts_complete_external_dr_attestation():
    private, anchor = _keypair()
    policy = _policy()
    authority = ExternalDRAttestationAuthorityV396(EventStore())
    decision = authority.intake(policy=policy, attestation=_attestation(private, policy), reviewer_anchor=anchor, now_ms=2_000)
    assert decision.allowed and decision.status is DRAttestationStatusV396.VERIFIED


def test_policy_hash_mismatch_blocks():
    private, anchor = _keypair(); policy = _policy(); bad = _attestation(private, policy, policy_hash="0" * 64)
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=bad, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "DR_POLICY_REFERENCE_MISMATCH"


def test_rpo_breach_blocks():
    private, anchor = _keypair(); policy = _policy(); bad = _attestation(private, policy, observed_rpo_seconds=31)
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=bad, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "RPO_BREACH"


def test_rto_breach_blocks():
    private, anchor = _keypair(); policy = _policy(); bad = _attestation(private, policy, observed_rto_seconds=121)
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=bad, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "RTO_BREACH"


def test_recovery_proof_incomplete_blocks():
    private, anchor = _keypair(); policy = _policy(); bad = _attestation(private, policy, recovery_invariants_pass=False)
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=bad, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "RECOVERY_PROOF_INCOMPLETE"


def test_synthetic_failover_ref_blocks():
    private, anchor = _keypair(); policy = _policy(); bad = _attestation(private, policy, failover_evidence_ref="synthetic:failover")
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=bad, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "INVALID_FAILOVER_REFERENCE"


def test_role_separation_blocks():
    private, anchor = _keypair(); policy = _policy(); bad = _attestation(private, policy, reviewer_id="custodian-1")
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=bad, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "DR_ROLE_SEPARATION_VIOLATION"


def test_reviewer_key_scope_blocks():
    private, anchor = _keypair(); policy = _policy();
    wrong_scope = ReviewerTrustAnchorV395(**{**anchor.__dict__, "allowed_scopes": ("OTHER",)})
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=_attestation(private, policy), reviewer_anchor=wrong_scope, now_ms=2_000)
    assert not d.allowed and d.reason == "REVIEWER_SCOPE_NOT_ALLOWED"


def test_invalid_signature_blocks():
    private, anchor = _keypair(); policy = _policy(); att = _attestation(private, policy)
    bad_sig = base64.b64encode(b"0" * 64).decode()
    tampered = ExternalDRAttestationV396(**{**att.__dict__, "signature_b64": bad_sig, "signature_hash": hashlib.sha256(b"0" * 64).hexdigest()})
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=tampered, reviewer_anchor=anchor, now_ms=2_000)
    assert not d.allowed and d.reason == "DR_REVIEWER_SIGNATURE_INVALID"


def test_expired_attestation_blocks():
    private, anchor = _keypair(); policy = _policy(); att = _attestation(private, policy, attested_at_ms=1_000, expires_at_ms=1_500)
    d = ExternalDRAttestationAuthorityV396().intake(policy=policy, attestation=att, reviewer_anchor=anchor, now_ms=1_500)
    assert not d.allowed and d.status is DRAttestationStatusV396.EXPIRED


def test_sensitive_material_rejected():
    from trading_platform.v396.dr_attestation import _reject_sensitive, DRAttestationErrorV396
    try:
        _reject_sensitive({"private_key": "never-store"})
    except DRAttestationErrorV396 as exc:
        assert str(exc) == "SENSITIVE_DR_ATTESTATION_FIELD:root.private_key"
    else:
        raise AssertionError("sensitive field was accepted")


def test_idempotent_acceptance_and_restart_safe_read():
    private, anchor = _keypair(); policy = _policy(); store = EventStore(); authority = ExternalDRAttestationAuthorityV396(store); att = _attestation(private, policy)
    first = authority.intake(policy=policy, attestation=att, reviewer_anchor=anchor, now_ms=2_000)
    second = authority.intake(policy=policy, attestation=att, reviewer_anchor=anchor, now_ms=2_001)
    assert first.allowed and second.allowed
    assert store.verify_chain()
    assert authority.get(att.attestation_id) is not None


def test_no_private_key_field_in_safe_payload():
    private, anchor = _keypair(); policy = _policy(); att = _attestation(private, policy)
    payload = att.safe_payload()
    assert "private_key" not in str(payload).lower()
    assert "signature_b64" not in payload
