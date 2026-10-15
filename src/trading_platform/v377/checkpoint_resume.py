"""V3.77 — deterministic checkpoint/resume for the v3.x backtest path (§88).

The checkpoint captures the complete mutable state required by the V3.76
partial-fill execution loop: ledger, pending orders, fills, rejections,
equity curve, execution configuration, symbol, seed, and replay boundary.
A resume consumes only the suffix beginning at the checkpoint's exact
``next_event_offset`` and must reproduce the same final result as a full run.

Scope boundary: this is a backtest/research checkpoint artifact. It is not yet
a production-durable cross-process checkpoint store for the live execution
plane. The artifact is immutable, hash-verified, and fail-closed on mismatch.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json
from typing import Any, Sequence

from trading_platform.execution.models import Fill, OrderAction, OrderIntent, OrderType, Side
from trading_platform.replay.replay import canonical_hash
from trading_platform.v373.backtest_engine import (
    BacktestStageFunctions,
    MarketEvent,
    RejectedIntent,
    RejectionReason,
    SimulationMode,
)
from trading_platform.v376.partial_fill_execution import (
    PartialFillBacktestEngine,
    PartialFillBacktestResult,
    PartialFillExecutionModelConfig,
    PartialFillRejectionReason,
    _Ledger,
    _PendingOrder,
)
from trading_platform.core.ttl import ValidWindow


SNAPSHOT_VERSION = "V377_BACKTEST_CHECKPOINT_1"


class CheckpointResumeError(RuntimeError):
    """Raised when a checkpoint cannot be safely verified or resumed."""


@dataclass(frozen=True)
class BacktestCheckpoint:
    checkpoint_id: str
    snapshot_version: str
    event_offset: int
    next_event_offset: int
    execution_model_version: str
    mode: SimulationMode
    symbol: str
    seed: int
    state_hash: str
    snapshot_json: str

    def payload(self) -> dict[str, Any]:
        return json.loads(self.snapshot_json)

    def verify(self) -> bool:
        try:
            payload = self.payload()
        except json.JSONDecodeError:
            return False
        if payload.get("snapshot_version") != self.snapshot_version:
            return False
        if payload.get("event_offset") != self.event_offset:
            return False
        if payload.get("next_event_offset") != self.next_event_offset:
            return False
        if payload.get("execution_model_version") != self.execution_model_version:
            return False
        if payload.get("mode") != self.mode.value:
            return False
        if payload.get("symbol") != self.symbol:
            return False
        if payload.get("seed") != self.seed:
            return False
        return canonical_hash(payload) == self.state_hash

    def as_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_id": self.checkpoint_id,
            "snapshot_version": self.snapshot_version,
            "event_offset": self.event_offset,
            "next_event_offset": self.next_event_offset,
            "execution_model_version": self.execution_model_version,
            "mode": self.mode.value,
            "symbol": self.symbol,
            "seed": self.seed,
            "state_hash": self.state_hash,
            "snapshot": self.payload(),
        }


class InMemoryCheckpointStore:
    """Immutable research/test store for checkpoint artifacts.

    A production implementation still requires durable storage and restart
    integration; this store proves the artifact and replay contract without
    pretending to be that deployment layer.
    """

    def __init__(self) -> None:
        self._items: dict[str, BacktestCheckpoint] = {}

    def put(self, checkpoint: BacktestCheckpoint) -> None:
        if not checkpoint.verify():
            raise CheckpointResumeError("CHECKPOINT_INVALID")
        if checkpoint.checkpoint_id in self._items:
            raise CheckpointResumeError("CHECKPOINT_IMMUTABLE_ID_REUSE")
        self._items[checkpoint.checkpoint_id] = checkpoint

    def get(self, checkpoint_id: str) -> BacktestCheckpoint | None:
        return self._items.get(checkpoint_id)


class CheckpointedPartialFillBacktestEngine:
    """V3.77 resumable execution loop built on V3.76 mechanics."""

    def __init__(
        self,
        stages: BacktestStageFunctions,
        execution_model: PartialFillExecutionModelConfig,
        symbol: str,
        seed: int = 0,
    ) -> None:
        self._engine = PartialFillBacktestEngine(stages, execution_model, symbol, seed)
        self._stages = stages
        self._execution_model = execution_model
        self._symbol = symbol
        self._seed = seed

    def run(self, market_events: Sequence[MarketEvent]) -> PartialFillBacktestResult:
        return self._run_from_state(
            market_events,
            ledger=_Ledger(),
            pending=[],
            fills=[],
            rejected=[],
            equity_curve=[],
            last_offset=-1,
        )

    def run_to_checkpoint(
        self,
        market_events: Sequence[MarketEvent],
        *,
        checkpoint_after_event_offset: int,
        checkpoint_id: str,
    ) -> tuple[PartialFillBacktestResult, BacktestCheckpoint]:
        prefix = []
        suffix = []
        found = False
        for event in market_events:
            if found:
                suffix.append(event)
                continue
            prefix.append(event)
            if event.event_offset == checkpoint_after_event_offset:
                found = True
        if not found:
            raise CheckpointResumeError("CHECKPOINT_EVENT_OFFSET_NOT_FOUND")

        runtime = self._run_state(prefix)
        next_offset = suffix[0].event_offset if suffix else checkpoint_after_event_offset + 1
        checkpoint = self._checkpoint_from_state(
            checkpoint_id=checkpoint_id,
            event_offset=checkpoint_after_event_offset,
            next_event_offset=next_offset,
            ledger=runtime[0],
            pending=runtime[1],
            fills=runtime[2],
            rejected=runtime[3],
            equity_curve=runtime[4],
        )
        return self._result_from_state(
            prefix,
            runtime[0], runtime[1], runtime[2], runtime[3], runtime[4]
        ), checkpoint

    def resume(
        self,
        remaining_events: Sequence[MarketEvent],
        checkpoint: BacktestCheckpoint,
    ) -> PartialFillBacktestResult:
        self._verify_compatibility(checkpoint)
        if not checkpoint.verify():
            raise CheckpointResumeError("CHECKPOINT_INVALID")
        if remaining_events:
            first = remaining_events[0].event_offset
            if first != checkpoint.next_event_offset:
                raise CheckpointResumeError("CHECKPOINT_EVENT_BOUNDARY_MISMATCH")
        payload = checkpoint.payload()
        ledger, pending, fills, rejected, equity_curve = self._restore_state(payload)
        return self._run_from_state(
            remaining_events,
            ledger=ledger,
            pending=pending,
            fills=fills,
            rejected=rejected,
            equity_curve=equity_curve,
            last_offset=checkpoint.event_offset,
        )

    def checkpoint_json(self, checkpoint: BacktestCheckpoint) -> str:
        self._verify_compatibility(checkpoint)
        if not checkpoint.verify():
            raise CheckpointResumeError("CHECKPOINT_INVALID")
        return json.dumps(checkpoint.as_dict(), sort_keys=True, separators=(",", ":"))

    def _verify_compatibility(self, checkpoint: BacktestCheckpoint) -> None:
        if checkpoint.snapshot_version != SNAPSHOT_VERSION:
            raise CheckpointResumeError("CHECKPOINT_VERSION_INCOMPATIBLE")
        if checkpoint.execution_model_version != self._execution_model.version:
            raise CheckpointResumeError("CHECKPOINT_EXECUTION_MODEL_MISMATCH")
        if checkpoint.mode != self._execution_model.mode:
            raise CheckpointResumeError("CHECKPOINT_MODE_MISMATCH")
        if checkpoint.symbol != self._symbol:
            raise CheckpointResumeError("CHECKPOINT_SYMBOL_MISMATCH")
        if checkpoint.seed != self._seed:
            raise CheckpointResumeError("CHECKPOINT_SEED_MISMATCH")

    def _run_state(
        self,
        market_events: Sequence[MarketEvent],
    ) -> tuple[_Ledger, list[_PendingOrder], list[Fill], list[RejectedIntent], list[Decimal]]:
        return self._run_runtime(
            market_events,
            ledger=_Ledger(),
            pending=[],
            fills=[],
            rejected=[],
            equity_curve=[],
            last_offset=-1,
        )

    def _run_from_state(
        self,
        market_events: Sequence[MarketEvent],
        *,
        ledger: _Ledger,
        pending: list[_PendingOrder],
        fills: list[Fill],
        rejected: list[RejectedIntent],
        equity_curve: list[Decimal],
        last_offset: int,
    ) -> PartialFillBacktestResult:
        runtime = self._run_runtime(
            market_events,
            ledger=ledger,
            pending=pending,
            fills=fills,
            rejected=rejected,
            equity_curve=equity_curve,
            last_offset=last_offset,
        )
        return self._result_from_state(
            market_events,
            runtime[0], runtime[1], runtime[2], runtime[3], runtime[4]
        )

    def _run_runtime(
        self,
        market_events: Sequence[MarketEvent],
        *,
        ledger: _Ledger,
        pending: list[_PendingOrder],
        fills: list[Fill],
        rejected: list[RejectedIntent],
        equity_curve: list[Decimal],
        last_offset: int,
    ) -> tuple[_Ledger, list[_PendingOrder], list[Fill], list[RejectedIntent], list[Decimal]]:
        for event in market_events:
            if event.event_offset <= last_offset:
                raise CheckpointResumeError(
                    f"event_offset {event.event_offset} must exceed {last_offset}"
                )
            last_offset = event.event_offset

            feature = self._stages.feature_fn(event)
            regime = self._stages.regime_fn(event, feature)
            prediction = self._stages.prediction_fn(event, feature, regime)
            signal = self._stages.signal_fn(event, prediction)
            opportunity = self._stages.opportunity_fn(event, signal, regime)
            portfolio_decision = self._stages.portfolio_fn(event, opportunity, ledger.quantity)
            risk_decision = self._stages.risk_fn(event, portfolio_decision, ledger.quantity)
            intent = self._stages.intent_fn(event, risk_decision)
            if intent is not None:
                pending.append(
                    _PendingOrder(
                        ready_offset=event.event_offset + self._execution_model.latency_offsets,
                        intent=intent,
                        remaining_quantity=intent.quantity,
                    )
                )

            next_pending: list[_PendingOrder] = []
            for order in pending:
                if order.ready_offset > event.event_offset:
                    next_pending.append(order)
                    continue
                outcome = self._engine._try_partial_fill(order, event)
                if isinstance(outcome, RejectedIntent):
                    rejected.append(outcome)
                    continue
                if outcome is None:
                    next_pending.append(order)
                    continue
                fill, filled_quantity = outcome
                fills.append(fill)
                self._engine._apply_fill(ledger, fill, order.intent.side)
                order.remaining_quantity -= filled_quantity
                order.fill_index += 1
                if order.remaining_quantity > 0:
                    order.ready_offset = event.event_offset + 1
                    next_pending.append(order)
            pending = next_pending

            equity = ledger.equity(event.close)
            equity_curve.append(equity)

        return ledger, pending, fills, rejected, equity_curve

    def _checkpoint_from_state(
        self,
        *,
        checkpoint_id: str,
        event_offset: int,
        next_event_offset: int,
        ledger: _Ledger,
        pending: list[_PendingOrder],
        fills: list[Fill],
        rejected: list[RejectedIntent],
        equity_curve: list[Decimal],
    ) -> BacktestCheckpoint:
        if event_offset < 0:
            raise CheckpointResumeError("INVALID_CHECKPOINT_EVENT_OFFSET")
        payload = {
            "snapshot_version": SNAPSHOT_VERSION,
            "event_offset": event_offset,
            "next_event_offset": next_event_offset,
            "execution_model_version": self._execution_model.version,
            "mode": self._execution_model.mode.value,
            "symbol": self._symbol,
            "seed": self._seed,
            "ledger": {
                "quantity": str(ledger.quantity),
                "cash": str(ledger.cash),
            },
            "pending": [self._pending_payload(item) for item in pending],
            "fills": [self._fill_payload(item) for item in fills],
            "rejected": [self._rejected_payload(item) for item in rejected],
            "equity_curve": [str(value) for value in equity_curve],
        }
        snapshot_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        state_hash = canonical_hash(payload)
        return BacktestCheckpoint(
            checkpoint_id=checkpoint_id,
            snapshot_version=SNAPSHOT_VERSION,
            event_offset=event_offset,
            next_event_offset=next_event_offset,
            execution_model_version=self._execution_model.version,
            mode=self._execution_model.mode,
            symbol=self._symbol,
            seed=self._seed,
            state_hash=state_hash,
            snapshot_json=snapshot_json,
        )

    def _restore_state(
        self, payload: dict[str, Any]
    ) -> tuple[_Ledger, list[_PendingOrder], list[Fill], list[RejectedIntent], list[Decimal]]:
        ledger_data = payload["ledger"]
        ledger = _Ledger(Decimal(ledger_data["quantity"]), Decimal(ledger_data["cash"]))
        pending = [self._pending_from_payload(item) for item in payload["pending"]]
        fills = [self._fill_from_payload(item) for item in payload["fills"]]
        rejected = [self._rejected_from_payload(item) for item in payload["rejected"]]
        equity_curve = [Decimal(value) for value in payload["equity_curve"]]
        return ledger, pending, fills, rejected, equity_curve

    @staticmethod
    def _dt(value: datetime) -> str:
        return value.isoformat()

    @staticmethod
    def _dt_parse(value: str) -> datetime:
        return datetime.fromisoformat(value)

    def _intent_payload(self, intent: OrderIntent) -> dict[str, Any]:
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
            "valid_from": self._dt(intent.window.valid_from),
            "expires_at": self._dt(intent.window.expires_at),
            "price": None if intent.price is None else str(intent.price),
            "time_in_force": intent.time_in_force,
            "risk_reservation_id": intent.risk_reservation_id,
        }

    def _intent_from_payload(self, data: dict[str, Any]) -> OrderIntent:
        return OrderIntent(
            intent_id=data["intent_id"],
            decision_id=data["decision_id"],
            portfolio_decision_id=data["portfolio_decision_id"],
            risk_decision_id=data["risk_decision_id"],
            strategy_id=data["strategy_id"],
            model_id=data["model_id"],
            execution_version=data["execution_version"],
            symbol=data["symbol"],
            side=Side(data["side"]),
            action=OrderAction(data["action"]),
            quantity=Decimal(data["quantity"]),
            order_type=OrderType(data["order_type"]),
            window=ValidWindow(
                self._dt_parse(data["valid_from"]), self._dt_parse(data["expires_at"])
            ),
            price=None if data["price"] is None else Decimal(data["price"]),
            time_in_force=data["time_in_force"],
            risk_reservation_id=data["risk_reservation_id"],
        )

    def _pending_payload(self, order: _PendingOrder) -> dict[str, Any]:
        return {
            "ready_offset": order.ready_offset,
            "remaining_quantity": str(order.remaining_quantity),
            "fill_index": order.fill_index,
            "intent": self._intent_payload(order.intent),
        }

    def _pending_from_payload(self, data: dict[str, Any]) -> _PendingOrder:
        return _PendingOrder(
            ready_offset=int(data["ready_offset"]),
            intent=self._intent_from_payload(data["intent"]),
            remaining_quantity=Decimal(data["remaining_quantity"]),
            fill_index=int(data["fill_index"]),
        )

    def _fill_payload(self, fill: Fill) -> dict[str, Any]:
        return {
            "fill_id": fill.fill_id,
            "order_request_id": fill.order_request_id,
            "exchange_order_id": fill.exchange_order_id,
            "quantity": str(fill.quantity),
            "price": str(fill.price),
            "fee": str(fill.fee),
            "funding": str(fill.funding),
            "slippage": str(fill.slippage),
            "market_impact": str(fill.market_impact),
            "event_time": None if fill.event_time is None else self._dt(fill.event_time),
            "trade_id": fill.trade_id,
            "venue": fill.venue,
        }

    def _fill_from_payload(self, data: dict[str, Any]) -> Fill:
        return Fill(
            fill_id=data["fill_id"],
            order_request_id=data["order_request_id"],
            exchange_order_id=data["exchange_order_id"],
            quantity=Decimal(data["quantity"]),
            price=Decimal(data["price"]),
            fee=Decimal(data["fee"]),
            funding=Decimal(data["funding"]),
            slippage=Decimal(data["slippage"]),
            market_impact=Decimal(data["market_impact"]),
            event_time=None if data["event_time"] is None else self._dt_parse(data["event_time"]),
            trade_id=data["trade_id"],
            venue=data["venue"],
        )

    @staticmethod
    def _rejected_payload(item: RejectedIntent) -> dict[str, Any]:
        return {
            "intent_id": item.intent_id,
            "event_offset": item.event_offset,
            "reason_type": type(item.reason).__name__,
            "reason": item.reason.value,
        }

    @staticmethod
    def _rejected_from_payload(data: dict[str, Any]) -> RejectedIntent:
        reason_type = data["reason_type"]
        reason_value = data["reason"]
        if reason_type == PartialFillRejectionReason.__name__:
            reason = PartialFillRejectionReason(reason_value)
        else:
            reason = RejectionReason(reason_value)
        return RejectedIntent(data["intent_id"], int(data["event_offset"]), reason)

    def _result_from_state(
        self,
        market_events: Sequence[MarketEvent],
        ledger: _Ledger,
        pending: list[_PendingOrder],
        fills: list[Fill],
        rejected: list[RejectedIntent],
        equity_curve: list[Decimal],
    ) -> PartialFillBacktestResult:
        open_orders = tuple(
            sorted(
                ((order.intent.intent_id, order.remaining_quantity) for order in pending),
                key=lambda item: item[0],
            )
        )
        final_equity = equity_curve[-1] if equity_curve else ledger.cash
        state = {
            "symbol": self._symbol,
            "execution_model_version": self._execution_model.version,
            "mode": self._execution_model.mode.value,
            "participation_rate": str(self._execution_model.participation_rate),
            "fills": [
                {"fill_id": f.fill_id, "quantity": str(f.quantity), "price": str(f.price), "fee": str(f.fee)}
                for f in fills
            ],
            "rejected": [
                {"intent_id": r.intent_id, "offset": r.event_offset, "reason": r.reason.value}
                for r in rejected
            ],
            "open_orders": [(intent_id, str(quantity)) for intent_id, quantity in open_orders],
            "final_equity": str(final_equity),
            "event_count": len(market_events) if market_events else len(equity_curve),
        }
        # The caller may resume over a suffix, so the authoritative event count
        # is the number represented by the accumulated equity curve when no full
        # sequence was supplied. For a full run, it equals len(market_events).
        event_count = len(equity_curve)
        return PartialFillBacktestResult(
            fills=tuple(fills),
            rejected_intents=tuple(rejected),
            open_orders=open_orders,
            equity_curve=tuple(equity_curve),
            final_equity=final_equity,
            final_quantity=ledger.quantity,
            event_count=event_count,
            state_hash=canonical_hash({**state, "event_count": event_count}),
            execution_model_version=self._execution_model.version,
            mode=self._execution_model.mode,
        )


__all__ = [
    "BacktestCheckpoint",
    "CheckpointResumeError",
    "CheckpointedPartialFillBacktestEngine",
    "InMemoryCheckpointStore",
    "SNAPSHOT_VERSION",
]
