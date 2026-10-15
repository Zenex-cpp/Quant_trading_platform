from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil

from trading_platform.v428.repository_governance import validate_workflow_contract_v428

ROOT = Path(__file__).resolve().parents[2]


def test_v423_workflow_has_mandatory_triggers_entrypoint_and_artifacts():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert validate_workflow_contract_v428(workflow) == ()


def test_v423_entrypoint_uses_fixed_commands_and_shell_false():
    source = (ROOT / "scripts/run_milestone_validation.py").read_text(encoding="utf-8")
    assert '"-m", "pytest"' in source
    assert '"scripts/validate_release_hygiene.py"' in source
    assert "shell=False" in source
    assert "shell=True" not in source
    assert "subprocess.run(command" in source


def test_v423_entrypoint_audit_only_records_durable_preflight(tmp_path):
    base = ROOT / ".audit" / "v423-entrypoint-test"
    shutil.rmtree(base, ignore_errors=True)
    report = base / "preflight.json"
    store = base / "events.sqlite3"
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "scripts/run_milestone_validation.py", "--audit-only",
         "--decision-id", "V423-AUDIT-TEST", "--event-store", store.relative_to(ROOT).as_posix(), "--report", report.relative_to(ROOT).as_posix()],
        cwd=ROOT, env=env, shell=False, check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(report.read_text(encoding="utf-8"))
    assert output["status"] == "READY_FOR_MILESTONE"
    assert output["pipeline_status"] == "PRECHECK_ONLY"
    assert output["external_evidence"] is False
    assert output["production_ready"] is False
    assert store.is_file()
    shutil.rmtree(base, ignore_errors=True)


def test_v423_entrypoint_rejects_attempt_to_change_matrix_or_impact_set():
    source = (ROOT / "scripts/run_milestone_validation.py").read_text(encoding="utf-8")
    assert "MATRIX_OR_BASELINE_PATH_NOT_AUTHORIZED_FOR_RECOVERY_BUILD" in source
    assert "IMPACTED_REQUIREMENT_SET_MISMATCH" in source
    assert "EXPECTED_IMPACTED_IDS" in source
