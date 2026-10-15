from decimal import Decimal

from trading_platform.v381 import BinanceTestnetE2EHarnessV381, BinanceTestnetLivePreflightV381, E2EStatus


def test_v381_full_simulated_testnet_chain_passes():
    result = BinanceTestnetE2EHarnessV381().run()
    assert result.status is E2EStatus.PASS
    assert len(result.checks) == 12
    assert all(c["pass"] for c in result.checks)
    assert Decimal(result.position_quantity) == Decimal("0.0002")


def test_v381_chain_hash_is_deterministic():
    a = BinanceTestnetE2EHarnessV381().run()
    b = BinanceTestnetE2EHarnessV381().run()
    assert a.chain_hash == b.chain_hash
    assert a.accounting_state_hash == b.accounting_state_hash


def test_v381_reconciliation_negative_path_is_exercised():
    result = BinanceTestnetE2EHarnessV381().run(include_negative_reconciliation_case=True)
    check = next(c for c in result.checks if c["check"] == "negative_reconciliation_blocks")
    assert check["pass"] is True


def test_v381_private_ws_route_is_current_style_and_redacted():
    result = BinanceTestnetE2EHarnessV381().run()
    assert "/private/ws?" in result.websocket_route
    assert "<listenKey>" in result.websocket_route
    assert "REDACTED" not in result.websocket_route


def test_v381_live_preflight_does_not_mutate():
    result = BinanceTestnetLivePreflightV381().run()
    assert result["mutation"] == "NONE"
    assert result["status"] in {"PASS", "NOT_VERIFIED"}
