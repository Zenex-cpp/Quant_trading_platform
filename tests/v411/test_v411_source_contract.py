from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_v411_release_contract_files_exist():
    required = (
        ROOT / "src/trading_platform/v411/__init__.py",
        ROOT / "src/trading_platform/v411/operational_evidence.py",
        ROOT / "tests/v411/test_operational_evidence.py",
        ROOT / "tests/v411/test_v411_source_contract.py",
        ROOT / "V411_OPERATIONAL_EVIDENCE_PROTOCOL.md",
        ROOT / "V411_OPERATIONAL_EVIDENCE_PROTOCOL.json",
        ROOT / "V411_OPERATIONAL_EVIDENCE_MANIFEST_TEMPLATE.json",
        ROOT / "V411_RELEASE_NOTES.md",
        ROOT / "V411_CHANGE_IMPACT.md",
        ROOT / "V411_OPEN_GAPS_DELTA.md",
        ROOT / "V411_VERIFICATION_REPORT.md",
        ROOT / "compliance_v411.csv",
    )
    assert all(path.exists() for path in required)


def test_v411_source_contract_has_no_network_or_process_egress():
    source = (ROOT / "src/trading_platform/v411/operational_evidence.py").read_text(encoding="utf-8")
    forbidden = ("subprocess", "socket.", "requests.", "urllib.request", "httpx", "os.system", "urlopen")
    assert not any(token in source for token in forbidden)


def test_v411_source_contract_has_review_only_boundary_markers():
    source = (ROOT / "src/trading_platform/v411/operational_evidence.py").read_text(encoding="utf-8")
    for token in (
        "READY_FOR_EXTERNAL_REVIEW",
        "EXTERNAL_EVIDENCE_REQUIRED",
        "NON_EXTERNAL_SOURCE_FORBIDDEN",
        "PROTOCOL_FIELDS_MISSING",
        "MANIFEST_ID_CONFLICT",
    ):
        assert token in source
