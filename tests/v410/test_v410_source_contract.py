from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v410_release_contract_files_exist():
    required = (
        ROOT / "src/trading_platform/v410/__init__.py",
        ROOT / "src/trading_platform/v410/readiness_binding.py",
        ROOT / "tests/v410/test_readiness_binding.py",
        ROOT / "tests/v410/test_v410_source_contract.py",
        ROOT / "V410_RELEASE_NOTES.md",
        ROOT / "V410_CHANGE_IMPACT.md",
        ROOT / "V410_OPEN_GAPS_DELTA.md",
        ROOT / "V410_VERIFICATION_REPORT.md",
        ROOT / "V410_EXTERNAL_EVIDENCE.json",
        ROOT / "compliance_v410.csv",
    )
    assert all(p.exists() for p in required)


def test_v410_source_contract_has_no_network_or_process_egress():
    source = (ROOT / "src/trading_platform/v410/readiness_binding.py").read_text(encoding="utf-8")
    forbidden = ("subprocess", "socket.", "requests.", "urllib.request", "httpx", "os.system")
    assert not any(token in source for token in forbidden)


def test_v410_source_contract_contains_fail_closed_markers():
    source = (ROOT / "src/trading_platform/v410/readiness_binding.py").read_text(encoding="utf-8")
    for token in (
        "READINESS_BINDING_SCOPE_MISMATCH",
        "READINESS_EVIDENCE_FINGERPRINT_CHANGED",
        "READINESS_EVIDENCE_SET_CHANGED",
        "EVENT_CHAIN_INVALID",
        "DEPENDENCY_REQUIRES_REVALIDATION",
    ):
        assert token in source
