from __future__ import annotations

import base64
import json
from hashlib import sha256
from pathlib import Path
import subprocess
import sys
import tempfile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from trading_platform.v21.event_store import EventStore, canonical_json
from trading_platform.v424.repository_governance import RemoteRepositoryGovernanceEvidenceAuthorityV424
from trading_platform.v425.github_capture import (
    GitHubGovernanceCaptureErrorV425,
    build_github_governance_payload_v425,
    decode_github_content_v425,
    parse_codeowners_v425,
)

REPO = "acme/trading-platform"
BRANCH = "main"
HEAD = "a" * 40
NOW = 1_850_000_000_000
CODEOWNERS = b"/.github/CODEOWNERS @acme/platform-maintainers\n* @configured-maintainers\n"


def _file(path: str, body: bytes):
    return {"type": "file", "encoding": "base64", "path": path, "content": base64.b64encode(body).decode("ascii")}


def _fixtures(workflow_bytes: bytes, *, job_conclusion="success", codeowners=CODEOWNERS, rulesets=None, workflow_head=HEAD):
    base = "repos/acme/trading-platform"
    run_id = 12345
    routes: dict[str, object] = {
        base: {"full_name": REPO, "default_branch": BRANCH},
        f"{base}/branches/main": {"name": BRANCH, "protected": True, "commit": {"sha": HEAD}},
        f"{base}/branches/main/protection": {
            "enforce_admins": {"enabled": True},
            "allow_force_pushes": {"enabled": False},
            "allow_deletions": {"enabled": False},
            "required_status_checks": {"strict": True, "contexts": ["controlled-milestone-validation"], "checks": []},
            "required_pull_request_reviews": {"required_approving_review_count": 2, "dismiss_stale_reviews": True, "require_code_owner_reviews": True},
        },
        f"{base}/rulesets?includes_parents=true&per_page=100": rulesets if rulesets is not None else [],
        f"{base}/contents/.github/workflows/ci.yml?ref={HEAD}": _file(".github/workflows/ci.yml", workflow_bytes),
        f"{base}/contents/.github/CODEOWNERS?ref={HEAD}": _file(".github/CODEOWNERS", codeowners),
        "orgs/acme/teams/platform-maintainers": {"id": 201, "slug": "platform-maintainers", "organization": {"login": "acme"}},
        "users/configured-maintainers": {"id": 202, "login": "configured-maintainers"},
        f"{base}/commits/{HEAD}": {"sha": HEAD, "author": {"id": 301}, "committer": {"id": 302}},
        f"{base}/commits?path=.github/workflows/ci.yml&sha={HEAD}&per_page=100": [
            {"author": {"id": 401}, "committer": {"id": 402}},
        ],
        f"{base}/commits/{HEAD}/pulls?per_page=100": [
            {"merged_at": "2026-10-12T10:00:00Z", "merge_commit_sha": HEAD, "merged_by": {"id": 501}},
        ],
        f"{base}/actions/workflows/ci.yml/runs?branch=main&event=push&status=completed&per_page=100": {
            "workflow_runs": [{"id": run_id, "run_number": 8, "run_attempt": 1, "status": "completed", "conclusion": "success", "event": "push", "head_branch": BRANCH, "head_sha": workflow_head, "path": ".github/workflows/ci.yml"}],
        },
        f"{base}/actions/runs/{run_id}": {"id": run_id, "run_attempt": 1, "status": "completed", "conclusion": "success", "event": "push", "head_branch": BRANCH, "head_sha": workflow_head, "path": ".github/workflows/ci.yml"},
        f"{base}/actions/runs/{run_id}/jobs?per_page=100": {
            "jobs": [{"name": "controlled-milestone-validation", "status": "completed", "conclusion": job_conclusion}],
        },
        f"{base}/actions/runs/{run_id}/artifacts?per_page=100": {
            "artifacts": [{"name": f"V425-validation-audit-{run_id}-1", "expired": False}],
        },
    }
    return routes


