"""V3.97 external security + monitoring operational readiness attestation.

This authority admits external readiness evidence only when:
- security assessment is bound to the exact runtime policy and release hash;
- no unresolved CRITICAL/HIGH security findings remain;
- monitoring evidence covers all registered critical signals;
- alert delivery and on-call response stay within hard ceilings;
- both attestations are external, signed by trusted independent reviewers,
  valid, scope-compatible and free of sensitive material;
- both attestations reference the same release artifact hash;
- the final acceptance is durable and idempotent.

It does not manufacture infrastructure/security evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
import base64
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.v21.event_store import EventStore
from trading_platform.v361.evidence_package import canonical_json
from trading_platform.v395.trust_anchor_attestation import (
    ReviewerTrustAnchorV395,
    TrustAttestationErrorV395,
)


class ReadinessAttestationErrorV397(ValueError):
    __test__ = False


class ReadinessStatusV397(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    NOT_VERIFIED = "NOT_VERIFIED"


def _sha256_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _canonical(value: Mapping[str, Any]) -> bytes:
    return canonical_json(value)


def _b64decode(value: str, *, field: str) -> bytes:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except Exception as exc:
        raise ReadinessAttestationErrorV397(f"{field}_BASE64_INVALID") from exc
    if not raw:
        raise ReadinessAttestationErrorV397(f"{field}_EMPTY")
    return raw


def _reject_sensitive(value: Any, path: str = "root") -> None:
    forbidden = {
        "secret", "secrets", "private_key", "api_key", "api_secret", "password",
        "token", "credential", "credentials", "access_token", "refresh_token",
        "mnemonic", "seed_phrase",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in forbidden or any(fragment in lowered for fragment in ("private_key", "api_secret", "password", "seed_phrase")):
                raise ReadinessAttestationErrorV397(f"SENSITIVE_READINESS_FIELD:{path}.{key}")
            _reject_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, nested in enumerate(value):
            _reject_sensitive(nested, f"{path}[{idx}]")


def _reject_synthetic(ref: str, field: str) -> None:
    if not ref or ref.startswith(("demo:", "synthetic:", "fixture:", "mock:")):
        raise ReadinessAttestationErrorV397(f"INVALID_{field}_REFERENCE")


def _verify_signature(attestation: Any, reviewer_anchor: ReviewerTrustAnchorV395) -> None:
    if reviewer_anchor.reviewer_key_id != attestation.reviewer_key_id:
        raise ReadinessAttestationErrorV397("REVIEWER_KEY_ID_MISMATCH")
    reviewer_anchor.validate(scope=attestation.scope, now_ms=attestation.reviewed_at_ms)
    try:
        Ed25519PublicKey.from_public_bytes(reviewer_anchor.public_key_bytes()).verify(
            attestation.signature_bytes(), _canonical(attestation.body_for_hash())
        )
    except InvalidSignature as exc:
        raise ReadinessAttestationErrorV397(f"{attestation.kind}_SIGNATURE_INVALID") from exc


@dataclass(frozen=True)
class SecurityAssessmentPolicyV397:
    policy_version: str
    scope: str
    required_methodology_version: str
    max_open_critical: int
    max_open_high: int
    max_ttl_ms: int
    policy_hash: str

    def body(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "scope": self.scope,
            "required_methodology_version": self.required_methodology_version,
            "max_open_critical": self.max_open_critical,
            "max_open_high": self.max_open_high,
            "max_ttl_ms": self.max_ttl_ms,
        }

    def computed_hash(self) -> str:
        return _sha256_bytes(_canonical(self.body()))

    def validate(self) -> None:
        if not self.policy_version or not self.scope or not self.required_methodology_version:
            raise ReadinessAttestationErrorV397("SECURITY_POLICY_INCOMPLETE")
        if self.max_open_critical < 0 or self.max_open_high < 0 or self.max_ttl_ms <= 0:
            raise ReadinessAttestationErrorV397("SECURITY_POLICY_INVALID")
        if self.policy_hash != self.computed_hash():
            raise ReadinessAttestationErrorV397("SECURITY_POLICY_HASH_MISMATCH")


@dataclass(frozen=True)
class MonitoringPolicyV397:
    policy_version: str
    scope: str
    required_signal_codes: tuple[str, ...]
    max_delivery_latency_ms: int
    max_oncall_response_ms: int
    max_unresolved_critical_alerts: int
    max_ttl_ms: int
    policy_hash: str

    def body(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "scope": self.scope,
            "required_signal_codes": sorted(self.required_signal_codes),
            "max_delivery_latency_ms": self.max_delivery_latency_ms,
            "max_oncall_response_ms": self.max_oncall_response_ms,
            "max_unresolved_critical_alerts": self.max_unresolved_critical_alerts,
            "max_ttl_ms": self.max_ttl_ms,
        }

    def computed_hash(self) -> str:
        return _sha256_bytes(_canonical(self.body()))

    def validate(self) -> None:
        if not self.policy_version or not self.scope or not self.required_signal_codes:
            raise ReadinessAttestationErrorV397("MONITORING_POLICY_INCOMPLETE")
        if len(set(self.required_signal_codes)) != len(self.required_signal_codes):
            raise ReadinessAttestationErrorV397("MONITORING_POLICY_DUPLICATE_SIGNAL")
        if self.max_delivery_latency_ms < 0 or self.max_oncall_response_ms < 0 or self.max_unresolved_critical_alerts < 0 or self.max_ttl_ms <= 0:
            raise ReadinessAttestationErrorV397("MONITORING_POLICY_INVALID")
        if self.policy_hash != self.computed_hash():
            raise ReadinessAttestationErrorV397("MONITORING_POLICY_HASH_MISMATCH")


@dataclass(frozen=True)
class ExternalSecurityAssessmentV397:
    assessment_id: str
    kind: str
    scope: str
    policy_version: str
    policy_hash: str
    methodology_version: str
    release_artifact_hash: str
    code_version: str
    open_critical_findings: int
    open_high_findings: int
    evidence_ref: str
    remediation_evidence_ref: str
    source_system: str
    reviewer_id: str
    reviewer_key_id: str
    reviewed_at_ms: int
    expires_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "ACCEPT"

    @property
    def kind_name(self) -> str:
        return "SECURITY_ASSESSMENT"

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "kind": self.kind,
            "scope": self.scope,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "methodology_version": self.methodology_version,
            "release_artifact_hash": self.release_artifact_hash,
            "code_version": self.code_version,
            "open_critical_findings": self.open_critical_findings,
            "open_high_findings": self.open_high_findings,
            "evidence_ref": self.evidence_ref,
            "remediation_evidence_ref": self.remediation_evidence_ref,
            "source_system": self.source_system,
            "reviewer_id": self.reviewer_id,
            "reviewer_key_id": self.reviewer_key_id,
            "reviewed_at_ms": self.reviewed_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "decision": self.decision,
        }

    def signature_bytes(self) -> bytes:
        return _b64decode(self.signature_b64, field="SECURITY_SIGNATURE")

    def signature_hash_value(self) -> str:
        return _sha256_bytes(self.signature_bytes())

    def validate(self, *, policy: SecurityAssessmentPolicyV397, now_ms: int) -> None:
        _reject_sensitive(self.body_for_hash())
        if self.kind != self.kind_name:
            raise ReadinessAttestationErrorV397("SECURITY_ASSESSMENT_KIND_INVALID")
        if self.decision != "ACCEPT":
            raise ReadinessAttestationErrorV397("SECURITY_ASSESSMENT_DECISION_NOT_ACCEPT")
        if any(not str(v) for v in (self.assessment_id, self.scope, self.policy_version, self.policy_hash, self.release_artifact_hash, self.code_version, self.evidence_ref, self.source_system, self.reviewer_id, self.reviewer_key_id)):
            raise ReadinessAttestationErrorV397("SECURITY_ASSESSMENT_IDENTIFIERS_REQUIRED")
        _reject_synthetic(self.evidence_ref, "SECURITY_EVIDENCE")
        _reject_synthetic(self.remediation_evidence_ref, "SECURITY_REMEDIATION_EVIDENCE")
        if self.scope != policy.scope or self.policy_version != policy.policy_version or self.policy_hash != policy.policy_hash:
            raise ReadinessAttestationErrorV397("SECURITY_POLICY_REFERENCE_MISMATCH")
        if self.methodology_version != policy.required_methodology_version:
            raise ReadinessAttestationErrorV397("SECURITY_METHODOLOGY_MISMATCH")
        if self.open_critical_findings > policy.max_open_critical:
            raise ReadinessAttestationErrorV397("SECURITY_CRITICAL_FINDINGS_OPEN")
        if self.open_high_findings > policy.max_open_high:
            raise ReadinessAttestationErrorV397("SECURITY_HIGH_FINDINGS_OPEN")
        if self.reviewed_at_ms >= self.expires_at_ms or self.expires_at_ms - self.reviewed_at_ms > policy.max_ttl_ms:
            raise ReadinessAttestationErrorV397("SECURITY_ATTESTATION_TTL_INVALID")
        if not (self.reviewed_at_ms <= now_ms < self.expires_at_ms):
            raise ReadinessAttestationErrorV397("SECURITY_ATTESTATION_EXPIRED")
        if self.signature_hash != self.signature_hash_value():
            raise ReadinessAttestationErrorV397("SECURITY_SIGNATURE_HASH_MISMATCH")

    def safe_payload(self) -> dict[str, Any]:
        return {
            **self.body_for_hash(),
            "signature_hash": self.signature_hash,
            "attestation_hash": _sha256_bytes(_canonical(self.body_for_hash())),
        }


@dataclass(frozen=True)
class ExternalMonitoringAttestationV397:
    attestation_id: str
    kind: str
    scope: str
    policy_version: str
    policy_hash: str
    release_artifact_hash: str
    observed_signal_codes: tuple[str, ...]
    observed_delivery_latency_ms: int
    observed_oncall_response_ms: int
    unresolved_critical_alerts: int
    drill_evidence_ref: str
    paging_evidence_ref: str
    dashboard_evidence_ref: str
    source_system: str
    reviewer_id: str
    reviewer_key_id: str
    reviewed_at_ms: int
    expires_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "ACCEPT"

    kind_name = "MONITORING_ATTESTATION"

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "kind": self.kind,
            "scope": self.scope,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "release_artifact_hash": self.release_artifact_hash,
            "observed_signal_codes": sorted(self.observed_signal_codes),
            "observed_delivery_latency_ms": self.observed_delivery_latency_ms,
            "observed_oncall_response_ms": self.observed_oncall_response_ms,
            "unresolved_critical_alerts": self.unresolved_critical_alerts,
            "drill_evidence_ref": self.drill_evidence_ref,
            "paging_evidence_ref": self.paging_evidence_ref,
            "dashboard_evidence_ref": self.dashboard_evidence_ref,
            "source_system": self.source_system,
            "reviewer_id": self.reviewer_id,
            "reviewer_key_id": self.reviewer_key_id,
            "reviewed_at_ms": self.reviewed_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "decision": self.decision,
        }

    def signature_bytes(self) -> bytes:
        return _b64decode(self.signature_b64, field="MONITORING_SIGNATURE")

    def signature_hash_value(self) -> str:
        return _sha256_bytes(self.signature_bytes())

    def validate(self, *, policy: MonitoringPolicyV397, now_ms: int) -> None:
        _reject_sensitive(self.body_for_hash())
        if self.kind != self.kind_name:
            raise ReadinessAttestationErrorV397("MONITORING_ATTESTATION_KIND_INVALID")
        if self.decision != "ACCEPT":
            raise ReadinessAttestationErrorV397("MONITORING_ATTESTATION_DECISION_NOT_ACCEPT")
        if any(not str(v) for v in (self.attestation_id, self.scope, self.policy_version, self.policy_hash, self.release_artifact_hash, self.drill_evidence_ref, self.paging_evidence_ref, self.dashboard_evidence_ref, self.source_system, self.reviewer_id, self.reviewer_key_id)):
            raise ReadinessAttestationErrorV397("MONITORING_ATTESTATION_IDENTIFIERS_REQUIRED")
        for field, ref in (("MONITORING_DRILL", self.drill_evidence_ref), ("PAGING", self.paging_evidence_ref), ("DASHBOARD", self.dashboard_evidence_ref)):
            _reject_synthetic(ref, field)
        if self.scope != policy.scope or self.policy_version != policy.policy_version or self.policy_hash != policy.policy_hash:
            raise ReadinessAttestationErrorV397("MONITORING_POLICY_REFERENCE_MISMATCH")
        missing = set(policy.required_signal_codes) - set(self.observed_signal_codes)
        if missing:
            raise ReadinessAttestationErrorV397("MONITORING_SIGNAL_COVERAGE_INCOMPLETE")
        if self.observed_delivery_latency_ms > policy.max_delivery_latency_ms:
            raise ReadinessAttestationErrorV397("MONITORING_DELIVERY_LATENCY_BREACH")
        if self.observed_oncall_response_ms > policy.max_oncall_response_ms:
            raise ReadinessAttestationErrorV397("MONITORING_ONCALL_RESPONSE_BREACH")
        if self.unresolved_critical_alerts > policy.max_unresolved_critical_alerts:
            raise ReadinessAttestationErrorV397("MONITORING_CRITICAL_ALERTS_UNRESOLVED")
        if self.reviewed_at_ms >= self.expires_at_ms or self.expires_at_ms - self.reviewed_at_ms > policy.max_ttl_ms:
            raise ReadinessAttestationErrorV397("MONITORING_ATTESTATION_TTL_INVALID")
        if not (self.reviewed_at_ms <= now_ms < self.expires_at_ms):
            raise ReadinessAttestationErrorV397("MONITORING_ATTESTATION_EXPIRED")
        if self.signature_hash != self.signature_hash_value():
            raise ReadinessAttestationErrorV397("MONITORING_SIGNATURE_HASH_MISMATCH")

    def safe_payload(self) -> dict[str, Any]:
        return {
            **self.body_for_hash(),
            "signature_hash": self.signature_hash,
            "attestation_hash": _sha256_bytes(_canonical(self.body_for_hash())),
        }


@dataclass(frozen=True)
class SecurityMonitoringReadinessDecisionV397:
    allowed: bool
    reason: str
    readiness_id: str
    release_artifact_hash: str
    status: ReadinessStatusV397
    security_attestation_id: str | None
    monitoring_attestation_id: str | None


class SecurityMonitoringReadinessAuthorityV397:
    EVENT_TYPE = "SECURITY_MONITORING_READINESS_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def admit(
        self,
        *,
        readiness_id: str,
        release_artifact_hash: str,
        security_policy: SecurityAssessmentPolicyV397,
        monitoring_policy: MonitoringPolicyV397,
        security_attestation: ExternalSecurityAssessmentV397,
        monitoring_attestation: ExternalMonitoringAttestationV397,
        security_reviewer_anchor: ReviewerTrustAnchorV395,
        monitoring_reviewer_anchor: ReviewerTrustAnchorV395,
        now_ms: int,
    ) -> SecurityMonitoringReadinessDecisionV397:
        status = ReadinessStatusV397.REJECTED
        try:
            if not readiness_id or not release_artifact_hash:
                raise ReadinessAttestationErrorV397("READINESS_IDENTIFIERS_REQUIRED")
            security_policy.validate()
            monitoring_policy.validate()
            security_attestation.validate(policy=security_policy, now_ms=now_ms)
            monitoring_attestation.validate(policy=monitoring_policy, now_ms=now_ms)
            if security_attestation.release_artifact_hash != release_artifact_hash or monitoring_attestation.release_artifact_hash != release_artifact_hash:
                raise ReadinessAttestationErrorV397("READINESS_RELEASE_HASH_MISMATCH")
            if security_attestation.reviewer_id == monitoring_attestation.reviewer_id:
                raise ReadinessAttestationErrorV397("READINESS_REVIEWER_INDEPENDENCE_VIOLATION")
            if security_attestation.source_system == monitoring_attestation.source_system:
                raise ReadinessAttestationErrorV397("READINESS_SOURCE_INDEPENDENCE_VIOLATION")
            _verify_signature(security_attestation, security_reviewer_anchor)
            _verify_signature(monitoring_attestation, monitoring_reviewer_anchor)
            status = ReadinessStatusV397.VERIFIED
            event_id = f"security-monitoring-readiness:{readiness_id}:accepted"
            payload = {
                "readiness_id": readiness_id,
                "release_artifact_hash": release_artifact_hash,
                "security_policy_hash": security_policy.policy_hash,
                "monitoring_policy_hash": monitoring_policy.policy_hash,
                "security_attestation_id": security_attestation.assessment_id,
                "monitoring_attestation_id": monitoring_attestation.attestation_id,
                "security_attestation_hash": security_attestation.safe_payload()["attestation_hash"],
                "monitoring_attestation_hash": monitoring_attestation.safe_payload()["attestation_hash"],
                "security_reviewer_id": security_attestation.reviewer_id,
                "monitoring_reviewer_id": monitoring_attestation.reviewer_id,
                "security_reviewer_key_fingerprint": security_reviewer_anchor.fingerprint,
                "monitoring_reviewer_key_fingerprint": monitoring_reviewer_anchor.fingerprint,
                "status": status.value,
            }
            existing = self.store.get(event_id)
            if existing is None:
                self.store.append(event_id=event_id, occurred_at_ms=now_ms, event_type=self.EVENT_TYPE, aggregate_id=readiness_id, payload=payload)
            elif dict(existing.payload) != payload:
                raise ReadinessAttestationErrorV397("READINESS_EVENT_ID_CONFLICT")
            return SecurityMonitoringReadinessDecisionV397(True, "SECURITY_MONITORING_READINESS_ACCEPTED", readiness_id, release_artifact_hash, status, security_attestation.assessment_id, monitoring_attestation.attestation_id)
        except (ReadinessAttestationErrorV397, TrustAttestationErrorV395) as exc:
            if "EXPIRED" in str(exc):
                status = ReadinessStatusV397.EXPIRED
            return SecurityMonitoringReadinessDecisionV397(False, str(exc), readiness_id, release_artifact_hash, status, security_attestation.assessment_id, monitoring_attestation.attestation_id)

    def get(self, readiness_id: str):
        return self.store.get(f"security-monitoring-readiness:{readiness_id}:accepted")

    def verify_chain(self) -> bool:
        return self.store.verify_chain()
