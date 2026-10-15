from pathlib import Path

def test_v395_source_contract_and_docs_exist():
    root = Path(__file__).resolve().parents[2]
    assert (root / "src/trading_platform/v395/trust_anchor_attestation.py").exists()
    assert (root / "src/trading_platform/v395/__init__.py").exists()
    assert (root / "V395_TRUST_ANCHOR_ATTESTATION_RUNBOOK.md").exists()
    assert (root / "V395_RELEASE_NOTES.md").exists()
    assert (root / "V395_VERIFICATION_REPORT.md").exists()
