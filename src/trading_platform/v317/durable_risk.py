from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping

from trading_platform.risk.budget import BudgetScope
from trading_platform.v21.event_store import EventStore, LedgerEvent


class RiskReservationConflict(RuntimeError):
    """Persisted reservation state cannot safely satisfy the requested operation."""


class RiskReservationReplayError(RuntimeError):
    """Durable risk-reservation history cannot be reconstructed safely."""


class RiskReservationState(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    OVERRIDDEN = "OVERRIDDEN"


@dataclass(frozen=True)
class RiskReservationRecord:
    reservation_id: str
    scope: BudgetScope
    requested: Decimal
    allowed: Decimal
    intent_id: str
    risk_decision_id: str
    accounting_projection_hash: str
    created_at_ms: int
    expires_at_ms: int | None = None

    def payload(self) -> dict[str, str | int | None]:
        return {
            "reservation_id": self.reservation_id,
            "scope": self.scope.value,
            "requested": str(self.requested),
            "allowed": str(self.allowed),
            "intent_id": self.intent_id,
            "risk_decision_id": self.risk_decision_id,
            "accounting_projection_hash": self.accounting_projection_hash,
            "created_at_ms": self.created_at_ms,
            "expires_at_ms": self.expires_at_ms,
        }


@dataclass(frozen=True)
class RiskReservationSnapshot:
    record: RiskReservationRecord
    state: RiskReservationState
    terminal_reason: str | None = None
    consumed_at_ms: int | None = None


@dataclass(frozen=True)
class RiskBudgetProjection:
    allocated: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")
    consumed: Decimal = Decimal("0")
    released: Decimal = Decimal("0")
    expired: Decimal = Decimal("0")
    overridden: Decimal = Decimal("0")

    @property
    def remaining(self) -> Decimal:
        # Released/expired/overridden are audit counters. Their amounts have already
        # left `reserved`, so adding them again would double-credit available risk.
        return self.allocated - self.reserved - self.consumed


class DurableRiskReservationBook:
    """SQLite-backed append-only risk reservation ledger with deterministic replay.

    A reservation is bound to the exact intent, risk decision and accounting projection
    that justified it. Consumption is persisted before external transport and is never
    retried blindly after a restart.
    """

    BUDGET_INIT = "RISK_BUDGET_INIT"
    RESERVED = "RISK_RESERVED"
    CONSUMED = "RISK_CONSUMED"
    RELEASED = "RISK_RELEASED"
    EXPIRED = "RISK_EXPIRED"
    OVERRIDDEN = "RISK_OVERRIDDEN"

    def __init__(self, store: EventStore | None = None, *, allocated: Decimal = Decimal("0")) -> None:
        self.store = store or EventStore()
        self._configured_allocated = self._validate_amount(allocated, "INVALID_ALLOCATED_BUDGET")
        self._ensure_budget_init()

    @property
    def projection(self) -> RiskBudgetProjection:
        if not self.store.verify_chain():
            raise RiskReservationReplayError("RISK_EVENT_CHAIN_INVALID")
        state = RiskBudgetProjection()
        reservations: dict[str, RiskReservationSnapshot] = {}
        for event in self.store.iter_events():
            try:
                if event.event_type == self.BUDGET_INIT:
                    allocation = self._decimal(event.payload.get("allocated"), "INVALID_ALLOCATED_BUDGET_EVENT")
                    if state.allocated != Decimal("0") and state.allocated != allocation:
                        raise RiskReservationReplayError("BUDGET_ALLOCATION_CONFLICT")
                    state = RiskBudgetProjection(allocation, state.reserved, state.consumed, state.released, state.expired, state.overridden)
                elif event.event_type == self.RESERVED:
                    record = self._record_from_payload(event.payload)
                    if record.reservation_id in reservations:
                        raise RiskReservationReplayError("DUPLICATE_RESERVATION_ID")
                    if record.allowed > state.remaining:
                        raise RiskReservationReplayError("RISK_BUDGET_OVERDRAWN")
                    state = RiskBudgetProjection(state.allocated, state.reserved + record.allowed, state.consumed, state.released, state.expired, state.overridden)
                    reservations[record.reservation_id] = RiskReservationSnapshot(record, RiskReservationState.RESERVED)
                elif event.event_type in {self.CONSUMED, self.RELEASED, self.EXPIRED, self.OVERRIDDEN}:
                    rid = str(event.payload.get("reservation_id", ""))
                    current = reservations.get(rid)
                    if current is None:
                        raise RiskReservationReplayError("TERMINAL_RESERVATION_WITHOUT_RESERVE")
                    target = self._terminal_state(event.event_type)
                    if current.state is not RiskReservationState.RESERVED:
                        raise RiskReservationReplayError("RESERVATION_DOUBLE_TERMINAL_TRANSITION")
                    amt = current.record.allowed
                    if target is RiskReservationState.CONSUMED:
                        state = RiskBudgetProjection(state.allocated, state.reserved - amt, state.consumed + amt, state.released, state.expired, state.overridden)
                    elif target is RiskReservationState.RELEASED:
                        state = RiskBudgetProjection(state.allocated, state.reserved - amt, state.consumed, state.released + amt, state.expired, state.overridden)
                    elif target is RiskReservationState.EXPIRED:
                        state = RiskBudgetProjection(state.allocated, state.reserved - amt, state.consumed, state.released, state.expired + amt, state.overridden)
                    else:
                        state = RiskBudgetProjection(state.allocated, state.reserved - amt, state.consumed, state.released, state.expired, state.overridden + amt)
                    reservations[rid] = RiskReservationSnapshot(current.record, target, str(event.payload.get("reason", "")) or None,
                                                                  event.occurred_at_ms if target is RiskReservationState.CONSUMED else None)
                else:
                    raise RiskReservationReplayError(f"UNKNOWN_RISK_EVENT_TYPE:{event.event_type}")
            except RiskReservationReplayError:
                raise
            except Exception as exc:
                raise RiskReservationReplayError("INVALID_RISK_EVENT") from exc
        if state.remaining < 0:
            raise RiskReservationReplayError("NEGATIVE_RISK_REMAINING")
        return state

    def reservations(self) -> tuple[RiskReservationSnapshot, ...]:
        self._replay_reservations()
        out: list[RiskReservationSnapshot] = []
        for event in self.store.iter_events():
            if event.event_type != self.RESERVED:
                continue
            record = self._record_from_payload(event.payload)
            out.append(self._snapshot_for(record.reservation_id))
        unique = {s.record.reservation_id: s for s in out}
        return tuple(unique[k] for k in sorted(unique))

    def reserve(self, record: RiskReservationRecord) -> RiskReservationSnapshot:
        self._validate_record(record)
        prior = self._safe_get(record.reservation_id)
        if prior is not None:
            if prior.record != record:
                raise RiskReservationConflict("RESERVATION_ID_PAYLOAD_CONFLICT")
            return prior
        projection = self.projection
        if record.allowed > projection.remaining:
            raise RiskReservationConflict("RISK_BUDGET_EXCEEDED")
        event = self.store.append(
            event_id=f"risk:reserve:{record.reservation_id}",
            occurred_at_ms=record.created_at_ms,
            event_type=self.RESERVED,
            aggregate_id=record.reservation_id,
            payload=record.payload(),
        )
        if event.duplicate:
            return self._snapshot_for(record.reservation_id)
        return RiskReservationSnapshot(record, RiskReservationState.RESERVED)

    def consume(self, reservation_id: str, *, intent_id: str, risk_decision_id: str,
                requested_risk: Decimal, accounting_projection_hash: str, occurred_at_ms: int,
                reason: str = "PRE_TRANSPORT_RISK_COMMIT") -> RiskReservationSnapshot:
        current = self._required(reservation_id)
        self._validate_binding(current.record, intent_id, risk_decision_id, requested_risk, accounting_projection_hash)
        if current.record.expires_at_ms is not None and occurred_at_ms >= current.record.expires_at_ms:
            raise RiskReservationConflict("RESERVATION_EXPIRED")
        if current.state is not RiskReservationState.RESERVED:
            raise RiskReservationConflict(f"RESERVATION_NOT_CONSUMABLE:{current.state.value}")
        try:
            self.store.append_exclusive(
                event_id=f"risk:consume:{reservation_id}",
                occurred_at_ms=occurred_at_ms,
                event_type=self.CONSUMED,
                aggregate_id=reservation_id,
                payload={"reservation_id": reservation_id, "reason": reason},
                exclusive_event_types=(self.CONSUMED, self.RELEASED, self.EXPIRED, self.OVERRIDDEN),
            )
        except RuntimeError as exc:
            marker = str(exc)
            if marker.startswith("EXCLUSIVE_AGGREGATE_TERMINAL:"):
                terminal = marker.rsplit(":", 1)[-1]
                raise RiskReservationConflict(f"RESERVATION_TERMINAL_CONFLICT:{terminal}") from exc
            raise RiskReservationConflict(marker) from exc
        return self._snapshot_for(reservation_id)

    def release(self, reservation_id: str, *, reason: str, occurred_at_ms: int) -> RiskReservationSnapshot:
        current = self._required(reservation_id)
        if current.state is not RiskReservationState.RESERVED:
            raise RiskReservationConflict(f"RESERVATION_NOT_RELEASABLE:{current.state.value}")
        if not reason:
            raise ValueError("RISK_RELEASE_REASON_REQUIRED")
        try:
            self.store.append_exclusive(
                event_id=f"risk:release:{reservation_id}", occurred_at_ms=occurred_at_ms,
                event_type=self.RELEASED, aggregate_id=reservation_id,
                payload={"reservation_id": reservation_id, "reason": reason},
                exclusive_event_types=(self.CONSUMED, self.RELEASED, self.EXPIRED, self.OVERRIDDEN),
            )
        except RuntimeError as exc:
            raise RiskReservationConflict(str(exc)) from exc
        return self._snapshot_for(reservation_id)

    def expire(self, reservation_id: str, *, occurred_at_ms: int, reason: str = "RESERVATION_EXPIRED") -> RiskReservationSnapshot:
        current = self._required(reservation_id)
        if current.state is not RiskReservationState.RESERVED:
            raise RiskReservationConflict(f"RESERVATION_NOT_EXPIRABLE:{current.state.value}")
        try:
            self.store.append_exclusive(
                event_id=f"risk:expire:{reservation_id}", occurred_at_ms=occurred_at_ms,
                event_type=self.EXPIRED, aggregate_id=reservation_id,
                payload={"reservation_id": reservation_id, "reason": reason},
                exclusive_event_types=(self.CONSUMED, self.RELEASED, self.EXPIRED, self.OVERRIDDEN),
            )
        except RuntimeError as exc:
            raise RiskReservationConflict(str(exc)) from exc
        return self._snapshot_for(reservation_id)

    def override(self, reservation_id: str, *, reason: str, occurred_at_ms: int) -> RiskReservationSnapshot:
        current = self._required(reservation_id)
        if current.state is not RiskReservationState.RESERVED:
            raise RiskReservationConflict(f"RESERVATION_NOT_OVERRIDABLE:{current.state.value}")
        if not reason:
            raise ValueError("RISK_OVERRIDE_REASON_REQUIRED")
        try:
            self.store.append_exclusive(
                event_id=f"risk:override:{reservation_id}", occurred_at_ms=occurred_at_ms,
                event_type=self.OVERRIDDEN, aggregate_id=reservation_id,
                payload={"reservation_id": reservation_id, "reason": reason},
                exclusive_event_types=(self.CONSUMED, self.RELEASED, self.EXPIRED, self.OVERRIDDEN),
            )
        except RuntimeError as exc:
            raise RiskReservationConflict(str(exc)) from exc
        return self._snapshot_for(reservation_id)

    def _ensure_budget_init(self) -> None:
        first = next(self.store.iter_events(), None)
        if first is None:
            self.store.append(
                event_id="risk:budget:init",
                occurred_at_ms=0,
                event_type=self.BUDGET_INIT,
                aggregate_id="RISK_BUDGET",
                payload={"allocated": str(self._configured_allocated)},
            )
            return
        if first.event_type != self.BUDGET_INIT:
            raise RiskReservationReplayError("RISK_BUDGET_INIT_MISSING")
        persisted = self._decimal(first.payload.get("allocated"), "INVALID_ALLOCATED_BUDGET_EVENT")
        if persisted != self._configured_allocated:
            raise RiskReservationConflict("BUDGET_ALLOCATION_CHANGED")

    def _replay_reservations(self) -> dict[str, RiskReservationSnapshot]:
        self.projection
        out: dict[str, RiskReservationSnapshot] = {}
        for event in self.store.iter_events():
            if event.event_type == self.RESERVED:
                record = self._record_from_payload(event.payload)
                out[record.reservation_id] = RiskReservationSnapshot(record, RiskReservationState.RESERVED)
            elif event.event_type in {self.CONSUMED, self.RELEASED, self.EXPIRED, self.OVERRIDDEN}:
                rid = str(event.payload.get("reservation_id", ""))
                prior = out[rid]
                state = self._terminal_state(event.event_type)
                out[rid] = RiskReservationSnapshot(prior.record, state,
                                                   str(event.payload.get("reason", "")) or None,
                                                   event.occurred_at_ms if state is RiskReservationState.CONSUMED else None)
        return out

    def _safe_get(self, reservation_id: str) -> RiskReservationSnapshot | None:
        try:
            return self._snapshot_for(reservation_id)
        except KeyError:
            return None

    def _required(self, reservation_id: str) -> RiskReservationSnapshot:
        snap = self._safe_get(reservation_id)
        if snap is None:
            raise RiskReservationConflict("RESERVATION_NOT_FOUND")
        return snap

    def _snapshot_for(self, reservation_id: str) -> RiskReservationSnapshot:
        reservations = self._replay_reservations()
        return reservations[reservation_id]

    def _validate_record(self, record: RiskReservationRecord) -> None:
        if not record.reservation_id or not record.intent_id or not record.risk_decision_id:
            raise ValueError("INVALID_RISK_RESERVATION_IDENTITY")
        if not record.accounting_projection_hash:
            raise ValueError("RISK_ACCOUNTING_HASH_REQUIRED")
        if record.requested < 0 or record.allowed < 0 or record.allowed > record.requested:
            raise ValueError("INVALID_RISK_RESERVATION")
        if record.allowed > self._configured_allocated:
            raise ValueError("RISK_RESERVATION_EXCEEDS_ALLOCATED")
        self._validate_amount(record.requested, "NON_FINITE_RISK_REQUESTED")
        self._validate_amount(record.allowed, "NON_FINITE_RISK_ALLOWED")
        if record.created_at_ms < 0:
            raise ValueError("INVALID_RISK_RESERVATION_TIMESTAMP")
        if record.expires_at_ms is not None and record.expires_at_ms <= record.created_at_ms:
            raise ValueError("INVALID_RISK_RESERVATION_EXPIRY")

    @staticmethod
    def _validate_amount(value: Decimal, error: str) -> Decimal:
        if not value.is_finite() or value < 0:
            raise ValueError(error)
        return value

    @staticmethod
    def _decimal(value: Any, error: str) -> Decimal:
        try:
            out = Decimal(str(value))
        except Exception as exc:
            raise ValueError(error) from exc
        if not out.is_finite() or out < 0:
            raise ValueError(error)
        return out

    @staticmethod
    def _terminal_state(event_type: str) -> RiskReservationState:
        return {
            DurableRiskReservationBook.CONSUMED: RiskReservationState.CONSUMED,
            DurableRiskReservationBook.RELEASED: RiskReservationState.RELEASED,
            DurableRiskReservationBook.EXPIRED: RiskReservationState.EXPIRED,
            DurableRiskReservationBook.OVERRIDDEN: RiskReservationState.OVERRIDDEN,
        }[event_type]

    @staticmethod
    def _record_from_payload(payload: Mapping[str, Any]) -> RiskReservationRecord:
        try:
            return RiskReservationRecord(
                reservation_id=str(payload["reservation_id"]),
                scope=BudgetScope(str(payload["scope"])),
                requested=Decimal(str(payload["requested"])),
                allowed=Decimal(str(payload["allowed"])),
                intent_id=str(payload["intent_id"]),
                risk_decision_id=str(payload["risk_decision_id"]),
                accounting_projection_hash=str(payload["accounting_projection_hash"]),
                created_at_ms=int(payload["created_at_ms"]),
                expires_at_ms=None if payload.get("expires_at_ms") is None else int(payload["expires_at_ms"]),
            )
        except Exception as exc:
            raise RiskReservationReplayError("INVALID_RISK_RESERVATION_PAYLOAD") from exc

    @staticmethod
    def _validate_binding(record: RiskReservationRecord, intent_id: str, risk_decision_id: str,
                          requested_risk: Decimal, accounting_projection_hash: str) -> None:
        if record.intent_id != intent_id:
            raise RiskReservationConflict("RESERVATION_INTENT_MISMATCH")
        if record.risk_decision_id != risk_decision_id:
            raise RiskReservationConflict("RESERVATION_RISK_DECISION_MISMATCH")
        try:
            requested = Decimal(str(requested_risk))
        except Exception as exc:
            raise RiskReservationConflict("INVALID_REQUESTED_RISK") from exc
        if not requested.is_finite() or requested < 0 or requested > record.allowed:
            raise RiskReservationConflict("RESERVATION_RISK_LIMIT")
        if record.accounting_projection_hash != accounting_projection_hash:
            raise RiskReservationConflict("RESERVATION_ACCOUNTING_HASH_STALE")


class RiskReservationGate:
    """Final risk-reservation gate used immediately before external transport."""

    def __init__(self, book: DurableRiskReservationBook):
        self.book = book

    def consume_for_dispatch(self, *, reservation_id: str, intent_id: str, risk_decision_id: str,
                             requested_risk: Decimal, accounting_projection_hash: str,
                             occurred_at_ms: int) -> RiskReservationSnapshot:
        return self.book.consume(
            reservation_id,
            intent_id=intent_id,
            risk_decision_id=risk_decision_id,
            requested_risk=requested_risk,
            accounting_projection_hash=accounting_projection_hash,
            occurred_at_ms=occurred_at_ms,
        )
