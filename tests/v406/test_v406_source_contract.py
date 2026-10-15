from pathlib import Path


def test_v406_source_has_no_network_or_process_egress_imports():
    source = Path("src/trading_platform/v406/gate_revalidation.py").read_text()
    forbidden = ("import socket", "import requests", "import urllib", "import subprocess", "from subprocess", "Popen(")
    assert not any(token in source for token in forbidden)
