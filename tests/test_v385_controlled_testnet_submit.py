from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v21.event_store import EventStore
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v384 import ConnectivityProofV384, OperatorApprovalV384, TestnetExecutionActivationAuthorityV384, TestnetExecutionActivationConfigV384 as ActivationConfigV384
from trading_platform.v385 import ControlledSubmitError, ControlledTestnetSubmitAuthorityV385, PreTradeSnapshotV385

BASE = datetime(2026,10,5,10,0,tzinfo=timezone.utc)

class Gateway:
    def __init__(self, fail=False): self.calls=[]; self.fail=fail
    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        if self.fail: raise TimeoutError("timeout")
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "EX-1", raw={"status":"NEW"})

def intent():
    return OrderIntent("I-385","D-385","P-385","R-385","S-385","M-385","V385","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.0002"),OrderType.LIMIT,ValidWindow(BASE,BASE+timedelta(minutes=5)),Decimal("50000"),"GTC","RR-385")

def authority():
    a=TestnetExecutionActivationAuthorityV384(ActivationConfigV384(max_notional=Decimal("25")),clock=lambda: BASE)
    a.activate(
        connectivity=ConnectivityProofV384("VERIFIED","EV-385",BASE,BASE+timedelta(minutes=5),"https://testnet.binancefuture.com",0),
        approval=OperatorApprovalV384("APR-385","operator","TESTNET_ORDER_MUTATION",BASE,BASE+timedelta(minutes=5),"controlled"),
        reconciliation_state="GREEN",now=BASE)
    return a

def snapshot():
    i=intent()
    # Order request ID is derived by v380 from intent_id + execution_version.
    import hashlib
    rid="or-"+hashlib.sha256((i.intent_id+i.execution_version).encode()).hexdigest()[:24]
    return PreTradeSnapshotV385("SNP-385",BASE,i.intent_id,rid,"DCHAIN","POS","PORT","RISK","LIMITS","MARKET","LIQ","MODEL","STRATEGY","VERSIONS","FLAT","RECONCILED","GREEN",False)

def test_happy_path_has_durable_snapshot_and_dispatch_claim():
    store=EventStore(); gw=Gateway(); auth=authority(); ctl=ControlledTestnetSubmitAuthorityV385(activation=auth,gateway=gw,event_store=store,clock=lambda: BASE)
    out=ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=snapshot(),now=BASE)
    assert out.status=="ACKNOWLEDGED" and len(gw.calls)==1
    assert any(e.event_type=="PRE_TRADE_SNAPSHOT_CAPTURED" for e in store.iter_events())
    assert any(e.event_type=="ORDER_DISPATCH_ATTEMPTED" for e in store.iter_events())
    assert any(e.event_type=="ORDER_DISPATCH_OBSERVED" for e in store.iter_events())

def test_repeat_submit_is_blocked_and_does_not_duplicate_side_effect():
    store=EventStore(); gw=Gateway(); ctl=ControlledTestnetSubmitAuthorityV385(activation=authority(),gateway=gw,event_store=store,clock=lambda: BASE)
    ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=snapshot(),now=BASE)
    with pytest.raises(Exception):
        ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=snapshot(),now=BASE)
    assert len(gw.calls)==1

def test_transport_exception_becomes_unknown_and_blocks_retry():
    store=EventStore(); gw=Gateway(fail=True); ctl=ControlledTestnetSubmitAuthorityV385(activation=authority(),gateway=gw,event_store=store,clock=lambda: BASE)
    with pytest.raises(ControlledSubmitError,match="UNKNOWN"):
        ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=snapshot(),now=BASE)
    assert len(gw.calls)==1
    with pytest.raises(Exception):
        ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=snapshot(),now=BASE)
    assert len(gw.calls)==1

def test_unknown_position_blocks_before_external_submit():
    store=EventStore(); gw=Gateway(); ctl=ControlledTestnetSubmitAuthorityV385(activation=authority(),gateway=gw,event_store=store,clock=lambda: BASE)
    s=snapshot(); s=PreTradeSnapshotV385(**{**s.__dict__,"position_state":"UNKNOWN"})
    with pytest.raises(ControlledSubmitError,match="POSITION_UNKNOWN"):
        ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=s,now=BASE)
    assert not gw.calls

def test_stale_market_blocks_before_external_submit():
    store=EventStore(); gw=Gateway(); ctl=ControlledTestnetSubmitAuthorityV385(activation=authority(),gateway=gw,event_store=store,clock=lambda: BASE)
    s=snapshot(); s=PreTradeSnapshotV385(**{**s.__dict__,"market_stale":True})
    with pytest.raises(ControlledSubmitError,match="MARKET_DATA_STALE"):
        ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=s,now=BASE)
    assert not gw.calls

def test_snapshot_binding_conflict_blocks_submit():
    store=EventStore(); gw=Gateway(); ctl=ControlledTestnetSubmitAuthorityV385(activation=authority(),gateway=gw,event_store=store,clock=lambda: BASE)
    s=snapshot(); s=PreTradeSnapshotV385(**{**s.__dict__,"order_request_id":"wrong"})
    with pytest.raises(ControlledSubmitError,match="ORDER_REQUEST_MISMATCH"):
        ctl.submit(intent(),credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL",b"TEST_SECRET_SENTINEL"),pre_trade_snapshot=s,now=BASE)
    assert not gw.calls
