from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
import hashlib

from trading_platform.execution.models import Fill, OrderIntent
from trading_platform.v19.user_stream import NormalizedUserEvent, UserEventType, normalize_user_event
from trading_platform.v34.execution_bridge import ExecutionBridge, ExecutionObservation, BridgeStatus
from trading_platform.v35.binance_execution import (
    BinanceTestnetExecutionGateway,
    RuntimeCredentialValues,
    SubmitObservation,
    ExchangeOutcome,
    ExchangeUncertain,
)
from trading_platform.execution.lifecycle import OrderExecutionState
from trading_platform.execution.unknown import UnknownResolution
from trading_platform.v17.evidence import canonical_json
from trading_platform.v313.durable_correlation import DurableExecutionCorrelationStore
from trading_platform.v321.durable_dispatch import DispatchAttemptState, DurableDispatchAttemptLedger, DispatchAttemptConflict
from trading_platform.v322.durable_reconciliation import DurableDispatchReconciliationLedger, DispatchReconciliationConflict


def _dec(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


@dataclass(frozen=True)
class BinanceOrderTradeUpdate:
    event: NormalizedUserEvent
    client_order_id: str | None
    exchange_order_id: str | None
    execution_type: str | None
    order_status: str | None
    trade_id: str | None
    last_fill_quantity: Decimal
    last_fill_price: Decimal
    cumulative_filled_quantity: Decimal
    commission: Decimal
    commission_asset: str | None
    order_trade_time_ms: int | None

    @property
    def is_trade(self) -> bool:
        return self.execution_type == "TRADE" and self.last_fill_quantity > 0 and self.trade_id not in (None, "0")

    @property
    def dedupe_key(self) -> str:
        if self.is_trade:
            return f"TRADE:{self.exchange_order_id}:{self.trade_id}"
        return f"EVENT:{self.event.raw_hash}"


def parse_order_trade_update(event_or_payload: NormalizedUserEvent | Mapping[str, Any]) -> BinanceOrderTradeUpdate:
    event = event_or_payload if isinstance(event_or_payload, NormalizedUserEvent) else normalize_user_event(event_or_payload)
    order = event.payload.get("o") if isinstance(event.payload.get("o"), Mapping) else {}
    return BinanceOrderTradeUpdate(
        event=event,
        client_order_id=str(order.get("c")) if order.get("c") is not None else None,
        exchange_order_id=str(order.get("i")) if order.get("i") is not None else None,
        execution_type=str(order.get("x")).upper() if order.get("x") is not None else None,
        order_status=str(order.get("X")).upper() if order.get("X") is not None else None,
        trade_id=str(order.get("t")) if order.get("t") is not None else None,
        last_fill_quantity=_dec(order.get("l")),
        last_fill_price=_dec(order.get("L")),
        cumulative_filled_quantity=_dec(order.get("z")),
        commission=_dec(order.get("n")),
        commission_asset=str(order.get("N")) if order.get("N") is not None else None,
        order_trade_time_ms=int(order["T"]) if order.get("T") is not None else None,
    )


@dataclass(frozen=True)
class UserEventApplyResult:
    accepted: bool
    duplicate: bool
    correlated: bool
    intent_id: str | None
    client_order_id: str | None
    exchange_order_id: str | None
    status: BridgeStatus | None
    fill_id: str | None = None
    reason: str | None = None


class BinanceExecutionCorrelation:
    """Correlates Binance user-data order updates to committed intents.

    The correlator is intentionally network-free. It uses user-stream evidence as the
    preferred source of truth, deduplicates trade updates, and can drive a REST query only
    when a previously UNKNOWN submit needs reconciliation.
    """

    def __init__(self, bridge: ExecutionBridge | None = None, durable_store: DurableExecutionCorrelationStore | None = None, now_epoch: Any | None = None,
                 dispatch_attempt_ledger: DurableDispatchAttemptLedger | None = None,
                 dispatch_reconciliation_ledger: DurableDispatchReconciliationLedger | None = None):
        self.bridge = bridge or ExecutionBridge()
        self.durable_store = durable_store
        self.dispatch_attempt_ledger = dispatch_attempt_ledger
        self.dispatch_reconciliation_ledger = dispatch_reconciliation_ledger
        import time
        self._now_epoch = now_epoch or time.time
        self._by_client: dict[str, str] = {}
        self._by_exchange: dict[str, str] = {}
        self._intents: dict[str, OrderIntent] = {}
        self._seen_event_keys: set[str] = set()
        self._fill_ids_by_trade: dict[str, str] = {}

    def register(self, *, intent: OrderIntent, client_order_id: str, order_request_id: str | None = None) -> None:
        if not client_order_id:
            raise ValueError("CLIENT_ORDER_ID_REQUIRED")
        prior = self._by_client.get(client_order_id)
        if prior is not None and prior != intent.intent_id:
            raise ValueError("CLIENT_ORDER_ID_CORRELATION_CONFLICT")
        self._by_client[client_order_id] = intent.intent_id
        self._intents[intent.intent_id] = intent
        if self.durable_store is not None:
            self.durable_store.register(intent_id=intent.intent_id, order_request_id=order_request_id, client_order_id=client_order_id, now_epoch=float(self._now_epoch()))

    def bind_exchange_order(self, *, intent_id: str, exchange_order_id: str) -> None:
        if not exchange_order_id:
            raise ValueError("EXCHANGE_ORDER_ID_REQUIRED")
        prior = self._by_exchange.get(exchange_order_id)
        if prior is not None and prior != intent_id:
            raise ValueError("EXCHANGE_ORDER_ID_CORRELATION_CONFLICT")
        self._by_exchange[exchange_order_id] = intent_id
        if self.durable_store is not None:
            self.durable_store.bind_exchange(intent_id=intent_id, exchange_order_id=exchange_order_id, now_epoch=float(self._now_epoch()))

    def correlate(self, *, client_order_id: str | None, exchange_order_id: str | None) -> str | None:
        by_client = self._by_client.get(client_order_id) if client_order_id else None
        by_exchange = self._by_exchange.get(exchange_order_id) if exchange_order_id else None
        if by_client and by_exchange and by_client != by_exchange:
            raise ValueError("ORDER_CORRELATION_CONFLICT")
        intent_id = by_client or by_exchange
        if intent_id is None and self.durable_store is not None:
            record = self.durable_store.correlate(client_order_id=client_order_id, exchange_order_id=exchange_order_id)
            intent_id = record.intent_id if record else None
            if intent_id is not None:
                self._by_client[record.client_order_id] = record.intent_id
                if record.exchange_order_id:
                    self._by_exchange[record.exchange_order_id] = record.intent_id
        return intent_id

    def observe(self, event_or_payload: NormalizedUserEvent | Mapping[str, Any]) -> UserEventApplyResult:
        event = event_or_payload if isinstance(event_or_payload, NormalizedUserEvent) else normalize_user_event(event_or_payload)
        if event.event_type is not UserEventType.ORDER_TRADE_UPDATE:
            return UserEventApplyResult(False, False, False, None, None, None, None, reason="NOT_ORDER_TRADE_UPDATE")
        update = parse_order_trade_update(event)
        key = update.dedupe_key
        if key in self._seen_event_keys:
            intent_id = self.correlate(client_order_id=update.client_order_id, exchange_order_id=update.exchange_order_id)
            return UserEventApplyResult(True, True, intent_id is not None, intent_id,
                                        update.client_order_id, update.exchange_order_id, None,
                                        reason="DUPLICATE_USER_EVENT")
        self._seen_event_keys.add(key)
        intent_id = self.correlate(client_order_id=update.client_order_id, exchange_order_id=update.exchange_order_id)
        if intent_id is None:
            if self.durable_store is not None:
                self.durable_store.append_event(event_id=update.event.raw_hash, intent_id=None, client_order_id=update.client_order_id,
                                                 exchange_order_id=update.exchange_order_id, event_type=update.event.event_type.value,
                                                 raw_hash=update.event.raw_hash, observed_at_epoch=float(self._now_epoch()), payload=update.event.payload)
            return UserEventApplyResult(True, False, False, None, update.client_order_id,
                                        update.exchange_order_id, BridgeStatus.RECONCILIATION_REQUIRED,
                                        reason="UNCORRELATED_EXCHANGE_ORDER")
        if update.exchange_order_id:
            self.bind_exchange_order(intent_id=intent_id, exchange_order_id=update.exchange_order_id)
        if self.durable_store is not None:
            record = self.durable_store.correlate(client_order_id=update.client_order_id, exchange_order_id=update.exchange_order_id)
            self.durable_store.append_event(event_id=update.event.raw_hash, intent_id=record.intent_id if record else intent_id,
                                             client_order_id=update.client_order_id, exchange_order_id=update.exchange_order_id,
                                             event_type=update.event.event_type.value, raw_hash=update.event.raw_hash,
                                             observed_at_epoch=float(self._now_epoch()), payload=update.event.payload)
        self._reconcile_dispatch_attempt_from_user_event(update, intent_id=intent_id)
        status_obs = self.bridge.observe_ack(
            intent_id=intent_id,
            status=update.order_status or "UNKNOWN",
            exchange_order_id=update.exchange_order_id,
            client_order_id=update.client_order_id,
            executed_qty=update.cumulative_filled_quantity,
        )
        fill_id = None
        if update.is_trade:
            fill_id = f"binance-trade:{update.exchange_order_id}:{update.trade_id}"
            fill = Fill(
                fill_id=fill_id,
                order_request_id=self.bridge._requests[intent_id].order_request_id,
                exchange_order_id=update.exchange_order_id or "",
                quantity=update.last_fill_quantity,
                price=update.last_fill_price,
                fee=update.commission,
                event_time=update.order_trade_time_ms,
                trade_id=update.trade_id,
                venue="BINANCE",
            )
            # FillLedger is authoritative for duplicate protection; keep explicit trade-id
            # tracking as a second correlation guard.
            if update.trade_id not in self._fill_ids_by_trade:
                self.bridge.apply_fill(intent=self._intents[intent_id], fill=fill)
                self._fill_ids_by_trade[update.trade_id or key] = fill_id
            else:
                fill_id = self._fill_ids_by_trade[update.trade_id]
        return UserEventApplyResult(True, False, True, intent_id, update.client_order_id,
                                    update.exchange_order_id, status_obs.status, fill_id=fill_id)

    def _reconcile_dispatch_attempt_from_user_event(self, update: BinanceOrderTradeUpdate, *, intent_id: str) -> None:
        ledger = self.dispatch_reconciliation_ledger
        attempt_ledger = self.dispatch_attempt_ledger
        if ledger is None or attempt_ledger is None or not update.client_order_id:
            return
        req = self.bridge._requests.get(intent_id)
        if req is None or not getattr(req, "order_request_id", None):
            return
        attempt = attempt_ledger.get(req.order_request_id)
        if attempt is None or attempt.state not in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
            return
        status = (update.order_status or "").upper()
        target = {
            "NEW": DispatchAttemptState.ACKNOWLEDGED,
            "PARTIALLY_FILLED": DispatchAttemptState.ACKNOWLEDGED,
            "FILLED": DispatchAttemptState.ACKNOWLEDGED,
            "CANCELED": DispatchAttemptState.CANCELLED,
            "CANCELLED": DispatchAttemptState.CANCELLED,
            "REJECTED": DispatchAttemptState.REJECTED,
            "EXPIRED": DispatchAttemptState.REJECTED,
        }.get(status)
        if target is None:
            return
        evidence_payload = {
            "raw_hash": update.event.raw_hash,
            "event_type": update.event.event_type.value,
            "client_order_id": update.client_order_id,
            "exchange_order_id": update.exchange_order_id,
            "execution_type": update.execution_type,
            "order_status": update.order_status,
        }
        try:
            ledger.reconcile(
                order_request_id=req.order_request_id,
                resolved_state=target,
                evidence_id=update.event.raw_hash,
                evidence_source="USER_STREAM",
                evidence_fingerprint=DurableDispatchReconciliationLedger.evidence_fingerprint(evidence_payload),
                exchange_order_id=update.exchange_order_id,
                observed_at_ms=int(float(self._now_epoch()) * 1000),
            )
        except DispatchReconciliationConflict:
            raise

    def submit_and_reconcile(self, *, intent: OrderIntent, client_order_id: str,
                             gateway: BinanceTestnetExecutionGateway,
                             credentials: RuntimeCredentialValues,
                             exchange_submit) -> ExecutionObservation:
        """Network boundary helper: submit once; on transport ambiguity, query without retrying.

        `exchange_submit` is a callable accepting the committed OrderRequest and credentials;
        in production this is `gateway.submit`. A transport exception never triggers a second
        POST. The following GET is a reconciliation action keyed by the same clientOrderId.
        """
        self.register(intent=intent, client_order_id=client_order_id)
        req = self.bridge._requests.get(intent.intent_id)
        if req is None:
            raise ValueError("ORDER_REQUEST_NOT_COMMITTED")
        try:
            obs: SubmitObservation = exchange_submit(req, credentials=credentials)
        except ExchangeUncertain:
            self.bridge.mark_unknown(intent.intent_id, exchange_order_id=None, client_order_id=client_order_id)
            req_for_unknown = self.bridge._requests.get(intent.intent_id)
            if self.dispatch_attempt_ledger is not None and req_for_unknown is not None:
                attempt = self.dispatch_attempt_ledger.get(req_for_unknown.order_request_id)
                if attempt is not None and attempt.state is DispatchAttemptState.PENDING:
                    self.dispatch_attempt_ledger.observe(
                        order_request_id=req_for_unknown.order_request_id,
                        state=DispatchAttemptState.UNKNOWN,
                        exchange_order_id=None,
                        outcome="UNKNOWN",
                        reason="SUBMIT_EXCEPTION",
                        observed_at_ms=int(float(self._now_epoch()) * 1000),
                    )
            return self.reconcile_unknown(intent_id=intent.intent_id, gateway=gateway, credentials=credentials)
        if obs.exchange_order_id:
            self.bind_exchange_order(intent_id=intent.intent_id, exchange_order_id=obs.exchange_order_id)
        status = {
            ExchangeOutcome.ACKNOWLEDGED: "ACKNOWLEDGED",
            ExchangeOutcome.REJECTED: "REJECTED",
            ExchangeOutcome.CANCELLED: "CANCELLED",
            ExchangeOutcome.UNKNOWN: "UNKNOWN",
        }[obs.outcome]
        return self.bridge.observe_ack(
            intent_id=intent.intent_id, status=status,
            exchange_order_id=obs.exchange_order_id, client_order_id=obs.client_order_id,
        )

    def _reconcile_dispatch_attempt_from_rest(self, *, intent_id: str, req: Any, observation: SubmitObservation, resolved_state: DispatchAttemptState) -> None:
        ledger = self.dispatch_reconciliation_ledger
        attempt_ledger = self.dispatch_attempt_ledger
        if ledger is None or attempt_ledger is None:
            return
        attempt = attempt_ledger.get(req.order_request_id)
        if attempt is None or attempt.state not in {DispatchAttemptState.PENDING, DispatchAttemptState.UNKNOWN}:
            return
        payload = {
            "source": "REST_ORDER_STATUS",
            "intent_id": intent_id,
            "order_request_id": req.order_request_id,
            "client_order_id": observation.client_order_id,
            "exchange_order_id": observation.exchange_order_id,
            "outcome": observation.outcome.value,
            "raw": dict(observation.raw or {}),
        }
        evidence_fp = DurableDispatchReconciliationLedger.evidence_fingerprint(payload)
        evidence_id = f"REST_ORDER_STATUS:{intent_id}:{observation.client_order_id}:{observation.exchange_order_id or 'NONE'}:{observation.outcome.value}"
        ledger.reconcile(
            order_request_id=req.order_request_id,
            resolved_state=resolved_state,
            evidence_id=evidence_id,
            evidence_source="REST_ORDER_STATUS",
            evidence_fingerprint=evidence_fp,
            exchange_order_id=observation.exchange_order_id,
            observed_at_ms=int(float(self._now_epoch()) * 1000),
        )

    def reconcile_unknown(self, *, intent_id: str, gateway: BinanceTestnetExecutionGateway,
                          credentials: RuntimeCredentialValues) -> ExecutionObservation:
        req = self.bridge._requests.get(intent_id)
        if req is None:
            raise ValueError("ORDER_REQUEST_NOT_COMMITTED")
        self.bridge.assert_reconciliation_open(intent_id)
        try:
            obs = gateway.query(symbol=req.symbol, client_order_id=req.client_order_id, credentials=credentials)
        except ExchangeUncertain:
            raise
        self.register(intent=self._intents[intent_id], client_order_id=req.client_order_id)
        if obs.exchange_order_id:
            self.bind_exchange_order(intent_id=intent_id, exchange_order_id=obs.exchange_order_id)
        raw_status = str(obs.raw.get("status", "")).upper() if obs.raw else ""
        state = {
            "NEW": OrderExecutionState.ACKNOWLEDGED,
            "PARTIALLY_FILLED": OrderExecutionState.PARTIALLY_FILLED,
            "FILLED": OrderExecutionState.FILLED,
            "CANCELED": OrderExecutionState.CANCELLED,
            "CANCELLED": OrderExecutionState.CANCELLED,
            "REJECTED": OrderExecutionState.REJECTED,
            "EXPIRED": OrderExecutionState.EXPIRED,
        }.get(raw_status, gateway.lifecycle_target(obs))
        if state is OrderExecutionState.UNKNOWN:
            return self.bridge.reconcile_resolved(
                intent_id, resolved_state=OrderExecutionState.UNKNOWN,
                evidence_id="rest-query-unknown", resolution=UnknownResolution.STILL_UNKNOWN,
            )
        if state is OrderExecutionState.FILLED:
            # A REST order-status response does not by itself provide a trade-level fill ID.
            # Never synthesize fills or mark accounting complete without user-stream trade evidence.
            if obs.raw and _dec(obs.raw.get("executedQty"), Decimal("0")) > self.bridge.fill_ledger.total_quantity(req.order_request_id):
                return self.bridge.reconcile_resolved(
                    intent_id, resolved_state=OrderExecutionState.UNKNOWN,
                    evidence_id="rest-query-filled-accounting-gap", resolution=UnknownResolution.STILL_UNKNOWN,
                )
            self._reconcile_dispatch_attempt_from_rest(
                intent_id=intent_id, req=req, observation=obs,
                resolved_state=DispatchAttemptState.ACKNOWLEDGED,
            )
            return self.bridge.reconcile_resolved(
                intent_id, resolved_state=OrderExecutionState.FILLED,
                evidence_id="rest-query-filled", resolution=UnknownResolution.FILLED,
            )
        if state in {OrderExecutionState.ACKNOWLEDGED, OrderExecutionState.PARTIALLY_FILLED, OrderExecutionState.CANCELLED, OrderExecutionState.REJECTED, OrderExecutionState.EXPIRED}:
            self._reconcile_dispatch_attempt_from_rest(
                intent_id=intent_id, req=req, observation=obs, resolved_state={
                    OrderExecutionState.ACKNOWLEDGED: DispatchAttemptState.ACKNOWLEDGED,
                    OrderExecutionState.PARTIALLY_FILLED: DispatchAttemptState.ACKNOWLEDGED,
                    OrderExecutionState.CANCELLED: DispatchAttemptState.CANCELLED,
                    OrderExecutionState.REJECTED: DispatchAttemptState.REJECTED,
                    OrderExecutionState.EXPIRED: DispatchAttemptState.REJECTED,
                }[state],
            )
        resolution = {
            OrderExecutionState.CANCELLED: UnknownResolution.CANCELLED,
            OrderExecutionState.REJECTED: UnknownResolution.REJECTED,
            OrderExecutionState.EXPIRED: UnknownResolution.EXPIRED,
        }.get(state, UnknownResolution.RECONCILED)
        return self.bridge.reconcile_resolved(intent_id, resolved_state=state, evidence_id="rest-query", resolution=resolution)
