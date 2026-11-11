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


def test_v429_m16_matrix_points_to_live_configuration_conflict_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m16 = rows["M16"]
    assert m16["implementation_status"] == "TESTED"
    assert "src/trading_platform/v343/config_authority.py" in m16["code_reference"]
    assert "src/trading_platform/v312/execution_runtime.py" in m16["code_reference"]
    assert "src/trading_platform/v325/deployment_activation.py" in m16["code_reference"]
    assert "src/trading_platform/v31/authority.py" in m16["code_reference"]
    assert "tests/test_v343_m16_configuration_conflict.py" in m16["test_reference"]
    assert "tests/v312/test_execution_runtime.py" in m16["test_reference"]
    assert "tests/v325/test_deployment_activation.py" in m16["test_reference"]
    assert m16["evidence_reference"] == "V429_M16_REMEDIATION_REPORT.md"
    assert "Independent" in m16["unresolved_gap"]


def test_v429_m1_matrix_points_to_testnet_read_only_guard_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    m1 = rows["M1"]
    assert m1["implementation_status"] == "TESTED"
    assert "trading_platform/testnet/session.py" in m1["code_reference"]
    assert "trading_platform/testnet/runner.py" in m1["code_reference"]
    assert "tests/test_testnet_read_only_boundary.py" in m1["test_reference"]
    assert m1["evidence_reference"] == "V429_M1_M5_TRANSPORT_REMEDIATION.md"
    assert "Independent review" in m1["unresolved_gap"]


def test_v429_m1_to_m5_matrix_points_to_final_dispatch_authority_evidence():
    with (ROOT / "compliance_v429.csv").open(newline="", encoding="utf-8") as stream:
        rows = {row["machine_check_id"]: row for row in csv.DictReader(stream)}
    for key in ("M1", "M2", "M3", "M4", "M5"):
        assert rows[key]["implementation_status"] == "TESTED"
        assert "trading_platform/v311/dispatch_guard.py" in rows[key]["code_reference"]
        assert "tests/v318/test_dispatch_freshness.py" in rows[key]["test_reference"]
        assert rows[key]["evidence_reference"] == "V429_M1_M5_TRANSPORT_REMEDIATION.md"
        for code_path in (
            "trading_platform/v36/user_execution.py",
            "trading_platform/v379/execution_parity.py",
            "trading_platform/v380/order_adapter.py",
            "trading_platform/v384/testnet_execution_activation.py",
            "trading_platform/v385/controlled_testnet_submit.py",
        ):
            assert code_path in rows[key]["code_reference"]
        assert "tests/test_v385_controlled_testnet_submit.py" in rows[key]["test_reference"]
        assert "Independent review" in rows[key]["unresolved_gap"]
    assert "RISK_DECISION_LEDGER_REQUIRED" in (ROOT / "tests/v318/test_dispatch_freshness.py").read_text(encoding="utf-8")
    assert "CONTROLLED_SUBMIT_AUTHORITY_REQUIRED" in (ROOT / "src/trading_platform/v380/order_adapter.py").read_text(encoding="utf-8")
    assert "dispatcher: \"GuardedExecutionDispatcher\"" in (ROOT / "src/trading_platform/v36/user_execution.py").read_text(encoding="utf-8")
