from decimal import Decimal

import pytest

from trading_platform.v380 import (
    BinancePrivateWebSocketConfig,
    BinanceUserDataProjection,
    UserDataApplyReason,
    UserDataHealth,
)


def order_event(*, E=1000, T=1000, status="NEW", x="NEW", z="0", l="0", L="0", trade="0", order_id=77, client="tp-abc"):
    return {
        "e": "ORDER_TRADE_UPDATE",
        "E": E,
        "T": T,
        "o": {
            "s": "BTCUSDT", "c": client, "S": "BUY", "o": "LIMIT", "f": "GTC",
            "q": "1", "ap": str(L or "0"), "x": x, "X": status,
            "i": order_id, "l": l, "z": z, "L": L, "t": trade,
        },
    }


def account_event(*, E=1100, T=1100, qty="1"):
    return {
        "e": "ACCOUNT_UPDATE", "E": E, "T": T,
        "a": {"m": "ORDER", "P": [{"s": "BTCUSDT", "ps": "BOTH", "pa": qty, "ep": "100", "up": "1"}]},
    }


def test_private_ws_url_is_routed_for_current_binance_architecture():
    url = BinancePrivateWebSocketConfig(environment="TESTNET").url(
        listen_key="LK", events=["ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE"]
    )
    assert url.startswith("wss://stream.binancefuture.com/private/ws?")
    assert "listenKey=LK" in url
    assert "events=ORDER_TRADE_UPDATE" in url
    assert "events=ACCOUNT_UPDATE" in url


def test_private_ws_production_route_is_not_legacy():
    url = BinancePrivateWebSocketConfig(environment="PRODUCTION").url(listen_key="LK")
    assert url == "wss://fstream.binance.com/private/ws/LK"
    assert "/ws/" in url


def test_order_update_projects_and_is_idempotent():
    p = BinanceUserDataProjection(); p.start()
    e = order_event(status="PARTIALLY_FILLED", x="TRADE", z="0.4", l="0.4", L="100", trade="9")
    a = p.apply(e, now_epoch=1.1)
    b = p.apply(e, now_epoch=1.1)
    assert a.accepted and a.changed
    assert b.duplicate and not b.changed
    snap = p.snapshot(now_epoch=1.1)
    assert snap.orders[0].cumulative_filled_quantity == Decimal("0.4")
    assert snap.seen_trade_count == 1


def test_out_of_order_same_event_type_blocks():
    p = BinanceUserDataProjection(); p.start()
    assert p.apply(order_event(E=2000, T=2000), now_epoch=2.0).accepted
    r = p.apply(order_event(E=1900, T=1900, order_id=78), now_epoch=2.0)
    assert not r.accepted
    assert r.reason is UserDataApplyReason.OUT_OF_ORDER
    assert p.snapshot(now_epoch=2.0).health is UserDataHealth.GAP_SUSPECTED
    assert not p.snapshot(now_epoch=2.0).trading_allowed


def test_trade_dedup_uses_order_and_trade_id_even_when_raw_differs():
    p = BinanceUserDataProjection(); p.start()
    e1 = order_event(E=1000, T=1000, x="TRADE", status="PARTIALLY_FILLED", z="0.1", l="0.1", L="100", trade="5")
    e2 = order_event(E=1001, T=1001, x="TRADE", status="PARTIALLY_FILLED", z="0.1", l="0.1", L="100", trade="5")
    assert p.apply(e1, now_epoch=1.1).accepted
    assert p.apply(e2, now_epoch=1.1).duplicate
    assert p.snapshot(now_epoch=1.1).seen_trade_count == 1


def test_account_update_projects_position_and_reconciliation_green():
    p = BinanceUserDataProjection(); p.start()
    p.apply(order_event(E=1000, T=1000), now_epoch=1.1)
    p.apply(account_event(E=1100, T=1100, qty="1"), now_epoch=1.1)
    rest = {"openOrders": [{"orderId": 77, "clientOrderId": "tp-abc", "symbol": "BTCUSDT", "status": "NEW", "executedQty": "0"}],
            "positions": [{"symbol": "BTCUSDT", "positionAmt": "1"}]}
    r = p.reconcile(rest, now_epoch=1.1)
    assert r.trading_allowed
    assert r.state.value == "GREEN"


def test_reconciliation_mismatch_blocks():
    p = BinanceUserDataProjection(); p.start()
    p.apply(order_event(E=1000, T=1000, status="PARTIALLY_FILLED", x="TRADE", z="0.4", l="0.4", L="100", trade="1"), now_epoch=1.1)
    rest = {"openOrders": [{"orderId": 77, "clientOrderId": "tp-abc", "symbol": "BTCUSDT", "status": "NEW", "executedQty": "0"}],
            "positions": [{"symbol": "BTCUSDT", "positionAmt": "0"}]}
    r = p.reconcile(rest, now_epoch=1.1)
    assert not r.trading_allowed
    assert r.state.value == "RED"


