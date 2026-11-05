from __future__ import annotations

import pytest

from trading_platform.testnet.runner import LiveTestnetEvidenceRunner, RunnerConfig
from trading_platform.testnet.session import LiveTestnetSession, SessionConfig


class RecordingTransport:
    def __init__(self):
        self.calls = []

    def signed_request(self, method, path, *, params, api_key, secret):
        self.calls.append((method, path))
        return {"ok": True}

    def request(self, method, url, *, headers=None, params=None):
        self.calls.append((method, url))
        return {"ok": True}


def test_session_denies_order_submission_before_transport(tmp_path):
    transport = RecordingTransport()
    session = LiveTestnetSession(
        SessionConfig(base_url="https://testnet.binancefuture.com", evidence_dir=tmp_path),
        api_key="test-key",
        secret=b"test-secret",
        transport=transport,
    )

    with pytest.raises(PermissionError, match="TESTNET_READ_ONLY_METHOD_REQUIRED"):
        session.run_probe("order", "POST", "/fapi/v1/order", {}, lambda _: (True, (), ()))

    assert transport.calls == []


def test_evidence_runner_denies_order_submission_before_transport(tmp_path):
    transport = RecordingTransport()
    runner = LiveTestnetEvidenceRunner(
        RunnerConfig(base_url="https://testnet.binancefuture.com", websocket_url=None, evidence_dir=tmp_path),
        api_key="test-key",
        secret=b"test-secret",
        transport=transport,
    )

    with pytest.raises(PermissionError, match="TESTNET_READ_ONLY_METHOD_REQUIRED"):
        runner.run_signed_query(
            scenario_id="order",
            name="order submission",
            method="POST",
            path="/fapi/v1/order",
            params={"symbol": "BTCUSDT"},
            request_ref="local-test",
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "config",
    [
        lambda: SessionConfig(base_url="https://fapi.binance.com"),
        lambda: RunnerConfig(base_url="https://fapi.binance.com", websocket_url=None),
    ],
)
def test_testnet_read_only_runners_reject_mainnet_hosts(config):
    with pytest.raises(ValueError, match="MAINNET_HOST_BLOCKED"):
        config().validate()


@pytest.mark.parametrize("path", ["https://testnet.binancefuture.com/fapi/v1/order", "//evil.example/path", "/fapi/v1/ping?method=POST"])
def test_read_only_session_rejects_noncanonical_request_targets(path, tmp_path):
    transport = RecordingTransport()
    session = LiveTestnetSession(
        SessionConfig(base_url="https://testnet.binancefuture.com", evidence_dir=tmp_path),
        api_key="test-key",
        secret=b"test-secret",
        transport=transport,
    )

    with pytest.raises(PermissionError, match="TESTNET_READ_ONLY_PATH_INVALID"):
        session.run_probe("bad-path", "GET", path, {}, lambda _: (True, (), ()))

    assert transport.calls == []
