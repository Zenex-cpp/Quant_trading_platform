from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_v390_source_contract_has_required_boundaries():
    source = (ROOT / "src/trading_platform/v390/egress_boundary.py").read_text()
    required = [
        "ProxyHandler({})",
        "_NoRedirectHandler",
        "assert_no_ambient_proxy",
        "TESTNET_EGRESS_TARGET_DENIED",
        "BinanceV390TestnetExecutionGateway",
    ]
    for token in required:
        assert token in source


def test_v390_runbook_and_compliance_files_exist():
    for rel in [
        "V390_RELEASE_NOTES.md",
        "V390_CHANGE_IMPACT.md",
        "V390_VERIFICATION_REPORT.md",
        "V390_M25_NETWORK_ISOLATION.md",
        "ops/v390_testnet_egress_checklist.txt",
        "compliance_v390.csv",
    ]:
        assert (ROOT / rel).exists(), rel
