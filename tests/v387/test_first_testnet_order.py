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
from trading_platform.v385 import ControlledTestnetSubmitAuthorityV385, PreTradeSnapshotV385
from trading_platform.v386 import OperatorSessionAuthorityV386, UserDataHealthV386
from trading_platform.v387 import FirstTestnetOrderPolicyV387, FirstTestnetOrderRunnerV387, QuoteSnapshotV387, OrderEventObservationV387, ReconciliationResultV387

BASE=datetime(2026,10,5,10,0,tzinfo=timezone.utc)
class G:
    def __init__(self): self.calls=0
    def submit(self,o,*,credentials): self.calls+=1; return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED,o.client_order_id,'EX-387',raw={'status':'NEW'})
def mk():
    i=OrderIntent('I-387','D-387','P-387','R-387','S-387','M-387','V387','BTCUSDT',Side.BUY,OrderAction.OPEN,Decimal('0.0002'),OrderType.LIMIT,ValidWindow(BASE,BASE+timedelta(minutes=5)),Decimal('49900'),'GTC','RR-387')
    rid='or-'+hashlib.sha256((i.intent_id+i.execution_version).encode()).hexdigest()[:24]
    snap=PreTradeSnapshotV385('SNP-387',BASE,i.intent_id,rid,'D','POS','PORT','RISK','LIMITS','MARKET','LIQ','MODEL','STRATEGY','VERSIONS','FLAT','RECONCILED','GREEN',False)
    a=TestnetExecutionActivationAuthorityV384(ActivationConfigV384(max_notional=Decimal('25')),clock=lambda:BASE)
    a.activate(connectivity=ConnectivityProofV384('VERIFIED','EV-387',BASE,BASE+timedelta(minutes=5),'https://testnet.binancefuture.com',0),approval=OperatorApprovalV384('APR-387','operator','TESTNET_ORDER_MUTATION',BASE,BASE+timedelta(minutes=5),'controlled'),reconciliation_state='GREEN',now=BASE)
    g=G(); store=EventStore(); ctl=ControlledTestnetSubmitAuthorityV385(activation=a,gateway=g,event_store=store,clock=lambda:BASE); op=OperatorSessionAuthorityV386(activation=a,submitter=ctl,clock=lambda:BASE)
    conn=ConnectivityEvidenceV383(PreflightStatus.VERIFIED,'https://testnet.binancefuture.com','wss://ws-api.testnet.binancefuture.com/ws-api/v3','wss://ws-api.testnet.binancefuture.com/ws-api/v3','RESOLVED',BASE.timestamp()*1000,BASE.timestamp()*1000,0,'OK')
    gate=op.preflight(connectivity=conn,user_data=UserDataHealthV386(True,True,True,BASE.timestamp(),'OK'),reconciliation_green=True,credentials=RuntimeCredentialValues('K',b'S'),now=BASE)
    runner=FirstTestnetOrderRunnerV387(session=op,clock=lambda:BASE)
    quote=QuoteSnapshotV387('BTCUSDT',Decimal('50010'),Decimal('50020'),BASE)
    return i,snap,g,gate,runner,quote

def test_arms_only_with_non_marketable_fresh_quote():
    i,s,g,gate,r,q=mk(); out=r.prepare(gate=gate,intent=i,quote=q,now=BASE); assert out.allowed and r.state.value=='ARMED'

def test_marketable_price_blocked():
    i,s,g,gate,r,q=mk(); i=OrderIntent(**{**i.__dict__,'price':Decimal('50015')}); out=r.prepare(gate=gate,intent=i,quote=q,now=BASE); assert not out.allowed and out.reason=='NON_MARKETABLE_PRICE'

def test_stale_quote_blocked():
    i,s,g,gate,r,q=mk(); q=QuoteSnapshotV387('BTCUSDT',Decimal('50010'),Decimal('50020'),BASE-timedelta(seconds=3)); out=r.prepare(gate=gate,intent=i,quote=q,now=BASE); assert not out.allowed and out.reason=='QUOTE_STALE'

