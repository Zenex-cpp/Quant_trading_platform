from decimal import Decimal
import pytest

from trading_platform.execution.models import OrderAction, PositionState
from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v331 import PositionAuthorityConflict, PositionAuthorityLedger, PositionAuthorityState


def recon(state=ReconciliationState.GREEN, diff=None):
    return ReconciliationResult(
        state, diff or ReconciliationDiff(),
        "rest-hash", "stream-hash", "REST_WS_MATCH" if state is ReconciliationState.GREEN else "REST_WS_DIVERGENCE",
    )

def seed(**kwargs):
    ledger = PositionAuthorityLedger()
    ledger.record_reconciliation(
        symbol=kwargs.get("symbol", "BTCUSDT"),
        local_quantity=kwargs.get("local", Decimal("0")),
        exchange_quantity=kwargs.get("exchange", Decimal("0")),
        reconciliation=kwargs.get("reconciliation", recon()),
        observed_at_ms=1000, ttl_ms=1000,
        position_state=kwargs.get("position_state"),
    )
    return ledger

def test_green_reconciliation_creates_orderable_authority():
    ledger = seed()
    rec = ledger.assert_orderable(symbol="BTCUSDT", action=OrderAction.OPEN, now_ms=1500)
    assert rec.authority_state is PositionAuthorityState.VERIFIED
    assert rec.position_state is PositionState.FLAT

def test_mismatched_reconciliation_is_unknown_and_blocks_order():
    diff = ReconciliationDiff(position_mismatches=("BTCUSDT",))
    ledger = seed(reconciliation=recon(ReconciliationState.RED, diff))
    with pytest.raises(PositionAuthorityConflict, match="POSITION_AUTHORITY_BLOCKED:UNKNOWN"):
        ledger.assert_orderable(symbol="BTCUSDT", action=OrderAction.OPEN, now_ms=1500)

def test_stale_authority_blocks_order():
    ledger = seed()
    with pytest.raises(PositionAuthorityConflict, match="POSITION_AUTHORITY_EXPIRED"):
        ledger.assert_orderable(symbol="BTCUSDT", action=OrderAction.OPEN, now_ms=2000)

def test_unknown_position_state_blocks_order_even_with_green_reconciliation():
    ledger = seed(position_state=PositionState.UNKNOWN)
    with pytest.raises(PositionAuthorityConflict, match="POSITION_UNKNOWN_BLOCKS_ORDER"):
        ledger.assert_orderable(symbol="BTCUSDT", action=OrderAction.OPEN, now_ms=1500)

def test_missing_symbol_authority_fails_closed():
    ledger = seed()
    with pytest.raises(PositionAuthorityConflict, match="POSITION_AUTHORITY_MISSING"):
        ledger.assert_orderable(symbol="ETHUSDT", action=OrderAction.OPEN, now_ms=1500)

def test_restart_reconstructs_authority():
    store = EventStore()
    ledger = PositionAuthorityLedger(store)
    ledger.record_reconciliation(
        symbol="BTCUSDT", local_quantity=Decimal("0"), exchange_quantity=Decimal("0"),
        reconciliation=recon(), observed_at_ms=1000, ttl_ms=1000, position_state=PositionState.FLAT,
    )
    reloaded = PositionAuthorityLedger(store)
    assert reloaded.assert_orderable(symbol="BTCUSDT", action=OrderAction.OPEN, now_ms=1500).position_state is PositionState.FLAT

def test_chain_corruption_blocks_order_authority():
    store = EventStore()
    ledger = PositionAuthorityLedger(store)
    ledger.record_reconciliation(
        symbol="BTCUSDT", local_quantity=Decimal("0"), exchange_quantity=Decimal("0"),
        reconciliation=recon(), observed_at_ms=1000, ttl_ms=1000, position_state=PositionState.FLAT,
    )
    tamper_event_store(store, "UPDATE events SET event_hash='corrupted' WHERE sequence=1")
    with pytest.raises(PositionAuthorityConflict, match="POSITION_AUTHORITY_CHAIN_INVALID"):
        ledger.assert_orderable(symbol="BTCUSDT", action=OrderAction.OPEN, now_ms=1500)

def test_duplicate_same_authorization_is_idempotent():
    store = EventStore()
    ledger = PositionAuthorityLedger(store)
    r = recon()
    a = dict(symbol="BTCUSDT", local_quantity=Decimal("0"), exchange_quantity=Decimal("0"), reconciliation=r, observed_at_ms=1000, ttl_ms=1000, position_state=PositionState.FLAT)
    first = ledger.record_reconciliation(**a)
    second = ledger.record_reconciliation(**a)
    assert first.fingerprint == second.fingerprint
    assert store.latest_sequence() == 1
