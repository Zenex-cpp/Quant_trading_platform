from pathlib import Path


def test_v409_release_contract_files_exist_and_package_boundary_is_present():
    root = Path(__file__).resolve().parents[2]
    required = (
        root / "src/trading_platform/v409/__init__.py",
        root / "src/trading_platform/v409/production_readiness.py",
        root / "tests/v409/test_production_readiness.py",
        root / "V409_RELEASE_NOTES.md",
        root / "V409_CHANGE_IMPACT.md",
        root / "V409_OPEN_GAPS_DELTA.md",
        root / "V409_VERIFICATION_REPORT.md",
        root / "V409_EXTERNAL_EVIDENCE.json",
        root / "compliance_v409.csv",
    )
    assert all(p.exists() for p in required)
