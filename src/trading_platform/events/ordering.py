"""Deterministic event ordering with fail-closed streaming checks.

Ordering is source-scoped. A stable total order for concurrent sources is a
replay convention; it does not establish causal order between those sources.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, TypeVar

from trading_platform.events.envelope import EventEnvelope


T = TypeVar("T")


def _envelope(event: Any) -> EventEnvelope:
    envelope = event if isinstance(event, EventEnvelope) else getattr(event, "envelope", None)
    if not isinstance(envelope, EventEnvelope):
        raise ValueError("EVENT_ENVELOPE_REQUIRED")
    envelope.validate()
    return envelope


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def event_ordering_key(event: Any) -> tuple[datetime, str, bool, int, datetime, str]:
    """Return the canonical batch/replay key defined by §28."""
    envelope = _envelope(event)
    sequence_missing = envelope.sequence_number is None
    return (
        _utc(envelope.event_time),
        envelope.source,
        sequence_missing,
        envelope.sequence_number if envelope.sequence_number is not None else 0,
        _utc(envelope.receive_time),
        envelope.event_id,
    )


def order_events(events: Iterable[T]) -> tuple[T, ...]:
    """Order a replay batch and reject conflicting per-source chronology."""
    ordered = tuple(sorted(tuple(events), key=event_ordering_key))
    guard = EventStreamOrderGuard()
    for event in ordered:
        guard.observe(event)
    return ordered


@dataclass(frozen=True)
class _SourceCursor:
    event_time: datetime
    receive_time: datetime
    event_id: str
    sequence_number: int | None


class EventStreamOrderGuard:
    """Validate a live source stream without silently reordering late events.

    Instantiate one guard per active process. Its cursor is in-memory and must
    not be treated as durable venue sequencing or as an exactly-once guarantee.
    """

    def __init__(self) -> None:
        self._last_by_source: dict[str, _SourceCursor] = {}
        self._last_sequence_by_source: dict[str, int] = {}
        self._seen_event_ids: set[str] = set()

    def observe(self, event: Any) -> None:
        envelope = _envelope(event)
        if envelope.event_id in self._seen_event_ids:
            raise ValueError("EVENT_ID_REUSE_REQUIRES_IDEMPOTENCY_CONTRACT")

        previous = self._last_by_source.get(envelope.source)
        event_time = _utc(envelope.event_time)
        receive_time = _utc(envelope.receive_time)
        if previous is not None:
            if event_time < previous.event_time:
                raise ValueError("LATE_EVENT_REQUIRES_REPLAY")
            if event_time == previous.event_time:
                current_tie_key = (
                    envelope.sequence_number is None,
                    envelope.sequence_number if envelope.sequence_number is not None else 0,
                    receive_time,
                    envelope.event_id,
                )
                previous_tie_key = (
                    previous.sequence_number is None,
                    previous.sequence_number if previous.sequence_number is not None else 0,
                    previous.receive_time,
                    previous.event_id,
                )
                if current_tie_key < previous_tie_key:
                    raise ValueError("EVENT_TIE_BREAK_ORDER_REGRESSION")

        if envelope.sequence_number is not None:
            last_sequence = self._last_sequence_by_source.get(envelope.source)
            if last_sequence is not None and envelope.sequence_number <= last_sequence:
                if envelope.sequence_number == last_sequence:
                    raise ValueError("EVENT_SEQUENCE_REUSED")
                raise ValueError("OUT_OF_ORDER_EVENT_REQUIRES_REPLAY")

        self._seen_event_ids.add(envelope.event_id)
        self._last_by_source[envelope.source] = _SourceCursor(
            event_time=event_time,
            receive_time=receive_time,
            event_id=envelope.event_id,
            sequence_number=envelope.sequence_number,
        )
        if envelope.sequence_number is not None:
            self._last_sequence_by_source[envelope.source] = envelope.sequence_number
