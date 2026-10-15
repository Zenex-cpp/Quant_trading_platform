from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Callable
from .reconciliation import ReconciliationResult, ReconciliationState

class RecoveryState(str, Enum): HEALTHY='HEALTHY'; RECOVERING='RECOVERING'; BLOCKED='BLOCKED'; VERIFIED='VERIFIED'

@dataclass(frozen=True)
class RecoveryResult:
    state: RecoveryState
    reconciliation: ReconciliationResult | None
    actions: tuple[str, ...]
    reason: str

class RecoveryCoordinator:
    def __init__(self, *, reconcile: Callable[[], ReconciliationResult], resubscribe: Callable[[], None] | None=None):
        self.reconcile=reconcile
        self.resubscribe=resubscribe
        self.state=RecoveryState.HEALTHY

    def recover(self, cause: str) -> RecoveryResult:
        self.state=RecoveryState.RECOVERING
        actions=[]
        if self.resubscribe:
            self.resubscribe(); actions.append('RESUBSCRIBE_STREAM')
        result=self.reconcile(); actions.append('REST_WS_RECONCILE')
        if result.state is ReconciliationState.GREEN:
            self.state=RecoveryState.VERIFIED
            return RecoveryResult(self.state,result,tuple(actions),'RECOVERY_VERIFIED')
        self.state=RecoveryState.BLOCKED
        return RecoveryResult(self.state,result,tuple(actions),'RECOVERY_FAILED:'+cause)

    def require_verified(self) -> None:
        if self.state is not RecoveryState.VERIFIED:
            raise PermissionError('RECOVERY_NOT_VERIFIED')
