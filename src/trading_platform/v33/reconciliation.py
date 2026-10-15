from dataclasses import dataclass
from enum import Enum

class ReconciliationRequired(RuntimeError):
    """Raised when an ambiguous execution state forbids a new dispatch."""

@dataclass(frozen=True)
class ReconciliationRequest:
    intent_id: str
    reason: str
    order_request_id: str | None = None
    client_order_id: str | None = None
    required: bool = True

class ReconciliationOutcome(str, Enum):
    RESOLVED = "RESOLVED"
    STILL_UNKNOWN = "STILL_UNKNOWN"


def require_reconciliation(*, intent_id: str, reason: str, order_request_id: str | None = None,
                           client_order_id: str | None = None) -> ReconciliationRequest:
    return ReconciliationRequest(intent_id, reason, order_request_id, client_order_id, True)
