#!/usr/bin/env python3
"""Mandatory, fixed-command milestone preflight and validation runner.

Only the pinned repository regression and release-hygiene commands may run.
This runner intentionally accepts no arbitrary command string and never enables
production or trading runtime. CI invokes the same entrypoint as local release
validation, then uploads the JSON report and SQLite audit ledger.
"""
from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_MILESTONE_ID = "V4.28-RECOVERY"
EXPECTED_BASELINE_VERSION = "V4.27-RECOVERY"
EXPECTED_MATRIX_PATH = "compliance_v428.csv"
EXPECTED_BASELINE_HASH_PATH = "V427_BASELINE_ARCHIVE_SHA256.txt"
EXPECTED_IMPACTED_IDS = ("CI-PREFLIGHT-01", "REPO-GOV-01", "REPO-GOV-02", "REPO-GOV-03", "REPO-GOV-CAPTURE-01", "REPO-GOV-SIGN-01", "REPO-GOV-PATH-01", "REPO-GOV-PATH-02")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v21.event_store import EventStore
from trading_platform.v422.milestone_compliance_preflight import (
    MilestoneCompliancePreflightAuthorityV422,
    MilestonePreflightErrorV422,
)
from trading_platform.v428.repository_governance import validate_workflow_contract_v428
from trading_platform.v428.path_safety import (
    PathSafetyErrorV428, ensure_paths_distinct_v428, resolve_repository_path_v428,
    write_audit_text_v428,
)


CONTRACT_FILES = (
    "compliance_v428.csv",
    "V427_BASELINE_ARCHIVE_SHA256.txt",
    "V424_REPOSITORY_GOVERNANCE_EVIDENCE_TEMPLATE.json",
    "V428_EXTERNAL_EVIDENCE.json",
    "V428_RECONSTRUCTION_NOTE.md",
    "V424_RECONSTRUCTION_NOTE.md",
    "V425_RECONSTRUCTION_NOTE.md",
    "docs/V425_REPOSITORY_GOVERNANCE_CAPTURE.md",
    "docs/V428_PATH_CONFINEMENT.md",
    ".github/workflows/ci.yml",
    "scripts/run_milestone_validation.py",
    "scripts/validate_release_hygiene.py",
    "scripts/verify_repository_governance.py",
    "scripts/capture_github_governance.py",
    "scripts/sign_github_governance_evidence.py",
    "requirements-ci.txt",
    "src/trading_platform/v422/milestone_compliance_preflight.py",
    "src/trading_platform/v424/repository_governance.py",
    "src/trading_platform/v425/github_capture.py",
    "src/trading_platform/v427/capture_hardening.py",
    "src/trading_platform/v428/github_capture.py",
    "src/trading_platform/v428/repository_governance.py",
    "src/trading_platform/v428/path_safety.py",
    "tests/v422/test_milestone_compliance_preflight.py",
    "tests/v423/test_milestone_entrypoint.py",
    "tests/v424/test_repository_governance.py",
    "tests/v425/test_github_capture.py",
    "tests/v425/test_milestone_pipeline_v425.py",
    "tests/v428/test_github_capture_v428.py",
    "tests/v427/test_capture_hardening_v427.py",
    "tests/v428/test_path_safety_v428.py",
    "tests/v428/test_repository_governance_v428.py",
    "schemas/v424_milestone_preflight.schema.json",
    "schemas/v424_repository_governance_evidence.schema.json",
    "schemas/v428_repository_governance_evidence.schema.json",
    "config/repository_governance_trust_v424.json",
)


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"CONTRACT_FILE_MISSING:{path}")
    h = sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    return rows


