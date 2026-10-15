from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import hashlib
import json

class ReconciliationSeverity(str, Enum):
    EXPECTED = "EXPECTED"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

class AccountingTruth(str, Enum):
    LOCAL = "LOCAL"
    EXCHANGE = "EXCHANGE"
    RECONSTRUCTED = "RECONSTRUCTED"

@dataclass(frozen=True)
class CashComponents:
    pnl: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    deposits_withdrawals: Decimal = Decimal("0")
    other_events: Decimal = Decimal("0")

    @property
    def equity_change(self) -> Decimal:
        return self.pnl + self.fees + self.funding + self.deposits_withdrawals + self.other_events

@dataclass(frozen=True)
class PnLView:
    realized: Decimal = Decimal("0")
    unrealized: Decimal = Decimal("0")
    fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    execution_impact: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    market_impact: Decimal = Decimal("0")
    carrying_cost: Decimal = Decimal("0")

    @property
    def net_pnl(self) -> Decimal:
        return self.realized + self.unrealized + self.fees + self.funding

@dataclass(frozen=True)
class AccountingSnapshot:
    timestamp_ns: int
    equity: Decimal
    cash: CashComponents
    pnl: PnLView
    position_notional: Decimal = Decimal("0")
    margin_used: Decimal = Decimal("0")
    source: AccountingTruth = AccountingTruth.RECONSTRUCTED

    def canonical_payload(self) -> dict:
        return {
            "timestamp_ns": self.timestamp_ns,
            "equity": str(self.equity),
            "cash": {
                "pnl": str(self.cash.pnl), "fees": str(self.cash.fees),
                "funding": str(self.cash.funding), "deposits_withdrawals": str(self.cash.deposits_withdrawals),
                "other_events": str(self.cash.other_events),
            },
            "pnl": {k: str(getattr(self.pnl, k)) for k in (
                "realized", "unrealized", "fees", "funding", "execution_impact",
                "slippage", "market_impact", "carrying_cost"
            )},
            "position_notional": str(self.position_notional),
            "margin_used": str(self.margin_used),
            "source": self.source.value,
        }

    @property
    def state_hash(self) -> str:
        raw = json.dumps(self.canonical_payload(), sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(raw).hexdigest()

@dataclass(frozen=True)
class PnLReconciliation:
    local: AccountingSnapshot
    exchange: AccountingSnapshot
    reconstructed: AccountingSnapshot
    equity_tolerance: Decimal = Decimal("0.00000001")
    pnl_tolerance: Decimal = Decimal("0.00000001")

    def _close(self, a: Decimal, b: Decimal, tolerance: Decimal) -> bool:
        return abs(a - b) <= tolerance

    def classify(self) -> ReconciliationSeverity:
        exchange_vs_reconstructed = self._close(self.exchange.equity, self.reconstructed.equity, self.equity_tolerance)
        local_vs_reconstructed = self._close(self.local.equity, self.reconstructed.equity, self.equity_tolerance)
        if exchange_vs_reconstructed and local_vs_reconstructed:
            return ReconciliationSeverity.EXPECTED
        if exchange_vs_reconstructed and not local_vs_reconstructed:
            return ReconciliationSeverity.WARNING
        return ReconciliationSeverity.CRITICAL

    @property
    def reconciled(self) -> bool:
        return self.classify() != ReconciliationSeverity.CRITICAL

    @property
    def exact(self) -> bool:
        return self.classify() == ReconciliationSeverity.EXPECTED

    def discrepancies(self) -> dict[str, str]:
        return {
            "local_vs_exchange": str(self.local.equity - self.exchange.equity),
            "local_vs_reconstructed": str(self.local.equity - self.reconstructed.equity),
            "exchange_vs_reconstructed": str(self.exchange.equity - self.reconstructed.equity),
        }

def reconstruct_equity(*, opening_equity: Decimal, change: CashComponents) -> Decimal:
    return opening_equity + change.equity_change


def assert_accounting_invariants(snapshot: AccountingSnapshot) -> None:
    values = [snapshot.equity, snapshot.cash.equity_change, snapshot.pnl.net_pnl,
              snapshot.pnl.fees, snapshot.pnl.funding]
    if any(not v.is_finite() for v in values):
        raise AssertionError("NON_FINITE_ACCOUNTING_VALUE")
    if snapshot.timestamp_ns < 0:
        raise AssertionError("INVALID_ACCOUNTING_TIMESTAMP")
    if snapshot.position_notional < 0 or snapshot.margin_used < 0:
        raise AssertionError("NEGATIVE_RISK_BALANCE")
