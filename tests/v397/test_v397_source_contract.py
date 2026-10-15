from pathlib import Path


def test_v397_release_contract_documents_exist():
    root = Path(__file__).resolve().parents[2]
    required = (
        "V397_RELEASE_NOTES.md",
        "V397_CHANGE_IMPACT.md",
        "V397_OPEN_GAPS_DELTA.md",
        "V397_SECURITY_MONITORING_READINESS_RUNBOOK.md",
        "V397_VERIFICATION_REPORT.md",
        "V397_SECURITY_MONITORING_EVIDENCE.json",
        "compliance_v397.csv",
    )
    missing = [name for name in required if not (root / name).exists()]
    assert not missing, missing