def _payload(*, job_conclusion="success", codeowners=CODEOWNERS, rulesets=None, workflow_head=HEAD):
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    routes = _fixtures(workflow, job_conclusion=job_conclusion, codeowners=codeowners, rulesets=rulesets, workflow_head=workflow_head)
    queried = []
    def api(route):
        queried.append(route)
        if route not in routes:
            raise AssertionError(f"unexpected API route: {route}")
        return routes[route]
    def download(run_id, name):
        assert run_id == 12345
        assert name == "V425-validation-audit-12345-1"
        return [("V425_MILESTONE_PREFLIGHT.json", b'{"status":"READY_FOR_MILESTONE"}\n'), ("V425_MILESTONE_PREFLIGHT.sqlite3", b"sqlite-test-bytes")]
    payload = build_github_governance_payload_v425(
        repository=REPO, branch=BRANCH, local_head_sha=HEAD,
        local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=86_400_000,
        api=api, download_artifact=download,
    )
    return payload, queried


def test_v425_capture_builds_provider_payload_from_realistic_read_only_responses():
    payload, routes = _payload()
    assert payload["repository"] == REPO
    assert payload["protected_head_sha"] == HEAD
    assert payload["branch_protection"]["enabled"] is True
    assert payload["branch_protection"]["required_status_checks"]["strict"] is True
    assert payload["hosted_workflow_run"]["status_check_conclusion"] == "success"
    assert {item["name"] for item in payload["hosted_workflow_run"]["artifacts"]} == {
        "V425_MILESTONE_PREFLIGHT.json", "V425_MILESTONE_PREFLIGHT.sqlite3"
    }
    assert len(payload["workflow_author_ids"]) == 2
    assert payload["merge_actor_ids"] == ["501"]
    assert "repos/acme/trading-platform/rulesets?includes_parents=true&per_page=100" in routes


def test_v425_rejects_local_checkout_that_does_not_match_protected_remote_head():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    routes = _fixtures(workflow)
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="LOCAL_CHECKOUT_DOES_NOT_MATCH_REMOTE_PROTECTED_HEAD"):
        build_github_governance_payload_v425(
            repository=REPO, branch=BRANCH, local_head_sha="b" * 40,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda route: routes[route], download_artifact=lambda *_: [],
        )


def test_v425_refuses_failed_or_missing_required_hosted_job():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    routes = _fixtures(workflow, job_conclusion="failure")
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="REQUIRED_HOSTED_JOB_NOT_SUCCESSFUL"):
        build_github_governance_payload_v425(
            repository=REPO, branch=BRANCH, local_head_sha=HEAD,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda route: routes[route], download_artifact=lambda *_: [],
        )


def test_v425_refuses_missing_codeowners_self_ownership_rule():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    routes = _fixtures(workflow, codeowners=b"* @configured-maintainers\n")
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="CODEOWNERS_SELF_OWNERSHIP_RULE_REQUIRED"):
        build_github_governance_payload_v425(
            repository=REPO, branch=BRANCH, local_head_sha=HEAD,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda route: routes[route], download_artifact=lambda *_: [],
        )


def test_v425_conservatively_captures_active_ruleset_bypass_actors():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    ruleset = {"id": 77, "enforcement": "active", "details": {"id": 77, "bypass_actors": [{"actor_id": 99, "actor_type": "Team", "bypass_mode": "always"}]}}
    routes = _fixtures(workflow, rulesets=[ruleset])
    routes["repos/acme/trading-platform/rulesets/77"] = ruleset["details"]
    payload = build_github_governance_payload_v425(
        repository=REPO, branch=BRANCH, local_head_sha=HEAD,
        local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
        api=lambda route: routes[route], download_artifact=lambda *_: [
            ("V425_MILESTONE_PREFLIGHT.json", b"report"),
            ("V425_MILESTONE_PREFLIGHT.sqlite3", b"db"),
        ],
    )
    assert payload["branch_protection"]["bypass_actors"] == [{"actor_id": "99", "actor_type": "Team", "bypass_mode": "always"}]


