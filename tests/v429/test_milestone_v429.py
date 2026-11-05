from __future__ import annotations
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


def test_v429_milestone_runner_matrix_workflow_and_security_controls_are_aligned():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    assert rows["REPO-GOV-PATH-03"]["implementation_status"] == "TESTED"
    assert rows["REPO-GOV-PATH-04"]["implementation_status"] == "TESTED"
    runner = (ROOT / "scripts/run_milestone_validation_v429.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    for value in ("V4.29-RECOVERY", "V4.28-RECOVERY", "compliance_v429.csv", "V428_BASELINE_ARCHIVE_SHA256.txt"):
        assert value in runner
        assert value in workflow
    for value in ("src/trading_platform/v429/external_file_safety.py", "tests/v429/test_external_file_safety_v429.py", "tests/v429/test_signer_hardening_v429.py"):
        assert value in runner


def test_v429_matrix_does_not_claim_external_governance_is_verified():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    for key in ("REPO-GOV-01", "REPO-GOV-02", "REPO-GOV-03", "REPO-GOV-CAPTURE-01", "REPO-GOV-SIGN-01"):
        assert rows[key]["implementation_status"] in {"PARTIAL", "TESTED"}
        assert rows[key]["unresolved_gap"]


def test_v429_m27_matrix_points_to_restart_safe_invalidation_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m27 = rows["M27"]
    assert m27["implementation_status"] == "TESTED"
    assert "tests/v354/test_m27_holdout_compromise.py" in m27["test_reference"]
    assert m27["evidence_reference"] == "V429_M27_REMEDIATION_REPORT.md"
    assert "Independent" in m27["unresolved_gap"]


def test_v429_m26_matrix_points_to_durable_applicability_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m26 = rows["M26"]
    assert m26["implementation_status"] == "TESTED"
    assert "src/trading_platform/v353/methodology_authority.py" in m26["code_reference"]
    assert "tests/test_v353_m26_method_applicability.py" in m26["test_reference"]
    assert m26["evidence_reference"] == "V353_VERIFICATION_REPORT.md"
    assert "Independent" in m26["unresolved_gap"]
