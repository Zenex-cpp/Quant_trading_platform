"""V3.75 — Backtest/live decision-stage parity contract (§85).

This module deliberately closes only the *decision-stage* portion of §85.
It provides a live/shadow-side runner that consumes the same
``BacktestStageFunctions`` used by V3.73/V3.74 and a deterministic trace
that can be compared against a backtest trace for identical market events
and identical externally supplied position state.

It does not claim full live parity:
- no live market-data transport is implemented here;
- no exchange execution is performed;
- no live accounting/reconciliation path is substituted;
- no real-time latency or event-loop equivalence is claimed.

The purpose is to make the shared decision seam machine-checkable before
building a live/shadow execution harness.
"""

from __future__ import annotations

from dataclasses import dataclass, is_dataclass, asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
from hashlib import sha256
from typing import Any, Callable, Mapping, Sequence

from trading_platform.replay.replay import canonical_hash
from trading_platform.v373.backtest_engine import (
    BacktestEngine,
    BacktestStageFunctions,
    ExecutionModelConfig,
    MarketEvent,
)
from trading_platform.execution.models import OrderIntent


class ParityInputError(ValueError):
    """Invalid parity-run input."""


@dataclass(frozen=True)
class DecisionTraceRecord:
    event_offset: int
    event_time: str
    symbol: str
    position_quantity: str
    feature_hash: str
    regime_hash: str
    prediction_hash: str
    signal_hash: str
    opportunity_hash: str
    portfolio_hash: str
    risk_hash: str
    intent_hash: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DecisionTrace:
    trace_version: str
    records: tuple[DecisionTraceRecord, ...]
    state_hash: str

    @property
    def event_offsets(self) -> tuple[int, ...]:
        return tuple(r.event_offset for r in self.records)

    @property
    def position_quantities(self) -> tuple[Decimal, ...]:
        return tuple(Decimal(r.position_quantity) for r in self.records)


@dataclass(frozen=True)
class ParityComparison:
    status: str
    compared_events: int
    mismatch_offsets: tuple[int, ...]
    backtest_hash: str
    live_hash: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


@dataclass(frozen=True)
class LiveDecisionResult:
    trace: DecisionTrace
    intents: tuple[OrderIntent | None, ...]


