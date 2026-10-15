from __future__ import annotations

import base64
import hashlib
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import canonical_json
from trading_platform.v395.trust_anchor_attestation import ReviewerKeyStatusV395, ReviewerTrustAnchorV395
from trading_platform.v397.readiness_attestation import (
    ExternalMonitoringAttestationV397,
    ExternalSecurityAssessmentV397,
    MonitoringPolicyV397,
    ReadinessStatusV397,
    SecurityAssessmentPolicyV397,
    SecurityMonitoringReadinessAuthorityV397,
)

NOW = 2_000
RELEASE_HASH = "f" * 64


def _anchor(key_id: str, scope: str, private: Ed25519PrivateKey):
    public = private.public_key().public_bytes_raw()
    return ReviewerTrustAnchorV395(
        reviewer_key_id=key_id,
        public_key_b64=base64.b64encode(public).decode(),
        valid_from_ms=100,
        expires_at_ms=100_000,
        status=ReviewerKeyStatusV395.ACTIVE,
        allowed_scopes=(scope,),
        fingerprint=hashlib.sha256(public).hexdigest(),
    )


def _security_policy():
    p = SecurityAssessmentPolicyV397("SEC-POL-397", "PRODUCTION_SECURITY_MONITORING", "SEC-METHOD-1", 0, 0, 7_200_000, "")
    return SecurityAssessmentPolicyV397(p.policy_version, p.scope, p.required_methodology_version, p.max_open_critical, p.max_open_high, p.max_ttl_ms, p.computed_hash())


def _monitoring_policy():
    p = MonitoringPolicyV397("MON-POL-397", "PRODUCTION_SECURITY_MONITORING", ("STALE_MARKET_DATA", "RECONCILIATION_MISMATCH", "RISK_HALT", "SECURITY_BOUNDARY_VIOLATION"), 5_000, 30_000, 0, 7_200_000, "")
    return MonitoringPolicyV397(p.policy_version, p.scope, p.required_signal_codes, p.max_delivery_latency_ms, p.max_oncall_response_ms, p.max_unresolved_critical_alerts, p.max_ttl_ms, p.computed_hash())


def _sign(body: dict, private: Ed25519PrivateKey):
    sig = private.sign(canonical_json(body))
    return base64.b64encode(sig).decode(), hashlib.sha256(sig).hexdigest()


def _security(private, policy, **overrides):
    b = dict(
        assessment_id="SEC-397-1", kind="SECURITY_ASSESSMENT", scope=policy.scope,
        policy_version=policy.policy_version, policy_hash=policy.policy_hash,
        methodology_version=policy.required_methodology_version, release_artifact_hash=RELEASE_HASH,
        code_version="v3.97", open_critical_findings=0, open_high_findings=0,
        evidence_ref="ops://security/assessment/397", remediation_evidence_ref="ops://security/remediation/397",
        source_system="external-security-assessor", reviewer_id="security-reviewer", reviewer_key_id="key-sec-397",
        reviewed_at_ms=1_000, expires_at_ms=10_000, signature_b64="", signature_hash="",
    )
    b.update(overrides)
    unsigned = ExternalSecurityAssessmentV397(**b)
    sig_b64, sig_hash = _sign(unsigned.body_for_hash(), private)
    return ExternalSecurityAssessmentV397(**{**b, "signature_b64": sig_b64, "signature_hash": sig_hash})


def _monitoring(private, policy, **overrides):
    b = dict(
        attestation_id="MON-397-1", kind="MONITORING_ATTESTATION", scope=policy.scope,
        policy_version=policy.policy_version, policy_hash=policy.policy_hash, release_artifact_hash=RELEASE_HASH,
        observed_signal_codes=policy.required_signal_codes, observed_delivery_latency_ms=1_000,
        observed_oncall_response_ms=10_000, unresolved_critical_alerts=0,
        drill_evidence_ref="ops://monitoring/drill/397", paging_evidence_ref="ops://monitoring/paging/397",
        dashboard_evidence_ref="ops://monitoring/dashboard/397", source_system="external-monitoring-assessor",
        reviewer_id="monitoring-reviewer", reviewer_key_id="key-mon-397", reviewed_at_ms=1_000,
        expires_at_ms=10_000, signature_b64="", signature_hash="",
    )
    b.update(overrides)
    unsigned = ExternalMonitoringAttestationV397(**b)
    sig_b64, sig_hash = _sign(unsigned.body_for_hash(), private)
    return ExternalMonitoringAttestationV397(**{**b, "signature_b64": sig_b64, "signature_hash": sig_hash})


def _fixture():
    sec_private = Ed25519PrivateKey.generate(); mon_private = Ed25519PrivateKey.generate()
    sec_policy = _security_policy(); mon_policy = _monitoring_policy()
    sec_anchor = _anchor("key-sec-397", sec_policy.scope, sec_private)
    mon_anchor = _anchor("key-mon-397", mon_policy.scope, mon_private)
    sec = _security(sec_private, sec_policy); mon = _monitoring(mon_private, mon_policy)
    authority = SecurityMonitoringReadinessAuthorityV397(EventStore())
    return authority, sec_policy, mon_policy, sec, mon, sec_anchor, mon_anchor


