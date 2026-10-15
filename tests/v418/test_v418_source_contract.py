from pathlib import Path

from trading_platform.v418.machine_check_readiness import MachineCheckReadinessAuthorityV418


def test_v418_source_has_no_network_process_or_credential_surface():
    source = Path("src/trading_platform/v418/machine_check_readiness.py").read_text(encoding="utf-8")
    forbidden = (
        "import requests", "import httpx", "import socket", "import websocket",
        "import subprocess", "from subprocess", "os.system(", "Popen(",
        "api_key", "api_secret", "private_key", "password",
        "production_ready = True", "activate_production(",
    )
    assert [token for token in forbidden if token in source] == []


def test_v418_authority_has_no_runtime_activation_or_production_ready_attribute():
    authority = MachineCheckReadinessAuthorityV418()
    assert not hasattr(authority, "production_ready")
    assert not hasattr(authority, "activate")
