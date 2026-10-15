from decimal import Decimal
import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.v315 import DurableAccountingLedger, DurableFill
from trading_platform.v316 import AccountingGateDenied, AccountingState, DurableAccountingAuthority


def mkledger(tmp_path):
    ledger = DurableAccountingLedger(EventStore(str(tmp_path / "accounting.db")))
    ledger.append_fill(DurableFill("f1", "o1", "BTCUSDT", "BUY", Decimal("1"), Decimal("100")))
    return ledger


def test_restore_is_unreconciled_and_blocks_new_risk(tmp_path):
    authority = DurableAccountingAuthority(mkledger(tmp_path))
    snap = authority.restore()
    assert snap.state is AccountingState.UNRECONCILED
    with pytest.raises(AccountingGateDenied, match="ACCOUNTING_NOT_ALLOWED"):
        authority.assert_new_risk_allowed()


def test_explicit_reconciliation_opens_gate(tmp_path):
    authority = DurableAccountingAuthority(mkledger(tmp_path))
    authority.restore()
    snap = authority.mark_reconciled(evidence_id="recon-1")
    assert snap.allows_new_risk
    authority.assert_new_risk_allowed()


def test_unknown_and_new_event_close_gate_monotonically(tmp_path):
    authority = DurableAccountingAuthority(mkledger(tmp_path))
    authority.restore()
    authority.mark_reconciled(evidence_id="recon-1")
    authority.mark_unknown(reason="EXCHANGE_EQUITY_MISMATCH")
    with pytest.raises(AccountingGateDenied):
        authority.assert_new_risk_allowed()
    authority.append_fill_and_require_reconciled(
        DurableFill("f2", "o2", "BTCUSDT", "SELL", Decimal("1"), Decimal("101"))
    )
    assert authority.snapshot().state is AccountingState.UNRECONCILED
