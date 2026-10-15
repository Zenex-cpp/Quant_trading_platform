from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from trading_platform.v21.event_store import EventStore, sha256_json


class MarketDataAuthorityState(str, Enum):
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class MarketDataAuthorityConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketDataAuthorityRecord:
    authorization_id: str
    symbol: str
    feed_id: str
    authority_state: MarketDataAuthorityState
    event_time_ms: int
    receive_time_ms: int
    processing_time_ms: int
    observed_at_ms: int
    max_age_ms: int
    valid_from_ms: int
    expires_at_ms: int
    source: str
    sequence_number: int | None

    @property
    def fingerprint(self) -> str:
        return sha256_json({
            "authorization_id": self.authorization_id,
            "symbol": self.symbol,
            "feed_id": self.feed_id,
            "authority_state": self.authority_state.value,
            "event_time_ms": self.event_time_ms,
            "receive_time_ms": self.receive_time_ms,
            "processing_time_ms": self.processing_time_ms,
            "observed_at_ms": self.observed_at_ms,
            "max_age_ms": self.max_age_ms,
            "valid_from_ms": self.valid_from_ms,
            "expires_at_ms": self.expires_at_ms,
            "source": self.source,
            "sequence_number": self.sequence_number,
        })


class MarketDataAuthorityLedger:
    """Durable, fail-closed authority for market-data freshness.

    Realtime ingestion produces evidence; this ledger decides whether that evidence is
    sufficiently fresh for a risk-increasing order. No implicit freshness is assumed.
    """

    RECORDED = "MARKET_DATA_AUTHORIZATION_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def record_observation(
        self,
        *,
        symbol: str,
        feed_id: str,
        event_time_ms: int,
        receive_time_ms: int,
        processing_time_ms: int,
        max_age_ms: int,
        source: str,
        sequence_number: int | None = None,
    ) -> MarketDataAuthorityRecord:
        values = (event_time_ms, receive_time_ms, processing_time_ms, max_age_ms)
        if not symbol or not feed_id or not source:
            raise ValueError("MARKET_DATA_AUTHORITY_FIELDS_REQUIRED")
        if any(v < 0 for v in values) or max_age_ms <= 0:
            raise ValueError("INVALID_MARKET_DATA_AUTHORITY_TIME")
        if receive_time_ms < event_time_ms:
            raise ValueError("MARKET_RECEIVE_BEFORE_EVENT_TIME")
        if processing_time_ms < receive_time_ms:
            raise ValueError("MARKET_PROCESSING_BEFORE_RECEIVE_TIME")
        if sequence_number is not None and sequence_number < 0:
            raise ValueError("INVALID_MARKET_SEQUENCE")

        expires_at_ms = event_time_ms + max_age_ms
        state = (
            MarketDataAuthorityState.VERIFIED
            if processing_time_ms < expires_at_ms
            else MarketDataAuthorityState.EXPIRED
        )
        authorization_id = f"market-auth:{symbol}:{feed_id}:{event_time_ms}:{sequence_number if sequence_number is not None else processing_time_ms}"
        payload = {
            "authorization_id": authorization_id,
            "symbol": symbol,
            "feed_id": feed_id,
            "authority_state": state.value,
            "event_time_ms": event_time_ms,
            "receive_time_ms": receive_time_ms,
            "processing_time_ms": processing_time_ms,
            "observed_at_ms": processing_time_ms,
            "max_age_ms": max_age_ms,
            "valid_from_ms": receive_time_ms,
            "expires_at_ms": expires_at_ms,
            "source": source,
            "sequence_number": sequence_number,
        }
        result = self.store.append(
            event_id=authorization_id,
            occurred_at_ms=processing_time_ms,
            event_type=self.RECORDED,
            aggregate_id=f"{symbol}:{feed_id}",
            payload=payload,
        )
        if result.duplicate and dict(result.event.payload) != payload:
            raise MarketDataAuthorityConflict("MARKET_DATA_AUTHORIZATION_ID_REUSE")
        return self._from_event(result.event.payload)

    def current(self, *, symbol: str, feed_id: str) -> MarketDataAuthorityRecord | None:
        aggregate_id = f"{symbol}:{feed_id}"
        events = [
            e for e in self.store.iter_events()
            if e.event_type == self.RECORDED and e.aggregate_id == aggregate_id
        ]
        return self._from_event(events[-1].payload) if events else None

    def assert_fresh(self, *, symbol: str, now_ms: int, feed_id: str = "primary") -> MarketDataAuthorityRecord:
        if now_ms < 0:
            raise MarketDataAuthorityConflict("INVALID_MARKET_AUTHORITY_CLOCK")
        if not self.store.verify_chain():
            raise MarketDataAuthorityConflict("MARKET_DATA_AUTHORITY_CHAIN_INVALID")
        record = self.current(symbol=symbol, feed_id=feed_id)
        if record is None:
            raise MarketDataAuthorityConflict("MARKET_DATA_AUTHORITY_MISSING")
        if now_ms < record.valid_from_ms:
            raise MarketDataAuthorityConflict("MARKET_DATA_AUTHORITY_NOT_YET_VALID")
        if now_ms >= record.expires_at_ms:
            raise MarketDataAuthorityConflict("MARKET_DATA_STALE")
        if record.authority_state is not MarketDataAuthorityState.VERIFIED:
            raise MarketDataAuthorityConflict(f"MARKET_DATA_AUTHORITY_BLOCKED:{record.authority_state.value}")
        return record

    @staticmethod
    def _from_event(p: Mapping[str, object]) -> MarketDataAuthorityRecord:
        return MarketDataAuthorityRecord(
            authorization_id=str(p["authorization_id"]),
            symbol=str(p["symbol"]),
            feed_id=str(p["feed_id"]),
            authority_state=MarketDataAuthorityState(str(p["authority_state"])),
            event_time_ms=int(p["event_time_ms"]),
            receive_time_ms=int(p["receive_time_ms"]),
            processing_time_ms=int(p["processing_time_ms"]),
            observed_at_ms=int(p["observed_at_ms"]),
            max_age_ms=int(p["max_age_ms"]),
            valid_from_ms=int(p["valid_from_ms"]),
            expires_at_ms=int(p["expires_at_ms"]),
            source=str(p["source"]),
            sequence_number=(None if p.get("sequence_number") is None else int(p["sequence_number"])),
        )
