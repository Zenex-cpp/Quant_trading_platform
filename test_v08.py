from decimal import Decimal as D
from trading_platform.execution.lifecycle import OrderLifecycle, OrderExecutionState
from trading_platform.execution.unknown import UnknownOrderResolver, UnknownOrderCase, UnknownResolution
from trading_platform.execution.precision import InstrumentRules
from trading_platform.execution.reconciliation_flow import ReconciliationResult
from trading_platform.execution.testnet_adapter import TestnetExecutionAdapter, TestnetEndpointConfig

class T:
    __test__ = False
    def send(self,r): return {'status':'ACK'}
    def cancel(self,r): return {'status':'CANCELLED'}
    def query(self,r): return {'status':'FILLED'}

def test_lifecycle_and_idempotency():
    x=OrderLifecycle(); x.apply(OrderExecutionState.SUBMITTED,event_id='e1',idempotency_key='k1'); x.apply(OrderExecutionState.SUBMITTED,event_id='e1',idempotency_key='k1'); assert x.state==OrderExecutionState.SUBMITTED

def test_invalid_transition():
    x=OrderLifecycle()
    try: x.apply(OrderExecutionState.FILLED,event_id='e',idempotency_key='k')
    except ValueError as e: assert 'INVALID_ORDER_TRANSITION' in str(e)
    else: raise AssertionError

def test_unknown_no_blind_retry():
    r=UnknownOrderResolver(); r.open(UnknownOrderCase('c','cid',None))
    try: r.assert_no_blind_retry('c')
    except ValueError as e: assert str(e)=='UNKNOWN_ORDER_NO_BLIND_RETRY'
    else: raise AssertionError

def test_unknown_resolution():
    r=UnknownOrderResolver(); r.open(UnknownOrderCase('c','cid','ex')); z=r.resolve('c',UnknownResolution.FILLED); assert z.status=='RESOLVED:FILLED'

def test_precision_rules():
    x=InstrumentRules(D('0.1'),D('0.01'),D('0.01'),D('5'))
    assert x.normalize_price(D('100.29'))==D('100.2'); assert x.normalize_qty(D('1.239'))==D('1.23'); x.validate_notional(D('1'),D('5'))

def test_min_notional_blocks():
    x=InstrumentRules(D('0.1'),D('0.01'),D('0.01'),D('10'))
    try: x.validate_notional(D('1'),D('5'))
    except ValueError as e: assert str(e)=='MIN_NOTIONAL_VIOLATION'
    else: raise AssertionError

def test_recovery_proof():
    r=ReconciliationResult('c',True,True,True,True,True,'MATCHED'); assert r.recovery_verified
    r2=ReconciliationResult('c',True,True,False,True,True,'MISMATCH'); assert not r2.recovery_verified

def test_testnet_guard():
    TestnetExecutionAdapter(TestnetEndpointConfig('https://example','TESTNET'),T())
    try: TestnetExecutionAdapter(TestnetEndpointConfig('https://example','LIVE'),T())
    except ValueError as e: assert str(e)=='NON_TESTNET_ENVIRONMENT_BLOCKED'
    else: raise AssertionError
