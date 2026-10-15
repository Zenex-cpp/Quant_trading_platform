"""Pure transformations for V4.25 read-only GitHub governance evidence capture.

Network/process behavior lives only in scripts/capture_github_governance.py.
These functions fail closed when the provider snapshot is incomplete or ambiguous.
"""
from __future__ import annotations

from hashlib import sha256
import re
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import quote

from trading_platform.v21.event_store import canonical_json
from trading_platform.v427.capture_hardening import (
    CaptureHardeningErrorV427,
    decode_github_content_strict_v427,
)


class GitHubGovernanceCaptureErrorV428(ValueError):
    __test__ = False


_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_BRANCH_SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_HANDLE_USER = re.compile(r"^@([A-Za-z0-9-]+)$")
_HANDLE_TEAM = re.compile(r"^@([A-Za-z0-9-]+)/([A-Za-z0-9-]+)$")
_REQUIRED_CONTEXT = "controlled-milestone-validation"
_WORKFLOW_PATH = ".github/workflows/ci.yml"
_CODEOWNERS_PATH = ".github/CODEOWNERS"
_REQUIRED_FILES = ("V428_MILESTONE_PREFLIGHT.json", "V428_MILESTONE_PREFLIGHT.sqlite3")


def _sha256_bytes(body: bytes) -> str:
    return sha256(body).hexdigest()


def _positive_id(value: Any, label: str) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise GitHubGovernanceCaptureErrorV428(f"{label}_ID_INVALID") from None
    if number <= 0:
        raise GitHubGovernanceCaptureErrorV428(f"{label}_ID_INVALID")
    return str(number)


def _unique_ids(values: Sequence[Any], label: str) -> list[str]:
    normalized = sorted({_positive_id(v, label) for v in values if v is not None})
    if not normalized:
        raise GitHubGovernanceCaptureErrorV428(f"{label}_IDS_MISSING")
    return normalized


def decode_github_content_v428(response: Mapping[str, Any], *, path: str) -> bytes:
    if response.get("type") != "file" or response.get("encoding") != "base64":
        raise GitHubGovernanceCaptureErrorV428(f"REMOTE_FILE_NOT_BASE64_FILE:{path}")
    if str(response.get("path", "")) != path:
        raise GitHubGovernanceCaptureErrorV428(f"REMOTE_FILE_PATH_MISMATCH:{path}")
    try:
        return decode_github_content_strict_v427(response, path=path)
    except CaptureHardeningErrorV427 as exc:
        # Preserve V4.25's public exception type while upgrading its parser.
        raise GitHubGovernanceCaptureErrorV428(str(exc)) from None


def parse_codeowners_v428(body: bytes) -> tuple[list[str], list[str]]:
    """Return unique owner handles and the owners on an explicit self-rule.

    This deliberately does not attempt to implement GitHub's complete pattern
    matcher. The independent reviewer still validates the effective rule set;
    this parser requires an explicit `/.github/CODEOWNERS` rule to exist.
    """
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GitHubGovernanceCaptureErrorV428("CODEOWNERS_NOT_UTF8") from exc
    all_handles: set[str] = set()
    self_rule_owners: list[str] = []
    for raw_line in text.splitlines():
        clean = raw_line.split("#", 1)[0].strip()
        if not clean:
            continue
        parts = clean.split()
        if len(parts) < 2:
            raise GitHubGovernanceCaptureErrorV428("CODEOWNERS_RULE_WITHOUT_OWNER")
        pattern, owners = parts[0], parts[1:]
        if not all(handle.startswith("@") for handle in owners):
            raise GitHubGovernanceCaptureErrorV428("CODEOWNERS_OWNER_TOKEN_INVALID")
        for handle in owners:
            if not (_HANDLE_USER.fullmatch(handle) or _HANDLE_TEAM.fullmatch(handle)):
                raise GitHubGovernanceCaptureErrorV428(f"CODEOWNERS_OWNER_HANDLE_INVALID:{handle}")
            all_handles.add(handle)
        if pattern == "/.github/CODEOWNERS":
            self_rule_owners = owners
    if not all_handles:
        raise GitHubGovernanceCaptureErrorV428("CODEOWNERS_OWNER_HANDLES_MISSING")
    if not self_rule_owners:
        raise GitHubGovernanceCaptureErrorV428("CODEOWNERS_SELF_OWNERSHIP_RULE_REQUIRED")
    return sorted(all_handles, key=str.casefold), list(dict.fromkeys(self_rule_owners))


