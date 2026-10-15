from pathlib import Path


def test_v403_source_has_no_network_or_process_egress_imports():
    source = Path("src/trading_platform/v403/revalidation.py").read_text()
    forbidden = ("import socket", "import requests", "import urllib", "import subprocess", "from subprocess", "import os.system", "Popen(")
    assert not any(token in source for token in forbidden)
