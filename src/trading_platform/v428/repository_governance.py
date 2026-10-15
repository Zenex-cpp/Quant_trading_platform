"""V4.24 verifier for externally attested repository-host governance evidence.

No network calls are made here. A VERIFIED result requires an externally
captured provider snapshot signed by a configured trust key; a missing trust key
or evidence yields BLOCKED. This decision is repository-governance-only and can
never set production_ready.
"""
from __future__ import annotations

from dataclasses import dataclass
import base64
from hashlib import sha256
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from trading_platform.v21.event_store import EventStore, LedgerEvent, canonical_json


class RepositoryGovernanceErrorV428(ValueError):
    __test__ = False


EVENT_TYPE_V428 = "REMOTE_REPOSITORY_GOVERNANCE_EVALUATED_V428"
REQUIRED_STATUS_CHECK_V428 = "controlled-milestone-validation"
REQUIRED_WORKFLOW_PATH_V428 = ".github/workflows/ci.yml"
REQUIRED_PREFLIGHT_ARTIFACTS_V428 = {
    "V428_MILESTONE_PREFLIGHT.json",
    "V428_MILESTONE_PREFLIGHT.sqlite3",
}
SHA256_PATTERN_V428 = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_PATTERN_V428 = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def canonical_hash_v428(value: Any) -> str:
    return sha256(canonical_json(value)).hexdigest()


def validate_workflow_contract_v428(text: str) -> tuple[str, ...]:
    """Validate the active local CI contract without claiming hosted CI ran.

    V4.29 keeps the V4.28 remote evidence payload/artifact names for backwards
    compatibility, but its milestone runner and release matrix have a new
    versioned contract.
    """
    normalized_for_version = text.replace("\r\n", "\n") if isinstance(text, str) else ""
    if "V4.29-RECOVERY" in normalized_for_version and "compliance_v429.csv" in normalized_for_version:
        from trading_platform.v429.workflow_contract import validate_workflow_contract_v429
        return validate_workflow_contract_v429(text)
    blockers: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return ("WORKFLOW_SOURCE_MISSING",)
    normalized = text.replace("\r\n", "\n")
    is_v428 = "V4.28-RECOVERY" in normalized and "compliance_v428.csv" in normalized
    preflight_prefix = "V428" if is_v428 else "V425"
    requirements = {
        "WORKFLOW_PUSH_TRIGGER_MISSING": ("push:",),
        "WORKFLOW_PULL_REQUEST_TRIGGER_MISSING": ("pull_request:",),
        "WORKFLOW_MANUAL_TRIGGER_MISSING": ("workflow_dispatch:",),
        "WORKFLOW_CONTROLLED_ENTRYPOINT_MISSING": ("scripts/run_milestone_validation.py",),
        "WORKFLOW_STATUS_CONTEXT_MISSING": (REQUIRED_STATUS_CHECK_V428,),
        "WORKFLOW_ALWAYS_UPLOADS_PREFLIGHT_MISSING": ("if: always()",),
        "WORKFLOW_PREFLIGHT_JSON_ARTIFACT_MISSING": (f"{preflight_prefix}_MILESTONE_PREFLIGHT.json",),
        "WORKFLOW_PREFLIGHT_DB_ARTIFACT_MISSING": (f"{preflight_prefix}_MILESTONE_PREFLIGHT.sqlite3",),
        "WORKFLOW_HIDDEN_AUDIT_ARTIFACTS_NOT_INCLUDED": ("include-hidden-files: true",),
    }
    for reason, needles in requirements.items():
        if not all(needle in normalized for needle in needles):
            blockers.append(reason)
    if "python scripts/run_milestone_validation.py" not in normalized:
        blockers.append("WORKFLOW_ENTRYPOINT_INVOCATION_MISSING")
    if "permissions:" not in normalized or "contents: read" not in normalized:
        blockers.append("WORKFLOW_MINIMUM_PERMISSIONS_NOT_DECLARED")
    if "controlled-milestone-validation:" not in normalized:
        blockers.append("WORKFLOW_JOB_ID_MISMATCH")
    pinned_actions = (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    )
    if not all(action in normalized for action in pinned_actions):
        blockers.append("WORKFLOW_ACTIONS_NOT_PINNED_TO_APPROVED_FULL_SHA")
    return tuple(sorted(set(blockers)))


