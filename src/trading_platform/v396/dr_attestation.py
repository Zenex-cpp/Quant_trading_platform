"""V3.96 external operational backup/DR attestation intake.

This module admits externally produced DR evidence only when the exact runtime
DR policy snapshot is covered, observed RPO/RTO satisfy the hard policy, failover
and failback references are non-synthetic, and an independent trusted reviewer
signs the canonical attestation body. It never manufactures infrastructure proof.
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


class DRAttestationErrorV396(ValueError):
    __test__ = False


class DRAttestationStatusV396(str, Enum):
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
        raise DRAttestationErrorV396(f"{field}_BASE64_INVALID") from exc
    if not raw:
        raise DRAttestationErrorV396(f"{field}_EMPTY")
    return raw


def _reject_sensitive(value: Any, path: str = "root") -> None:
    forbidden = {
        "secret", "secrets", "private_key", "api_key", "api_secret", "password",
        "token", "credential", "credentials", "mnemonic", "seed_phrase",
    }
    if isinstance(value, Mapping):
        for key, nested in value.items():
            lowered = str(key).lower()
            if lowered in forbidden or any(fragment in lowered for fragment in ("private_key", "api_secret", "password", "seed_phrase")):
                raise DRAttestationErrorV396(f"SENSITIVE_DR_ATTESTATION_FIELD:{path}.{key}")
            _reject_sensitive(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for idx, nested in enumerate(value):
            _reject_sensitive(nested, f"{path}[{idx}]")


def _reject_synthetic(ref: str, field: str) -> None:
    if not ref or ref.startswith(("demo:", "synthetic:", "fixture:", "mock:")):
        raise DRAttestationErrorV396(f"INVALID_{field}_REFERENCE")


@dataclass(frozen=True)
class DRPolicySnapshotV396:
    policy_version: str
    scope: str
    required_rpo_seconds: int
    required_rto_seconds: int
    policy_hash: str

    def body(self) -> dict[str, Any]:
        return {
            "policy_version": self.policy_version,
            "scope": self.scope,
            "required_rpo_seconds": self.required_rpo_seconds,
            "required_rto_seconds": self.required_rto_seconds,
        }

    def computed_hash(self) -> str:
        return _sha256_bytes(_canonical(self.body()))

    def validate(self) -> None:
        if not self.policy_version or not self.scope:
            raise DRAttestationErrorV396("DR_POLICY_SNAPSHOT_INCOMPLETE")
        if self.required_rpo_seconds < 0 or self.required_rto_seconds < 0:
            raise DRAttestationErrorV396("DR_POLICY_THRESHOLD_INVALID")
        if self.policy_hash != self.computed_hash():
            raise DRAttestationErrorV396("DR_POLICY_HASH_MISMATCH")


@dataclass(frozen=True)
class ExternalDRAttestationV396:
    attestation_id: str
    scope: str
    policy_version: str
    policy_hash: str
    backup_artifact_hash: str
    restore_evidence_hash: str
    observed_rpo_seconds: int
    observed_rto_seconds: int
    failover_evidence_ref: str
    failback_evidence_ref: str
    recovery_proof_ref: str
    recovery_state_reconciled: bool
    recovery_invariants_pass: bool
    no_unresolved_critical_issue: bool
    recovery_guards_pass: bool
    operator_id: str
    custodian_id: str
    reviewer_id: str
    reviewer_key_id: str
    attested_at_ms: int
    expires_at_ms: int
    signature_b64: str
    signature_hash: str
    decision: str = "ACCEPT"

    def body_for_hash(self) -> dict[str, Any]:
        return {
            "attestation_id": self.attestation_id,
            "scope": self.scope,
            "policy_version": self.policy_version,
            "policy_hash": self.policy_hash,
            "backup_artifact_hash": self.backup_artifact_hash,
            "restore_evidence_hash": self.restore_evidence_hash,
            "observed_rpo_seconds": self.observed_rpo_seconds,
            "observed_rto_seconds": self.observed_rto_seconds,
            "failover_evidence_ref": self.failover_evidence_ref,
            "failback_evidence_ref": self.failback_evidence_ref,
            "recovery_proof_ref": self.recovery_proof_ref,
            "recovery_state_reconciled": self.recovery_state_reconciled,
            "recovery_invariants_pass": self.recovery_invariants_pass,
            "no_unresolved_critical_issue": self.no_unresolved_critical_issue,
            "recovery_guards_pass": self.recovery_guards_pass,
            "operator_id": self.operator_id,
            "custodian_id": self.custodian_id,
            "reviewer_id": self.reviewer_id,
            "reviewer_key_id": self.reviewer_key_id,
            "attested_at_ms": self.attested_at_ms,
            "expires_at_ms": self.expires_at_ms,
            "decision": self.decision,
        }

    def computed_attestation_hash(self) -> str:
        return _sha256_bytes(_canonical(self.body_for_hash()))

    def signature_bytes(self) -> bytes:
        return _b64decode(self.signature_b64, field="DR_ATTESTATION_SIGNATURE")

    def validate_structure(self, *, now_ms: int, max_ttl_ms: int = 7 * 24 * 3600 * 1000) -> None:
        _reject_sensitive(self.body_for_hash())
        required = (
            self.attestation_id, self.scope, self.policy_version, self.policy_hash,
            self.backup_artifact_hash, self.restore_evidence_hash,
            self.failover_evidence_ref, self.failback_evidence_ref,
            self.recovery_proof_ref, self.operator_id, self.custodian_id,
            self.reviewer_id, self.reviewer_key_id, self.signature_hash,
        )
        if any(not str(value) for value in required):
            raise DRAttestationErrorV396("DR_ATTESTATION_IDENTIFIERS_REQUIRED")
        if self.decision != "ACCEPT":
            raise DRAttestationErrorV396("DR_ATTESTATION_DECISION_NOT_ACCEPT")
        for field, ref in (
            ("FAILOVER", self.failover_evidence_ref),
            ("FAILBACK", self.failback_evidence_ref),
            ("RECOVERY_PROOF", self.recovery_proof_ref),
        ):
            _reject_synthetic(ref, field)
        if self.operator_id == self.custodian_id or self.reviewer_id in {self.operator_id, self.custodian_id}:
            raise DRAttestationErrorV396("DR_ROLE_SEPARATION_VIOLATION")
        if self.observed_rpo_seconds < 0 or self.observed_rto_seconds < 0:
            raise DRAttestationErrorV396("OBSERVED_RPO_RTO_INVALID")
        if not all((self.recovery_state_reconciled, self.recovery_invariants_pass, self.no_unresolved_critical_issue, self.recovery_guards_pass)):
            raise DRAttestationErrorV396("RECOVERY_PROOF_INCOMPLETE")
        if not (self.attested_at_ms < self.expires_at_ms and self.expires_at_ms - self.attested_at_ms <= max_ttl_ms):
            raise DRAttestationErrorV396("DR_ATTESTATION_VALIDITY_INVALID")
        if not (self.attested_at_ms <= now_ms < self.expires_at_ms):
            raise DRAttestationErrorV396("DR_ATTESTATION_EXPIRED")
        if _sha256_bytes(self.signature_bytes()) != self.signature_hash:
            raise DRAttestationErrorV396("DR_SIGNATURE_HASH_MISMATCH")

    def safe_payload(self) -> dict[str, Any]:
        return {
            **self.body_for_hash(),
            "signature_hash": self.signature_hash,
            "attestation_fingerprint": _sha256_bytes(_canonical({"attestation_id": self.attestation_id, "policy_hash": self.policy_hash})),
        }


@dataclass(frozen=True)
class DRAttestationDecisionV396:
    allowed: bool
    reason: str
    attestation_id: str
    policy_version: str
    policy_hash: str
    status: DRAttestationStatusV396
    reviewer_id: str | None


class ExternalDRAttestationAuthorityV396:
    EVENT_TYPE = "EXTERNAL_DR_ATTESTATION_ACCEPTED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def intake(
        self,
        *,
        policy: DRPolicySnapshotV396,
        attestation: ExternalDRAttestationV396,
        reviewer_anchor: ReviewerTrustAnchorV395,
        now_ms: int,
    ) -> DRAttestationDecisionV396:
        status = DRAttestationStatusV396.REJECTED
        try:
            policy.validate()
            attestation.validate_structure(now_ms=now_ms)
            if attestation.scope != policy.scope or attestation.policy_version != policy.policy_version or attestation.policy_hash != policy.policy_hash:
                raise DRAttestationErrorV396("DR_POLICY_REFERENCE_MISMATCH")
            if attestation.observed_rpo_seconds > policy.required_rpo_seconds:
                raise DRAttestationErrorV396("RPO_BREACH")
            if attestation.observed_rto_seconds > policy.required_rto_seconds:
                raise DRAttestationErrorV396("RTO_BREACH")
            reviewer_anchor.validate(scope=attestation.scope, now_ms=now_ms)
            if reviewer_anchor.reviewer_key_id != attestation.reviewer_key_id:
                raise DRAttestationErrorV396("REVIEWER_KEY_ID_MISMATCH")
            try:
                Ed25519PublicKey.from_public_bytes(reviewer_anchor.public_key_bytes()).verify(
                    attestation.signature_bytes(), _canonical(attestation.body_for_hash())
                )
            except InvalidSignature as exc:
                raise DRAttestationErrorV396("DR_REVIEWER_SIGNATURE_INVALID") from exc
            status = DRAttestationStatusV396.VERIFIED
            event_id = f"external-dr-attestation:{attestation.attestation_id}:accepted"
            payload = {
                **attestation.safe_payload(),
                "reviewer_key_fingerprint": reviewer_anchor.fingerprint,
                "status": status.value,
            }
            self.store.append(
                event_id=event_id,
                occurred_at_ms=now_ms,
                event_type=self.EVENT_TYPE,
                aggregate_id=attestation.attestation_id,
                payload=payload,
            )
            return DRAttestationDecisionV396(
                True, "EXTERNAL_DR_ATTESTATION_ACCEPTED", attestation.attestation_id,
                policy.policy_version, policy.policy_hash, status, attestation.reviewer_id,
            )
        except (DRAttestationErrorV396, TrustAttestationErrorV395) as exc:
            if "EXPIRED" in str(exc):
                status = DRAttestationStatusV396.EXPIRED
            return DRAttestationDecisionV396(
                False, str(exc), attestation.attestation_id, attestation.policy_version,
                attestation.policy_hash, status, attestation.reviewer_id,
            )

    def get(self, attestation_id: str):
        return self.store.get(f"external-dr-attestation:{attestation_id}:accepted")
