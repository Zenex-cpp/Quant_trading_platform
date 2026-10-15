from pathlib import Path

def test_v389_contract_artifacts_present():
    root = Path(__file__).resolve().parents[2]
    assert (root / "docs/V389_TESTNET_RUNTIME_CREDENTIAL_BOUNDARY.md").exists()
    assert (root / "ops/v389_testnet_credential_checklist.txt").exists()
    assert (root / "V389_RELEASE_NOTES.md").exists()
    assert (root / "run_v389_credential_preflight.py").exists()
    assert (root / "schemas/v389_testnet_credential_registry.csv").exists()
    assert (root / "compliance_v389.csv").exists()
