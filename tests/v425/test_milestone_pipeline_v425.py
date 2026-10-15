from __future__ import annotations
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def test_v425_audit_only_creates_nested_event_store_parent_before_opening_sqlite():
    base = ROOT / ".audit" / "v425-nested-test"
    report = base / "preflight.json"
    store = base / "events.sqlite3"
    try:
        shutil.rmtree(ROOT / ".audit" / "v425-nested-test", ignore_errors=True)
        result = subprocess.run(
            [sys.executable, "scripts/run_milestone_validation.py", "--audit-only",
             "--decision-id", "V425-NESTED-AUDIT-TEST",
             "--event-store", str(store.relative_to(ROOT)),
             "--report", str(report.relative_to(ROOT))],
            cwd=ROOT, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            shell=False, check=False, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        parsed = json.loads(report.read_text(encoding="utf-8"))
        assert parsed["status"] == "READY_FOR_MILESTONE"
        assert parsed["pipeline_status"] == "PRECHECK_ONLY"
        assert store.is_file()
    finally:
        shutil.rmtree(ROOT / ".audit" / "v425-nested-test", ignore_errors=True)
