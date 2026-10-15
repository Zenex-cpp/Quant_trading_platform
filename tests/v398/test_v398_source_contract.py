from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v398_source_contains_critical_guards():
    source = (ROOT / "src/trading_platform/v398/critical_promotion.py").read_text(encoding="utf-8")
    for token in (
        'PRODUCTION_SCOPE_REQUIRED',
        'CRITICAL_SCOPE_REQUIRED',
        'DUAL_APPROVAL_REQUIRED',
        'TRUST_ANCHOR_ATTESTATION_REQUIRED',
        'SECURITY_MONITORING_READINESS_REQUIRED',
        'DR_ATTESTATION_REQUIRED',
        'INDEPENDENT_HUMAN_REVIEW_REQUIRED',
        'ROLLBACK_RELEASE_HASH_MISMATCH',
        'CRITICAL_PROMOTION_DEPENDENCY_BLOCKED',
        'CRITICAL_PROMOTION_READINESS_ACCEPTED',
    ):
        assert token in source


def test_v398_runbook_and_compliance_exist():
    assert (ROOT / "V398_CRITICAL_PROMOTION_RUNBOOK.md").exists()
    assert (ROOT / "V398_CHANGE_IMPACT.md").exists()
    assert (ROOT / "V398_OPEN_GAPS_DELTA.md").exists()
    assert (ROOT / "compliance_v398.csv").exists()
