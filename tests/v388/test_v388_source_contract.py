from pathlib import Path

def test_v388_docs_and_runner_present():
    root = Path(__file__).resolve().parents[2]
    assert (root / "docs/V388_TESTNET_EVIDENCE_CLOSURE.md").exists()
    assert (root / "ops/v388_first_testnet_evidence_checklist.txt").exists()
    assert (root / "V388_RELEASE_NOTES.md").exists()
    assert (root / "run_v388_first_testnet_evidence.py").exists()
