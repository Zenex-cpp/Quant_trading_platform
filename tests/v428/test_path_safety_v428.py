from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v428.path_safety import (
    PathSafetyErrorV428,
    ensure_paths_distinct_v428,
    resolve_external_output_v428,
    resolve_repository_path_v428,
    write_audit_text_v428,
)


def test_v428_repository_relative_paths_accept_regular_internal_file(tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".audit").mkdir(parents=True)
    (root / "config").mkdir()
    (root / "config/trust.json").write_text("{}", encoding="utf-8")
    assert resolve_repository_path_v428(root, "config/trust.json", label="TRUST", must_exist_file=True) == root.resolve() / "config/trust.json"


@pytest.mark.parametrize("raw", ["../escape.json", "../../tmp/escape", "/tmp/escape.json", "C:\\\\temp\\\\escape.json", "//server/share/file", "", "nul\x00byte"])
def test_v428_repository_path_rejects_absolute_traversal_and_invalid_paths(tmp_path: Path, raw: str):
    root = tmp_path / "repo"
    root.mkdir()
    with pytest.raises(PathSafetyErrorV428):
        resolve_repository_path_v428(root, raw, label="TEST")


def test_v428_resolver_rejects_symlink_component_and_broken_symlink(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.json").write_text("secret", encoding="utf-8")
    (root / "linked-dir").symlink_to(outside, target_is_directory=True)
    (root / "broken-link").symlink_to(outside / "missing.json")
    with pytest.raises(PathSafetyErrorV428, match="SYMLINK"):
        resolve_repository_path_v428(root, "linked-dir/payload.json", label="INPUT")
    with pytest.raises(PathSafetyErrorV428, match="SYMLINK"):
        resolve_repository_path_v428(root, "broken-link", label="INPUT")


def test_v428_outputs_are_limited_to_audit_tree_and_cannot_collide(tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".audit").mkdir(parents=True)
    (root / ".github/workflows").mkdir(parents=True)
    source = root / ".github/workflows/ci.yml"
    source.write_text("safe", encoding="utf-8")
    report = resolve_repository_path_v428(root, ".audit/report.json", label="REPORT", output_scope=".audit")
    with pytest.raises(PathSafetyErrorV428, match="OUTPUT_SCOPE"):
        resolve_repository_path_v428(root, ".github/workflows/ci.yml", label="REPORT", output_scope=".audit")
    with pytest.raises(PathSafetyErrorV428, match="OUTPUT_OVERWRITES_INPUT"):
        ensure_paths_distinct_v428(outputs={"report": source}, protected_inputs={"workflow": source})
    with pytest.raises(PathSafetyErrorV428, match="OUTPUT_PATH_COLLISION"):
        ensure_paths_distinct_v428(outputs={"report": report, "event_store": report}, protected_inputs={})


def test_v428_audit_writer_refuses_symlinked_final_component(tmp_path: Path):
    root = tmp_path / "repo"
    (root / ".audit").mkdir(parents=True)
    outside = tmp_path / "outside.txt"
    outside.write_text("do not overwrite", encoding="utf-8")
    (root / ".audit/report.json").symlink_to(outside)
    with pytest.raises(PathSafetyErrorV428):
        write_audit_text_v428(root, root / ".audit/report.json", "tampered")
    assert outside.read_text(encoding="utf-8") == "do not overwrite"


def test_v428_external_signer_output_cannot_overwrite_key_or_unsigned_evidence(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    evidence = tmp_path / "unsigned.json"
    key = tmp_path / "private.pem"
    evidence.write_text("{}", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    with pytest.raises(PathSafetyErrorV428, match="OVERWRITES_EVIDENCE"):
        resolve_external_output_v428(root, evidence, label="OUTPUT", protected_inputs={"evidence": evidence, "private_key": key})
    with pytest.raises(PathSafetyErrorV428, match="OVERWRITES_PRIVATE_KEY"):
        resolve_external_output_v428(root, key, label="OUTPUT", protected_inputs={"evidence": evidence, "private_key": key})
    target = resolve_external_output_v428(root, tmp_path / "signed.json", label="OUTPUT", protected_inputs={"evidence": evidence, "private_key": key})
    assert target == tmp_path / "signed.json"


def test_v428_capture_rejects_source_overwrite_before_gh_authentication():
    workflow = ROOT / ".github/workflows/ci.yml"
    before = workflow.read_bytes()
    result = subprocess.run(
        [sys.executable, "scripts/capture_github_governance.py", "--repository", "acme/trading-platform", "--output", ".github/workflows/ci.yml"],
        cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, shell=False,
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "PATH_POLICY_REJECTED" in result.stderr
    assert workflow.read_bytes() == before


def test_v428_governance_verifier_rejects_report_path_outside_audit_before_writing():
    workflow = ROOT / ".github/workflows/ci.yml"
    before = workflow.read_bytes()
    result = subprocess.run(
        [sys.executable, "scripts/verify_repository_governance.py", "--repository", "acme/trading-platform",
         "--report", ".github/workflows/ci.yml", "--event-store", ".audit/v428-bad.sqlite3"],
        cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, shell=False,
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 2
    assert "PATH_POLICY_REJECTED" in result.stderr
    assert workflow.read_bytes() == before


def test_v428_milestone_runner_rejects_event_store_path_traversal():
    marker = ROOT.parent / "V428_SHOULD_NOT_BE_CREATED.sqlite3"
    marker.unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, "scripts/run_milestone_validation.py", "--audit-only",
         "--decision-id", "V428-PATH-TRAVERSAL-TEST", "--event-store", "../V428_SHOULD_NOT_BE_CREATED.sqlite3"],
        cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, shell=False,
        check=False, capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "PATH_POLICY_REJECTED" in result.stderr or "PATH_POLICY_REJECTED" in result.stdout
    assert not marker.exists()


def test_v428_compliance_and_runner_contract_are_aligned():
    import csv
    with (ROOT / "compliance_v428.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    assert rows["REPO-GOV-PATH-01"]["implementation_status"] in {"IMPLEMENTED", "TESTED"}
    assert rows["REPO-GOV-PATH-02"]["implementation_status"] in {"IMPLEMENTED", "TESTED"}
    runner = (ROOT / "scripts/run_milestone_validation.py").read_text(encoding="utf-8")
    assert "V4.28-RECOVERY" in runner
    assert "compliance_v428.csv" in runner
    assert "src/trading_platform/v428/path_safety.py" in runner
    assert "tests/v428/test_path_safety_v428.py" in runner


def test_v428_external_writer_refuses_final_symlink(tmp_path: Path):
    target = tmp_path / "real.json"
    target.write_text("preserve", encoding="utf-8")
    link = tmp_path / "signed.json"
    link.symlink_to(target)
    from trading_platform.v428.path_safety import write_external_text_v428
    with pytest.raises(PathSafetyErrorV428, match="SYMLINK"):
        write_external_text_v428(link, "overwrite")
    assert target.read_text(encoding="utf-8") == "preserve"


def test_v428_repository_output_rejects_fifo_in_audit_tree(tmp_path: Path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO not supported on this platform")
    root = tmp_path / "repo"
    (root / ".audit").mkdir(parents=True)
    os.mkfifo(root / ".audit/report.json")
    with pytest.raises(PathSafetyErrorV428, match="NOT_REGULAR_FILE"):
        resolve_repository_path_v428(root, ".audit/report.json", label="REPORT", output_scope=".audit")
