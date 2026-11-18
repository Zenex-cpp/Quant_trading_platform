from datetime import datetime, timedelta, timezone

import pytest

from trading_platform.events.envelope import EventEnvelope
from trading_platform.events.ordering import EventStreamOrderGuard, order_events


BASE = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)


def envelope(
    event_id: str,
    *,
    source: str = "venue-a",
    event_offset: int = 0,
    receive_offset: int | None = None,
    sequence: int | None = None,
) -> EventEnvelope:
    effective_receive_offset = event_offset + 1 if receive_offset is None else receive_offset
    return EventEnvelope(
        event_id=event_id,
        event_type="market.tick",
        event_version="1",
        schema_version="1",
        event_time=BASE + timedelta(seconds=event_offset),
        receive_time=BASE + timedelta(seconds=effective_receive_offset),
        processing_time=BASE + timedelta(seconds=effective_receive_offset + 1),
        source=source,
        correlation_id=None,
        sequence_number=sequence,
    )


def test_equal_timestamp_batch_uses_source_sequence_and_event_id():
    events = [
        envelope("a-2", receive_offset=1, sequence=2),
        envelope("b-1", source="venue-b", sequence=1),
        envelope("a-1", receive_offset=2, sequence=1),
    ]
    ordered = order_events(events)
    assert [event.event_id for event in ordered] == ["a-1", "a-2", "b-1"]


def test_source_sequence_orders_equal_exchange_time_when_receive_time_arrives_out_of_order():
    events = [
        envelope("seq-2", receive_offset=1, sequence=2),
        envelope("seq-1", receive_offset=3, sequence=1),
    ]
    assert [event.event_id for event in order_events(events)] == ["seq-1", "seq-2"]


def test_missing_sequence_uses_receive_time_then_event_id():
    events = [
        envelope("later", receive_offset=3),
        envelope("tie-b", receive_offset=2),
        envelope("tie-a", receive_offset=2),
        envelope("earlier", receive_offset=1),
    ]
    ordered = order_events(events)
    assert [event.event_id for event in ordered] == ["earlier", "tie-a", "tie-b", "later"]


def test_batch_rejects_event_time_that_conflicts_with_source_sequence():
    events = [
        envelope("seq-2", event_offset=1, sequence=2),
        envelope("seq-1", event_offset=2, sequence=1),
    ]
    with pytest.raises(ValueError, match="OUT_OF_ORDER_EVENT_REQUIRES_REPLAY"):
        order_events(events)


def test_live_stream_rejects_out_of_order_sequence_and_late_event():
    guard = EventStreamOrderGuard()
    guard.observe(envelope("seq-4", event_offset=2, sequence=4))
    with pytest.raises(ValueError, match="OUT_OF_ORDER_EVENT_REQUIRES_REPLAY"):
        guard.observe(envelope("seq-3", event_offset=3, sequence=3))

    late_guard = EventStreamOrderGuard()
    late_guard.observe(envelope("current", event_offset=5, receive_offset=6))
    with pytest.raises(ValueError, match="LATE_EVENT_REQUIRES_REPLAY"):
        late_guard.observe(envelope("late", event_offset=4, receive_offset=7))


def test_live_stream_rejects_equal_time_tie_break_regression():
    guard = EventStreamOrderGuard()
    guard.observe(envelope("z-event", receive_offset=2))
    with pytest.raises(ValueError, match="EVENT_TIE_BREAK_ORDER_REGRESSION"):
        guard.observe(envelope("a-event", receive_offset=2))


def test_ordering_is_source_scoped_and_duplicate_ids_fail_closed():
    guard = EventStreamOrderGuard()
    guard.observe(envelope("shared-id", source="venue-a", sequence=100))
    guard.observe(envelope("other-source", source="venue-b", sequence=1))
    with pytest.raises(ValueError, match="EVENT_ID_REUSE_REQUIRES_IDEMPOTENCY_CONTRACT"):
        guard.observe(envelope("shared-id", source="venue-c", sequence=1))

    simultaneous = order_events([
        envelope("z", source="venue-z", sequence=1),
        envelope("a", source="venue-a", sequence=90_000),
    ])
    assert [event.source for event in simultaneous] == ["venue-a", "venue-z"]


def test_ordering_requires_valid_envelopes():
    invalid = envelope("invalid", event_offset=2, receive_offset=1)
    with pytest.raises(ValueError, match="RECEIVE_BEFORE_EVENT_TIME"):
        order_events([invalid])