def test_wrong_tif_blocked():
    i,s,g,gate,r,q=mk(); i=OrderIntent(**{**i.__dict__,'time_in_force':'IOC'}); out=r.prepare(gate=gate,intent=i,quote=q,now=BASE); assert not out.allowed and out.reason=='TIME_IN_FORCE_GTC'

def test_single_shot_submit_and_unknown_does_not_retry():
    i,s,g,gate,r,q=mk(); prep=r.prepare(gate=gate,intent=i,quote=q,now=BASE); out=r.submit_once(preparation=prep,gate=gate,intent=i,credentials=RuntimeCredentialValues('K',b'S'),pre_trade_snapshot=s,now=BASE); assert out.status=='ACKNOWLEDGED' and g.calls==1
    with pytest.raises(PermissionError,match='FIRST_TESTNET_SINGLE_SHOT_ONLY'): r.submit_once(preparation=prep,gate=gate,intent=i,credentials=RuntimeCredentialValues('K',b'S'),pre_trade_snapshot=s,now=BASE)
    assert g.calls==1

def test_observation_requires_correlation_and_monotonic_time():
    i,s,g,gate,r,q=mk(); prep=r.prepare(gate=gate,intent=i,quote=q,now=BASE); out=r.submit_once(preparation=prep,gate=gate,intent=i,credentials=RuntimeCredentialValues('K',b'S'),pre_trade_snapshot=s,now=BASE)
    with pytest.raises(PermissionError,match='ORDER_EVENT_CORRELATION_MISMATCH'):
        r.observe(OrderEventObservationV387('WRONG-CID','NEW',BASE+timedelta(seconds=1)))
    r.observe(OrderEventObservationV387(out.client_order_id,'NEW',BASE+timedelta(seconds=2)))
    with pytest.raises(PermissionError,match='ORDER_EVENT_OUT_OF_ORDER'):
        r.observe(OrderEventObservationV387(out.client_order_id,'CANCELED',BASE+timedelta(seconds=1)))

def test_terminal_observation_and_reconciliation_complete():
    i,s,g,gate,r,q=mk(); prep=r.prepare(gate=gate,intent=i,quote=q,now=BASE); out=r.submit_once(preparation=prep,gate=gate,intent=i,credentials=RuntimeCredentialValues('K',b'S'),pre_trade_snapshot=s,now=BASE); r.observe(OrderEventObservationV387(out.client_order_id,'NEW',BASE+timedelta(seconds=1))); r.observe(OrderEventObservationV387(out.client_order_id,'CANCELED',BASE+timedelta(seconds=2))); r.complete(reconciliation=ReconciliationResultV387(True,out.client_order_id,'EX-387',True,True,'GREEN')); assert r.state.value=='COMPLETE'

def test_out_of_order_event_blocked():
    i,s,g,gate,r,q=mk(); prep=r.prepare(gate=gate,intent=i,quote=q,now=BASE); out=r.submit_once(preparation=prep,gate=gate,intent=i,credentials=RuntimeCredentialValues('K',b'S'),pre_trade_snapshot=s,now=BASE); r.observe(OrderEventObservationV387(out.client_order_id,'NEW',BASE+timedelta(seconds=2))); 
    with pytest.raises(PermissionError,match='ORDER_EVENT_OUT_OF_ORDER'): r.observe(OrderEventObservationV387(out.client_order_id,'CANCELED',BASE+timedelta(seconds=1)))

def test_expired_in_match_treated_terminal():
    i,s,g,gate,r,q=mk(); prep=r.prepare(gate=gate,intent=i,quote=q,now=BASE); out=r.submit_once(preparation=prep,gate=gate,intent=i,credentials=RuntimeCredentialValues('K',b'S'),pre_trade_snapshot=s,now=BASE); r.observe(OrderEventObservationV387(out.client_order_id,'EXPIRED_IN_MATCH',BASE+timedelta(seconds=1))); assert r.state.value=='RECONCILING'
