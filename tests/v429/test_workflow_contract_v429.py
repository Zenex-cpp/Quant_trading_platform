from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trading_platform.v429.workflow_contract import validate_workflow_contract_v429
from trading_platform.v428.repository_governance import validate_workflow_contract_v428


def test_v429_ci_workflow_contract_passes_and_preserves_capture_artifact_compatibility():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert validate_workflow_contract_v429(text) == ()
    # The V4.28 evidence authority delegates to the V4.29 workflow validator.
    assert validate_workflow_contract_v428(text) == ()
    assert "V428_MILESTONE_PREFLIGHT.json" in text
    assert "V428_MILESTONE_PREFLIGHT.sqlite3" in text


def test_v429_workflow_contract_rejects_legacy_entrypoint_or_warn_only_artifacts():
    text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    altered = text.replace("scripts/run_milestone_validation_v429.py", "scripts/run_milestone_validation.py")
    altered = altered.replace("if-no-files-found: error", "if-no-files-found: warn")
    blockers = set(validate_workflow_contract_v429(altered))
    assert "WORKFLOW_CONTROLLED_ENTRYPOINT_MISSING" in blockers
    assert "WORKFLOW_ENTRYPOINT_INVOCATION_MISSING" in blockers
    assert "WORKFLOW_AUDIT_ARTIFACT_MISSING_MUST_FAIL" in blockers
