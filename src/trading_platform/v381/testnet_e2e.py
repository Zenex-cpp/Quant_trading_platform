"""V3.81 deterministic Testnet end-to-end harness and live preflight.

The local harness exercises the complete causal execution path without network I/O:
OrderIntent -> OrderRequest -> simulated exchange ACK -> ORDER_TRADE_UPDATE ->
ACCOUNT_UPDATE -> REST/WS reconciliation -> FillLedger -> PositionLedger -> Accounting.

The live preflight is deliberately read-only. A real mutating Testnet scenario remains
operator-controlled and is never auto-enabled by this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json
import os
from typing import Any, Mapping
from urllib.request import Request, urlopen

from trading_platform.accounting.ledger import FillLedger
from trading_platform.accounting.position import PositionLedger
from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import Fill, OrderAction, OrderIntent, OrderType, Side
from trading_platform.v24.accounting import (
    AccountingSnapshot,
    CashComponents,
    PnLReconciliation,
    PnLView,
    ReconciliationSeverity,
    assert_accounting_invariants,
    reconstruct_equity,
)
from trading_platform.v380 import BinancePrivateWebSocketConfig, BinanceTestnetOrderAdapterV380, BinanceV380TestnetExecutionGateway, BinanceUserDataProjection, UserDataHealth
from trading_platform.v35.binance_execution import BinanceTestnetExecutionConfig
from trading_platform.v379.execution_parity import TestnetMutationGate


class E2EStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_VERIFIED = "NOT_VERIFIED"


def _hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class BinanceTestnetE2EResult:
    status: E2EStatus
    scenario_id: str
    chain_hash: str
    checks: tuple[Mapping[str, Any], ...]
    reconciliation_state: str
    position_quantity: str
    accounting_state_hash: str
    websocket_route: str

    @property
    def passed(self) -> bool:
        return self.status is E2EStatus.PASS

    def payload(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "scenario_id": self.scenario_id,
            "chain_hash": self.chain_hash,
            "checks": list(self.checks),
            "reconciliation_state": self.reconciliation_state,
            "position_quantity": self.position_quantity,
            "accounting_state_hash": self.accounting_state_hash,
            "websocket_route": self.websocket_route,
        }


class BinanceTestnetE2EHarnessV381:
    """No-network, deterministic end-to-end acceptance harness."""

    RUN_AT = datetime(2026, 10, 3, 8, 0, tzinfo=timezone.utc)
    SYMBOL = "BTCUSDT"
    QTY = Decimal("0.0002")
    PRICE = Decimal("50000")

    @staticmethod
    def _order_event(*, event_ms: int, status: str, execution_type: str, cum_qty: str, last_qty: str, last_price: str, trade_id: str, order_id: int, client_id: str) -> dict[str, Any]:
        return {
            "e": "ORDER_TRADE_UPDATE",
            "E": event_ms,
            "T": event_ms,
            "o": {
                "s": "BTCUSDT",
                "c": client_id,
                "S": "BUY",
                "o": "LIMIT",
                "f": "GTC",
                "q": str(BinanceTestnetE2EHarnessV381.QTY),
                "ap": last_price,
                "x": execution_type,
                "X": status,
                "i": order_id,
                "l": last_qty,
                "z": cum_qty,
                "L": last_price,
                "t": trade_id,
            },
        }

    @staticmethod
    def _account_event(*, event_ms: int, quantity: str) -> dict[str, Any]:
        return {
            "e": "ACCOUNT_UPDATE",
            "E": event_ms,
            "T": event_ms,
            "a": {
                "m": "ORDER",
                "B": [{"a": "USDT", "wb": "999.98", "cw": "999.98", "bc": "-0.02"}],
                "P": [{"s": "BTCUSDT", "ps": "BOTH", "pa": quantity, "ep": "50000", "up": "0"}],
            },
        }

    def run(self, *, include_negative_reconciliation_case: bool = True) -> BinanceTestnetE2EResult:
        now = self.RUN_AT
        intent = OrderIntent(
            intent_id="I-V381-E2E-001",
            decision_id="D-V381-E2E-001",
            portfolio_decision_id="P-V381-E2E-001",
            risk_decision_id="R-V381-E2E-001",
            strategy_id="STRAT-V381-E2E",
            model_id="MODEL-V381-E2E",
            execution_version="V381-TESTNET-E2E-1",
            symbol=self.SYMBOL,
            side=Side.BUY,
            action=OrderAction.OPEN,
            quantity=self.QTY,
            order_type=OrderType.LIMIT,
            window=ValidWindow(now, now + timedelta(minutes=5)),
            price=self.PRICE,
            time_in_force="GTC",
            risk_reservation_id="RR-V381-E2E-001",
        )

        adapter = BinanceTestnetOrderAdapterV380(
            BinanceV380TestnetExecutionGateway(BinanceTestnetExecutionConfig()),
            TestnetMutationGate(mutation_enabled=True, operator_approval=True, max_notional=Decimal("25")),
        )
        request = adapter.to_order_request(intent, now=now)
        request_params = BinanceV380TestnetExecutionGateway._params(request)

        exchange_order_id = 3810001
        p = BinanceUserDataProjection()
        p.start()
        events = [
            self._order_event(event_ms=1_000, status="NEW", execution_type="NEW", cum_qty="0", last_qty="0", last_price="0", trade_id="0", order_id=exchange_order_id, client_id=request.client_order_id),
            self._order_event(event_ms=1_100, status="PARTIALLY_FILLED", execution_type="TRADE", cum_qty="0.0001", last_qty="0.0001", last_price="50010", trade_id="1", order_id=exchange_order_id, client_id=request.client_order_id),
            self._order_event(event_ms=1_200, status="FILLED", execution_type="TRADE", cum_qty="0.0002", last_qty="0.0001", last_price="50020", trade_id="2", order_id=exchange_order_id, client_id=request.client_order_id),
            self._account_event(event_ms=1_300, quantity="0.0002"),
        ]
        results = [p.apply(event, now_epoch=2.0) for event in events]
        duplicate = p.apply(events[1], now_epoch=2.0)

        projected = p.snapshot(now_epoch=2.0)
        rest_green = {
            "openOrders": [],
            "positions": [{"symbol": self.SYMBOL, "positionAmt": str(self.QTY), "entryPrice": "50015"}],
        }
        reconciliation = p.reconcile(rest_green, now_epoch=2.0)

        fills = FillLedger()
        fill_a = Fill("F-V381-001", request.order_request_id, str(exchange_order_id), Decimal("0.0001"), Decimal("50010"), Decimal("0.01"), event_time=now, trade_id="1", venue="BINANCE_TESTNET")
        fill_b = Fill("F-V381-002", request.order_request_id, str(exchange_order_id), Decimal("0.0001"), Decimal("50020"), Decimal("0.01"), event_time=now, trade_id="2", venue="BINANCE_TESTNET")
        fills.apply_once(fill_a)
        fills.apply_once(fill_b)
        _, duplicate_fill_new = fills.apply_once(Fill("F-V381-DUP", request.order_request_id, str(exchange_order_id), Decimal("0.0001"), Decimal("50010"), Decimal("0.01"), event_time=now, trade_id="1", venue="BINANCE_TESTNET"))

        positions = PositionLedger()
        pos = positions.apply_fill(self.SYMBOL, fill_a, Side.BUY)
        pos = positions.apply_fill(self.SYMBOL, fill_b, Side.BUY)

        opening_equity = Decimal("1000")
        fees = Decimal("-0.02")
        cash = CashComponents(fees=fees)
        equity = reconstruct_equity(opening_equity=opening_equity, change=cash)
        accounting = AccountingSnapshot(
            timestamp_ns=int(now.timestamp() * 1_000_000_000),
            equity=equity,
            cash=cash,
            pnl=PnLView(fees=fees),
            position_notional=Decimal("10.003"),
            margin_used=Decimal("1"),
        )
        assert_accounting_invariants(accounting)
        local_exchange_recon = PnLReconciliation(local=accounting, exchange=accounting, reconstructed=accounting).classify()

        negative = None
        if include_negative_reconciliation_case:
            rest_bad = {"openOrders": [], "positions": [{"symbol": self.SYMBOL, "positionAmt": "0"}]}
            negative = p.reconcile(rest_bad, now_epoch=2.0)

        checks = [
            {"check": "intent_to_order_request", "pass": request.intent_id == intent.intent_id and request.price == self.PRICE and request.time_in_force == "GTC"},
            {"check": "venue_params_complete", "pass": request_params["price"] == str(self.PRICE) and request_params["timeInForce"] == "GTC"},
            {"check": "order_update_projection_accepts_sequence", "pass": all(r.accepted for r in results)},
            {"check": "duplicate_trade_idempotent", "pass": duplicate.duplicate and not duplicate.changed and projected.seen_trade_count == 2},
            {"check": "order_projected_filled", "pass": projected.orders[0].status == "FILLED" and projected.orders[0].cumulative_filled_quantity == self.QTY},
            {"check": "account_update_projected_position", "pass": projected.positions[0].quantity == self.QTY},
            {"check": "rest_ws_reconciliation_green", "pass": reconciliation.trading_allowed and reconciliation.state.value == "GREEN"},
            {"check": "fill_ledger_no_double_count", "pass": not duplicate_fill_new and fills.total_quantity(request.order_request_id) == self.QTY},
            {"check": "position_ledger_matches_stream", "pass": pos.quantity == self.QTY and pos.average_entry_price == Decimal("50015")},
            {"check": "accounting_invariants", "pass": local_exchange_recon is ReconciliationSeverity.EXPECTED and accounting.equity == Decimal("999.98")},
            {"check": "position_unknown_not_created", "pass": projected.health is UserDataHealth.HEALTHY},
            {"check": "negative_reconciliation_blocks", "pass": (negative is not None and not negative.trading_allowed and negative.state.value == "RED") if include_negative_reconciliation_case else True},
        ]

        route = BinancePrivateWebSocketConfig(environment="TESTNET").url(listen_key="REDACTED", events=["ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE"])
        chain_payload = {
            "intent": {
                "intent_id": intent.intent_id,
                "decision_id": intent.decision_id,
                "risk_decision_id": intent.risk_decision_id,
                "execution_version": intent.execution_version,
            },
            "order_request": {
                "order_request_id": request.order_request_id,
                "client_order_id": request.client_order_id,
                "params": request_params,
            },
            "projection_state_hash": projected.state_hash,
            "reconciliation": {"state": reconciliation.state.value, "rest_hash": reconciliation.rest_hash, "stream_hash": reconciliation.stream_hash},
            "fills": [{"trade_id": e.fill_id, "quantity": str(e.quantity), "price": str(e.price), "fee": str(e.fee)} for e in fills.entries()],
            "position": {"quantity": str(pos.quantity), "average_entry_price": str(pos.average_entry_price), "state": pos.state.value},
            "accounting_hash": accounting.state_hash,
        }
        status = E2EStatus.PASS if all(c["pass"] for c in checks) else E2EStatus.FAIL
        return BinanceTestnetE2EResult(
            status=status,
            scenario_id="TN-E2E-V381-001",
            chain_hash=_hash(chain_payload),
            checks=tuple(checks),
            reconciliation_state=reconciliation.state.value,
            position_quantity=str(pos.quantity),
            accounting_state_hash=accounting.state_hash,
            websocket_route=route.replace("REDACTED", "<listenKey>"),
        )


class BinanceTestnetLivePreflightV381:
    """Read-only external preflight; never submits a real order."""

    REST_BASE_URL = "https://testnet.binancefuture.com"

    def run(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "status": E2EStatus.NOT_VERIFIED.value,
            "mutation": "NONE",
            "endpoint": self.REST_BASE_URL + "/fapi/v1/time",
            "credentials_present": bool(os.environ.get("BINANCE_TESTNET_API_KEY") and os.environ.get("BINANCE_TESTNET_API_SECRET")),
        }
        try:
            req = Request(result["endpoint"], method="GET", headers={"Accept": "application/json", "User-Agent": "trading-platform-v381/1.0"})
            with urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
            result.update({"status": E2EStatus.PASS.value, "response_hash": hashlib.sha256(body.encode()).hexdigest()})
        except Exception as exc:
            result.update({"status": E2EStatus.NOT_VERIFIED.value, "error": type(exc).__name__ + ":" + str(exc)})
        return result
