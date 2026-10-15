from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import pytest
from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderIntent, OrderAction, OrderType, Side
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v319 import DurableOrderIntentLedger, OrderIntentConflict, OrderIntentReplayError

NOW=datetime(2026,9,18,tzinfo=timezone.utc)

def intent(q=Decimal("0.001")):
    return OrderIntent("I319","D319","P319","R319","S319","M319","E319","BTCUSDT",Side.BUY,OrderAction.OPEN,q,OrderType.MARKET,ValidWindow(NOW,NOW+timedelta(minutes=5)),risk_reservation_id="RR319")

def test_record_restart_restore(tmp_path: Path):
    path=str(tmp_path/"intent.db")
    DurableOrderIntentLedger(EventStore(path)).record(intent(), recorded_at_ms=1)
    restored=DurableOrderIntentLedger(EventStore(path)).get("I319")
    assert restored is not None and restored.intent == intent()

def test_same_id_different_payload_is_rejected(tmp_path: Path):
    ledger=DurableOrderIntentLedger(EventStore(str(tmp_path/"i.db")))
    ledger.record(intent(), recorded_at_ms=1)
    with pytest.raises(OrderIntentConflict, match="PAYLOAD_CONFLICT"):
        ledger.record(intent(Decimal("0.002")), recorded_at_ms=2)

def test_missing_intent_is_not_authoritative(tmp_path: Path):
    ledger=DurableOrderIntentLedger(EventStore(str(tmp_path/"i.db")))
    with pytest.raises(OrderIntentConflict, match="NOT_FOUND"):
        ledger.assert_matches(intent())

def test_corrupt_chain_is_detected(tmp_path: Path):
    ledger=DurableOrderIntentLedger(EventStore(str(tmp_path/"i.db")))
    ledger.record(intent(), recorded_at_ms=1)
    tamper_event_store(ledger.store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}','order-intent:record:I319'))
    with pytest.raises(OrderIntentReplayError, match="CHAIN_INVALID"):
        ledger.restore()
