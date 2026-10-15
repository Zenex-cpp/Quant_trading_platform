from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping

from trading_platform.v19.user_stream import NormalizedUserEvent, UserEventType

@dataclass(frozen=True)
class ReconciliationTrigger:
    required: bool
    reason: str
    blocking: bool = True

class UserStateReconciler:
    """Event-driven reconciliation trigger. It never mutates exchange state."""
    TERMINAL = {"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH"}

    def on_event(self, event: NormalizedUserEvent) -> ReconciliationTrigger:
        if event.event_type in {UserEventType.LISTEN_KEY_EXPIRED, UserEventType.UNKNOWN}:
            return ReconciliationTrigger(True, event.event_type.value, True)
        if event.event_type is UserEventType.MARGIN_CALL:
            return ReconciliationTrigger(True, "MARGIN_CALL", True)
        if event.event_type is UserEventType.ACCOUNT_UPDATE:
            return ReconciliationTrigger(True, "ACCOUNT_UPDATE", False)
        if event.event_type is UserEventType.ORDER_TRADE_UPDATE:
            if event.order_status in self.TERMINAL:
                return ReconciliationTrigger(True, "TERMINAL_ORDER_UPDATE", False)
            return ReconciliationTrigger(False, "ORDER_UPDATE_NONTERMINAL", False)
        return ReconciliationTrigger(False, "NO_RECONCILIATION_REQUIRED", False)