def test_v425_refuses_artifacts_with_missing_or_duplicate_preflight_files():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    routes = _fixtures(workflow)
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="REQUIRED_PREFLIGHT_ARTIFACT_FILES_MISSING"):
        build_github_governance_payload_v425(
            repository=REPO, branch=BRANCH, local_head_sha=HEAD,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda route: routes[route],
            download_artifact=lambda *_: [("V425_MILESTONE_PREFLIGHT.json", b"report")],
        )
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="DUPLICATE_REQUIRED_ARTIFACT_FILE"):
        build_github_governance_payload_v425(
            repository=REPO, branch=BRANCH, local_head_sha=HEAD,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda route: routes[route],
            download_artifact=lambda *_: [("one/V425_MILESTONE_PREFLIGHT.json", b"a"), ("two/V425_MILESTONE_PREFLIGHT.json", b"b"), ("V425_MILESTONE_PREFLIGHT.sqlite3", b"db")],
        )


def test_v425_rule_parser_requires_explicit_self_ownership_and_resolves_all_handles():
    handles, self_owners = parse_codeowners_v425(CODEOWNERS)
    assert handles == ["@acme/platform-maintainers", "@configured-maintainers"]
    assert self_owners == ["@acme/platform-maintainers"]
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="CODEOWNERS_OWNER_TOKEN_INVALID"):
        parse_codeowners_v425(b"/.github/CODEOWNERS platform-maintainers\n")


def test_v425_signed_capture_payload_is_accepted_only_with_v24_trust_contract():
    payload, _ = _payload()
    workflow_text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    # Add no fake remote proof: this is a synthetic fixture used only for contract testing.
    payload["source_refs"] = sorted(set(payload["source_refs"]))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    import hashlib
    public_hash = hashlib.sha256(public).hexdigest()
    attestation = {"key_id": "test-key", "signer_id": "independent-reviewer", "signer_role": "INDEPENDENT_REPOSITORY_ADMIN_REVIEWER", "signed_at_ms": NOW + 1, "expires_at_ms": NOW + 1000}
    signature = private.sign(canonical_json({"payload": payload, "attestation": attestation}))
    attestation["signature_b64"] = base64.b64encode(signature).decode("ascii")
    # New payload owner mappings and source refs satisfy the tightened V4.25 verifier contract.
    from trading_platform.v21.event_store import EventStore
    authority = RemoteRepositoryGovernanceEvidenceAuthorityV424(
        store=EventStore(), expected_repository=REPO, expected_branch=BRANCH,
        trusted_signer_key_id="test-key", trusted_signer_public_key_b64=base64.b64encode(public).decode("ascii"),
        trusted_signer_id="independent-reviewer", trusted_signer_public_key_sha256=public_hash,
    )
    decision = authority.evaluate(decision_id="v425-synthetic-contract", payload=payload, attestation=attestation, now_ms=NOW + 2, workflow_text=workflow_text)
    assert decision.status == "VERIFIED"
    assert decision.allowed


