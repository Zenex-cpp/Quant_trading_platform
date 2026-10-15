from pathlib import Path
import pytest
from trading_platform.testnet.runner import RunnerConfig, ScenarioResult, offline_runner_contract_summary
from trading_platform.testnet.scenarios import ScenarioStatus


def test_runner_requires_testnet_and_tls():
    with pytest.raises(ValueError, match="TLS_REQUIRED"):
        RunnerConfig("http://testnet.invalid", None).validate()
    with pytest.raises(ValueError, match="MAINNET_HOST_BLOCKED"):
        RunnerConfig("https://fapi.binance.com", None).validate()
    RunnerConfig("https://testnet.invalid", None).validate()


def test_ws_mainnet_is_blocked():
    with pytest.raises(ValueError, match="MAINNET_WS_HOST_BLOCKED"):
        RunnerConfig("https://testnet.invalid", "wss://ws-fapi.binance.com/ws").validate()


def test_result_hash_is_deterministic():
    r = ScenarioResult("TN-03", "order", ScenarioStatus.PASS, "t1", "t2", "TESTNET", "https://testnet.invalid/fapi/v1/order", "req1", "abc", ("ok",), ("x=PASS",))
    assert len(r.artifact_hash) == 64
    assert r.artifact_hash == r.artifact_hash


def test_offline_contract_never_claims_production_ready():
    s = offline_runner_contract_summary()
    assert s["production_ready"] is False
    assert "TN-11" in s["offline_only"]
    assert "TN-03" in s["live_network_required"]
