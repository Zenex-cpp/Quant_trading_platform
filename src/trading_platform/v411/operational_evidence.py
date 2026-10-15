from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v360.readiness_evidence import EvidenceSourceKind, REQUIRED_EVIDENCE_CLASSES


class OperationalEvidenceManifestErrorV411(ValueError):
    __test__ = False


@dataclass(frozen=True)
class OperationalEvidenceProtocolV411:
    evidence_class: str
    objective: str
    required_artifact_kinds: tuple[str, ...]
    required_fields: tuple[str, ...]
    source_expectation: str = "EXTERNAL"


REQUIRED_OPERATIONAL_EVIDENCE_PROTOCOLS_V411: dict[str, OperationalEvidenceProtocolV411] = {
    "LIVE_VENUE": OperationalEvidenceProtocolV411(
        "LIVE_VENUE",
        "Authenticate and exercise the governed non-production venue path with externally sourced mutation evidence.",
        ("authenticated_session", "mutation_result", "venue_reconciliation"),
        ("environment_id", "session_ref", "mutation_ref", "reconciliation_ref", "attestation_ref"),
    ),
    "NETWORK_SEGMENTATION": OperationalEvidenceProtocolV411(
        "NETWORK_SEGMENTATION",
        "Demonstrate enforced separation between research, testnet/shadow and production trading paths.",
        ("route_policy", "firewall_or_acl", "independent_validation"),
        ("environment_id", "policy_ref", "isolation_test_ref", "attestation_ref"),
    ),
    "SECRET_STORE": OperationalEvidenceProtocolV411(
        "SECRET_STORE",
        "Demonstrate deployed secret storage, rotation, expiry/revocation and audit controls without exposing secret material.",
        ("vault_state", "rotation_record", "revocation_record"),
        ("environment_id", "vault_ref", "rotation_ref", "revocation_ref", "attestation_ref"),
    ),
    "BACKUP_RESTORE": OperationalEvidenceProtocolV411(
        "BACKUP_RESTORE",
        "Demonstrate production backup creation, restore integrity and measured recovery targets.",
        ("backup_manifest", "restore_result", "integrity_check"),
        ("environment_id", "backup_ref", "restore_ref", "rpo_rto_ref", "attestation_ref"),
    ),
    "DISASTER_RECOVERY": OperationalEvidenceProtocolV411(
        "DISASTER_RECOVERY",
        "Demonstrate failover, failback and post-recovery reconciliation under controlled infrastructure conditions.",
        ("failure_injection", "failover_result", "failback_result", "recovery_proof"),
        ("environment_id", "dr_exercise_ref", "failover_ref", "failback_ref", "recovery_proof_ref", "attestation_ref"),
    ),
    "SECURITY_REVIEW": OperationalEvidenceProtocolV411(
        "SECURITY_REVIEW",
        "Demonstrate an independent security assessment covering the production threat model and remediation state.",
        ("independent_assessment", "findings_register", "remediation_statement"),
        ("assessment_ref", "scope_ref", "findings_ref", "attestation_ref"),
    ),
    "MONITORING": OperationalEvidenceProtocolV411(
        "MONITORING",
        "Demonstrate production monitoring, paging, silence detection and exercised on-call escalation.",
        ("monitoring_state", "paging_result", "on_call_drill"),
        ("environment_id", "monitoring_ref", "page_ref", "on_call_ref", "attestation_ref"),
    ),
    "ROLLBACK": OperationalEvidenceProtocolV411(
        "ROLLBACK",
        "Demonstrate an executed production rollback against the governed rollback target and reconciled end state.",
        ("rollback_execution", "post_rollback_reconciliation", "recovery_proof"),
        ("environment_id", "rollback_ref", "reconciliation_ref", "recovery_proof_ref", "attestation_ref"),
    ),
    "INDEPENDENT_REVIEW": OperationalEvidenceProtocolV411(
        "INDEPENDENT_REVIEW",
        "Demonstrate independent human review/approval operation with subject coverage and durable attestation.",
        ("review_record", "independence_check", "approval_attestation"),
        ("review_ref", "reviewer_id", "subject_coverage_ref", "attestation_ref"),
    ),
}


@dataclass(frozen=True)
class OperationalEvidenceManifestDecisionV411:
    allowed: bool
    status: str
    reason: str
    package_id: str
    manifest_hash: str
    evidence_ids: tuple[str, ...]

    @property
    def externally_admissible(self) -> bool:
        return self.allowed and self.status == "READY_FOR_EXTERNAL_REVIEW"


@dataclass(frozen=True)
class _ManifestRecord:
    package_id: str
    scope: str
    manifest_hash: str
    evidence_ids: tuple[str, ...]


