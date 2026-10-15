from trading_platform.v20.recovery import RecoveryCoordinator, RecoveryState
from trading_platform.v20.reconciliation import ReconciliationResult, ReconciliationDiff, ReconciliationState

def green():
    return ReconciliationResult(ReconciliationState.GREEN, ReconciliationDiff(), 'r','s','REST_WS_MATCH')
def red():
    return ReconciliationResult(ReconciliationState.RED, ReconciliationDiff(status_mismatches=('1',)), 'r','s','REST_WS_DIVERGENCE')

def test_recovery_verified_and_resubscribe():
    seen=[]
    c=RecoveryCoordinator(reconcile=green, resubscribe=lambda: seen.append('r'))
    out=c.recover('stream_expired')
    assert out.state is RecoveryState.VERIFIED and seen==['r']
    c.require_verified()

def test_failed_recovery_is_blocked():
    c=RecoveryCoordinator(reconcile=red)
    out=c.recover('divergence')
    assert out.state is RecoveryState.BLOCKED
    try: c.require_verified(); assert False
    except PermissionError as e: assert str(e)=='RECOVERY_NOT_VERIFIED'
