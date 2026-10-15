#!/usr/bin/env python3
from __future__ import annotations
import hashlib,json,sys
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from pathlib import Path
ROOT=Path(__file__).resolve().parent; sys.path.insert(0,str(ROOT/'src'))
from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction,OrderIntent,OrderType,Side
from trading_platform.v21.event_store import EventStore
from trading_platform.v35.binance_execution import RuntimeCredentialValues,SubmitObservation,ExchangeOutcome
from trading_platform.v383_connectivity import ConnectivityEvidenceV383,PreflightStatus
from trading_platform.v384 import ConnectivityProofV384,OperatorApprovalV384,TestnetExecutionActivationAuthorityV384,TestnetExecutionActivationConfigV384
from trading_platform.v385 import ControlledTestnetSubmitAuthorityV385,PreTradeSnapshotV385
from trading_platform.v386 import OperatorSessionAuthorityV386,UserDataHealthV386
NOW=datetime(2026,10,5,10,0,tzinfo=timezone.utc)
class G:
    def __init__(self): self.calls=0
    def submit(self,o,*,credentials): self.calls+=1; return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED,o.client_order_id,'EX-386',raw={'status':'NEW'})
def main():
    i=OrderIntent('I-V386','D-V386','P-V386','R-V386','S-V386','M-V386','V386-1','BTCUSDT',Side.BUY,OrderAction.OPEN,Decimal('0.0002'),OrderType.LIMIT,ValidWindow(NOW,NOW+timedelta(minutes=5)),Decimal('50000'),'GTC','RR-V386')
    rid='or-'+hashlib.sha256((i.intent_id+i.execution_version).encode()).hexdigest()[:24]
    s=PreTradeSnapshotV385('SNP-V386',NOW,i.intent_id,rid,'D','POS','PORT','RISK','LIMITS','MARKET','LIQ','MODEL','STRATEGY','VERSIONS','FLAT','RECONCILED','GREEN',False)
    a=TestnetExecutionActivationAuthorityV384(TestnetExecutionActivationConfigV384(max_notional=Decimal('25')),clock=lambda:NOW)
    a.activate(connectivity=ConnectivityProofV384('VERIFIED','EV-V386',NOW,NOW+timedelta(minutes=5),'https://testnet.binancefuture.com',0),approval=OperatorApprovalV384('APR-V386','operator','TESTNET_ORDER_MUTATION',NOW,NOW+timedelta(minutes=5),'controlled'),reconciliation_state='GREEN',now=NOW)
    store=EventStore(); g=G(); ctl=ControlledTestnetSubmitAuthorityV385(activation=a,gateway=g,event_store=store,clock=lambda:NOW); op=OperatorSessionAuthorityV386(activation=a,submitter=ctl,clock=lambda:NOW)
    conn=ConnectivityEvidenceV383(PreflightStatus.VERIFIED,'https://testnet.binancefuture.com','wss://ws-api.testnet.binancefuture.com/ws-api/v3','wss://ws-api.testnet.binancefuture.com/ws-api/v3','RESOLVED',NOW.timestamp()*1000,NOW.timestamp()*1000,0,'OK')
    user=UserDataHealthV386(True,True,True,NOW.timestamp(),'OK'); creds=RuntimeCredentialValues('RUNTIME_KEY',b'RUNTIME_SECRET')
    gate=op.preflight(connectivity=conn,user_data=user,reconciliation_green=True,credentials=creds,now=NOW)
    checks=[{'check':'operational_gate_ready','pass':gate.allowed},{'check':'required_user_data_fresh','pass':dict(gate.checks).get('USER_DATA_EVENT_FRESH') is True},{'check':'activation_bound','pass':bool(gate.activation_id)}]
    out=op.submit_once(gate=gate,intent=i,credentials=creds,pre_trade_snapshot=s,now=NOW)
    checks.append({'check':'controlled_submit_acknowledged','pass':out.status=='ACKNOWLEDGED'})
    checks.append({'check':'single_external_side_effect','pass':g.calls==1})
    payload={'artifact_type':'V386_OPERATOR_TESTNET_SESSION_EVIDENCE','local_status':'PASS' if all(c['pass'] for c in checks) else 'FAIL','checks':checks,'state':op.state.value,'gateway_calls':g.calls,'runtime_connectivity_status':'NOT_VERIFIED','mutating_live_testnet_called':False,'production_ready':False}
    body=json.dumps(payload,sort_keys=True,separators=(',',':'),default=str).encode(); payload['evidence_hash']=hashlib.sha256(body).hexdigest()
    p=ROOT/'V386_OPERATOR_TESTNET_SESSION_EVIDENCE.json'; p.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(p); print(payload['local_status']); print(payload['evidence_hash'])
    return 0 if payload['local_status']=='PASS' else 1
if __name__=='__main__': raise SystemExit(main())
