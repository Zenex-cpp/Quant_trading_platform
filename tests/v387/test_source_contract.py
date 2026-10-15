from pathlib import Path

def test_v387_docs_present():
    root=Path(__file__).resolve().parents[2]
    assert (root/'docs/V387_FIRST_TESTNET_ORDER_RUNBOOK.md').exists()
    assert (root/'ops/v387_first_testnet_checklist.txt').exists()
    assert (root/'V387_BINANCE_REFERENCES.md').exists()
