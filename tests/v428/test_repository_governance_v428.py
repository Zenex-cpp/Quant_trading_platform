from __future__ import annotations
import base64
import copy
import json
import os
from pathlib import Path
from hashlib import sha256
import subprocess
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v428.repository_governance import (
    RemoteRepositoryGovernanceEvidenceAuthorityV428,
    RepositoryGovernanceErrorV428,
    validate_workflow_contract_v428,
)

ROOT = Path(__file__).resolve().parents[2]
NOW = 1_850_000_000_000
REPO = "acme/trading-platform"
BRANCH = "main"
KEY_ID = "repo-governance-review-key"
SIGNER_ID = "independent-admin-reviewer"


def _private():
    return Ed25519PrivateKey.generate()


def _payload(now=NOW):
    run_id = 87531
    workflow_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    codeowners_body = "/.github/CODEOWNERS @acme/platform-maintainers\n* @configured-maintainers\n"
    head = "a" * 40
    return {
        "schema_version": "V4.24",
        "snapshot_id": "github-settings-snapshot-87531",
        "provider": "github",
        "workflow_sha256": sha256(workflow_text.encode("utf-8")).hexdigest(),
        "codeowners_file": {
            "path": ".github/CODEOWNERS",
            "sha256": sha256(codeowners_body.encode("utf-8")).hexdigest(),
            "source_ref": f"https://api.github.com/repos/{REPO}/contents/.github/CODEOWNERS?ref={head}",
            "owner_mappings": [
                {"handle": "@acme/platform-maintainers", "kind": "team", "id": "201", "source_ref": "https://api.github.com/orgs/acme/teams/platform-maintainers"},
                {"handle": "@configured-maintainers", "kind": "user", "id": "202", "source_ref": "https://api.github.com/users/configured-maintainers"},
            ],
            "self_ownership_rule": {"pattern": "/.github/CODEOWNERS", "owners": ["@acme/platform-maintainers"]},
        },
        "repository": REPO,
        "protected_branch": BRANCH,
        "protected_head_sha": head,
        "captured_at_ms": now - 100,
        "expires_at_ms": now + 50_000,
        "branch_protection": {
            "enabled": True,
            "enforce_admins": True,
            "allow_force_pushes": False,
            "allow_deletions": False,
            "bypass_actors": [],
            "required_status_checks": {"strict": True, "contexts": ["controlled-milestone-validation"]},
            "required_pull_request_reviews": {
                "required_approving_review_count": 2,
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": True,
            },
        },
        "hosted_workflow_run": {
            "repository": REPO,
            "run_id": run_id,
            "run_attempt": 1,
            "status": "completed",
            "conclusion": "success",
            "event": "push",
            "branch": BRANCH,
            "head_sha": head,
            "workflow_path": ".github/workflows/ci.yml",
            "job_name": "controlled-milestone-validation",
            "status_check_context": "controlled-milestone-validation",
            "status_check_conclusion": "success",
            "run_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
            "artifacts": [
                {"name": "V428_MILESTONE_PREFLIGHT.json", "sha256": "b" * 64},
                {"name": "V428_MILESTONE_PREFLIGHT.sqlite3", "sha256": "c" * 64},
            ],
        },
        "source_refs": [
            f"https://api.github.com/repos/{REPO}/branches/{BRANCH}/protection",
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}",
            f"https://api.github.com/repos/{REPO}/rulesets?includes_parents=true&per_page=100",
        ],
        "workflow_author_ids": ["workflow-author"],
        "change_author_ids": ["change-author"],
        "merge_actor_ids": ["merge-actor"],
    }


