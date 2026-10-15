from decimal import Decimal
import pytest
from trading_platform.v24.accounting import AccountingSnapshot, CashComponents, PnLView, PnLReconciliation, ReconciliationSeverity, assert_accounting_invariants
from trading_platform.v24.pnl import FillPnLAttribution, PnLLedger

def snap(equity: str, source):
    return AccountingSnapshot(100, Decimal(equity), CashComponents(pnl=Decimal("5"), fees=Decimal("-1")), PnLView(realized=Decimal("5"), fees=Decimal("-1")), source=source)

def test_reconciliation_exact():
    from trading_platform.v24.accounting import AccountingTruth
    r = PnLReconciliation(snap("104", AccountingTruth.LOCAL), snap("104", AccountingTruth.EXCHANGE), snap("104", AccountingTruth.RECONSTRUCTED))
    assert r.classify() is ReconciliationSeverity.EXPECTED
    assert r.exact and r.reconciled

def test_reconciliation_local_only_divergence_is_warning():
    from trading_platform.v24.accounting import AccountingTruth
    r = PnLReconciliation(snap("105", AccountingTruth.LOCAL), snap("104", AccountingTruth.EXCHANGE), snap("104", AccountingTruth.RECONSTRUCTED))
    assert r.classify() is ReconciliationSeverity.WARNING
    assert r.reconciled

def test_exchange_vs_reconstructed_divergence_is_critical():
    from trading_platform.v24.accounting import AccountingTruth
    r = PnLReconciliation(snap("105", AccountingTruth.LOCAL), snap("106", AccountingTruth.EXCHANGE), snap("104", AccountingTruth.RECONSTRUCTED))
    assert r.classify() is ReconciliationSeverity.CRITICAL
    assert not r.reconciled

def test_non_finite_blocked():
    from trading_platform.v24.accounting import AccountingTruth
    s = snap("104", AccountingTruth.LOCAL)
    bad = AccountingSnapshot(s.timestamp_ns, Decimal("NaN"), s.cash, s.pnl, source=s.source)
    with pytest.raises(AssertionError, match="NON_FINITE_ACCOUNTING_VALUE"):
        assert_accounting_invariants(bad)

def test_pnl_attribution_idempotent_and_anti_reuse():
    ledger = PnLLedger()
    a = FillPnLAttribution("f1", "o1", "BTCUSDT", trade_fee=Decimal("-0.2"), funding=Decimal("-0.1"), realized_pnl=Decimal("2"))
    assert ledger.apply(a) == a
    assert ledger.apply(a) == a
    with pytest.raises(ValueError, match="FILL_PNL_ID_REUSE"):
        ledger.apply(FillPnLAttribution("f1", "o1", "BTCUSDT", realized_pnl=Decimal("3")))

def test_cost_aggregation_separates_buckets():
    ledger = PnLLedger()
    ledger.apply(FillPnLAttribution("f1", "o1", "BTCUSDT", trade_fee=Decimal("-1"), funding=Decimal("-2"), slippage=Decimal("-0.5"), realized_pnl=Decimal("5")))
    realized, costs = ledger.aggregate()
    assert realized == Decimal("5")
    assert costs.trade_fee == Decimal("-1")
    assert costs.funding == Decimal("-2")
    assert costs.slippage == Decimal("-0.5")