def test_listen_key_expired_is_fail_closed():
    p = BinanceUserDataProjection(); p.start()
    r = p.apply({"e": "listenKeyExpired", "E": 2000, "T": 2000}, now_epoch=2.1)
    assert r.reason is UserDataApplyReason.LISTEN_KEY_EXPIRED
    assert p.snapshot(now_epoch=2.1).health is UserDataHealth.EXPIRED
    assert not p.snapshot(now_epoch=2.1).trading_allowed


def test_stale_stream_blocks_new_risk():
    p = BinanceUserDataProjection(stale_after_seconds=10); p.start()
    p.apply(order_event(E=1000, T=1000), now_epoch=1.0)
    assert p.snapshot(now_epoch=20.0).health is UserDataHealth.STALE
    assert not p.snapshot(now_epoch=20.0).trading_allowed


def test_unknown_event_does_not_silently_enable_trading():
    p = BinanceUserDataProjection(); p.start()
    r = p.apply({"e": "SOMETHING_UNKNOWN", "E": 1000, "T": 1000}, now_epoch=1.0)
    assert not r.accepted
    assert r.reason is UserDataApplyReason.UNKNOWN_EVENT

def test_limit_order_request_contains_price_and_tif():
    from datetime import datetime, timezone
    from trading_platform.core.ttl import ValidWindow
    from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
    from trading_platform.v379.execution_parity import TestnetMutationGate
    from trading_platform.v380 import BinanceTestnetOrderAdapterV380, BinanceV380TestnetExecutionGateway
    from trading_platform.v35.binance_execution import BinanceTestnetExecutionConfig

    intent = OrderIntent(
        intent_id="I-LIMIT", decision_id="D", portfolio_decision_id="P", risk_decision_id="R",
        strategy_id="S", model_id="M", execution_version="V380", symbol="BTCUSDT", side=Side.BUY,
        action=OrderAction.OPEN, quantity=Decimal("1"), order_type=OrderType.LIMIT, price=Decimal("99"),
        time_in_force="GTC", window=ValidWindow(datetime(2026,1,1,tzinfo=timezone.utc), datetime(2030,1,1,tzinfo=timezone.utc)),
    )
    adapter = BinanceTestnetOrderAdapterV380(
        BinanceV380TestnetExecutionGateway(BinanceTestnetExecutionConfig()),
        TestnetMutationGate(mutation_enabled=True, operator_approval=True, max_notional=Decimal("200")),
    )
    request = adapter.to_order_request(intent, now=datetime(2026,1,1,tzinfo=timezone.utc))
    assert request.price == Decimal("99")
    assert request.time_in_force == "GTC"


def test_v380_gateway_params_encode_limit_price_and_tif():
    from datetime import datetime, timezone
    from trading_platform.execution.models import OrderRequest, OrderType, Side
    from trading_platform.v380 import BinanceV380TestnetExecutionGateway
    req = OrderRequest(
        order_request_id="r", correlation_id="c", idempotency_key="i", client_order_id="cid",
        intent_id="intent", risk_decision_id="risk", execution_version="V380",
        timestamp=datetime(2026,1,1,tzinfo=timezone.utc), deadline=datetime(2030,1,1,tzinfo=timezone.utc),
        symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.LIMIT, quantity=Decimal("1"),
        price=Decimal("99.5"), time_in_force="GTC",
    )
    params = BinanceV380TestnetExecutionGateway._params(req)
    assert params["price"] == "99.5"
    assert params["timeInForce"] == "GTC"
    assert params["type"] == "LIMIT"


def test_v380_gateway_blocks_incomplete_limit_request():
    from datetime import datetime, timezone
    from trading_platform.execution.models import OrderRequest, OrderType, Side
    from trading_platform.v380 import BinanceV380TestnetExecutionGateway
    req = OrderRequest(
        order_request_id="r", correlation_id="c", idempotency_key="i", client_order_id="cid",
        intent_id="intent", risk_decision_id="risk", execution_version="V380",
        timestamp=datetime(2026,1,1,tzinfo=timezone.utc), deadline=datetime(2030,1,1,tzinfo=timezone.utc),
        symbol="BTCUSDT", side=Side.BUY, order_type=OrderType.LIMIT, quantity=Decimal("1"),
        price=Decimal("99.5"),
    )
    with pytest.raises(ValueError, match="LIMIT_TIME_IN_FORCE_REQUIRED"):
        BinanceV380TestnetExecutionGateway._params(req)
