from pathlib import Path

from trading_platform.v370.security_review_drill import run_security_review_drill


def test_clean_package_passes_security_review_drill(tmp_path):
    (tmp_path / "src" / "trading_platform" / "research").mkdir(parents=True)
    result = run_security_review_drill(tmp_path)
    assert result["status"] == "PASS"
    assert result["finding_count"] == 0


def test_private_key_marker_is_blocked(tmp_path):
    src = tmp_path / "src" / "trading_platform"
    src.mkdir(parents=True)
    (src / "bad.pem").write_text("-----BEGIN PRIVATE KEY-----\nsecret\n")
    result = run_security_review_drill(tmp_path)
    assert result["status"] == "FAIL"
    assert any(f["category"] == "SECRET_PATH" for f in result["findings"])
    assert any(f["category"] == "PRIVATE_KEY" for f in result["findings"])


def test_research_network_import_is_blocked(tmp_path):
    research = tmp_path / "src" / "trading_platform" / "research"
    research.mkdir(parents=True)
    (research / "bad.py").write_text("import requests\nURL='https://api.binance.com'\n")
    result = run_security_review_drill(tmp_path)
    assert result["status"] == "FAIL"
    assert any(f["category"] == "RESEARCH_NETWORK_IMPORT" for f in result["findings"])
    assert any(f["category"] == "RESEARCH_PRODUCTION_ENDPOINT" for f in result["findings"])


def test_hardcoded_secret_is_blocked(tmp_path):
    src = tmp_path / "src" / "trading_platform"
    src.mkdir(parents=True)
    (src / "config.py").write_text(("api_" + "secret") + " = \"SUPER_SECRET_VALUE_123\"\n")
    result = run_security_review_drill(tmp_path)
    assert result["status"] == "FAIL"
    assert any(f["category"] == "HARDCODED_SECRET" for f in result["findings"])