def _workflow():
    return (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")


def _signed(payload, private=None, *, now=NOW, signer=SIGNER_ID):
    private = private or _private()
    raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    public_b64 = base64.b64encode(raw).decode("ascii")
    public_hash = __import__("hashlib").sha256(raw).hexdigest()
    attestation = {
        "key_id": KEY_ID,
        "signer_id": signer,
        "signer_role": "INDEPENDENT_REPOSITORY_ADMIN_REVIEWER",
        "signed_at_ms": now - 50,
        "expires_at_ms": now + 30_000,
    }
    signed_message = {"payload": payload, "attestation": dict(attestation)}
    signature = private.sign(canonical_json(signed_message))
    attestation["signature_b64"] = base64.b64encode(signature).decode("ascii")
    return private, public_b64, public_hash, attestation


def _authority(store, public_b64, public_hash, *, signer=SIGNER_ID):
    return RemoteRepositoryGovernanceEvidenceAuthorityV428(
        store=store, expected_repository=REPO, expected_branch=BRANCH,
        trusted_signer_key_id=KEY_ID, trusted_signer_public_key_b64=public_b64,
        trusted_signer_id=signer, trusted_signer_public_key_sha256=public_hash,
    )


def test_v428_valid_signed_remote_snapshot_is_recorded_but_not_production_ready():
    payload = _payload()
    private, public_b64, public_hash, attestation = _signed(payload)
    store = EventStore()
    decision = _authority(store, public_b64, public_hash).evaluate(
        decision_id="repo-gov-verified", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "VERIFIED"
    assert decision.allowed
    assert decision.blocking_reasons == ()
    event = _authority(store, public_b64, public_hash).assert_verified("repo-gov-verified", expected_payload_hash=decision.payload_hash)
    assert event.payload["production_ready"] is False
    assert event.payload["external_evidence"] is False
    assert store.verify_chain()


def test_v428_missing_trust_anchor_fails_closed():
    payload = _payload()
    _, public_b64, public_hash, attestation = _signed(payload)
    store = EventStore()
    decision = RemoteRepositoryGovernanceEvidenceAuthorityV428(
        store=store, expected_repository=REPO, expected_branch=BRANCH,
    ).evaluate(decision_id="repo-gov-no-trust", payload=payload, attestation=attestation, now_ms=NOW, workflow_text=_workflow())
    assert decision.status == "BLOCKED"
    assert not decision.allowed
    assert "REPOSITORY_GOVERNANCE_TRUST_ANCHOR_NOT_CONFIGURED" in decision.blocking_reasons


def test_v428_branch_protection_gap_blocks_even_a_valid_signature():
    payload = _payload()
    payload["branch_protection"]["enforce_admins"] = False
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-no-admin-enforcement", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "BRANCH_PROTECTION_ADMIN_ENFORCEMENT_REQUIRED" in decision.blocking_reasons


def test_v428_signature_and_reviewer_separation_are_enforced():
    payload = _payload()
    _, public_b64, public_hash, attestation = _signed(payload)
    attestation["signature_b64"] = base64.b64encode(b"x" * 64).decode("ascii")
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-bad-signature", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "ATTESTATION_SIGNATURE_INVALID" in decision.blocking_reasons

    payload = _payload()
    payload["change_author_ids"] = [SIGNER_ID]
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-reviewer-conflict", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "REVIEWER_NOT_INDEPENDENT_OF_AUTHORS_OR_MERGE_ACTOR" in decision.blocking_reasons


def test_v428_rejects_wrong_repository_stale_snapshot_and_missing_required_check():
    payload = _payload()
    payload["repository"] = "someone/else"
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-wrong-scope", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert "REPOSITORY_SCOPE_MISMATCH" in decision.blocking_reasons

    payload = _payload(now=NOW - 2 * 86_400_000)
    _, public_b64, public_hash, attestation = _signed(payload, now=NOW - 2 * 86_400_000)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-stale", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert "EVIDENCE_STALE" in decision.blocking_reasons

    payload = _payload()
    payload["branch_protection"]["required_status_checks"]["contexts"] = ["pytest"]
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-no-required-context", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert "MILESTONE_STATUS_CHECK_NOT_REQUIRED" in decision.blocking_reasons


def test_v428_decision_id_is_immutable_and_repeated_evaluation_idempotent():
    payload = _payload()
    _, public_b64, public_hash, attestation = _signed(payload)
    store = EventStore()
    authority = _authority(store, public_b64, public_hash)
    first = authority.evaluate(decision_id="repo-gov-idempotent", payload=payload, attestation=attestation, now_ms=NOW, workflow_text=_workflow())
    second = authority.evaluate(decision_id="repo-gov-idempotent", payload=payload, attestation=attestation, now_ms=NOW, workflow_text=_workflow())
    assert first.event_hash == second.event_hash
    assert second.duplicate
    changed = copy.deepcopy(payload)
    changed["snapshot_id"] = "different-snapshot"
    _, _, _, new_attestation = _signed(changed)
    try:
        authority.evaluate(decision_id="repo-gov-idempotent", payload=changed, attestation=new_attestation, now_ms=NOW, workflow_text=_workflow())
    except RepositoryGovernanceErrorV428 as exc:
        assert "DECISION_ID_CONFLICT" in str(exc)
    else:
        raise AssertionError("changed evidence must not reuse a decision ID")


def test_v428_static_contract_and_source_do_not_enable_network_or_production():
    workflow = _workflow()
    assert validate_workflow_contract_v428(workflow) == ()
    source = (ROOT / "src/trading_platform/v428/repository_governance.py").read_text(encoding="utf-8")
    assert "import requests" not in source
    assert "urllib.request" not in source
    assert "subprocess" not in source
    assert '"production_ready": False' in source
    assert '"activation_flag": "NOT_SET"' in source


def test_v428_local_cli_reports_unverified_without_production_trust():
    report = ROOT / ".audit" / "test-v428-governance.json"
    store = ROOT / ".audit" / "test-v428-governance.sqlite3"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        result = subprocess.run(
            [sys.executable, "scripts/verify_repository_governance.py", "--repository", REPO,
             "--evidence", "V424_REPOSITORY_GOVERNANCE_EVIDENCE_TEMPLATE.json",
             "--trust", "config/repository_governance_trust_v424.json",
             "--report", report.relative_to(ROOT).as_posix(), "--event-store", store.relative_to(ROOT).as_posix(), "--decision-id", "repo-gov-cli-test", "--now-ms", str(NOW)],
            cwd=ROOT, env=env, shell=False, check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        output = json.loads(report.read_text(encoding="utf-8"))
        assert output["status"] == "BLOCKED"
        assert output["trust_anchor_configured"] is False
        assert output["production_ready"] is False
        assert "REPOSITORY_GOVERNANCE_TRUST_ANCHOR_NOT_CONFIGURED" in output["blocking_reasons"]
    finally:
        report.unlink(missing_ok=True)
        store.unlink(missing_ok=True)
        Path(str(store) + "-wal").unlink(missing_ok=True)
        Path(str(store) + "-shm").unlink(missing_ok=True)


def test_v428_schema_matches_positive_snapshot_and_signature_covers_metadata():
    import jsonschema
    schema = json.loads((ROOT / "schemas/v428_repository_governance_evidence.schema.json").read_text(encoding="utf-8"))
    payload = _payload()
    jsonschema.validate(payload, schema)

    _, public_b64, public_hash, attestation = _signed(payload)
    attestation["signed_at_ms"] -= 1  # envelope time is covered by the signature, not editable metadata
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-attestation-metadata-tamper", payload=payload,
        attestation=attestation, now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "ATTESTATION_SIGNATURE_INVALID" in decision.blocking_reasons


def test_v428_codeowners_source_and_trust_key_fingerprint_are_bound():
    payload = _payload()
    payload["codeowners_file"]["source_ref"] = "https://api.github.com/repos/acme/trading-platform/contents/.github/CODEOWNERS?ref=wrong"
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-codeowners-source-mismatch", payload=payload,
        attestation=attestation, now_ms=NOW, workflow_text=_workflow(),
    )
    assert "CODEOWNERS_PROVIDER_SOURCE_REF_REQUIRED" in decision.blocking_reasons

    payload = _payload()
    _, public_b64, public_hash, attestation = _signed(payload)
    wrong_fingerprint = "0" * 64 if public_hash != "0" * 64 else "1" * 64
    authority = RemoteRepositoryGovernanceEvidenceAuthorityV428(
        store=EventStore(), expected_repository=REPO, expected_branch=BRANCH,
        trusted_signer_key_id=KEY_ID, trusted_signer_public_key_b64=public_b64,
        trusted_signer_id=SIGNER_ID, trusted_signer_public_key_sha256=wrong_fingerprint,
    )
    decision = authority.evaluate(
        decision_id="repo-gov-trust-fingerprint-mismatch", payload=payload,
        attestation=attestation, now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "TRUSTED_PUBLIC_KEY_FINGERPRINT_MISMATCH" in decision.blocking_reasons


def test_v425_codeowners_owner_mapping_and_ruleset_source_are_required():
    payload = _payload()
    del payload["codeowners_file"]["owner_mappings"]
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-no-owner-mapping", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "CODEOWNERS_OWNER_ID_MAPPING_REQUIRED" in decision.blocking_reasons

    payload = _payload()
    payload["source_refs"] = [ref for ref in payload["source_refs"] if "/rulesets?" not in ref]
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-no-ruleset-source", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "REPOSITORY_RULESETS_API_SOURCE_REF_REQUIRED" in decision.blocking_reasons


def test_v425_owner_identity_duplicate_and_self_rule_are_rejected():
    payload = _payload()
    payload["codeowners_file"]["self_ownership_rule"] = {"pattern": "*", "owners": ["@acme/platform-maintainers"]}
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-self-rule-invalid", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "CODEOWNERS_SELF_OWNERSHIP_RULE_REQUIRED" in decision.blocking_reasons

    payload = _payload()
    payload["workflow_author_ids"] = ["workflow-author", "workflow-author"]
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-duplicate-author", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "WORKFLOW_AUTHOR_IDS_DUPLICATE" in decision.blocking_reasons


def test_v425_codeowners_owner_mapping_must_match_provider_identity_endpoint():
    payload = _payload()
    payload["codeowners_file"]["owner_mappings"][0]["source_ref"] = "https://api.github.com/users/not-the-team"
    _, public_b64, public_hash, attestation = _signed(payload)
    decision = _authority(EventStore(), public_b64, public_hash).evaluate(
        decision_id="repo-gov-owner-source-mismatch", payload=payload, attestation=attestation,
        now_ms=NOW, workflow_text=_workflow(),
    )
    assert decision.status == "BLOCKED"
    assert "CODEOWNERS_OWNER_MAPPING_INVALID" in decision.blocking_reasons
