from pathlib import Path


def test_v396_source_contract_and_docs_exist():
    root = Path(__file__).resolve().parents[2]
    required = (
        root / "src/trading_platform/v396/dr_attestation.py",
        root / "src/trading_platform/v396/__init__.py",
        root / "V396_RELEASE_NOTES.md",
        root / "V396_CHANGE_IMPACT.md",
        root / "V396_OPEN_GAPS_DELTA.md",
        root / "V396_DR_ATTESTATION_RUNBOOK.md",
        root / "V396_VERIFICATION_REPORT.md",
        root / "compliance_v396.csv",
        root / "V396_EXTERNAL_DR_ATTESTATION_EVIDENCE.json",
    )
    assert all(p.exists() for p in required)
