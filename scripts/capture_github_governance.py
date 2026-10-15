#!/usr/bin/env python3
"""Read-only capture of real GitHub repository governance evidence.

Requires GitHub CLI authentication with read access to repository metadata,
contents, actions and administration settings. Does not modify provider state.
The output is unsigned and must be reviewed/signed by the independent reviewer.
"""
from __future__ import annotations
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v428.github_capture import build_github_governance_payload_v428, GitHubGovernanceCaptureErrorV428
from trading_platform.v427.capture_hardening import (
    CaptureHardeningErrorV427,
    validate_capture_artifact_size_v427,
)
from trading_platform.v428.path_safety import (
    PathSafetyErrorV428, ensure_paths_distinct_v428, resolve_repository_path_v428,
    write_audit_text_v428,
)

_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _run(args: list[str], *, cwd: Path = ROOT, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            args, cwd=cwd, env={**os.environ, "GH_PROMPT_DISABLED": "1"},
            shell=False, check=False, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise GitHubGovernanceCaptureErrorV428("GITHUB_CLI_COMMAND_FAILED_OR_TIMED_OUT") from None
    if completed.returncode != 0:
        # Do not echo stderr/stdout: CLI errors may contain sensitive request details.
        raise GitHubGovernanceCaptureErrorV428(f"GITHUB_CLI_COMMAND_FAILED:{Path(args[0]).name}:{completed.returncode}")
    return completed


def _api(route: str) -> object:
    result = _run([
        "gh", "api", route,
        "-H", "Accept: application/vnd.github+json",
        "-H", "X-GitHub-Api-Version: 2026-03-10",
    ])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise GitHubGovernanceCaptureErrorV428("GITHUB_API_JSON_INVALID") from None


def _download(run_id: int, artifact_name: str, repository: str) -> list[tuple[str, bytes]]:
    with tempfile.TemporaryDirectory(prefix="v425-gh-artifact-") as temp:
        dest = Path(temp).resolve()
        _run(["gh", "run", "download", str(run_id), "--repo", repository,
              "--name", artifact_name, "--dir", str(dest)], timeout=180)
        files: list[tuple[str, bytes]] = []
        total_bytes = 0
        for candidate in dest.rglob("*"):
            if candidate.is_symlink():
                raise GitHubGovernanceCaptureErrorV428("ARTIFACT_SYMLINK_REJECTED")
            if not candidate.is_file():
                continue
            resolved = candidate.resolve()
            if not resolved.is_relative_to(dest):
                raise GitHubGovernanceCaptureErrorV428("ARTIFACT_PATH_ESCAPE_REJECTED")
            if candidate.name in {"V428_MILESTONE_PREFLIGHT.json", "V428_MILESTONE_PREFLIGHT.sqlite3"}:
                try:
                    size = candidate.stat().st_size
                    total_bytes = validate_capture_artifact_size_v427(
                        candidate.name, size, total_so_far_bytes=total_bytes
                    )
                    # Read at most the declared per-file limit + 1 byte to avoid
                    # unbounded allocation if an artifact changes after stat().
                    limit = size if size <= 0 else size
                    with candidate.open("rb") as stream:
                        body = stream.read(limit + 1)
                    if len(body) != size:
                        raise GitHubGovernanceCaptureErrorV428("ARTIFACT_SIZE_CHANGED_DURING_READ")
                    files.append((candidate.relative_to(dest).as_posix(), body))
                except CaptureHardeningErrorV427 as exc:
                    raise GitHubGovernanceCaptureErrorV428(str(exc)) from None
        return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="OWNER/REPOSITORY")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--output", default=".audit/V428_REPOSITORY_GOVERNANCE_UNSIGNED.json")
    parser.add_argument("--ttl-ms", type=int, default=86_400_000)
    parser.add_argument("--captured-at-ms", type=int, default=None)
    args = parser.parse_args(argv)
    if not _REPO_RE.fullmatch(args.repository):
        parser.error("--repository must be OWNER/REPOSITORY")
    try:
        target = resolve_repository_path_v428(ROOT, args.output, label="CAPTURE_OUTPUT", output_scope=".audit")
        workflow_path = resolve_repository_path_v428(ROOT, ".github/workflows/ci.yml", label="WORKFLOW", must_exist_file=True)
        ensure_paths_distinct_v428(
            outputs={"capture_output": target},
            protected_inputs={"workflow": workflow_path, "capture_script": Path(__file__).resolve()},
        )
        if target.suffix.lower() != ".json":
            raise PathSafetyErrorV428("CAPTURE_OUTPUT_JSON_REQUIRED")
        reserved = {
            (ROOT / ".audit/V428_MILESTONE_PREFLIGHT.json").resolve(),
            (ROOT / ".audit/V428_MILESTONE_PREFLIGHT.sqlite3").resolve(),
            (ROOT / ".audit/V428_REPOSITORY_GOVERNANCE.json").resolve(),
            (ROOT / ".audit/V428_REPOSITORY_GOVERNANCE.sqlite3").resolve(),
        }
        if target in reserved:
            raise PathSafetyErrorV428("CAPTURE_OUTPUT_RESERVED_AUDIT_PATH")
    except PathSafetyErrorV428 as exc:
        parser.error(f"PATH_POLICY_REJECTED:{exc}")
    _run(["gh", "auth", "status"], timeout=20)
    head = _run(["git", "rev-parse", "HEAD"], cwd=ROOT, timeout=10).stdout.strip().lower()
    workflow_bytes = workflow_path.read_bytes()
    captured_at_ms = args.captured_at_ms if args.captured_at_ms is not None else time.time_ns() // 1_000_000
    try:
        payload = build_github_governance_payload_v428(
            repository=args.repository, branch=args.branch, local_head_sha=head,
            local_workflow_bytes=workflow_bytes, captured_at_ms=captured_at_ms, ttl_ms=args.ttl_ms,
            api=_api, download_artifact=lambda run_id, name: _download(run_id, name, args.repository),
        )
        output = {**payload, "attestation": None}
        target.parent.mkdir(parents=True, exist_ok=True)
        write_audit_text_v428(ROOT, target, json.dumps(output, indent=2, sort_keys=True) + "\n")
    except (GitHubGovernanceCaptureErrorV428, PathSafetyErrorV428) as exc:
        print(f"GITHUB_GOVERNANCE_CAPTURE=BLOCKED:{exc}", file=sys.stderr)
        return 2
    print("GITHUB_GOVERNANCE_CAPTURE=CAPTURED_UNSIGNED")
    print(f"REPOSITORY={payload['repository']}")
    print(f"BRANCH={payload['protected_branch']}")
    print(f"HEAD_SHA={payload['protected_head_sha']}")
    print(f"OUTPUT={target.relative_to(ROOT)}")
    print("SIGNATURE_REQUIRED=INDEPENDENT_REVIEWER_OUTSIDE_THIS_WORKFLOW")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
