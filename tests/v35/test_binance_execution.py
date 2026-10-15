from decimal import Decimal
from datetime import datetime, timezone
import pytest

from trading_platform.execution.models import OrderRequest, Side, OrderType
from trading_platform.v35.binance_execution import (
    BinanceTestnetExecutionConfig, BinanceTestnetExecutionGateway,
    RuntimeCredentialValues, ExchangeOutcome, ExchangeUncertain,
)

class FakeClientGateway(BinanceTestnetExecutionGateway):
    def __init__(self, raw=None, exc=None):
        super().__init__(BinanceTestnetExecutionConfig())
        self.raw = raw
        self.exc = exc
    def _client(self, creds):
        class C:
            def __init__(self, raw, exc): self.raw, self.exc = raw, exc
            def signed_request(self, *a, **kw):
                if self.exc: raise self.exc
                return self.raw
        return C(self.raw, self.exc)

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)

def order():
    return OrderRequest("or1","corr1","idem1","cid-1","intent1","risk1","exec1",NOW,NOW,"BTCUSDT",Side.BUY,OrderType.MARKET,Decimal("0.001"))

def creds():
    return RuntimeCredentialValues("key", b"secret")

def test_submit_ack_maps_order_id_and_client_id():
    g = FakeClientGateway({"status":"NEW","orderId":12345,"clientOrderId":"cid-1"})
    r = g.submit(order(), credentials=creds())
    assert r.outcome is ExchangeOutcome.ACKNOWLEDGED
    assert r.exchange_order_id == "12345"
    assert r.client_order_id == "cid-1"

def test_unknown_submit_transport_requires_query_not_retry():
    g = FakeClientGateway(exc=TimeoutError())
    with pytest.raises(ExchangeUncertain, match="SUBMIT_OUTCOME_UNKNOWN"):
        g.submit(order(), credentials=creds())

def test_query_cancel_and_correlation():
    q = FakeClientGateway({"status":"FILLED","orderId":9,"clientOrderId":"cid-1"})
    r = q.query(symbol="BTCUSDT", client_order_id="cid-1", credentials=creds())
    assert r.outcome is ExchangeOutcome.ACKNOWLEDGED
    c = FakeClientGateway({"status":"CANCELED","orderId":9,"clientOrderId":"cid-1"})
    r2 = c.cancel(symbol="BTCUSDT", client_order_id="cid-1", credentials=creds())
    assert r2.outcome is ExchangeOutcome.CANCELLED

def test_config_blocks_mainnet_and_non_tls():
    with pytest.raises(ValueError, match="NON_TESTNET_ENVIRONMENT_BLOCKED"):
        BinanceTestnetExecutionGateway(BinanceTestnetExecutionConfig(environment="MAINNET"))
    with pytest.raises(ValueError, match="TLS_REQUIRED"):
        BinanceTestnetExecutionGateway(BinanceTestnetExecutionConfig(base_url="http://testnet.binancefuture.com"))

def test_missing_runtime_credentials_fail_closed():
    with pytest.raises(ValueError, match="RUNTIME_CREDENTIALS_REQUIRED"):
        RuntimeCredentialValues("", b"").values()
