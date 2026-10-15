from enum import Enum
from dataclasses import dataclass
from typing import FrozenSet

class OrderExecutionState(str, Enum):
    CREATED='CREATED'; SUBMITTED='SUBMITTED'; ACKNOWLEDGED='ACKNOWLEDGED'; PARTIALLY_FILLED='PARTIALLY_FILLED'; FILLED='FILLED'; CANCEL_REQUESTED='CANCEL_REQUESTED'; CANCELLED='CANCELLED'; REJECTED='REJECTED'; EXPIRED='EXPIRED'; UNKNOWN='UNKNOWN'

TERMINAL=frozenset({OrderExecutionState.FILLED,OrderExecutionState.CANCELLED,OrderExecutionState.REJECTED,OrderExecutionState.EXPIRED})
_ALLOWED={
 OrderExecutionState.CREATED:frozenset({OrderExecutionState.SUBMITTED,OrderExecutionState.EXPIRED,OrderExecutionState.UNKNOWN}),
 OrderExecutionState.SUBMITTED:frozenset({OrderExecutionState.ACKNOWLEDGED,OrderExecutionState.PARTIALLY_FILLED,OrderExecutionState.FILLED,OrderExecutionState.REJECTED,OrderExecutionState.UNKNOWN,OrderExecutionState.CANCEL_REQUESTED}),
 OrderExecutionState.ACKNOWLEDGED:frozenset({OrderExecutionState.PARTIALLY_FILLED,OrderExecutionState.FILLED,OrderExecutionState.CANCEL_REQUESTED,OrderExecutionState.EXPIRED,OrderExecutionState.REJECTED,OrderExecutionState.UNKNOWN}),
 OrderExecutionState.PARTIALLY_FILLED:frozenset({OrderExecutionState.PARTIALLY_FILLED,OrderExecutionState.FILLED,OrderExecutionState.CANCEL_REQUESTED,OrderExecutionState.UNKNOWN,OrderExecutionState.EXPIRED}),
 OrderExecutionState.CANCEL_REQUESTED:frozenset({OrderExecutionState.CANCELLED,OrderExecutionState.PARTIALLY_FILLED,OrderExecutionState.FILLED,OrderExecutionState.UNKNOWN}),
 OrderExecutionState.UNKNOWN:frozenset({OrderExecutionState.ACKNOWLEDGED,OrderExecutionState.PARTIALLY_FILLED,OrderExecutionState.FILLED,OrderExecutionState.CANCELLED,OrderExecutionState.REJECTED,OrderExecutionState.EXPIRED,OrderExecutionState.UNKNOWN}),
}

@dataclass(frozen=True)
class OrderTransition:
    source: OrderExecutionState
    target: OrderExecutionState
    event_id: str
    idempotency_key: str

class OrderLifecycle:
    def __init__(self) -> None:
        self.state=OrderExecutionState.CREATED
        self._applied: dict[str, OrderTransition]={}
    def apply(self, target: OrderExecutionState, *, event_id: str, idempotency_key: str) -> OrderExecutionState:
        prior=self._applied.get(idempotency_key)
        if prior:
            if prior.target != target or prior.event_id != event_id:
                raise ValueError('IDEMPOTENCY_CONFLICT')
            return self.state
        if self.state in TERMINAL and target != self.state:
            raise ValueError('TERMINAL_STATE_MUTATION')
        allowed=_ALLOWED.get(self.state,frozenset())
        if target not in allowed and target != self.state:
            raise ValueError(f'INVALID_ORDER_TRANSITION {self.state}->{target}')
        tr=OrderTransition(self.state,target,event_id,idempotency_key)
        self._applied[idempotency_key]=tr
        self.state=target
        return self.state