def _canonicalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, (datetime, date)):
        return {"__datetime__": value.isoformat()}
    if isinstance(value, Enum):
        return {"__enum__": f"{type(value).__name__}:{value.value}"}
    if is_dataclass(value):
        return {
            "__dataclass__": f"{type(value).__module__}.{type(value).__name__}",
            "value": _canonicalize(asdict(value)),
        }
    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_canonicalize(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted((_canonicalize(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True))
    return {
        "__type__": f"{type(value).__module__}.{type(value).__name__}",
        "__repr__": str(value),
    }


def _value_hash(value: Any) -> str:
    payload = json.dumps(
        _canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(payload).hexdigest()


@dataclass
class _TraceBuilder:
    event: MarketEvent
    position_quantity: Decimal | None
    feature: Any = None
    regime: Any = None
    prediction: Any = None
    signal: Any = None
    opportunity: Any = None
    portfolio: Any = None
    risk: Any = None
    intent: Any = None

    def record(self) -> DecisionTraceRecord:
        if self.position_quantity is None:
            raise ParityInputError("POSITION_QUANTITY_REQUIRED")
        return DecisionTraceRecord(
            event_offset=self.event.event_offset,
            event_time=self.event.event_time.isoformat(),
            symbol=self.event.symbol,
            position_quantity=str(self.position_quantity if self.position_quantity is not None else Decimal("0")),
            feature_hash=_value_hash(self.feature),
            regime_hash=_value_hash(self.regime),
            prediction_hash=_value_hash(self.prediction),
            signal_hash=_value_hash(self.signal),
            opportunity_hash=_value_hash(self.opportunity),
            portfolio_hash=_value_hash(self.portfolio),
            risk_hash=_value_hash(self.risk),
            intent_hash=_value_hash(self.intent),
        )


class BacktestDecisionTraceCollector:
    """Builds a traced ``BacktestStageFunctions`` wrapper."""

    def __init__(self, stages: BacktestStageFunctions) -> None:
        self._stages = stages
        self._builders: dict[int, _TraceBuilder] = {}

    def _builder(self, event: MarketEvent, position_quantity: Decimal | None = None) -> _TraceBuilder:
        current = self._builders.get(event.event_offset)
        if current is None:
            current = _TraceBuilder(event=event, position_quantity=position_quantity)
            self._builders[event.event_offset] = current
        elif position_quantity is not None:
            current.position_quantity = position_quantity
        return current

    def traced_stages(self) -> BacktestStageFunctions:
        def feature_fn(event):
            result = self._stages.feature_fn(event)
            self._builder(event).feature = result
            return result

        def regime_fn(event, feature):
            result = self._stages.regime_fn(event, feature)
            self._builder(event).regime = result
            return result

        def prediction_fn(event, feature, regime):
            result = self._stages.prediction_fn(event, feature, regime)
            self._builder(event).prediction = result
            return result

        def signal_fn(event, prediction):
            result = self._stages.signal_fn(event, prediction)
            self._builder(event).signal = result
            return result

        def opportunity_fn(event, signal, regime):
            result = self._stages.opportunity_fn(event, signal, regime)
            self._builder(event).opportunity = result
            return result

        def portfolio_fn(event, opportunity, qty):
            result = self._stages.portfolio_fn(event, opportunity, qty)
            self._builder(event, qty).portfolio = result
            return result

        def risk_fn(event, decision, qty):
            result = self._stages.risk_fn(event, decision, qty)
            self._builder(event, qty).risk = result
            return result

        def intent_fn(event, risk_decision):
            result = self._stages.intent_fn(event, risk_decision)
            self._builder(event).intent = result
            return result

        return BacktestStageFunctions(
            feature_fn=feature_fn,
            regime_fn=regime_fn,
            prediction_fn=prediction_fn,
            signal_fn=signal_fn,
            opportunity_fn=opportunity_fn,
            portfolio_fn=portfolio_fn,
            risk_fn=risk_fn,
            intent_fn=intent_fn,
        )

    def trace(self) -> DecisionTrace:
        records = tuple(
            self._builders[offset].record()
            for offset in sorted(self._builders)
        )
        state = {
            "trace_version": "V375_DECISION_TRACE_1",
            "records": [record.as_dict() for record in records],
        }
        return DecisionTrace(
            trace_version="V375_DECISION_TRACE_1",
            records=records,
            state_hash=canonical_hash(state),
        )


def capture_backtest_decision_trace(
    stages: BacktestStageFunctions,
    execution_model: ExecutionModelConfig,
    symbol: str,
    market_events: Sequence[MarketEvent],
    *,
    seed: int = 0,
) -> tuple[DecisionTrace, Any]:
    collector = BacktestDecisionTraceCollector(stages)
    result = BacktestEngine(
        collector.traced_stages(),
        execution_model,
        symbol,
        seed,
    ).run(market_events)
    trace = collector.trace()
    if trace.event_offsets != tuple(event.event_offset for event in market_events):
        raise RuntimeError("BACKTEST_TRACE_EVENT_COVERAGE_MISMATCH")
    return trace, result


class LiveDecisionEngine:
    """Decision-only live/shadow runner using the same stage object."""

    def __init__(self, stages: BacktestStageFunctions) -> None:
        self._stages = stages

    def run(
        self,
        market_events: Sequence[MarketEvent],
        position_quantities: Sequence[Decimal],
    ) -> LiveDecisionResult:
        if len(market_events) != len(position_quantities):
            raise ParityInputError("POSITION_SEQUENCE_LENGTH_MISMATCH")

        records: list[DecisionTraceRecord] = []
        intents: list[OrderIntent | None] = []
        last_offset = -1

        for event, position_quantity in zip(market_events, position_quantities):
            if event.event_offset <= last_offset:
                raise ParityInputError("OUT_OF_ORDER_LIVE_EVENT")
            last_offset = event.event_offset

            feature = self._stages.feature_fn(event)
            regime = self._stages.regime_fn(event, feature)
            prediction = self._stages.prediction_fn(event, feature, regime)
            signal = self._stages.signal_fn(event, prediction)
            opportunity = self._stages.opportunity_fn(event, signal, regime)
            portfolio = self._stages.portfolio_fn(event, opportunity, position_quantity)
            risk = self._stages.risk_fn(event, portfolio, position_quantity)
            intent = self._stages.intent_fn(event, risk)

            records.append(
                DecisionTraceRecord(
                    event_offset=event.event_offset,
                    event_time=event.event_time.isoformat(),
                    symbol=event.symbol,
                    position_quantity=str(position_quantity),
                    feature_hash=_value_hash(feature),
                    regime_hash=_value_hash(regime),
                    prediction_hash=_value_hash(prediction),
                    signal_hash=_value_hash(signal),
                    opportunity_hash=_value_hash(opportunity),
                    portfolio_hash=_value_hash(portfolio),
                    risk_hash=_value_hash(risk),
                    intent_hash=_value_hash(intent),
                )
            )
            intents.append(intent)

        state = {
            "trace_version": "V375_DECISION_TRACE_1",
            "records": [record.as_dict() for record in records],
        }
        trace = DecisionTrace(
            trace_version="V375_DECISION_TRACE_1",
            records=tuple(records),
            state_hash=canonical_hash(state),
        )
        return LiveDecisionResult(trace=trace, intents=tuple(intents))


def compare_decision_traces(
    backtest_trace: DecisionTrace,
    live_trace: DecisionTrace,
) -> ParityComparison:
    mismatch_offsets: list[int] = []
    by_offset = {record.event_offset: record for record in live_trace.records}

    for record in backtest_trace.records:
        other = by_offset.get(record.event_offset)
        if other != record:
            mismatch_offsets.append(record.event_offset)

    for offset in live_trace.event_offsets:
        if offset not in {record.event_offset for record in backtest_trace.records}:
            mismatch_offsets.append(offset)

    mismatch_offsets = sorted(set(mismatch_offsets))
    status = "PASS" if not mismatch_offsets else "FAIL"
    return ParityComparison(
        status=status,
        compared_events=max(len(backtest_trace.records), len(live_trace.records)),
        mismatch_offsets=tuple(mismatch_offsets),
        backtest_hash=backtest_trace.state_hash,
        live_hash=live_trace.state_hash,
    )
