from decimal import Decimal
import pytest
from trading_platform.accounting.invariants import assert_equity_reconciliation

def test_accounting_reconciles():
    assert_equity_reconciliation(Decimal("105"), pnl=Decimal("120"), fees=Decimal("-5"), funding=Decimal("-2"), deposits_withdrawals=Decimal("-8")) is None

def test_accounting_mismatch_fails():
    with pytest.raises(AssertionError):
        assert_equity_reconciliation(Decimal("104"), pnl=Decimal("120"), fees=Decimal("-5"), funding=Decimal("-2"), deposits_withdrawals=Decimal("-8"))
