from pathlib import Path

from trading_platform.v417.production_readiness_compliance import ProductionReadinessComplianceAuthorityV417


def test_v417_source_has_no_external_side_effect_surface():
    source = Path("src/trading_platform/v417/production_readiness_compliance.py").read_text(encoding="utf-8")
    forbidden = (
        "import requests", "import httpx", "import socket", "import websocket",
        "import subprocess", "from subprocess", "os.system(", "Popen(",
        "api_key", "api_secret", "private_key", "password", "credential",
    )
    assert [token for token in forbidden if token in source] == []


def test_v417_authority_has_no_production_runtime_flag():
    authority = ProductionReadinessComplianceAuthorityV417()
    assert not hasattr(authority, "production_ready")
    assert not hasattr(authority, "activate")