def test_accepts_complete_security_and_monitoring_readiness():
    authority, sp, mp, sec, mon, sa, ma = _fixture()
    d = authority.admit(readiness_id="READY-397-1", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=mon, security_reviewer_anchor=sa, monitoring_reviewer_anchor=ma, now_ms=NOW)
    assert d.allowed and d.status is ReadinessStatusV397.VERIFIED


def test_security_critical_finding_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); bad = _security(Ed25519PrivateKey.generate(), sp, open_critical_findings=1)
    # Rebuild a valid anchor for the replacement signature.
    p = Ed25519PrivateKey.generate(); bad = _security(p, sp, open_critical_findings=1); anchor = _anchor("key-sec-397", sp.scope, p)
    d = authority.admit(readiness_id="READY-397-2", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=bad, monitoring_attestation=mon, security_reviewer_anchor=anchor, monitoring_reviewer_anchor=ma, now_ms=NOW)
    assert not d.allowed and d.reason == "SECURITY_CRITICAL_FINDINGS_OPEN"


def test_security_high_finding_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _security(p, sp, open_high_findings=1); anchor = _anchor("key-sec-397", sp.scope, p)
    d = authority.admit(readiness_id="READY-397-3", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=bad, monitoring_attestation=mon, security_reviewer_anchor=anchor, monitoring_reviewer_anchor=ma, now_ms=NOW)
    assert not d.allowed and d.reason == "SECURITY_HIGH_FINDINGS_OPEN"


def test_monitoring_signal_coverage_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, observed_signal_codes=("STALE_MARKET_DATA",)); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-4", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "MONITORING_SIGNAL_COVERAGE_INCOMPLETE"


def test_monitoring_latency_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, observed_delivery_latency_ms=5_001); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-5", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "MONITORING_DELIVERY_LATENCY_BREACH"


def test_monitoring_oncall_response_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, observed_oncall_response_ms=30_001); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-6", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "MONITORING_ONCALL_RESPONSE_BREACH"


def test_unresolved_critical_alerts_block():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, unresolved_critical_alerts=1); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-7", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "MONITORING_CRITICAL_ALERTS_UNRESOLVED"


def test_release_hash_mismatch_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, release_artifact_hash="e" * 64); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-8", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "READINESS_RELEASE_HASH_MISMATCH"


def test_reviewers_must_be_distinct():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, reviewer_id="security-reviewer"); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-9", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "READINESS_REVIEWER_INDEPENDENCE_VIOLATION"


def test_sources_must_be_distinct():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, source_system=sec.source_system); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-10", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=NOW)
    assert not d.allowed and d.reason == "READINESS_SOURCE_INDEPENDENCE_VIOLATION"


def test_invalid_signature_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture()
    bad = ExternalMonitoringAttestationV397(**{**mon.__dict__, "signature_b64": base64.b64encode(b"0" * 64).decode(), "signature_hash": hashlib.sha256(b"0" * 64).hexdigest()})
    d = authority.admit(readiness_id="READY-397-11", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=ma, now_ms=NOW)
    assert not d.allowed and d.reason == "MONITORING_ATTESTATION_SIGNATURE_INVALID"


def test_expired_attestation_blocks():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); p = Ed25519PrivateKey.generate(); bad = _monitoring(p, mp, reviewed_at_ms=1_000, expires_at_ms=1_500); anchor = _anchor("key-mon-397", mp.scope, p)
    d = authority.admit(readiness_id="READY-397-12", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=bad, security_reviewer_anchor=sa, monitoring_reviewer_anchor=anchor, now_ms=1_500)
    assert not d.allowed and d.status is ReadinessStatusV397.EXPIRED


def test_idempotent_durable_acceptance():
    authority, sp, mp, sec, mon, sa, ma = _fixture(); first = authority.admit(readiness_id="READY-397-13", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=mon, security_reviewer_anchor=sa, monitoring_reviewer_anchor=ma, now_ms=NOW); second = authority.admit(readiness_id="READY-397-13", release_artifact_hash=RELEASE_HASH, security_policy=sp, monitoring_policy=mp, security_attestation=sec, monitoring_attestation=mon, security_reviewer_anchor=sa, monitoring_reviewer_anchor=ma, now_ms=NOW + 1)
    assert first.allowed and second.allowed and authority.verify_chain()


def test_sensitive_material_rejected():
    from trading_platform.v397.readiness_attestation import _reject_sensitive, ReadinessAttestationErrorV397
    try:
        _reject_sensitive({"api_secret": "do-not-store"})
    except ReadinessAttestationErrorV397 as exc:
        assert str(exc) == "SENSITIVE_READINESS_FIELD:root.api_secret"
    else:
        raise AssertionError("sensitive field accepted")
