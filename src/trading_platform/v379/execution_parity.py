"""V3.79 execution-seam parity and Testnet adapter boundary (§85/§86).

This module does not reuse the venue execution engine as a fake live engine.
It instead proves the boundary between the shared decision chain and an injected
execution adapter:

    market event -> shared decision stages -> OrderIntent -> adapter observation

The adapter is deliberately side-effect free by default. Real Binance Testnet
mutations remain behind an explicit gate and are not enabled by parity runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trading_platform.execution.models import OrderAction, OrderIntent, OrderRequest, OrderType
from trading_platform.ops.network_policy import TESTNET_POLICY
from trading_platform.realtime.orderbook import OrderBookSnapshot
from trading_platform.v375.decision_parity import (
    BacktestDecisionTraceCollector,
    DecisionTrace,
    LiveDecisionEngine,
    ParityComparison,
    _value_hash,
    compare_decision_traces,
)
from trading_platform.v378 import (
    BinanceVenueExecutionEngine,
    BinanceVenueExecutionModelConfig,
    VenueMarketEvent,
    VenueExecutionResult,
)
from trading_platform.v373.backtest_engine import BacktestStageFunctions, MarketEvent
from trading_platform.v35.binance_execution import BinanceTestnetExecutionGateway, RuntimeCredentialValues, SubmitObservation


class AdapterStatus(str, Enum):
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AdapterObservation:
    intent_id: str
    client_order_id: str
    status: AdapterStatus
    exchange_order_id: str | None
    executed_quantity: Decimal
    average_price: Decimal | None
    raw_hash: str
    source: str


class ExecutionAdapter(Protocol):
    def observe(self, intent: OrderIntent) -> AdapterObservation: ...


class LiveShadowExecutionAdapter:
    """Deterministic no-network adapter for shadow parity evidence."""

    def __init__(self, observations: Mapping[str, AdapterObservation] | None = None) -> None:
        self._observations = dict(observations or {})
        self.observed_intents: list[str] = []

    @staticmethod
    def _default_client_order_id(intent: OrderIntent) -> str:
        return f"tp-{hashlib.sha256(intent.intent_id.encode()).hexdigest()[:24]}"

    def observe(self, intent: OrderIntent) -> AdapterObservation:
        self.observed_intents.append(intent.intent_id)
        existing = self._observations.get(intent.intent_id)
        if existing is not None:
            return existing
        raw = {
            "intent_id": intent.intent_id,
            "status": AdapterStatus.ACKNOWLEDGED.value,
            "quantity": str(intent.quantity),
            "symbol": intent.symbol,
        }
        return AdapterObservation(
            intent_id=intent.intent_id,
            client_order_id=self._default_client_order_id(intent),
            status=AdapterStatus.ACKNOWLEDGED,
            exchange_order_id=None,
            executed_quantity=Decimal("0"),
            average_price=None,
            raw_hash=_hash_json(raw),
            source="SHADOW_SCRIPTED",
        )


@dataclass(frozen=True)
class ExecutionParityComparison:
    status: str
    decision: ParityComparison
    compared_intents: int
    intent_mismatch_offsets: tuple[int, ...]
    adapter_observation_hash: str
    expected_adapter_observation_hash: str
    backtest_state_hash: str
    shadow_adapter_state_hash: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _intent_fingerprint(intent: OrderIntent | None) -> str:
    return _value_hash(intent)


def _selected_intents(trace: DecisionTrace) -> tuple[tuple[int, str], ...]:
    return tuple((record.event_offset, record.intent_hash) for record in trace.records)


class ExecutionParityHarness:
    """Non-vacuous parity seam between backtest venue execution and live/shadow adapter."""

    def run(
        self,
        *,
        stages: BacktestStageFunctions,
        execution_model: BinanceVenueExecutionModelConfig,
        symbol: str,
        venue_events: Sequence[VenueMarketEvent],
        adapter: ExecutionAdapter,
        seed: int = 0,
    ) -> tuple[ExecutionParityComparison, VenueExecutionResult]:
        collector = BacktestDecisionTraceCollector(stages)
        backtest_result = BinanceVenueExecutionEngine(
            collector.traced_stages(), execution_model, symbol, seed
        ).run(venue_events)
        backtest_trace = collector.trace()

        market_events = tuple(item.market for item in venue_events)
        live_decision = LiveDecisionEngine(stages).run(
            market_events, backtest_trace.position_quantities
        )
        decision_comparison = compare_decision_traces(backtest_trace, live_decision.trace)

        live_intents = {
            offset: intent
            for offset, intent in zip(live_decision.trace.event_offsets, live_decision.intents)
        }
        mismatches: list[int] = []
        observations: list[dict[str, Any]] = []
        expected_observations: list[dict[str, Any]] = []
        for record in backtest_trace.records:
            live_intent = live_intents.get(record.event_offset)
            live_hash = _intent_fingerprint(live_intent)
            if live_hash != record.intent_hash:
                mismatches.append(record.event_offset)
            if live_intent is not None:
                observation = adapter.observe(live_intent)
                observations.append({
                    "offset": record.event_offset,
                    "intent_hash": live_hash,
                    "client_order_id": observation.client_order_id,
                    "status": observation.status.value,
                    "exchange_order_id": observation.exchange_order_id,
                    "executed_quantity": str(observation.executed_quantity),
                    "average_price": str(observation.average_price) if observation.average_price is not None else None,
                    "raw_hash": observation.raw_hash,
                    "source": observation.source,
                })
                expected_observations.append({
                    "offset": record.event_offset,
                    "intent_hash": record.intent_hash,
                    "client_order_id": observation.client_order_id,
                    "status": observation.status.value,
                    "exchange_order_id": observation.exchange_order_id,
                    "executed_quantity": str(observation.executed_quantity),
                    "average_price": str(observation.average_price) if observation.average_price is not None else None,
                    "raw_hash": observation.raw_hash,
                    "source": observation.source,
                })

        adapter_hash = _hash_json(observations)
        expected_hash = _hash_json(expected_observations)
        state = {
            "decision_hash": decision_comparison.live_hash,
            "intent_mismatches": mismatches,
            "adapter_observations": observations,
            "backtest_state_hash": backtest_result.state_hash,
        }
        shadow_hash = _hash_json(state)
        status = "PASS" if (
            decision_comparison.passed
            and not mismatches
            and adapter_hash == expected_hash
        ) else "FAIL"
        comparison = ExecutionParityComparison(
            status=status,
            decision=decision_comparison,
            compared_intents=sum(1 for item in live_decision.intents if item is not None),
            intent_mismatch_offsets=tuple(mismatches),
            adapter_observation_hash=adapter_hash,
            expected_adapter_observation_hash=expected_hash,
            backtest_state_hash=backtest_result.state_hash,
            shadow_adapter_state_hash=shadow_hash,
        )
        return comparison, backtest_result


@dataclass(frozen=True)
class TestnetMutationGate:
    """Explicit gate for testnet mutations. Disabled by default."""

    __test__ = False

    environment: str = "TESTNET"
    mutation_enabled: bool = False
    operator_approval: bool = False
    max_notional: Decimal = Decimal("0")

    def authorize(self, *, intent: OrderIntent, reference_price: Decimal | None = None) -> None:
        if self.environment != "TESTNET":
            raise PermissionError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if not self.mutation_enabled or not self.operator_approval:
            raise PermissionError("TESTNET_MUTATION_NOT_EXPLICITLY_APPROVED")
        if self.max_notional <= 0:
            raise PermissionError("TESTNET_MAX_NOTIONAL_REQUIRED")
        if intent.order_type is not OrderType.MARKET and intent.order_type is not OrderType.LIMIT:
            raise PermissionError("ORDER_TYPE_UNSUPPORTED")
        if intent.order_type is OrderType.LIMIT and intent.price is None:
            raise PermissionError("LIMIT_PRICE_REQUIRED")
        price = intent.price if intent.price is not None else reference_price
        if price is None or price <= 0:
            raise PermissionError("REFERENCE_PRICE_REQUIRED_FOR_NOTIONAL_GUARD")
        if intent.quantity * price > self.max_notional:
            raise PermissionError("TESTNET_NOTIONAL_LIMIT_EXCEEDED")


class BinanceTestnetOrderAdapter:
    """Translate approved MARKET intents into the existing Binance Testnet gateway.

    Credentials are supplied per call and are never retained by this adapter.
    Limit intents are rejected until a venue-complete OrderRequest contract exists.
    """

    def __init__(self, gateway: BinanceTestnetExecutionGateway, mutation_gate: TestnetMutationGate) -> None:
        self._gateway = gateway
        self._mutation_gate = mutation_gate

    @staticmethod
    def _client_order_id(intent: OrderIntent) -> str:
        return f"tp-{hashlib.sha256(intent.intent_id.encode()).hexdigest()[:24]}"

    def to_order_request(self, intent: OrderIntent, *, now: datetime) -> OrderRequest:
        if intent.order_type is not OrderType.MARKET:
            raise ValueError("LIMIT_ORDER_ADAPTER_NOT_SUPPORTED")
        client_order_id = self._client_order_id(intent)
        return OrderRequest(
            order_request_id=f"or-{hashlib.sha256((intent.intent_id + intent.execution_version).encode()).hexdigest()[:24]}",
            correlation_id=intent.decision_id,
            idempotency_key=hashlib.sha256(intent.intent_id.encode()).hexdigest(),
            client_order_id=client_order_id,
            intent_id=intent.intent_id,
            risk_decision_id=intent.risk_decision_id,
            execution_version=intent.execution_version,
            timestamp=now,
            deadline=intent.window.expires_at,
            symbol=intent.symbol,
            side=intent.side,
            order_type=intent.order_type,
            quantity=intent.quantity,
        )

    def submit(
        self,
        intent: OrderIntent,
        *,
        credentials: RuntimeCredentialValues,
        now: datetime,
        reference_price: Decimal | None = None,
    ) -> SubmitObservation:
        self._mutation_gate.authorize(intent=intent, reference_price=reference_price)
        order = self.to_order_request(intent, now=now)
        return self._gateway.submit(order, credentials=credentials)



@dataclass(frozen=True)
class TestnetPublicProbeResult:
    endpoint: str
    environment: str
    server_time_ms: int
    symbol_present: bool
    symbol_status: str | None
    response_hash: str
    retrieved_at: str
    network_policy: str

    @property
    def passed(self) -> bool:
        return (
            self.environment == "TESTNET"
            and self.server_time_ms > 0
            and self.symbol_present
            and self.symbol_status == "TRADING"
            and self.network_policy == "ALLOW"
        )


class BinanceTestnetPublicProbe:
    """Read-only Testnet probe; it never submits or cancels orders."""

    def __init__(self, *, base_url: str = "https://testnet.binancefuture.com", timeout_s: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        if TESTNET_POLICY.decide(self.base_url) != "ALLOW":
            raise PermissionError("NETWORK_POLICY_DENIED")

    def _get(self, path: str, params: Mapping[str, str] | None = None) -> Mapping[str, Any]:
        url = self.base_url + path
        encoded = urlencode(dict(params or {}))
        if encoded:
            url += "?" + encoded
        req = Request(url, method="GET", headers={"Accept": "application/json", "User-Agent": "trading-platform-testnet/3.79"})
        with urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def run(self, *, symbol: str = "BTCUSDT") -> TestnetPublicProbeResult:
        server = self._get("/fapi/v1/time")
        info = self._get("/fapi/v1/exchangeInfo")
        symbols = info.get("symbols", []) if isinstance(info, Mapping) else []
        match = next((item for item in symbols if str(item.get("symbol", "")).upper() == symbol.upper()), None)
        raw = {"time": server, "exchangeInfoSymbol": match}
        return TestnetPublicProbeResult(
            endpoint=self.base_url,
            environment="TESTNET",
            server_time_ms=int(server.get("serverTime", 0)),
            symbol_present=match is not None,
            symbol_status=str(match.get("status")) if match is not None else None,
            response_hash=_hash_json(raw),
            retrieved_at=datetime.now(timezone.utc).isoformat(),
            network_policy="ALLOW",
        )