_FORBIDDEN_KEY_FRAGMENTS = (
    "api_key",
    "api_secret",
    "private_key",
    "access_token",
    "refresh_token",
    "password",
    "raw_secret",
    "secret_value",
)


def _reject_sensitive_keys(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_lower = str(key).lower()
            if any(fragment in key_lower for fragment in _FORBIDDEN_KEY_FRAGMENTS):
                raise OperationalEvidenceManifestErrorV411(f"SENSITIVE_FIELD_FORBIDDEN:{path}.{key}")
            _reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, f"{path}[{index}]")


def _canonical_hash(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("manifest_hash", None)
    return sha256(canonical_json(body)).hexdigest()


class OperationalEvidenceManifestAuthorityV411:
    """Machine-checkable completeness boundary before external evidence review.

    This authority never marks evidence VERIFIED and never changes production
    readiness. It only establishes that a manifest is structurally complete and
    suitable for the independent external review path.
    """

    EVENT_TYPE = "OPERATIONAL_EVIDENCE_MANIFEST_ADMITTED_V411"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def protocol(evidence_class: str) -> OperationalEvidenceProtocolV411:
        try:
            return REQUIRED_OPERATIONAL_EVIDENCE_PROTOCOLS_V411[evidence_class]
        except KeyError as exc:
            raise OperationalEvidenceManifestErrorV411("UNKNOWN_OPERATIONAL_EVIDENCE_CLASS") from exc

    @staticmethod
    def _validate_item(item: Mapping[str, Any], scope: str) -> str:
        required = {
            "evidence_id", "evidence_class", "scope", "source_kind", "source_system", "source_ref",
            "content_hash", "observed_at_ms", "valid_from_ms", "expires_at_ms", "artifact_refs",
            "attestation_ref",
        }
        missing = sorted(required - set(item))
        if missing:
            raise OperationalEvidenceManifestErrorV411(f"EVIDENCE_FIELDS_MISSING:{','.join(missing)}")
        evidence_id = str(item["evidence_id"]).strip()
        evidence_class = str(item["evidence_class"])
        if not evidence_id:
            raise OperationalEvidenceManifestErrorV411("EVIDENCE_ID_REQUIRED")
        if evidence_class not in REQUIRED_OPERATIONAL_EVIDENCE_PROTOCOLS_V411:
            raise OperationalEvidenceManifestErrorV411("EVIDENCE_CLASS_NOT_REQUIRED")
        if str(item["scope"]) != scope:
            raise OperationalEvidenceManifestErrorV411("EVIDENCE_SCOPE_MISMATCH")
        if str(item["source_kind"]) != EvidenceSourceKind.EXTERNAL.value:
            raise OperationalEvidenceManifestErrorV411("EXTERNAL_EVIDENCE_REQUIRED")
        for key in ("source_system", "source_ref", "attestation_ref"):
            if not str(item[key]).strip():
                raise OperationalEvidenceManifestErrorV411(f"{key.upper()}_REQUIRED")
        source_ref = str(item["source_ref"])
        if source_ref.startswith(("demo:", "synthetic:", "fixture:")):
            raise OperationalEvidenceManifestErrorV411("NON_EXTERNAL_SOURCE_FORBIDDEN")
        content_hash = str(item["content_hash"])
        if len(content_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in content_hash):
            raise OperationalEvidenceManifestErrorV411("CONTENT_HASH_INVALID")
        for field in ("observed_at_ms", "valid_from_ms", "expires_at_ms"):
            if not isinstance(item[field], int):
                raise OperationalEvidenceManifestErrorV411("EVIDENCE_TIME_FIELDS_MUST_BE_INT")
        if not (item["valid_from_ms"] <= item["observed_at_ms"] < item["expires_at_ms"]):
            raise OperationalEvidenceManifestErrorV411("EVIDENCE_TIME_WINDOW_INVALID")
        refs = item["artifact_refs"]
        if not isinstance(refs, list) or not refs or any(not str(ref).strip() for ref in refs):
            raise OperationalEvidenceManifestErrorV411("ARTIFACT_REFS_REQUIRED")
        protocol = OperationalEvidenceManifestAuthorityV411.protocol(evidence_class)
        fields = {str(key) for key in item}
        missing_protocol_fields = sorted(set(protocol.required_fields) - fields)
        if missing_protocol_fields:
            raise OperationalEvidenceManifestErrorV411(
                f"PROTOCOL_FIELDS_MISSING:{evidence_class}:{','.join(missing_protocol_fields)}"
            )
        return evidence_id

    def admit(self, manifest: Mapping[str, Any]) -> OperationalEvidenceManifestDecisionV411:
        _reject_sensitive_keys(manifest)
        required = {"protocol_version", "package_id", "scope", "created_at_ms", "source_system", "evidence", "manifest_hash"}
        missing = sorted(required - set(manifest))
        if missing:
            raise OperationalEvidenceManifestErrorV411(f"MANIFEST_FIELDS_MISSING:{','.join(missing)}")
        if str(manifest["protocol_version"]) != "V4.11-OPERATIONAL-EVIDENCE-1":
            raise OperationalEvidenceManifestErrorV411("PROTOCOL_VERSION_INVALID")
        package_id = str(manifest["package_id"]).strip()
        scope = str(manifest["scope"]).strip()
        if not package_id or not scope or not str(manifest["source_system"]).strip():
            raise OperationalEvidenceManifestErrorV411("MANIFEST_IDENTIFIERS_REQUIRED")
        if not isinstance(manifest["created_at_ms"], int):
            raise OperationalEvidenceManifestErrorV411("MANIFEST_CREATED_AT_MUST_BE_INT")
        if not isinstance(manifest["evidence"], list) or not manifest["evidence"]:
            raise OperationalEvidenceManifestErrorV411("MANIFEST_EVIDENCE_REQUIRED")
        computed = _canonical_hash(manifest)
        if str(manifest["manifest_hash"]) != computed:
            raise OperationalEvidenceManifestErrorV411("MANIFEST_HASH_MISMATCH")
        seen: set[str] = set()
        for item in manifest["evidence"]:
            if not isinstance(item, Mapping):
                raise OperationalEvidenceManifestErrorV411("EVIDENCE_ITEM_NOT_OBJECT")
            eid = self._validate_item(item, scope)
            if eid in seen:
                raise OperationalEvidenceManifestErrorV411("DUPLICATE_EVIDENCE_ID")
            seen.add(eid)
        classes = {str(item["evidence_class"]) for item in manifest["evidence"]}
        required_classes = set(REQUIRED_EVIDENCE_CLASSES)
        if classes != required_classes:
            missing_classes = sorted(required_classes - classes)
            extra_classes = sorted(classes - required_classes)
            if missing_classes:
                raise OperationalEvidenceManifestErrorV411(
                    f"REQUIRED_EVIDENCE_CLASS_MISSING:{','.join(missing_classes)}"
                )
            raise OperationalEvidenceManifestErrorV411(
                f"UNEXPECTED_EVIDENCE_CLASSES:{','.join(extra_classes)}"
            )
        evidence_ids = tuple(sorted(seen))
        event_id = f"operational-evidence-manifest:{package_id}:v411"
        payload = {
            "package_id": package_id,
            "scope": scope,
            "manifest_hash": computed,
            "evidence_ids": list(evidence_ids),
            "protocol_version": str(manifest["protocol_version"]),
        }
        existing = self.store.get(event_id)
        if existing is None:
            self.store.append(
                event_id=event_id,
                occurred_at_ms=int(manifest["created_at_ms"]),
                event_type=self.EVENT_TYPE,
                aggregate_id=package_id,
                payload=payload,
            )
        elif dict(existing.payload) != payload:
            raise OperationalEvidenceManifestErrorV411("MANIFEST_ID_CONFLICT")
        return OperationalEvidenceManifestDecisionV411(
            allowed=True,
            status="READY_FOR_EXTERNAL_REVIEW",
            reason="OPERATIONAL_EVIDENCE_MANIFEST_COMPLETE",
            package_id=package_id,
            manifest_hash=computed,
            evidence_ids=evidence_ids,
        )

    def get_record(self, package_id: str) -> _ManifestRecord | None:
        event = self.store.get(f"operational-evidence-manifest:{package_id}:v411")
        if event is None or event.event_type != self.EVENT_TYPE:
            return None
        return _ManifestRecord(
            package_id=str(event.payload["package_id"]),
            scope=str(event.payload["scope"]),
            manifest_hash=str(event.payload["manifest_hash"]),
            evidence_ids=tuple(sorted(str(x) for x in event.payload["evidence_ids"])),
        )

    def revalidate(self, manifest: Mapping[str, Any]) -> OperationalEvidenceManifestDecisionV411:
        decision = self.admit(manifest)
        record = self.get_record(decision.package_id)
        if record is None:
            raise OperationalEvidenceManifestErrorV411("MANIFEST_RECORD_MISSING")
        if record.manifest_hash != decision.manifest_hash:
            raise OperationalEvidenceManifestErrorV411("MANIFEST_FINGERPRINT_CHANGED")
        if record.evidence_ids != decision.evidence_ids:
            raise OperationalEvidenceManifestErrorV411("MANIFEST_EVIDENCE_SET_CHANGED")
        return decision