def _write_report(path: Path, payload: dict) -> None:
    write_audit_text_v428(ROOT, path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--milestone-id", default=EXPECTED_MILESTONE_ID)
    parser.add_argument("--baseline-version", default=EXPECTED_BASELINE_VERSION)
    parser.add_argument("--baseline-sha256-file", default=EXPECTED_BASELINE_HASH_PATH)
    parser.add_argument("--matrix", default=EXPECTED_MATRIX_PATH)
    parser.add_argument("--impacted-requirement", action="append", default=[], help="Must equal the fixed impacted-control set for this recovery release")
    parser.add_argument("--owner", default="Platform Engineering")
    parser.add_argument("--decision-id", default=None)
    parser.add_argument("--event-store", default=".audit/V428_MILESTONE_PREFLIGHT.sqlite3")
    parser.add_argument("--report", default=".audit/V428_MILESTONE_PREFLIGHT.json")
    parser.add_argument("--audit-only", action="store_true", help="Record/revalidate preflight but do not dispatch tests or hygiene")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = ROOT
    if args.matrix != EXPECTED_MATRIX_PATH or args.baseline_sha256_file != EXPECTED_BASELINE_HASH_PATH:
        raise SystemExit("MATRIX_OR_BASELINE_PATH_NOT_AUTHORIZED_FOR_RECOVERY_BUILD")
    try:
        matrix_path = resolve_repository_path_v428(root, args.matrix, label="MATRIX", must_exist_file=True)
        baseline_path = resolve_repository_path_v428(root, args.baseline_sha256_file, label="BASELINE", must_exist_file=True)
        workflow_path = resolve_repository_path_v428(root, ".github/workflows/ci.yml", label="WORKFLOW", must_exist_file=True)
        event_path = resolve_repository_path_v428(root, args.event_store, label="EVENT_STORE", output_scope=".audit")
        report_path = resolve_repository_path_v428(root, args.report, label="REPORT", output_scope=".audit")
        protected = {name: resolve_repository_path_v428(root, name, label="CONTRACT_INPUT", must_exist_file=True) for name in CONTRACT_FILES}
        protected.update({"matrix": matrix_path, "baseline": baseline_path, "workflow": workflow_path})
        ensure_paths_distinct_v428(
            outputs={"event_store": event_path, "report": report_path},
            protected_inputs=protected,
        )
        if event_path == report_path:
            raise PathSafetyErrorV428("OUTPUT_PATH_COLLISION:event_store:report")
    except PathSafetyErrorV428 as exc:
        raise SystemExit(f"PATH_POLICY_REJECTED:{exc}") from None
    decision_id = args.decision_id or f"V428-{uuid.uuid4().hex}"
    impacted = tuple(sorted(args.impacted_requirement or EXPECTED_IMPACTED_IDS))
    if args.milestone_id != EXPECTED_MILESTONE_ID:
        raise SystemExit(f"MILESTONE_ID_NOT_AUTHORIZED:{EXPECTED_MILESTONE_ID}")
    if args.baseline_version != EXPECTED_BASELINE_VERSION:
        raise SystemExit(f"BASELINE_VERSION_NOT_AUTHORIZED:{EXPECTED_BASELINE_VERSION}")
    if args.matrix != EXPECTED_MATRIX_PATH or args.baseline_sha256_file != EXPECTED_BASELINE_HASH_PATH:
        raise SystemExit("MATRIX_OR_BASELINE_PATH_NOT_AUTHORIZED_FOR_RECOVERY_BUILD")
    if impacted != tuple(sorted(EXPECTED_IMPACTED_IDS)):
        raise SystemExit("IMPACTED_REQUIREMENT_SET_MISMATCH")
    report: dict = {
        "schema_version": "V4.28",
        "milestone_id": args.milestone_id,
        "decision_id": decision_id,
        "owner": args.owner,
        "status": "BLOCKED",
        "steps": [],
        "external_evidence": False,
        "production_ready": False,
        "activation_flag": "NOT_SET",
        "source_lineage": "RECOVERY_BUILD_FROM_V4.27_RECOVERY_ARCHIVE; ORIGINAL_CANONICAL_V4.23_AND_V4.26_LINEAGE_NOT_ESTABLISHED",
    }
    try:
        rows = _load_rows(matrix_path)
        baseline_sha = baseline_path.read_text(encoding="utf-8").strip().split()[0].lower()
        if len(baseline_sha) != 64 or any(ch not in "0123456789abcdef" for ch in baseline_sha):
            raise ValueError("BASELINE_SHA256_FILE_INVALID")
        workflow_text = workflow_path.read_text(encoding="utf-8")
        workflow_blockers = list(validate_workflow_contract_v428(workflow_text))
        if workflow_blockers:
            raise ValueError("WORKFLOW_CONTRACT_BLOCKED:" + ",".join(workflow_blockers))
        input_hashes = {rel: _sha256(root / rel) for rel in CONTRACT_FILES}
        event_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        store = EventStore(str(event_path))
        authority = MilestoneCompliancePreflightAuthorityV422(store)
        decision = authority.evaluate(
            decision_id=decision_id,
            milestone_id=args.milestone_id,
            baseline_version=args.baseline_version,
            baseline_sha256=baseline_sha,
            rows=rows,
            impacted_ids=impacted,
            input_hashes=input_hashes,
            now_ms=time.time_ns() // 1_000_000,
        )
        report.update({
            "status": decision.status,
            "allowed": decision.allowed,
            "baseline_version": decision.baseline_version,
            "baseline_sha256": decision.baseline_sha256,
            "matrix_hash": decision.matrix_hash,
            "input_hashes": dict(decision.input_hashes),
            "impacted_ids": list(decision.impacted_ids),
            "blocking_reasons": list(decision.blockers),
            "preflight_event_hash": decision.event_hash,
            "event_store": str(event_path.relative_to(root)) if event_path.is_relative_to(root) else str(event_path),
            "audit_only": bool(args.audit_only),
        })
        _write_report(report_path, report)
        if not decision.allowed:
            return 2
        if args.audit_only:
            report["pipeline_status"] = "PRECHECK_ONLY"
            _write_report(report_path, report)
            return 0

        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env.setdefault("PIP_NO_CACHE_DIR", "1")
        fixed_commands = [
            ("full_regression", [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--disable-warnings", "--maxfail=1"]),
            ("release_hygiene", [sys.executable, "scripts/validate_release_hygiene.py", str(root)]),
        ]
        report["pipeline_status"] = "RUNNING"
        _write_report(report_path, report)
        for step_name, command in fixed_commands:
            # Re-read and re-hash everything immediately before every fixed command.
            current_rows = _load_rows(matrix_path)
            current_baseline = baseline_path.read_text(encoding="utf-8").strip().split()[0].lower()
            current_hashes = {rel: _sha256(root / rel) for rel in CONTRACT_FILES}
            authority.assert_current(
                decision_id,
                rows=current_rows,
                baseline_version=args.baseline_version,
                baseline_sha256=current_baseline,
                input_hashes=current_hashes,
            )
            current_workflow = workflow_path.read_text(encoding="utf-8")
            current_workflow_blockers = validate_workflow_contract_v428(current_workflow)
            if current_workflow_blockers:
                raise MilestonePreflightErrorV422("WORKFLOW_CONTRACT_CHANGED:" + ",".join(current_workflow_blockers))
            started = time.time_ns() // 1_000_000
            completed = subprocess.run(command, cwd=root, env=env, shell=False, check=False, text=True)
            step = {
                "name": step_name,
                "command": command,
                "return_code": int(completed.returncode),
                "started_at_ms": started,
                "finished_at_ms": time.time_ns() // 1_000_000,
                "status": "PASS" if completed.returncode == 0 else "FAIL",
            }
            report["steps"].append(step)
            _write_report(report_path, report)
            if completed.returncode != 0:
                report["status"] = "BLOCKED"
                report["pipeline_status"] = "FAILED"
                report["blocking_reasons"] = [f"PIPELINE_STEP_FAILED:{step_name}:{completed.returncode}"]
                _write_report(report_path, report)
                return int(completed.returncode or 1)
        report["status"] = "READY_FOR_MILESTONE"
        report["pipeline_status"] = "PASS"
        report["release_hygiene"] = "PASS"
        _write_report(report_path, report)
        return 0
    except Exception as exc:
        report["status"] = "BLOCKED"
        report["pipeline_status"] = "FAILED_CLOSED"
        report["blocking_reasons"] = [f"{type(exc).__name__}:{exc}"]
        _write_report(report_path, report)
        print(f"MILESTONE_VALIDATION=BLOCKED {type(exc).__name__}:{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