def test_v425_signer_requires_external_key_path_and_signs_metadata(tmp_path):
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "review-key.pem"
    private_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_path.chmod(0o600)
    payload, _ = _payload()
    payload["attestation"] = None
    evidence_path = tmp_path / "unsigned.json"
    evidence_path.write_text(json.dumps(payload), encoding="utf-8")
    output_path = tmp_path / "signed.json"
    result = subprocess.run(
        [sys.executable, "scripts/sign_github_governance_evidence.py", "--evidence", str(evidence_path),
         "--private-key-pem", str(private_path), "--key-id", "review-key", "--signer-id", "external-reviewer",
         "--output", str(output_path), "--now-ms", str(NOW + 1)],
        cwd=ROOT, shell=False, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    signed = json.loads(output_path.read_text(encoding="utf-8"))
    attestation = dict(signed.pop("attestation"))
    signature = base64.b64decode(attestation.pop("signature_b64"))
    private.public_key().verify(signature, canonical_json({"payload": signed, "attestation": attestation}))
    assert attestation["signer_role"] == "INDEPENDENT_REPOSITORY_ADMIN_REVIEWER"


def test_v425_scripts_use_fixed_argv_and_do_not_modify_remote_provider_state():
    source = (ROOT / "scripts/capture_github_governance.py").read_text(encoding="utf-8")
    assert "shell=False" in source
    assert '"gh", "api"' in source
    assert '"gh", "run", "download"' in source
    assert '"gh", "auth", "status"' in source
    assert "X-GitHub-Api-Version: 2026-03-10" in source
    assert "--method", "POST" not in source
    assert "--method", "PATCH" not in source
    assert "--method", "DELETE" not in source


def test_v425_capture_rejects_repository_path_traversal_and_run_detail_drift():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="REPOSITORY_FORMAT_INVALID"):
        build_github_governance_payload_v425(
            repository="../trading-platform", branch=BRANCH, local_head_sha=HEAD,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda _: {}, download_artifact=lambda *_: [],
        )

    routes = _fixtures(workflow)
    routes["repos/acme/trading-platform/actions/runs/12345"]["head_sha"] = "b" * 40
    with pytest.raises(GitHubGovernanceCaptureErrorV425, match="HOSTED_RUN_DETAIL_MISMATCH:head_sha"):
        build_github_governance_payload_v425(
            repository=REPO, branch=BRANCH, local_head_sha=HEAD,
            local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
            api=lambda route: routes[route], download_artifact=lambda *_: [],
        )


def test_v425_reads_inherited_organization_ruleset_from_organization_endpoint():
    workflow = (ROOT / ".github/workflows/ci.yml").read_bytes()
    ruleset = {"id": 88, "enforcement": "enabled", "source_type": "Organization", "source": "acme"}
    details = {"id": 88, "bypass_actors": []}
    routes = _fixtures(workflow, rulesets=[ruleset])
    routes["orgs/acme/rulesets/88"] = details
    queried = []
    payload = build_github_governance_payload_v425(
        repository=REPO, branch=BRANCH, local_head_sha=HEAD,
        local_workflow_bytes=workflow, captured_at_ms=NOW, ttl_ms=1000,
        api=lambda route: (queried.append(route), routes[route])[1],
        download_artifact=lambda *_: [
            ("V425_MILESTONE_PREFLIGHT.json", b"report"),
            ("V425_MILESTONE_PREFLIGHT.sqlite3", b"db"),
        ],
    )
    assert "orgs/acme/rulesets/88" in queried
    assert "https://api.github.com/orgs/acme/rulesets/88" in payload["source_refs"]
    assert payload["branch_protection"]["bypass_actors"] == []


def test_v425_signer_rejects_overly_open_external_private_key(tmp_path):
    private = Ed25519PrivateKey.generate()
    private_path = tmp_path / "insecure-review-key.pem"
    private_path.write_bytes(private.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    private_path.chmod(0o644)
    payload, _ = _payload()
    evidence_path = tmp_path / "unsigned.json"
    evidence_path.write_text(json.dumps({**payload, "attestation": None}), encoding="utf-8")
    output_path = tmp_path / "signed.json"
    result = subprocess.run(
        [sys.executable, "scripts/sign_github_governance_evidence.py", "--evidence", str(evidence_path),
         "--private-key-pem", str(private_path), "--key-id", "review-key", "--signer-id", "external-reviewer",
         "--output", str(output_path), "--now-ms", str(NOW + 1)],
        cwd=ROOT, shell=False, check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "PRIVATE_KEY_PERMISSIONS_TOO_OPEN" in result.stderr
    assert not output_path.exists()
