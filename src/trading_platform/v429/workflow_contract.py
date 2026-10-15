"""V4.29 CI workflow contract validation.

The governance-evidence artifact names remain V4.28 for capture-schema
compatibility; the milestone runner, matrix and baseline identity are V4.29.
"""
from __future__ import annotations

REQUIRED_STATUS_CHECK_V429 = "controlled-milestone-validation"


def validate_workflow_contract_v429(text: str) -> tuple[str, ...]:
    blockers: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return ("WORKFLOW_SOURCE_MISSING",)
    normalized = text.replace("\r\n", "\n")
    required = {
        "WORKFLOW_PUSH_TRIGGER_MISSING": "push:",
        "WORKFLOW_PULL_REQUEST_TRIGGER_MISSING": "pull_request:",
        "WORKFLOW_MANUAL_TRIGGER_MISSING": "workflow_dispatch:",
        "WORKFLOW_CONTROLLED_ENTRYPOINT_MISSING": "scripts/run_milestone_validation_v429.py",
        "WORKFLOW_STATUS_CONTEXT_MISSING": REQUIRED_STATUS_CHECK_V429,
        "WORKFLOW_ALWAYS_UPLOADS_PREFLIGHT_MISSING": "if: always()",
        # These two artifact names are deliberately retained because the
        # independent provider capture schema consumes them as opaque hashes.
        "WORKFLOW_PREFLIGHT_JSON_ARTIFACT_MISSING": "V428_MILESTONE_PREFLIGHT.json",
        "WORKFLOW_PREFLIGHT_DB_ARTIFACT_MISSING": "V428_MILESTONE_PREFLIGHT.sqlite3",
        "WORKFLOW_HIDDEN_AUDIT_ARTIFACTS_NOT_INCLUDED": "include-hidden-files: true",
        "WORKFLOW_V429_MILESTONE_ID_MISSING": "V4.29-RECOVERY",
        "WORKFLOW_V428_BASELINE_MISSING": "V4.28-RECOVERY",
        "WORKFLOW_MATRIX_V429_MISSING": "compliance_v429.csv",
        "WORKFLOW_BASELINE_HASH_FILE_MISSING": "V428_BASELINE_ARCHIVE_SHA256.txt",
        "WORKFLOW_PATH_HARDENING_CONTROLS_MISSING": "REPO-GOV-PATH-03",
        "WORKFLOW_EXCLUSIVE_OUTPUT_CONTROL_MISSING": "REPO-GOV-PATH-04",
    }
    for reason, needle in required.items():
        if needle not in normalized:
            blockers.append(reason)
    if "python scripts/run_milestone_validation_v429.py" not in normalized:
        blockers.append("WORKFLOW_ENTRYPOINT_INVOCATION_MISSING")
    if "permissions:" not in normalized or "contents: read" not in normalized:
        blockers.append("WORKFLOW_MINIMUM_PERMISSIONS_NOT_DECLARED")
    if "controlled-milestone-validation:" not in normalized:
        blockers.append("WORKFLOW_JOB_ID_MISMATCH")
    if "if-no-files-found: error" not in normalized:
        blockers.append("WORKFLOW_AUDIT_ARTIFACT_MISSING_MUST_FAIL")
    pinned_actions = (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1",
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    )
    if not all(action in normalized for action in pinned_actions):
        blockers.append("WORKFLOW_ACTIONS_NOT_PINNED_TO_APPROVED_FULL_SHA")
    return tuple(sorted(set(blockers)))
