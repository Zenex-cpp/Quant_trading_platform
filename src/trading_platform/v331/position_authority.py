from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Mapping

from trading_platform.execution.models import OrderAction, PositionState
from trading_platform.v20.reconciliation import ReconciliationResult, ReconciliationState
from trading_platform.v21.event_store import EventStore, sha256_json


class PositionAuthorityState(str, Enum):
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"


class PositionAuthorityConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class PositionAuthorityRecord:
    authorization_id: str
    symbol: str
    position_state: PositionState
    authority_state: PositionAuthorityState
    local_quantity: Decimal
    exchange_quantity: Decimal
    reconciliation_state: ReconciliationState
    reconciliation_hash: str
    observed_at_ms: int
    valid_from_ms: int
    expires_at_ms: int

    @property
    def fingerprint(self) -> str:
        return sha256_json({
            "authorization_id": self.authorization_id,
            "symbol": self.symbol,
            "position_state": self.position_state.value,
            "authority_state": self.authority_state.value,
            "local_quantity": str(self.local_quantity),
            "exchange_quantity": str(self.exchange_quantity),
            "reconciliation_state": self.reconciliation_state.value,
            "reconciliation_hash": self.reconciliation_hash,
            "observed_at_ms": self.observed_at_ms,
            "valid_from_ms": self.valid_from_ms,
            "expires_at_ms": self.expires_at_ms,
        })


class PositionAuthorityLedger:
    """Durable authority translating reconciliation evidence into order-usable position state.

    Reconciliation remains the evidence producer; this ledger is the single persisted
    authority consulted by risk-increasing order paths. No inferred position is accepted.
    """

    AUTHORIZED = "POSITION_AUTHORIZATION_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    def record_reconciliation(
        self,
        *,
        symbol: str,
        local_quantity: Decimal,
        exchange_quantity: Decimal,
        reconciliation: ReconciliationResult,
        observed_at_ms: int,
        ttl_ms: int,
        position_state: PositionState | None = None,
    ) -> PositionAuthorityRecord:
        if not symbol or observed_at_ms < 0 or ttl_ms <= 0:
            raise ValueError("INVALID_POSITION_AUTHORITY_INPUT")
        if not local_quantity.is_finite() or not exchange_quantity.is_finite():
            raise ValueError("NON_FINITE_POSITION")
        if reconciliation.state is ReconciliationState.GREEN and reconciliation.diff.clean:
            authority_state = PositionAuthorityState.VERIFIED
            effective_state = position_state or self._derive_state(local_quantity)
        elif reconciliation.state in {ReconciliationState.RED, ReconciliationState.UNKNOWN, ReconciliationState.BLOCKED}:
            authority_state = PositionAuthorityState.UNKNOWN
            effective_state = PositionState.UNKNOWN
        else:
            authority_state = PositionAuthorityState.UNKNOWN
            effective_state = PositionState.UNKNOWN

        authorization_id = (
            f"position-auth:{symbol}:{reconciliation.snapshot_id if hasattr(reconciliation, 'snapshot_id') else reconciliation.rest_hash}:"
            f"{observed_at_ms}"
        )
        # ReconciliationResult intentionally exposes stable hashes; snapshot identity is reconstructed from them.
        payload = {
            "authorization_id": authorization_id,
            "symbol": symbol,
            "position_state": effective_state.value,
            "authority_state": authority_state.value,
            "local_quantity": str(local_quantity),
            "exchange_quantity": str(exchange_quantity),
            "reconciliation_state": reconciliation.state.value,
            "reconciliation_hash": sha256_json({
                "rest_hash": reconciliation.rest_hash,
                "stream_hash": reconciliation.stream_hash,
                "reason": reconciliation.reason,
                "diff": reconciliation.diff.__dict__,
            }),
            "observed_at_ms": observed_at_ms,
            "valid_from_ms": observed_at_ms,
            "expires_at_ms": observed_at_ms + ttl_ms,
        }
        result = self.store.append(
            event_id=authorization_id,
            occurred_at_ms=observed_at_ms,
            event_type=self.AUTHORIZED,
            aggregate_id=symbol,
            payload=payload,
        )
        if result.duplicate and result.event.payload != payload:
            raise PositionAuthorityConflict("POSITION_AUTHORIZATION_ID_REUSE")
        return self._from_event(result.event.payload)

    def current(self, symbol: str) -> PositionAuthorityRecord | None:
        events = [e for e in self.store.iter_events() if e.event_type == self.AUTHORIZED and e.aggregate_id == symbol]
        return self._from_event(events[-1].payload) if events else None

    def assert_orderable(self, *, symbol: str, action: OrderAction, now_ms: int) -> PositionAuthorityRecord:
        record = self.current(symbol)
        if record is None:
            raise PositionAuthorityConflict("POSITION_AUTHORITY_MISSING")
        if not self.store.verify_chain():
            raise PositionAuthorityConflict("POSITION_AUTHORITY_CHAIN_INVALID")
        if now_ms < record.valid_from_ms or now_ms >= record.expires_at_ms:
            raise PositionAuthorityConflict("POSITION_AUTHORITY_EXPIRED")
        if record.authority_state is not PositionAuthorityState.VERIFIED:
            raise PositionAuthorityConflict(f"POSITION_AUTHORITY_BLOCKED:{record.authority_state.value}")
        if record.position_state is PositionState.UNKNOWN:
            raise PositionAuthorityConflict("POSITION_UNKNOWN_BLOCKS_ORDER")
        # Action-specific local safety: this authority does not invent a close-only bypass;
        # UNKNOWN state is blocked for every order, matching mandatory M3 semantics.
        return record

    @staticmethod
    def _derive_state(quantity: Decimal) -> PositionState:
        return PositionState.FLAT if quantity == 0 else PositionState.OPEN

    @staticmethod
    def _from_event(p: Mapping[str, object]) -> PositionAuthorityRecord:
        return PositionAuthorityRecord(
            authorization_id=str(p["authorization_id"]),
            symbol=str(p["symbol"]),
            position_state=PositionState(str(p["position_state"])),
            authority_state=PositionAuthorityState(str(p["authority_state"])),
            local_quantity=Decimal(str(p["local_quantity"])),
            exchange_quantity=Decimal(str(p["exchange_quantity"])),
            reconciliation_state=ReconciliationState(str(p["reconciliation_state"])),
            reconciliation_hash=str(p["reconciliation_hash"]),
            observed_at_ms=int(p["observed_at_ms"]),
            valid_from_ms=int(p["valid_from_ms"]),
            expires_at_ms=int(p["expires_at_ms"]),
        )