def _enabled(section: Any, key: str) -> bool | None:
    if not isinstance(section, Mapping):
        return None
    child = section.get(key)
    if not isinstance(child, Mapping) or not isinstance(child.get("enabled"), bool):
        return None
    return bool(child["enabled"])


def _actor_ids_from_rulesets(rulesets: Any) -> list[dict[str, str]]:
    if not isinstance(rulesets, Sequence) or isinstance(rulesets, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESETS_SNAPSHOT_INVALID")
    if len(rulesets) >= 100:
        raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESETS_PAGINATION_MAY_BE_INCOMPLETE")
    actors: list[dict[str, str]] = []
    for ruleset in rulesets:
        if not isinstance(ruleset, Mapping):
            raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_ENTRY_INVALID")
        if str(ruleset.get("enforcement", "")).lower() not in {"active", "enabled"}:
            continue
        details = ruleset.get("details")
        if not isinstance(details, Mapping):
            raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_DETAILS_REQUIRED")
        if not isinstance(details.get("bypass_actors"), Sequence) or isinstance(details.get("bypass_actors"), (str, bytes)):
            raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_BYPASS_ACTORS_UNREADABLE")
        for actor in details["bypass_actors"]:
            if not isinstance(actor, Mapping):
                raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_BYPASS_ACTOR_INVALID")
            actor_id = _positive_id(actor.get("actor_id"), "RULESET_BYPASS_ACTOR")
            actor_type = str(actor.get("actor_type", ""))
            bypass_mode = str(actor.get("bypass_mode", ""))
            if not actor_type or not bypass_mode:
                raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_BYPASS_ACTOR_METADATA_MISSING")
            actors.append({"actor_id": actor_id, "actor_type": actor_type, "bypass_mode": bypass_mode})
    # Deliberately conservative: any active ruleset bypass actor is treated as
    # a blocker by V4.24's authority until the independent reviewer confirms
    # scope/applicability; no rule-specific non-applicability is inferred here.
    return sorted(actors, key=lambda x: (x["actor_type"], x["actor_id"], x["bypass_mode"]))


def _normalize_required_checks(protection: Mapping[str, Any]) -> dict[str, Any]:
    checks = protection.get("required_status_checks")
    if not isinstance(checks, Mapping):
        return {"strict": None, "contexts": []}
    contexts: set[str] = set()
    old_contexts = checks.get("contexts", [])
    if isinstance(old_contexts, Sequence) and not isinstance(old_contexts, (str, bytes)):
        contexts.update(str(value) for value in old_contexts if str(value))
    new_checks = checks.get("checks", [])
    if isinstance(new_checks, Sequence) and not isinstance(new_checks, (str, bytes)):
        for check in new_checks:
            if isinstance(check, Mapping) and check.get("context"):
                contexts.add(str(check["context"]))
    return {"strict": checks.get("strict") is True, "contexts": sorted(contexts)}


def _resolve_codeowner(handle: str, api: Callable[[str], Any]) -> dict[str, str]:
    user_match = _HANDLE_USER.fullmatch(handle)
    team_match = _HANDLE_TEAM.fullmatch(handle)
    if user_match:
        login = user_match.group(1)
        route = f"users/{quote(login, safe='')}"
        response = api(route)
        if not isinstance(response, Mapping) or str(response.get("login", "")).casefold() != login.casefold():
            raise GitHubGovernanceCaptureErrorV428(f"CODEOWNERS_USER_RESOLUTION_FAILED:{handle}")
        return {"handle": handle, "kind": "user", "id": _positive_id(response.get("id"), "CODEOWNER_USER"), "source_ref": f"https://api.github.com/{route}"}
    if team_match:
        org, slug = team_match.groups()
        route = f"orgs/{quote(org, safe='')}/teams/{quote(slug, safe='')}"
        response = api(route)
        if not isinstance(response, Mapping) or str(response.get("slug", "")).casefold() != slug.casefold():
            raise GitHubGovernanceCaptureErrorV428(f"CODEOWNERS_TEAM_RESOLUTION_FAILED:{handle}")
        team_org = response.get("organization")
        if isinstance(team_org, Mapping) and str(team_org.get("login", "")).casefold() != org.casefold():
            raise GitHubGovernanceCaptureErrorV428(f"CODEOWNERS_TEAM_ORG_MISMATCH:{handle}")
        return {"handle": handle, "kind": "team", "id": _positive_id(response.get("id"), "CODEOWNER_TEAM"), "source_ref": f"https://api.github.com/{route}"}
    raise GitHubGovernanceCaptureErrorV428(f"CODEOWNERS_OWNER_HANDLE_INVALID:{handle}")


def build_github_governance_payload_v428(
    *,
    repository: str,
    branch: str,
    local_head_sha: str,
    local_workflow_bytes: bytes,
    captured_at_ms: int,
    ttl_ms: int,
    api: Callable[[str], Any],
    download_artifact: Callable[[int, str], Sequence[tuple[str, bytes]]],
) -> dict[str, Any]:
    """Capture and normalize a read-only provider snapshot.

    `api` performs exactly one read-only GET for the supplied fixed route.
    `download_artifact` downloads a named run artifact and returns basename/body
    pairs. Those injected interfaces make the normalizer unit-testable offline.
    """
    if not _REPOSITORY.fullmatch(repository) or any(part in {".", ".."} for part in repository.split("/")):
        raise GitHubGovernanceCaptureErrorV428("REPOSITORY_FORMAT_INVALID")
    if not branch or branch.startswith("-") or "\x00" in branch or "\n" in branch:
        raise GitHubGovernanceCaptureErrorV428("BRANCH_FORMAT_INVALID")
    if not _BRANCH_SHA.fullmatch(local_head_sha.lower()):
        raise GitHubGovernanceCaptureErrorV428("LOCAL_HEAD_SHA_INVALID")
    if int(captured_at_ms) <= 0 or int(ttl_ms) <= 0 or int(ttl_ms) > 86_400_000:
        raise GitHubGovernanceCaptureErrorV428("CAPTURE_TIME_OR_TTL_INVALID")

    owner, repo_name = repository.split("/", 1)
    canonical_repo = f"{owner}/{repo_name}"
    prefix = f"repos/{owner}/{repo_name}"
    branch_q = quote(branch, safe="")
    source_refs: list[str] = []

    repo_meta = api(prefix)
    source_refs.append(f"https://api.github.com/{prefix}")
    if not isinstance(repo_meta, Mapping) or str(repo_meta.get("full_name", "")).casefold() != canonical_repo.casefold():
        raise GitHubGovernanceCaptureErrorV428("REPOSITORY_METADATA_SCOPE_MISMATCH")
    if str(repo_meta.get("default_branch", "")) != branch:
        raise GitHubGovernanceCaptureErrorV428("BRANCH_IS_NOT_REPOSITORY_DEFAULT_BRANCH")

    branch_route = f"{prefix}/branches/{branch_q}"
    branch_meta = api(branch_route)
    source_refs.append(f"https://api.github.com/{branch_route}")
    if not isinstance(branch_meta, Mapping) or branch_meta.get("protected") is not True:
        raise GitHubGovernanceCaptureErrorV428("PROTECTED_BRANCH_REQUIRED")
    commit = branch_meta.get("commit")
    commit_obj = commit.get("commit") if isinstance(commit, Mapping) else None
    commit_sha = str(commit.get("sha", "")).lower() if isinstance(commit, Mapping) else ""
    if not _BRANCH_SHA.fullmatch(commit_sha):
        raise GitHubGovernanceCaptureErrorV428("REMOTE_PROTECTED_HEAD_SHA_INVALID")
    if commit_sha != local_head_sha.lower():
        raise GitHubGovernanceCaptureErrorV428("LOCAL_CHECKOUT_DOES_NOT_MATCH_REMOTE_PROTECTED_HEAD")
    if not isinstance(commit_obj, Mapping):
        # The branch endpoint's commit object is normally available. Full commit
        # details are requested below for identity/source normalization.
        commit_obj = {}

    protection_route = f"{prefix}/branches/{branch_q}/protection"
    protection = api(protection_route)
    if not isinstance(protection, Mapping):
        raise GitHubGovernanceCaptureErrorV428("BRANCH_PROTECTION_RESPONSE_INVALID")
    source_refs.append(f"https://api.github.com/{protection_route}")

    rulesets_route = f"{prefix}/rulesets?includes_parents=true&per_page=100"
    raw_rulesets = api(rulesets_route)
    if not isinstance(raw_rulesets, Sequence) or isinstance(raw_rulesets, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESETS_RESPONSE_INVALID")
    normalized_rulesets: list[dict[str, Any]] = []
    for ruleset in raw_rulesets:
        if not isinstance(ruleset, Mapping) or ruleset.get("id") is None:
            raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_ENTRY_INVALID")
        enforcement = str(ruleset.get("enforcement", ""))
        ruleset_id = int(ruleset["id"])
        source_type = str(ruleset.get("source_type", "Repository"))
        source_name = str(ruleset.get("source", canonical_repo))
        if source_type == "Repository":
            detail_route = f"{prefix}/rulesets/{ruleset_id}"
        elif source_type == "Organization":
            if not source_name or "/" in source_name:
                raise GitHubGovernanceCaptureErrorV428("ORGANIZATION_RULESET_SOURCE_INVALID")
            detail_route = f"orgs/{quote(source_name, safe='')}/rulesets/{ruleset_id}"
        elif source_type == "Enterprise":
            if not source_name or "/" in source_name:
                raise GitHubGovernanceCaptureErrorV428("ENTERPRISE_RULESET_SOURCE_INVALID")
            detail_route = f"enterprises/{quote(source_name, safe='')}/rulesets/{ruleset_id}"
        else:
            raise GitHubGovernanceCaptureErrorV428("RULESET_SOURCE_TYPE_UNSUPPORTED")
        details = api(detail_route)
        if not isinstance(details, Mapping) or int(details.get("id", -1)) != ruleset_id:
            raise GitHubGovernanceCaptureErrorV428("REPOSITORY_RULESET_DETAILS_UNAVAILABLE")
        normalized_rulesets.append({"enforcement": enforcement, "details": details})
        source_refs.append(f"https://api.github.com/{detail_route}")
    bypass_actors = _actor_ids_from_rulesets(normalized_rulesets)
    source_refs.append(f"https://api.github.com/{rulesets_route}")

    workflow_route = f"{prefix}/contents/{_WORKFLOW_PATH}?ref={commit_sha}"
    workflow_remote = decode_github_content_v428(api(workflow_route), path=_WORKFLOW_PATH)
    if workflow_remote != local_workflow_bytes:
        raise GitHubGovernanceCaptureErrorV428("REMOTE_WORKFLOW_DIFFERS_FROM_LOCAL_CHECKOUT")
    workflow_sha = _sha256_bytes(workflow_remote)
    source_refs.append(f"https://api.github.com/{prefix}/contents/{_WORKFLOW_PATH}?ref={commit_sha}")

    codeowners_route = f"{prefix}/contents/{_CODEOWNERS_PATH}?ref={commit_sha}"
    codeowners_body = decode_github_content_v428(api(codeowners_route), path=_CODEOWNERS_PATH)
    handles, self_rule_owners = parse_codeowners_v428(codeowners_body)
    mappings = [_resolve_codeowner(handle, api) for handle in handles]
    owner_map = {m["handle"]: m for m in mappings}
    if any(handle not in owner_map for handle in self_rule_owners):
        raise GitHubGovernanceCaptureErrorV428("CODEOWNERS_SELF_OWNER_NOT_RESOLVED")
    codeowners_record = {
        "path": _CODEOWNERS_PATH,
        "sha256": _sha256_bytes(codeowners_body),
        "source_ref": f"https://api.github.com/{codeowners_route}",
        "owner_mappings": mappings,
        "self_ownership_rule": {"pattern": "/.github/CODEOWNERS", "owners": self_rule_owners},
    }
    source_refs.append(codeowners_record["source_ref"])

    commit_route = f"{prefix}/commits/{commit_sha}"
    head_commit = api(commit_route)
    if not isinstance(head_commit, Mapping):
        raise GitHubGovernanceCaptureErrorV428("HEAD_COMMIT_METADATA_UNAVAILABLE")
    commit_author = head_commit.get("author")
    commit_committer = head_commit.get("committer")
    change_author_ids = _unique_ids([
        commit_author.get("id") if isinstance(commit_author, Mapping) else None,
        commit_committer.get("id") if isinstance(commit_committer, Mapping) else None,
    ], "CHANGE_AUTHOR")
    source_refs.append(f"https://api.github.com/{commit_route}")

    workflow_history_route = f"{prefix}/commits?path={quote(_WORKFLOW_PATH, safe='/')}&sha={commit_sha}&per_page=100"
    workflow_history = api(workflow_history_route)
    if not isinstance(workflow_history, Sequence) or isinstance(workflow_history, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("WORKFLOW_COMMIT_HISTORY_INVALID")
    if len(workflow_history) >= 100:
        raise GitHubGovernanceCaptureErrorV428("WORKFLOW_COMMIT_HISTORY_MAY_BE_INCOMPLETE")
    workflow_ids: list[Any] = []
    for item in workflow_history:
        if not isinstance(item, Mapping):
            raise GitHubGovernanceCaptureErrorV428("WORKFLOW_COMMIT_HISTORY_ENTRY_INVALID")
        for field in ("author", "committer"):
            actor = item.get(field)
            workflow_ids.append(actor.get("id") if isinstance(actor, Mapping) else None)
    workflow_author_ids = _unique_ids(workflow_ids, "WORKFLOW_AUTHOR")
    source_refs.append(f"https://api.github.com/{workflow_history_route}")

    associated_route = f"{prefix}/commits/{commit_sha}/pulls?per_page=100"
    associated_prs = api(associated_route)
    if not isinstance(associated_prs, Sequence) or isinstance(associated_prs, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("ASSOCIATED_PULL_REQUESTS_INVALID")
    if len(associated_prs) >= 100:
        raise GitHubGovernanceCaptureErrorV428("ASSOCIATED_PULL_REQUESTS_MAY_BE_INCOMPLETE")
    merge_actor_values: list[Any] = []
    for pr in associated_prs:
        if not isinstance(pr, Mapping):
            continue
        merged_at = pr.get("merged_at")
        merge_sha = str(pr.get("merge_commit_sha", "")).lower()
        merged_by = pr.get("merged_by")
        if merged_at and merge_sha == commit_sha and isinstance(merged_by, Mapping):
            merge_actor_values.append(merged_by.get("id"))
    merge_actor_ids = _unique_ids(merge_actor_values, "MERGE_ACTOR")
    source_refs.append(f"https://api.github.com/{associated_route}")

    runs_route = f"{prefix}/actions/workflows/ci.yml/runs?branch={quote(branch, safe='')}&event=push&status=completed&per_page=100"
    runs_response = api(runs_route)
    runs = runs_response.get("workflow_runs") if isinstance(runs_response, Mapping) else None
    if not isinstance(runs, Sequence) or isinstance(runs, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("WORKFLOW_RUNS_RESPONSE_INVALID")
    if len(runs) >= 100:
        raise GitHubGovernanceCaptureErrorV428("WORKFLOW_RUN_LIST_MAY_BE_INCOMPLETE")
    candidates = [run for run in runs if isinstance(run, Mapping)
                  and str(run.get("head_sha", "")).lower() == commit_sha
                  and str(run.get("head_branch", "")) == branch
                  and run.get("status") == "completed" and run.get("conclusion") == "success"
                  and run.get("event") == "push" and str(run.get("path", "")) == _WORKFLOW_PATH]
    if not candidates:
        raise GitHubGovernanceCaptureErrorV428("SUCCESSFUL_HOSTED_RUN_FOR_PROTECTED_HEAD_REQUIRED")
    run = max(candidates, key=lambda item: (int(item.get("run_number", 0)), int(item.get("run_attempt", 0))))
    run_id = int(run.get("id", 0))
    run_attempt = int(run.get("run_attempt", 0))
    if run_id <= 0 or run_attempt <= 0:
        raise GitHubGovernanceCaptureErrorV428("HOSTED_RUN_ID_INVALID")
    run_detail_route = f"{prefix}/actions/runs/{run_id}"
    run_detail = api(run_detail_route)
    if not isinstance(run_detail, Mapping):
        raise GitHubGovernanceCaptureErrorV428("HOSTED_RUN_DETAIL_RESPONSE_INVALID")
    for field, expected in (("id", run_id), ("run_attempt", run_attempt), ("status", "completed"), ("conclusion", "success"), ("event", "push"), ("head_branch", branch), ("head_sha", commit_sha), ("path", _WORKFLOW_PATH)):
        actual = run_detail.get(field)
        if field in {"head_sha"}:
            actual = str(actual or "").lower()
        if actual != expected:
            raise GitHubGovernanceCaptureErrorV428(f"HOSTED_RUN_DETAIL_MISMATCH:{field}")
    source_refs.append(f"https://api.github.com/{run_detail_route}")

    job_route = f"{prefix}/actions/runs/{run_id}/jobs?per_page=100"
    jobs_response = api(job_route)
    jobs = jobs_response.get("jobs") if isinstance(jobs_response, Mapping) else None
    if not isinstance(jobs, Sequence) or isinstance(jobs, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("HOSTED_RUN_JOBS_RESPONSE_INVALID")
    matching_jobs = [job for job in jobs if isinstance(job, Mapping) and job.get("name") == _REQUIRED_CONTEXT]
    if not any(job.get("status") == "completed" and job.get("conclusion") == "success" for job in matching_jobs):
        raise GitHubGovernanceCaptureErrorV428("REQUIRED_HOSTED_JOB_NOT_SUCCESSFUL")
    if len(jobs) >= 100:
        raise GitHubGovernanceCaptureErrorV428("HOSTED_RUN_JOBS_MAY_BE_INCOMPLETE")
    source_refs.append(f"https://api.github.com/{job_route}")

    artifacts_route = f"{prefix}/actions/runs/{run_id}/artifacts?per_page=100"
    artifacts_response = api(artifacts_route)
    artifacts = artifacts_response.get("artifacts") if isinstance(artifacts_response, Mapping) else None
    if not isinstance(artifacts, Sequence) or isinstance(artifacts, (str, bytes)):
        raise GitHubGovernanceCaptureErrorV428("HOSTED_RUN_ARTIFACTS_RESPONSE_INVALID")
    if len(artifacts) >= 100:
        raise GitHubGovernanceCaptureErrorV428("HOSTED_RUN_ARTIFACT_LIST_MAY_BE_INCOMPLETE")
    artifact_name = f"V428-validation-audit-{run_id}-{run_attempt}"
    matches = [a for a in artifacts if isinstance(a, Mapping) and a.get("name") == artifact_name and a.get("expired") is False]
    if len(matches) != 1:
        raise GitHubGovernanceCaptureErrorV428("EXPECTED_VALIDATION_ARTIFACT_MISSING_OR_AMBIGUOUS")
    downloaded_files = list(download_artifact(run_id, artifact_name))
    normalized_files: dict[str, bytes] = {}
    for name, body in downloaded_files:
        base = str(name).replace("\\", "/").split("/")[-1]
        if base in _REQUIRED_FILES:
            if base in normalized_files:
                raise GitHubGovernanceCaptureErrorV428(f"DUPLICATE_REQUIRED_ARTIFACT_FILE:{base}")
            if not isinstance(body, bytes) or not body:
                raise GitHubGovernanceCaptureErrorV428(f"REQUIRED_ARTIFACT_FILE_EMPTY:{base}")
            normalized_files[base] = body
    missing = sorted(set(_REQUIRED_FILES) - set(normalized_files))
    if missing:
        raise GitHubGovernanceCaptureErrorV428("REQUIRED_PREFLIGHT_ARTIFACT_FILES_MISSING:" + ",".join(missing))
    artifact_hashes = [{"name": name, "sha256": _sha256_bytes(normalized_files[name])} for name in sorted(_REQUIRED_FILES)]
    source_refs.append(f"https://api.github.com/{artifacts_route}")

    checks = _normalize_required_checks(protection)
    reviews = protection.get("required_pull_request_reviews")
    reviews = reviews if isinstance(reviews, Mapping) else {}
    bypass_actor_evidence: list[dict[str, str]] = bypass_actors
    payload = {
        "schema_version": "V4.24",
        "snapshot_id": f"github-{owner.lower()}-{repo_name.lower()}-{branch}-{commit_sha[:12]}-{int(captured_at_ms)}",
        "provider": "github",
        "repository": canonical_repo,
        "protected_branch": branch,
        "protected_head_sha": commit_sha,
        "workflow_sha256": workflow_sha,
        "codeowners_file": codeowners_record,
        "captured_at_ms": int(captured_at_ms),
        "expires_at_ms": int(captured_at_ms) + int(ttl_ms),
        "branch_protection": {
            "enabled": branch_meta.get("protected") is True,
            "enforce_admins": _enabled(protection, "enforce_admins") is True,
            "allow_force_pushes": _enabled(protection, "allow_force_pushes"),
            "allow_deletions": _enabled(protection, "allow_deletions"),
            "bypass_actors": bypass_actor_evidence,
            "required_status_checks": checks,
            "required_pull_request_reviews": {
                "required_approving_review_count": reviews.get("required_approving_review_count"),
                "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews") is True,
                "require_code_owner_reviews": reviews.get("require_code_owner_reviews") is True,
            },
        },
        "hosted_workflow_run": {
            "repository": canonical_repo,
            "run_id": run_id,
            "run_attempt": run_attempt,
            "status": str(run.get("status")),
            "conclusion": str(run.get("conclusion")),
            "event": str(run.get("event")),
            "branch": str(run.get("head_branch")),
            "head_sha": str(run.get("head_sha", "")).lower(),
            "workflow_path": str(run.get("path")),
            "job_name": _REQUIRED_CONTEXT,
            "status_check_context": _REQUIRED_CONTEXT,
            "status_check_conclusion": "success",
            "run_url": f"https://github.com/{canonical_repo}/actions/runs/{run_id}",
            "artifacts": artifact_hashes,
        },
        "source_refs": sorted(set(source_refs)),
        "workflow_author_ids": workflow_author_ids,
        "change_author_ids": change_author_ids,
        "merge_actor_ids": merge_actor_ids,
    }
    return payload
