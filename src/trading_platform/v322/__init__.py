"""V3.22 durable closure of PENDING/UNKNOWN dispatch attempts via reconciliation evidence."""

from .durable_reconciliation import (
    DurableDispatchReconciliation,
    DurableDispatchReconciliationLedger,
    DispatchReconciliationConflict,
    DispatchReconciliationReplayError,
)

__version__ = "3.22.0"

__all__ = [
    "DurableDispatchReconciliation",
    "DurableDispatchReconciliationLedger",
    "DispatchReconciliationConflict",
    "DispatchReconciliationReplayError",
]
