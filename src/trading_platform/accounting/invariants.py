from decimal import Decimal


def equity_change(*, pnl: Decimal, fees: Decimal, funding: Decimal, deposits_withdrawals: Decimal, other_events: Decimal = Decimal("0")) -> Decimal:
    return pnl + fees + funding + deposits_withdrawals + other_events


def assert_equity_reconciliation(actual_change: Decimal, *, pnl: Decimal, fees: Decimal, funding: Decimal, deposits_withdrawals: Decimal, other_events: Decimal = Decimal("0")) -> None:
    expected = equity_change(pnl=pnl, fees=fees, funding=funding, deposits_withdrawals=deposits_withdrawals, other_events=other_events)
    if actual_change != expected:
        raise AssertionError(f"EQUITY_MISMATCH expected={expected} actual={actual_change}")