@dataclass(frozen=True)
class RepositoryGovernanceDecisionV428:
    decision_id: str
    repository: str
    protected_branch: str
    status: str
    allowed: bool
    payload_hash: str
    attestation_hash: str
    blocking_reasons: tuple[str, ...]
    reviewer_id: str | None
    event_hash: str
    duplicate: bool = False


class RemoteRepositoryGovernanceEvidenceAuthorityV428:
    """Validate signed branch-protection and hosted-run evidence for one repo."""

    EVENT_TYPE = EVENT_TYPE_V428

    def __init__(
        self,
        *,
        store: EventStore | None = None,
        expected_repository: str,
        expected_branch: str = "main",
        trusted_signer_key_id: str | None = None,
        trusted_signer_public_key_b64: str | None = None,
        trusted_signer_id: str | None = None,
        trusted_signer_public_key_sha256: str | None = None,
        max_age_ms: int = 86_400_000,
    ) -> None:
        self.store = store or EventStore()
        self.expected_repository = expected_repository.strip().lower()
        self.expected_branch = expected_branch.strip()
        self.trusted_signer_key_id = trusted_signer_key_id.strip() if trusted_signer_key_id else None
        self.trusted_signer_public_key_b64 = trusted_signer_public_key_b64
        self.trusted_signer_id = trusted_signer_id.strip() if trusted_signer_id else None
        self.trusted_signer_public_key_sha256 = trusted_signer_public_key_sha256.lower() if trusted_signer_public_key_sha256 else None
        self.max_age_ms = int(max_age_ms)
        if "/" not in self.expected_repository or self.expected_repository.startswith("/") or self.expected_repository.endswith("/"):
            raise RepositoryGovernanceErrorV428("EXPECTED_REPOSITORY_MUST_BE_OWNER_NAME")
        if not self.expected_branch:
            raise RepositoryGovernanceErrorV428("EXPECTED_BRANCH_REQUIRED")
        if self.max_age_ms <= 0:
            raise RepositoryGovernanceErrorV428("MAX_AGE_MUST_BE_POSITIVE")

    def evaluate(
        self,
        *,
        decision_id: str,
        payload: Mapping[str, Any] | None,
        attestation: Mapping[str, Any] | None,
        now_ms: int,
        workflow_text: str,
    ) -> RepositoryGovernanceDecisionV428:
        if not decision_id.strip():
            raise RepositoryGovernanceErrorV428("DECISION_ID_REQUIRED")
        normalized_payload = dict(payload) if isinstance(payload, Mapping) else {}
        normalized_attestation = dict(attestation) if isinstance(attestation, Mapping) else {}
        blockers = list(validate_workflow_contract_v428(workflow_text))
        payload_hash = canonical_hash_v428(normalized_payload)
        attestation_hash = canonical_hash_v428(normalized_attestation)
        reviewer_id: str | None = None
        blockers.extend(self._validate_payload(normalized_payload, now_ms=now_ms, workflow_text=workflow_text))
        blockers.extend(self._validate_attestation(
            normalized_payload, normalized_attestation, now_ms=now_ms
        ))
        blockers = sorted(set(blockers))
        status = "VERIFIED" if not blockers else "BLOCKED"
        repo = str(normalized_payload.get("repository", ""))
        branch = str(normalized_payload.get("protected_branch", ""))
        reviewer_id = str(normalized_attestation.get("signer_id", "")) or None
        record_payload = {
            "decision_id": decision_id,
            "repository": repo,
            "protected_branch": branch,
            "status": status,
            "allowed": status == "VERIFIED",
            "payload_hash": payload_hash,
            "attestation_hash": attestation_hash,
            "blocking_reasons": blockers,
            "reviewer_id": reviewer_id,
            "repository_governance_evidence_verified": status == "VERIFIED",
            "external_evidence": False,
            "production_ready": False,
            "activation_flag": "NOT_SET",
        }
        existing = self.store.get(decision_id)
        if existing is not None:
            if existing.event_type != EVENT_TYPE_V428 or dict(existing.payload) != record_payload:
                raise RepositoryGovernanceErrorV428("DECISION_ID_CONFLICT")
            if not self.store.verify_chain():
                raise RepositoryGovernanceErrorV428("EVENT_STORE_CHAIN_INVALID")
            return self._decision(existing, duplicate=True)
        event = self.store.append(
            event_id=decision_id,
            occurred_at_ms=int(now_ms),
            event_type=EVENT_TYPE_V428,
            aggregate_id=repo or "UNKNOWN_REPOSITORY",
            payload=record_payload,
        ).event
        if not self.store.verify_chain():
            raise RepositoryGovernanceErrorV428("EVENT_STORE_CHAIN_INVALID_AFTER_APPEND")
        return self._decision(event, duplicate=False)

    def assert_verified(self, decision_id: str, *, expected_payload_hash: str | None = None) -> LedgerEvent:
        if not self.store.verify_chain():
            raise RepositoryGovernanceErrorV428("EVENT_STORE_CHAIN_INVALID")
        event = self.store.get(decision_id)
        if event is None or event.event_type != EVENT_TYPE_V428:
            raise RepositoryGovernanceErrorV428("DURABLE_REPOSITORY_GOVERNANCE_DECISION_REQUIRED")
        p = event.payload
        if p.get("status") != "VERIFIED" or p.get("allowed") is not True:
            raise RepositoryGovernanceErrorV428("REPOSITORY_GOVERNANCE_NOT_VERIFIED")
        if str(p.get("repository")) != self.expected_repository or str(p.get("protected_branch")) != self.expected_branch:
            raise RepositoryGovernanceErrorV428("REPOSITORY_GOVERNANCE_SCOPE_MISMATCH")
        if expected_payload_hash is not None and str(p.get("payload_hash")) != expected_payload_hash:
            raise RepositoryGovernanceErrorV428("REPOSITORY_GOVERNANCE_PAYLOAD_HASH_MISMATCH")
        return event

    def _validate_payload(self, payload: Mapping[str, Any], *, now_ms: int, workflow_text: str) -> list[str]:
        reasons: list[str] = []
        if payload.get("schema_version") != "V4.24":
            reasons.append("EVIDENCE_SCHEMA_VERSION_INVALID")
        if payload.get("provider") != "github":
            reasons.append("REPOSITORY_PROVIDER_NOT_GITHUB")
        expected_workflow_hash = sha256(workflow_text.encode("utf-8")).hexdigest()
        if str(payload.get("workflow_sha256", "")).lower() != expected_workflow_hash:
            reasons.append("WORKFLOW_SOURCE_HASH_MISMATCH")
        codeowners = payload.get("codeowners_file")
        if not isinstance(codeowners, Mapping) or codeowners.get("path") != ".github/CODEOWNERS" or not SHA256_PATTERN_V428.fullmatch(str(codeowners.get("sha256", "")).lower()):
            reasons.append("CODEOWNERS_FILE_PROVENANCE_REQUIRED")
        else:
            owner, repo_name = self.expected_repository.split("/", 1)
            required_codeowners_ref = f"https://api.github.com/repos/{owner}/{repo_name}/contents/.github/CODEOWNERS?ref={payload.get('protected_head_sha', '')}"
            if str(codeowners.get("source_ref", "")) != required_codeowners_ref:
                reasons.append("CODEOWNERS_PROVIDER_SOURCE_REF_REQUIRED")
            mappings = codeowners.get("owner_mappings")
            if not isinstance(mappings, Sequence) or isinstance(mappings, (str, bytes)) or not mappings:
                reasons.append("CODEOWNERS_OWNER_ID_MAPPING_REQUIRED")
                mappings = []
            mapped_handles: set[str] = set()
            for mapping in mappings:
                if not isinstance(mapping, Mapping):
                    reasons.append("CODEOWNERS_OWNER_MAPPING_INVALID")
                    continue
                handle = str(mapping.get("handle", ""))
                kind = str(mapping.get("kind", ""))
                owner_id = str(mapping.get("id", ""))
                source_ref = str(mapping.get("source_ref", ""))
                user_match = re.fullmatch(r"@([A-Za-z0-9-]+)", handle)
                team_match = re.fullmatch(r"@([A-Za-z0-9-]+)/([A-Za-z0-9-]+)", handle)
                expected_mapping_ref = None
                if user_match and kind == "user":
                    expected_mapping_ref = f"https://api.github.com/users/{user_match.group(1)}"
                elif team_match and kind == "team":
                    expected_mapping_ref = f"https://api.github.com/orgs/{team_match.group(1)}/teams/{team_match.group(2)}"
                if expected_mapping_ref is None or not owner_id.isdigit() or int(owner_id) <= 0 or source_ref != expected_mapping_ref:
                    reasons.append("CODEOWNERS_OWNER_MAPPING_INVALID")
                if handle in mapped_handles:
                    reasons.append("CODEOWNERS_OWNER_MAPPING_DUPLICATE")
                mapped_handles.add(handle)
            self_rule = codeowners.get("self_ownership_rule")
            if not isinstance(self_rule, Mapping) or self_rule.get("pattern") != "/.github/CODEOWNERS":
                reasons.append("CODEOWNERS_SELF_OWNERSHIP_RULE_REQUIRED")
            else:
                self_owners = self_rule.get("owners")
                if not isinstance(self_owners, Sequence) or isinstance(self_owners, (str, bytes)) or not self_owners:
                    reasons.append("CODEOWNERS_SELF_OWNERS_REQUIRED")
                elif any(str(handle) not in mapped_handles for handle in self_owners):
                    reasons.append("CODEOWNERS_SELF_OWNER_ID_UNRESOLVED")
        repository = str(payload.get("repository", "")).strip().lower()
        branch = str(payload.get("protected_branch", "")).strip()
        if repository != self.expected_repository:
            reasons.append("REPOSITORY_SCOPE_MISMATCH")
        if branch != self.expected_branch:
            reasons.append("PROTECTED_BRANCH_SCOPE_MISMATCH")
        try:
            captured = int(payload.get("captured_at_ms", 0))
            expires = int(payload.get("expires_at_ms", 0))
            if captured <= 0 or captured > now_ms:
                reasons.append("EVIDENCE_CAPTURE_TIME_INVALID")
            elif now_ms - captured > self.max_age_ms:
                reasons.append("EVIDENCE_STALE")
            if expires <= now_ms or expires <= captured:
                reasons.append("EVIDENCE_EXPIRED")
        except (TypeError, ValueError):
            reasons.append("EVIDENCE_TIME_FIELDS_INVALID")

        policy = payload.get("branch_protection")
        if not isinstance(policy, Mapping):
            reasons.append("BRANCH_PROTECTION_SNAPSHOT_REQUIRED")
        else:
            if policy.get("enabled") is not True:
                reasons.append("BRANCH_PROTECTION_NOT_ENABLED")
            if policy.get("enforce_admins") is not True:
                reasons.append("BRANCH_PROTECTION_ADMIN_ENFORCEMENT_REQUIRED")
            if policy.get("allow_force_pushes") is not False:
                reasons.append("FORCE_PUSH_MUST_BE_DISABLED")
            if policy.get("allow_deletions") is not False:
                reasons.append("BRANCH_DELETION_MUST_BE_DISABLED")
            bypass = policy.get("bypass_actors", None)
            if not isinstance(bypass, Sequence) or isinstance(bypass, (str, bytes)) or len(bypass) != 0:
                reasons.append("BRANCH_PROTECTION_BYPASS_ACTORS_MUST_BE_EMPTY")
            checks = policy.get("required_status_checks")
            if not isinstance(checks, Mapping) or checks.get("strict") is not True:
                reasons.append("STRICT_REQUIRED_STATUS_CHECKS_REQUIRED")
            contexts = checks.get("contexts") if isinstance(checks, Mapping) else None
            if not isinstance(contexts, Sequence) or isinstance(contexts, (str, bytes)) or REQUIRED_STATUS_CHECK_V428 not in contexts:
                reasons.append("MILESTONE_STATUS_CHECK_NOT_REQUIRED")
            reviews = policy.get("required_pull_request_reviews")
            if not isinstance(reviews, Mapping):
                reasons.append("REQUIRED_PULL_REQUEST_REVIEWS_MISSING")
            else:
                try:
                    count = int(reviews.get("required_approving_review_count", 0))
                except (TypeError, ValueError):
                    count = 0
                if count < 1:
                    reasons.append("INDEPENDENT_APPROVAL_REQUIRED")
                if reviews.get("dismiss_stale_reviews") is not True:
                    reasons.append("STALE_REVIEW_DISMISSAL_REQUIRED")
                if reviews.get("require_code_owner_reviews") is not True:
                    reasons.append("CODEOWNER_REVIEW_REQUIRED")

        protected_head_sha = str(payload.get("protected_head_sha", "")).lower()
        if not GIT_SHA_PATTERN_V428.fullmatch(protected_head_sha):
            reasons.append("PROTECTED_HEAD_SHA_INVALID")
        run = payload.get("hosted_workflow_run")
        if not isinstance(run, Mapping):
            reasons.append("HOSTED_WORKFLOW_RUN_EVIDENCE_REQUIRED")
        else:
            if str(run.get("repository", "")).lower() != self.expected_repository:
                reasons.append("HOSTED_RUN_REPOSITORY_MISMATCH")
            if str(run.get("branch", "")) != self.expected_branch:
                reasons.append("HOSTED_RUN_BRANCH_MISMATCH")
            if str(run.get("head_sha", "")).lower() != protected_head_sha:
                reasons.append("HOSTED_RUN_HEAD_SHA_MISMATCH")
            if run.get("status") != "completed" or run.get("conclusion") != "success":
                reasons.append("HOSTED_WORKFLOW_RUN_NOT_SUCCESSFUL")
            if run.get("event") != "push":
                reasons.append("HOSTED_RUN_MUST_VALIDATE_PROTECTED_BRANCH_PUSH")
            if run.get("workflow_path") != REQUIRED_WORKFLOW_PATH_V428:
                reasons.append("HOSTED_RUN_WORKFLOW_PATH_MISMATCH")
            if run.get("job_name") != REQUIRED_STATUS_CHECK_V428:
                reasons.append("HOSTED_RUN_REQUIRED_JOB_MISMATCH")
            if run.get("status_check_context") != REQUIRED_STATUS_CHECK_V428 or run.get("status_check_conclusion") != "success":
                reasons.append("HOSTED_STATUS_CHECK_NOT_SUCCESSFUL")
            try:
                run_id = int(run.get("run_id", 0))
                if run_id <= 0 or int(run.get("run_attempt", 0)) <= 0:
                    reasons.append("HOSTED_RUN_ID_INVALID")
            except (TypeError, ValueError):
                run_id = 0
                reasons.append("HOSTED_RUN_ID_INVALID")
            run_url = str(run.get("run_url", ""))
            if run_url != f"https://github.com/{self.expected_repository}/actions/runs/{run_id}":
                reasons.append("HOSTED_RUN_URL_INVALID")
            artifacts = run.get("artifacts")
            if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
                artifacts = []
            by_name = {str(item.get("name")): item for item in artifacts if isinstance(item, Mapping)}
            for name in REQUIRED_PREFLIGHT_ARTIFACTS_V428:
                artifact = by_name.get(name)
                if artifact is None:
                    reasons.append(f"HOSTED_RUN_ARTIFACT_MISSING:{name}")
                elif not SHA256_PATTERN_V428.fullmatch(str(artifact.get("sha256", "")).lower()):
                    reasons.append(f"HOSTED_RUN_ARTIFACT_HASH_INVALID:{name}")

        source_refs = payload.get("source_refs")
        if not isinstance(source_refs, Sequence) or isinstance(source_refs, (str, bytes)):
            source_refs = []
        owner, repo_name = self.expected_repository.split("/", 1)
        required_ref_prefixes = (
            f"https://api.github.com/repos/{owner}/{repo_name}/branches/{quote(self.expected_branch, safe='')}/protection",
            f"https://api.github.com/repos/{owner}/{repo_name}/actions/runs/",
            f"https://api.github.com/repos/{owner}/{repo_name}/rulesets?includes_parents=true&per_page=100",
        )
        refs_text = [str(value) for value in source_refs]
        if not any(ref.startswith(required_ref_prefixes[0]) for ref in refs_text):
            reasons.append("BRANCH_PROTECTION_API_SOURCE_REF_REQUIRED")
        if not any(ref.startswith(required_ref_prefixes[1]) for ref in refs_text):
            reasons.append("HOSTED_RUN_API_SOURCE_REF_REQUIRED")
        if required_ref_prefixes[2] not in refs_text:
            reasons.append("REPOSITORY_RULESETS_API_SOURCE_REF_REQUIRED")
        if not str(payload.get("snapshot_id", "")).strip():
            reasons.append("EXTERNAL_SNAPSHOT_ID_REQUIRED")
        for actor_field in ("workflow_author_ids", "change_author_ids", "merge_actor_ids"):
            values = payload.get(actor_field, [])
            if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
                reasons.append(f"{actor_field.upper()}_INVALID")
            elif not values or any(not str(value).strip() for value in values):
                reasons.append(f"{actor_field.upper()}_REQUIRED")
            elif len({str(value) for value in values}) != len(values):
                reasons.append(f"{actor_field.upper()}_DUPLICATE")
        return reasons

    def _validate_attestation(
        self,
        payload: Mapping[str, Any],
        attestation: Mapping[str, Any],
        *,
        now_ms: int,
    ) -> list[str]:
        reasons: list[str] = []
        if not self.trusted_signer_key_id or not self.trusted_signer_public_key_b64 or not self.trusted_signer_id or not self.trusted_signer_public_key_sha256:
            return ["REPOSITORY_GOVERNANCE_TRUST_ANCHOR_NOT_CONFIGURED"]
        key_id = str(attestation.get("key_id", ""))
        signer = str(attestation.get("signer_id", ""))
        if key_id != self.trusted_signer_key_id:
            reasons.append("ATTESTATION_KEY_ID_MISMATCH")
        if not signer:
            reasons.append("ATTESTATION_SIGNER_ID_REQUIRED")
        elif signer != self.trusted_signer_id:
            reasons.append("ATTESTATION_SIGNER_ID_MISMATCH")
        if attestation.get("signer_role") != "INDEPENDENT_REPOSITORY_ADMIN_REVIEWER":
            reasons.append("INDEPENDENT_REPOSITORY_ADMIN_REVIEWER_REQUIRED")
        try:
            signed_at = int(attestation.get("signed_at_ms", 0))
            expires_at = int(attestation.get("expires_at_ms", 0))
            try:
                payload_captured = int(payload.get("captured_at_ms", 0))
                payload_expires = int(payload.get("expires_at_ms", 0))
            except (TypeError, ValueError):
                payload_captured, payload_expires = 0, 0
            if signed_at <= 0 or signed_at > now_ms or now_ms - signed_at > self.max_age_ms:
                reasons.append("ATTESTATION_TIME_INVALID_OR_STALE")
            if signed_at < payload_captured:
                reasons.append("ATTESTATION_PRECEDES_EVIDENCE_CAPTURE")
            if expires_at <= now_ms or expires_at <= signed_at:
                reasons.append("ATTESTATION_EXPIRED")
            if payload_expires and expires_at > payload_expires:
                reasons.append("ATTESTATION_EXPIRY_EXCEEDS_EVIDENCE")
        except (TypeError, ValueError):
            reasons.append("ATTESTATION_TIME_FIELDS_INVALID")
        actor_sets: list[set[str]] = []
        for field in ("workflow_author_ids", "change_author_ids", "merge_actor_ids"):
            value = payload.get(field, [])
            actor_sets.append({str(v) for v in value} if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else set())
        if any(signer in actors for actors in actor_sets):
            reasons.append("REVIEWER_NOT_INDEPENDENT_OF_AUTHORS_OR_MERGE_ACTOR")
        try:
            public = base64.b64decode(self.trusted_signer_public_key_b64, validate=True)
            signature = base64.b64decode(str(attestation.get("signature_b64", "")), validate=True)
        except (ValueError, TypeError):
            reasons.append("ATTESTATION_BASE64_INVALID")
            return reasons
        if len(public) != 32:
            reasons.append("TRUSTED_PUBLIC_KEY_LENGTH_INVALID")
            return reasons
        if len(signature) != 64:
            reasons.append("ATTESTATION_SIGNATURE_LENGTH_INVALID")
            return reasons
        if self.trusted_signer_public_key_sha256 and sha256(public).hexdigest() != self.trusted_signer_public_key_sha256:
            reasons.append("TRUSTED_PUBLIC_KEY_FINGERPRINT_MISMATCH")
            return reasons
        signed_metadata = {
            "key_id": attestation.get("key_id"),
            "signer_id": attestation.get("signer_id"),
            "signer_role": attestation.get("signer_role"),
            "signed_at_ms": attestation.get("signed_at_ms"),
            "expires_at_ms": attestation.get("expires_at_ms"),
        }
        message = canonical_json({"payload": payload, "attestation": signed_metadata})
        try:
            Ed25519PublicKey.from_public_bytes(public).verify(signature, message)
        except InvalidSignature:
            reasons.append("ATTESTATION_SIGNATURE_INVALID")
        return reasons

    @staticmethod
    def _decision(event: LedgerEvent, *, duplicate: bool) -> RepositoryGovernanceDecisionV428:
        p = event.payload
        return RepositoryGovernanceDecisionV428(
            decision_id=str(p["decision_id"]), repository=str(p["repository"]),
            protected_branch=str(p["protected_branch"]), status=str(p["status"]),
            allowed=bool(p["allowed"]), payload_hash=str(p["payload_hash"]),
            attestation_hash=str(p["attestation_hash"]),
            blocking_reasons=tuple(str(v) for v in p["blocking_reasons"]),
            reviewer_id=str(p["reviewer_id"]) if p.get("reviewer_id") else None,
            event_hash=event.event_hash, duplicate=duplicate,
        )
