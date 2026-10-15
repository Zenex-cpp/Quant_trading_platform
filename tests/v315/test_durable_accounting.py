from decimal import Decimal

import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v315 import (
    AccountingConflict,
    AccountingReplayError,
    AccountingReconciliation,
    DurableAccountingLedger,
    DurableFill,
    ExchangeAccountingSnapshot,
    RestartSafeAccountingRegistry,
    prove_recovery,
)


def fill(fid, oid, side, qty, price, fee="0", funding="0"):
    return DurableFill(fid, oid, "BTCUSDT", side, Decimal(qty), Decimal(price), Decimal(fee), Decimal(funding), 1000)


def test_persists_and_replays_position_after_restart(tmp_path):
    path = tmp_path / "accounting.db"
    ledger = DurableAccountingLedger(EventStore(str(path)))
    ledger.append_fill(fill("f1", "o1", "BUY", "1", "100", "1", "0.2"))
    ledger.append_fill(fill("f2", "o2", "SELL", "0.4", "110", "0.4", "0"))
    state1 = ledger.reconstruct()

    ledger2 = DurableAccountingLedger(EventStore(str(path)))
    state2 = RestartSafeAccountingRegistry(ledger2).restore()

    assert state1 == state2
    p = state2.positions[0]
    assert p.quantity == Decimal("0.6")
    assert p.avg_entry_price == Decimal("100")
    assert p.realized_pnl == Decimal("4")
    assert p.fees == Decimal("1.4")
    assert p.funding == Decimal("0.2")
    assert state2.cash == Decimal("-1.2")


def test_duplicate_fill_is_idempotent_and_conflict_is_blocked(tmp_path):
    path = tmp_path / "accounting.db"
    ledger = DurableAccountingLedger(EventStore(str(path)))
    first = ledger.append_fill(fill("f1", "o1", "BUY", "1", "100"))
    second = ledger.append_fill(fill("f1", "o1", "BUY", "1", "100"))
    assert first.event_hash == second.event_hash
    with pytest.raises(Exception):
        ledger.append_fill(fill("f1", "o1", "BUY", "2", "100"))


def test_restart_recovery_proof_is_deterministic(tmp_path):
    path = tmp_path / "accounting.db"
    ledger = DurableAccountingLedger(EventStore(str(path)))
    ledger.append_fill(fill("f1", "o1", "BUY", "2", "100"))
    state, proof = prove_recovery(ledger)
    state2, proof2 = prove_recovery(DurableAccountingLedger(EventStore(str(path))))
    assert proof.passed and proof2.passed
    assert state.state_hash == state2.state_hash == proof.state_hash == proof2.state_hash


def test_invalid_event_chain_fails_closed(tmp_path):
    path = tmp_path / "accounting.db"
    store = EventStore(str(path))
    ledger = DurableAccountingLedger(store)
    ledger.append_fill(fill("f1", "o1", "BUY", "1", "100"))
    tamper_event_store(store, "UPDATE events SET payload_json='{}' WHERE event_id='fill:f1'")
    with pytest.raises(AccountingReplayError, match="EVENT_CHAIN_INVALID"):
        ledger.reconstruct()


def test_exchange_reconciliation_requires_equity_and_positions(tmp_path):
    ledger = DurableAccountingLedger(EventStore(str(tmp_path / "accounting.db")))
    ledger.append_fill(fill("f1", "o1", "BUY", "1", "100", "1"))
    state = ledger.reconstruct()
    recon = AccountingReconciliation(
        reconstructed=state,
        exchange=ExchangeAccountingSnapshot(equity=Decimal("-1"), positions={"BTCUSDT": Decimal("1")}, snapshot_id="x1"),
        equity_expected=Decimal("-1"),
    )
    assert recon.reconciled
    bad = AccountingReconciliation(
        reconstructed=state,
        exchange=ExchangeAccountingSnapshot(equity=Decimal("0"), positions={"BTCUSDT": Decimal("2")}, snapshot_id="x2"),
        equity_expected=Decimal("-1"),
    )
    assert not bad.reconciled
