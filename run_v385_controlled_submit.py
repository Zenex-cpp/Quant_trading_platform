#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/"src"))
from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v21.event_store import EventStore
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v384 import ConnectivityProofV384, OperatorApprovalV384, TestnetExecutionActivationAuthorityV384, TestnetExecutionActivationConfigV384
from trading_platform.v385 import ControlledTestnetSubmitAuthorityV385, PreTradeSnapshotV385, ControlledSubmitError
NOW=datetime(2026,10,5,10,0,tzinfo=timezone.utc)
class G:
    def __init__(self): self.calls=0
    def submit(self,order,*,credentials):
        self.calls+=1
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED,order.client_order_id,"EX-385",raw={"status":"NEW"})
def make_intent():
    return OrderIntent("I-V385-E1","D-V385-E1","P-V385-E1","R-V385-E1","S-V385","M-V385","V385-1","BTCUSDT",Side.BUY,OrderAction.OPEN,Decimal("0.0002"),OrderType.LIMIT,ValidWindow(NOW,NOW+timedelta(minutes=5)),Decimal("50000"),"GTC","RR-V385")
def activate():
    a=TestnetExecutionActivationAuthorityV384(TestnetExecutionActivationConfigV384(max_notional=Decimal("25")),clock=lambda:NOW)
    a.activate(connectivity=ConnectivityProofV384("VERIFIED","EV-V385",NOW,NOW+timedelta(minutes=5),"https://testnet.binancefuture.com",0),approval=OperatorApprovalV384("APR-V385","operator","TESTNET_ORDER_MUTATION",NOW,NOW+timedelta(minutes=5),"controlled"),reconciliation_state="GREEN",now=NOW)
    return a
def main():
    i=make_intent(); rid="or-"+hashlib.sha256((i.intent_id+i.execution_version).encode()).hexdigest()[:24]
    snap=PreTradeSnapshotV385("SNP-V385",NOW,i.intent_id,rid,"D","POS","PORT","RISK","LIMITS","MARKET","LIQ","MODEL","STRATEGY","VERSIONS","FLAT","RECONCILED","GREEN",False)
    store=EventStore(); g=G(); c=ControlledTestnetSubmitAuthorityV385(activation=activate(),gateway=g,event_store=store,clock=lambda:NOW)
    checks=[]
    out=c.submit(i,credentials=RuntimeCredentialValues("LOCAL_ONLY",b"LOCAL_SECRET"),pre_trade_snapshot=snap,now=NOW)
    checks.append({"check":"controlled_submit_acknowledged","pass":out.status=="ACKNOWLEDGED"})
    checks.append({"check":"single_gateway_side_effect","pass":g.calls==1})
    checks.append({"check":"pretrade_before_dispatch","pass":[e.event_type for e in store.iter_events()][:2]==["PRE_TRADE_SNAPSHOT_CAPTURED","ORDER_DISPATCH_ATTEMPTED"]})
    checks.append({"check":"credentials_not_persisted","pass":"LOCAL_SECRET" not in json.dumps([e.payload for e in store.iter_events()])})
    payload={"artifact_type":"V385_CONTROLLED_TESTNET_SUBMIT_EVIDENCE","local_status":"PASS" if all(c["pass"] for c in checks) else "FAIL","checks":checks,"gateway_calls":g.calls,"mutating_live_testnet_called":False,"runtime_connectivity_status":"NOT_VERIFIED","production_ready":False}
    body=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode(); payload["evidence_hash"]=hashlib.sha256(body).hexdigest()
    path=ROOT/"V385_CONTROLLED_TESTNET_SUBMIT_EVIDENCE.json"; path.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(path); print(payload["local_status"]); print(payload["evidence_hash"]); print(payload["runtime_connectivity_status"])
    return 0 if payload["local_status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
