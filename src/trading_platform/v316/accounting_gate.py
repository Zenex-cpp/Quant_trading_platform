from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from trading_platform.v315.durable_accounting import (
    AccountingProjection,
    DurableAccountingLedger,
    DurableFill,
)


class AccountingState(str, Enum):
    UNRECONCILED = "UNRECONCILED"
    RECONCILED = "RECONCILED"
    ADJUSTED = "ADJUSTED"
    UNKNOWN = "UNKNOWN"


class AccountingGateDenied(PermissionError):
    pass


@dataclass(frozen=True)
class AccountingGateSnapshot:
    state: AccountingState
    projection_hash: str | None
    reason: str

    @property
    def allows_new_risk(self) -> bool:
        return self.state in {AccountingState.RECONCILED, AccountingState.ADJUSTED}


class DurableAccountingAuthority:
    """Durable accounting authority and explicit risk gate.

    The authority never grants execution permission from a reconstruction alone. The
    caller must explicitly mark the reconstructed state reconciled after external evidence
    has been checked. UNKNOWN and UNRECONCILED therefore fail closed for new risk.
    """

    def __init__(self, ledger: DurableAccountingLedger) -> None:
        self.ledger = ledger
        self._state = AccountingState.UNRECONCILED
        self._reason = "ACCOUNTING_NOT_RECONCILED"
        self._projection: AccountingProjection | None = None

    def restore(self) -> AccountingGateSnapshot:
        self._projection = self.ledger.reconstruct()
        self._state = AccountingState.UNRECONCILED
        self._reason = "REPLAY_RESTORED_REQUIRES_RECONCILIATION"
        return self.snapshot()

    def mark_reconciled(self, *, evidence_id: str) -> AccountingGateSnapshot:
        if not evidence_id:
            raise ValueError("ACCOUNTING_EVIDENCE_ID_REQUIRED")
        if self._projection is None:
            self.restore()
        self._state = AccountingState.RECONCILED
        self._reason = f"RECONCILED:{evidence_id}"
        return self.snapshot()

    def mark_adjusted(self, *, evidence_id: str) -> AccountingGateSnapshot:
        if not evidence_id:
            raise ValueError("ACCOUNTING_EVIDENCE_ID_REQUIRED")
        if self._projection is None:
            self.restore()
        self._state = AccountingState.ADJUSTED
        self._reason = f"ADJUSTED:{evidence_id}"
        return self.snapshot()

    def mark_unknown(self, *, reason: str) -> AccountingGateSnapshot:
        if not reason:
            raise ValueError("ACCOUNTING_UNKNOWN_REASON_REQUIRED")
        self._state = AccountingState.UNKNOWN
        self._reason = reason
        return self.snapshot()

    def snapshot(self) -> AccountingGateSnapshot:
        return AccountingGateSnapshot(
            self._state,
            self._projection.state_hash if self._projection is not None else None,
            self._reason,
        )

    def assert_new_risk_allowed(self) -> None:
        snap = self.snapshot()
        if not snap.allows_new_risk:
            raise AccountingGateDenied(f"ACCOUNTING_NOT_ALLOWED:{snap.state.value}:{snap.reason}")

    @property
    def projection(self) -> AccountingProjection:
        if self._projection is None:
            self.restore()
        assert self._projection is not None
        return self._projection

    def append_fill_and_require_reconciled(self, fill: DurableFill) -> AccountingProjection:
        self.ledger.append_fill(fill)
        self._projection = self.ledger.reconstruct()
        self._state = AccountingState.UNRECONCILED
        self._reason = "NEW_ACCOUNTING_EVENT_REQUIRES_RECONCILIATION"
        return self._projection
