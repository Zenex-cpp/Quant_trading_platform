from trading_platform.v20.reconciliation import RestWebSocketReconciler, ReconciliationState

def acct(status='NEW', qty='0'):
    return {'openOrders':[{'orderId':1,'status':status,'executedQty':qty}], 'positions':[{'symbol':'BTCUSDT','positionAmt':'0'}]}

def test_rest_ws_green():
    r=RestWebSocketReconciler().reconcile(rest_account=acct(), stream_account=acct())
    assert r.state is ReconciliationState.GREEN and r.trading_allowed

def test_status_divergence_red():
    r=RestWebSocketReconciler().reconcile(rest_account=acct('NEW'), stream_account=acct('FILLED'))
    assert r.state is ReconciliationState.RED and not r.trading_allowed

def test_stale_stream_blocks():
    r=RestWebSocketReconciler().reconcile(rest_account=acct(), stream_account=acct(), stream_stale=True)
    assert r.state is ReconciliationState.RED

def test_position_divergence_red():
    r=RestWebSocketReconciler().reconcile(rest_account=acct(), stream_account={'openOrders':[{'orderId':1,'status':'NEW','executedQty':'0'}], 'positions':[{'symbol':'BTCUSDT','positionAmt':'1'}]})
    assert 'BTCUSDT' in r.diff.position_mismatches
