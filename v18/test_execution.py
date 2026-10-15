from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest

from trading_platform.v17.workflow import WorkflowConfig, TestnetWorkflow, MutationApproval
from trading_platform.v18.execution import OrderIntent, SafeTestnetExecution, OrderMode

class FakeTransport:
    def __init__(self): self.calls=[]
    def request(self, method, url, *, headers=None, params=None):
        self.calls.append((method,url,dict(params or {})))
        if url.endswith('/order/test'): return {"status":"TEST_OK"}
        if method == 'POST' and url.endswith('/order'): return {"orderId":123,"clientOrderId":params['newClientOrderId'],"status":"NEW"}
        if method == 'GET': return {"orderId":params.get('orderId',0),"status":"NEW"}
        if method == 'DELETE': return {"orderId":params.get('orderId',0),"status":"CANCELED"}
        return {}

def wf(tmp):
    t=FakeTransport(); w=TestnetWorkflow(WorkflowConfig('https://testnet.binancefuture.com', evidence_db=Path(tmp)/'e.sqlite'), transport=t, operator_id='op')
    w.set_reconciliation(True)
    return w,t

def approval():
    now=datetime.now(timezone.utc)
    return MutationApproval('A','op',now,now+timedelta(minutes=5),25,'testnet')

def test_deterministic_client_order_id():
    a=OrderIntent.deterministic(symbol='BTCUSDT',side='BUY',order_type='LIMIT',quantity='0.0001',price='50000')
    b=OrderIntent.deterministic(symbol='BTCUSDT',side='BUY',order_type='LIMIT',quantity='0.0001',price='50000')
    assert a.client_order_id == b.client_order_id
    assert len(a.client_order_id) <= 32

def test_order_cap_blocks():
    i=OrderIntent.deterministic(symbol='BTCUSDT',side='BUY',order_type='LIMIT',quantity='1',price='50000')
    with pytest.raises(PermissionError): i.validate(25, Decimal('50000'))

def test_test_order_is_non_mutating():
    with TemporaryDirectory() as d:
        w,t=wf(d); e=SafeTestnetExecution(w)
        i=OrderIntent.deterministic(symbol='BTCUSDT',side='BUY',order_type='LIMIT',quantity='0.0001',price='50000')
        o=e.test_order(i)
        assert o.status=='PASS'
        assert t.calls[0][0]=='POST' and t.calls[0][1].endswith('/order/test')

def test_place_order_requires_gate():
    with TemporaryDirectory() as d:
        t=FakeTransport(); w=TestnetWorkflow(WorkflowConfig('https://testnet.binancefuture.com', evidence_db=Path(d)/'e.sqlite'), transport=t, operator_id='op')
        e=SafeTestnetExecution(w)
        i=OrderIntent.deterministic(symbol='BTCUSDT',side='BUY',order_type='LIMIT',quantity='0.0001',price='50000')
        with pytest.raises(PermissionError): e.place_order(i, approval())

def test_place_and_cancel_are_explicitly_gated(monkeypatch):
    from trading_platform.v17 import workflow as workflow_module
    class PF:
        can_execute=True
    monkeypatch.setattr(workflow_module, 'build_preflight', lambda **kwargs: PF())
    with TemporaryDirectory() as d:
        w,t=wf(d); e=SafeTestnetExecution(w)
        i=OrderIntent.deterministic(symbol='BTCUSDT',side='BUY',order_type='LIMIT',quantity='0.0001',price='50000')
        out=e.place_order(i, approval())
        assert out.order_id=='123'
        cancelled=e.cancel_order(symbol='BTCUSDT', order_id='123', approval=approval())
        assert cancelled['status']=='CANCELED'

def test_cancel_requires_identifier():
    with TemporaryDirectory() as d:
        w,_=wf(d); e=SafeTestnetExecution(w)
        with pytest.raises(PermissionError): e.cancel_order(symbol='BTCUSDT', approval=approval())
