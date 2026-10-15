from pathlib import Path

import pytest

from trading_platform.v313.durable_correlation import (
    CorrelationConflict,
    DurableExecutionCorrelationStore,
    RestartSafeCorrelation,
)


def test_registration_and_bidirectional_binding_survives_restart(tmp_path: Path):
    db = str(tmp_path / "corr.db")
    s1 = DurableExecutionCorrelationStore(db)
    c1 = RestartSafeCorrelation(s1)
    c1.register(intent_id="i1", order_request_id="r1", client_order_id="cid-1", now_epoch=1.0)
    c1.bind_exchange(intent_id="i1", exchange_order_id="ex-77", now_epoch=2.0)
    s1.close()

    s2 = DurableExecutionCorrelationStore(db)
    c2 = RestartSafeCorrelation(s2)
    by_client = c2.correlate(client_order_id="cid-1", exchange_order_id=None)
    by_exchange = c2.correlate(client_order_id=None, exchange_order_id="ex-77")
    assert by_client and by_client.intent_id == "i1"
    assert by_exchange and by_exchange.intent_id == "i1"
    assert by_exchange.order_request_id == "r1"
    s2.close()


def test_conflicting_exchange_binding_fails_closed(tmp_path: Path):
    s = DurableExecutionCorrelationStore(str(tmp_path / "corr.db"))
    c = RestartSafeCorrelation(s)
    c.register(intent_id="i1", order_request_id="r1", client_order_id="cid-1", now_epoch=1.0)
    c.register(intent_id="i2", order_request_id="r2", client_order_id="cid-2", now_epoch=1.0)
    c.bind_exchange(intent_id="i1", exchange_order_id="ex-77", now_epoch=2.0)
    with pytest.raises(CorrelationConflict, match="EXCHANGE_ORDER_ID_CORRELATION_CONFLICT"):
        c.bind_exchange(intent_id="i2", exchange_order_id="ex-77", now_epoch=3.0)
    s.close()


def test_event_journal_is_idempotent_and_persists_evidence(tmp_path: Path):
    db = str(tmp_path / "corr.db")
    s = DurableExecutionCorrelationStore(db)
    c = RestartSafeCorrelation(s)
    rec = c.register(intent_id="i1", order_request_id="r1", client_order_id="cid-1", now_epoch=1.0)
    c.bind_exchange(intent_id="i1", exchange_order_id="ex-77", now_epoch=2.0)
    rec = c.correlate(client_order_id="cid-1", exchange_order_id="ex-77")
    assert c.journal(event_id="evt-1", record=rec, event_type="ORDER_TRADE_UPDATE", raw_hash="h1", observed_at_epoch=3.0, payload={"X":"NEW"})
    assert not c.journal(event_id="evt-1", record=rec, event_type="ORDER_TRADE_UPDATE", raw_hash="h1", observed_at_epoch=3.0, payload={"X":"NEW"})
    assert s.count_events() == 1
    rows = s.events_for_intent("i1")
    assert rows[0].exchange_order_id == "ex-77"
    assert rows[0].client_order_id == "cid-1"
    s.close()


def test_unknown_event_can_be_journaled_without_inventing_intent(tmp_path: Path):
    s = DurableExecutionCorrelationStore(str(tmp_path / "corr.db"))
    c = RestartSafeCorrelation(s)
    assert c.journal(event_id="evt-unknown", record=None, event_type="ORDER_TRADE_UPDATE", raw_hash="h2", observed_at_epoch=4.0, payload={"c":"unknown","i":99})
    row = s.events_for_intent("missing")
    assert row == ()
    assert s.count_events() == 1
    s.close()
