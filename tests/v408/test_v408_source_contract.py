from pathlib import Path


def test_source_contract_has_no_network_or_process_egress():
    src = Path(__file__).parents[2] / "src" / "trading_platform" / "v408" / "gate_promotion.py"
    text = src.read_text()
    forbidden = ("subprocess", "socket.", "requests.", "urllib.request", "httpx", "os.system")
    assert not any(token in text for token in forbidden)
