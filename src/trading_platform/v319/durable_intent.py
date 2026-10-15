from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v21.event_store import EventStore


class OrderIntentConflict(RuntimeError):
    """A durable OrderIntent identity was reused with different content."""


class OrderIntentReplayError(RuntimeError):
    """The durable OrderIntent ledger cannot be reconstructed safely."""


@dataclass(frozen=True)
class DurableOrderIntent:
    intent: OrderIntent
    recorded_at_ms: int
    fingerprint: str


class DurableOrderIntentLedger:
    """Append-only, hash-chained, restart-safe OrderIntent authority ledger."""

    RECORDED = "ORDER_INTENT_RECORDED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()

    @staticmethod
    def payload(intent: OrderIntent) -> dict[str, Any]:
        return {
            "intent_id": intent.intent_id,
            "decision_id": intent.decision_id,
            "portfolio_decision_id": intent.portfolio_decision_id,
            "risk_decision_id": intent.risk_decision_id,
            "strategy_id": intent.strategy_id,
            "model_id": intent.model_id,
            "execution_version": intent.execution_version,
            "symbol": intent.symbol,
            "side": intent.side.value,
            "action": intent.action.value,
            "quantity": str(intent.quantity),
            "order_type": intent.order_type.value,
            "valid_from": intent.window.valid_from.isoformat(),
            "expires_at": intent.window.expires_at.isoformat(),
            "price": str(intent.price) if intent.price is not None else None,
            "time_in_force": intent.time_in_force,
            "risk_reservation_id": intent.risk_reservation_id,
        }

    @classmethod
    def fingerprint(cls, intent: OrderIntent) -> str:
        return sha256(json.dumps(cls.payload(intent), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def record(self, intent: OrderIntent, *, recorded_at_ms: int) -> DurableOrderIntent:
        if not intent.intent_id:
            raise ValueError("ORDER_INTENT_ID_REQUIRED")
        if recorded_at_ms < 0:
            raise ValueError("INVALID_ORDER_INTENT_TIMESTAMP")
        payload = self.payload(intent)
        fp = self.fingerprint(intent)
        event = self.store.get(f"order-intent:record:{intent.intent_id}")
        if event is not None:
            if event.event_type != self.RECORDED or dict(event.payload) != payload:
                raise OrderIntentConflict("ORDER_INTENT_ID_PAYLOAD_CONFLICT")
            return DurableOrderIntent(self._from_payload(event.payload), event.occurred_at_ms, fp)
        result = self.store.append(
            event_id=f"order-intent:record:{intent.intent_id}",
            occurred_at_ms=recorded_at_ms,
            event_type=self.RECORDED,
            aggregate_id=intent.intent_id,
            payload=payload,
        )
        if result.duplicate and dict(result.event.payload) != payload:
            raise OrderIntentConflict("ORDER_INTENT_ID_PAYLOAD_CONFLICT")
        return DurableOrderIntent(intent, recorded_at_ms, fp)

    def restore(self) -> dict[str, DurableOrderIntent]:
        if not self.store.verify_chain():
            raise OrderIntentReplayError("ORDER_INTENT_EVENT_CHAIN_INVALID")
        out: dict[str, DurableOrderIntent] = {}
        for event in self.store.iter_events():
            if event.event_type != self.RECORDED:
                raise OrderIntentReplayError(f"UNKNOWN_ORDER_INTENT_EVENT_TYPE:{event.event_type}")
            intent = self._from_payload(event.payload)
            if intent.intent_id in out:
                raise OrderIntentReplayError("DUPLICATE_ORDER_INTENT_ID")
            out[intent.intent_id] = DurableOrderIntent(intent, event.occurred_at_ms, self.fingerprint(intent))
        return out

    def get(self, intent_id: str) -> DurableOrderIntent | None:
        return self.restore().get(intent_id)

    def assert_matches(self, intent: OrderIntent) -> DurableOrderIntent:
        stored = self.get(intent.intent_id)
        if stored is None:
            raise OrderIntentConflict("ORDER_INTENT_NOT_FOUND")
        if stored.fingerprint != self.fingerprint(intent):
            raise OrderIntentConflict("ORDER_INTENT_PAYLOAD_MISMATCH")
        return stored

    @staticmethod
    def _from_payload(payload: Mapping[str, Any]) -> OrderIntent:
        try:
            return OrderIntent(
                intent_id=str(payload["intent_id"]),
                decision_id=str(payload["decision_id"]),
                portfolio_decision_id=str(payload["portfolio_decision_id"]),
                risk_decision_id=str(payload["risk_decision_id"]),
                strategy_id=str(payload["strategy_id"]),
                model_id=str(payload["model_id"]),
                execution_version=str(payload["execution_version"]),
                symbol=str(payload["symbol"]),
                side=Side(str(payload["side"])),
                action=OrderAction(str(payload["action"])),
                quantity=Decimal(str(payload["quantity"])),
                order_type=OrderType(str(payload["order_type"])),
                window=ValidWindow(datetime.fromisoformat(str(payload["valid_from"])), datetime.fromisoformat(str(payload["expires_at"]))),
                price=None if payload.get("price") is None else Decimal(str(payload["price"])),
                time_in_force=payload.get("time_in_force"),
                risk_reservation_id=payload.get("risk_reservation_id"),
            )
        except Exception as exc:
            raise OrderIntentReplayError("INVALID_ORDER_INTENT_PAYLOAD") from exc
