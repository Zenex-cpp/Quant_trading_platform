from trading_platform.v20.reconciliation import RestWebSocketReconciler

if __name__ == '__main__':
    print('V2.0 offline reconciliation contract. No network calls are made.')
    r = RestWebSocketReconciler().reconcile(
        rest_account={'openOrders': [], 'positions': []},
        stream_account={'openOrders': [], 'positions': []},
    )
    print(r.state.value, r.reason)
