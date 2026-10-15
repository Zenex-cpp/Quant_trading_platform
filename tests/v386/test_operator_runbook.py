from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib

import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v21.event_store import EventStore
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v383_connectivity import ConnectivityEvidenceV383, PreflightStatus
from trading_platform.v384 import ConnectivityProofV384, OperatorApprovalV384, TestnetExecutionActivationAuthorityV384, TestnetExecutionActivationConfigV384 as ActivationConfigV384
from trading_platform.v385 import ControlledTestnetSubmitAuthorityV385, PreTradeSnapshotV385, ControlledSubmitError
from trading_platform.v386 import OperatorSessionAuthorityV386, UserDataHealthV386

BASE=datetime(2026,10,5,10,0,tzinfo=timezone.utc)

class Gateway:
    def __init__(self, outcome=ExchangeOutcome.ACKNOWLEDGED): self.calls=0; self.outcome=outcome
    def submit(self, order, *, credentials):
        self.calls += 1
        return SubmitObservation(self.outcome, order.client_order_id, "EX-386" if self.outcome != ExchangeOutcome.UNKNOWN else None, raw={"status":"NEW"})

def intent():
    return OrderIntent("I-386","D-386","P-386","R-386","S-386","M-386","V386","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.0002"),OrderType.LIMIT,ValidWindow(BASE,BASE+timedelta(minutes=5)),Decimal("50000"),"GTC","RR-386")

def activation():
    a=TestnetExecutionActivationAuthorityV384(ActivationConfigV384(max_notional=Decimal("25")),clock=lambda:BASE)
    a.activate(
        connectivity=ConnectivityProofV384("VERIFIED","EV-386",BASE,BASE+timedelta(minutes=5),"https://testnet.binancefuture.com",0),
        approval=OperatorApprovalV384("APR-386","operator","TESTNET_ORDER_MUTATION",BASE,BASE+timedelta(minutes=5),"controlled"),
        reconciliation_state="GREEN",now=BASE)
    return a

def snapshot():
    i=intent(); rid="or-"+hashlib.sha256((i.intent_id+i.execution_version).encode()).hexdigest()[:24]
    return PreTradeSnapshotV385("SNP-386",BASE,i.intent_id,rid,"DCHAIN","POS","PORT","RISK","LIMITS","MARKET","LIQ","MODEL","STRATEGY","VERSIONS","FLAT","RECONCILED","GREEN",False)

def evidence():
    return ConnectivityEvidenceV383(PreflightStatus.VERIFIED,"https://testnet.binancefuture.com","wss://ws-api.testnet.binancefuture.com/ws-api/v3","wss://ws-api.testnet.binancefuture.com/ws-api/v3","RESOLVED",BASE.timestamp()*1000,BASE.timestamp()*1000,0,"OK")

def session(outcome=ExchangeOutcome.ACKNOWLEDGED):
    store=EventStore(); gw=Gateway(outcome)
    auth=activation(); ctl=ControlledTestnetSubmitAuthorityV385(activation=auth,gateway=gw,event_store=store,clock=lambda:BASE)
    return OperatorSessionAuthorityV386(activation=auth,submitter=ctl,clock=lambda:BASE), gw

def good_ud():
    return UserDataHealthV386(True,True,True,BASE.timestamp(),"OK")

def creds():
    return RuntimeCredentialValues("KEY_RUNTIME",b"SECRET_RUNTIME")

def test_gate_requires_fresh_healthy_user_data():
    s,_=session()
    r=s.preflight(connectivity=evidence(),user_data=good_ud(),reconciliation_green=True,credentials=creds(),now=BASE)
    assert r.allowed and s.state.value=="READY"

def test_stale_user_data_blocks():
    s,_=session(); stale=UserDataHealthV386(True,True,True,(BASE-timedelta(seconds=16)).timestamp(),"STALE")
    r=s.preflight(connectivity=evidence(),user_data=stale,reconciliation_green=True,credentials=creds(),now=BASE)
    assert not r.allowed and r.reason=="USER_DATA_EVENT_FRESH"

def test_unhealthy_user_data_blocks():
    s,_=session(); bad=UserDataHealthV386(True,False,True,BASE.timestamp(),"WS_DOWN")
    r=s.preflight(connectivity=evidence(),user_data=bad,reconciliation_green=True,credentials=creds(),now=BASE)
    assert not r.allowed and r.reason=="USER_DATA_WEBSOCKET_HEALTHY"

def test_missing_credentials_blocks():
    s,_=session(); r=s.preflight(connectivity=evidence(),user_data=good_ud(),reconciliation_green=True,credentials=None,now=BASE)
    assert not r.allowed and r.reason=="RUNTIME_CREDENTIALS_PRESENT"

def test_nonverified_connectivity_blocks_even_with_active_activation():
    s,_=session(); bad=ConnectivityEvidenceV383(PreflightStatus.NOT_VERIFIED,"https://testnet.binancefuture.com","","","UNRESOLVED",None,BASE.timestamp()*1000,None,"DNS")
    r=s.preflight(connectivity=bad,user_data=good_ud(),reconciliation_green=True,credentials=creds(),now=BASE)
    assert not r.allowed and r.reason=="CONNECTIVITY_VERIFIED"

def test_controlled_submit_only_after_ready_gate():
    s,gw=session(); g=s.preflight(connectivity=evidence(),user_data=good_ud(),reconciliation_green=True,credentials=creds(),now=BASE)
    out=s.submit_once(gate=g,intent=intent(),credentials=creds(),pre_trade_snapshot=snapshot(),now=BASE)
    assert out.status=="ACKNOWLEDGED" and gw.calls==1

def test_submit_rejected_when_gate_blocked():
    s,gw=session(); g=s.preflight(connectivity=evidence(),user_data=good_ud(),reconciliation_green=False,credentials=creds(),now=BASE)
    with pytest.raises(PermissionError,match="OPERATOR_MUTATION_GATE_BLOCKED"):
        s.submit_once(gate=g,intent=intent(),credentials=creds(),pre_trade_snapshot=snapshot(),now=BASE)
    assert gw.calls==0

def test_unknown_requires_post_trade_reconciliation():
    s,gw=session(ExchangeOutcome.UNKNOWN); g=s.preflight(connectivity=evidence(),user_data=good_ud(),reconciliation_green=True,credentials=creds(),now=BASE)
    out=s.submit_once(gate=g,intent=intent(),credentials=creds(),pre_trade_snapshot=snapshot(),now=BASE)
    assert out.status=="UNKNOWN" and s.state.value=="UNKNOWN"
    with pytest.raises(ControlledSubmitError,match="POST_TRADE_RECONCILIATION_REQUIRED"):
        s.assert_post_trade_reconciliation(reconciliation_green=True)

def test_closed_session_cannot_mutate():
    s,gw=session(); g=s.preflight(connectivity=evidence(),user_data=good_ud(),reconciliation_green=True,credentials=creds(),now=BASE); s.close()
    with pytest.raises(PermissionError,match="OPERATOR_SESSION_CLOSED"):
        s.submit_once(gate=g,intent=intent(),credentials=creds(),pre_trade_snapshot=snapshot(),now=BASE)
    assert gw.calls==0
