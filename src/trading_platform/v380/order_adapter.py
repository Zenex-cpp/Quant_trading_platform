"""V3.80 venue-complete Binance Testnet order-request boundary.

V3.79 intentionally blocked LIMIT requests because the legacy OrderRequest did not
carry price/time-in-force. V3.80 extends the request contract and introduces a
versioned adapter/gateway boundary without mutating the frozen V3.79 adapter.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from trading_platform.execution.models import OrderIntent, OrderRequest, OrderType
from trading_platform.v35.binance_execution import (
    BinanceTestnetExecutionConfig,
    BinanceTestnetExecutionGateway,
    RuntimeCredentialValues,
    SubmitObservation,
)
from trading_platform.v379.execution_parity import TestnetMutationGate


class BinanceV380TestnetExecutionGateway(BinanceTestnetExecutionGateway):
    """V3.80 gateway parameter encoder; transport/signing stay in the V3.35 gateway."""

    __test__ = False

    @staticmethod
    def _params(order: OrderRequest) -> dict[str, str]:
        params = {
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.order_type.value,
            "quantity": str(order.quantity),
            "newClientOrderId": order.client_order_id,
        }
        if order.order_type is OrderType.LIMIT:
            if order.price is None or order.price <= 0:
                raise ValueError("LIMIT_PRICE_REQUIRED")
            if not order.time_in_force:
                raise ValueError("LIMIT_TIME_IN_FORCE_REQUIRED")
            params["price"] = str(order.price)
            params["timeInForce"] = str(order.time_in_force).upper()
        elif order.price is not None or order.time_in_force is not None:
            raise ValueError("MARKET_PRICE_TIF_NOT_ALLOWED")
        return params


class BinanceTestnetOrderAdapterV380:
    """Fail-closed V3.80 mapping from complete OrderIntent to OrderRequest."""

    def __init__(self, gateway: BinanceV380TestnetExecutionGateway, mutation_gate: TestnetMutationGate) -> None:
        self._gateway = gateway
        self._mutation_gate = mutation_gate

    @staticmethod
    def _client_order_id(intent: OrderIntent) -> str:
        return f"tp-{hashlib.sha256(intent.intent_id.encode()).hexdigest()[:24]}"

    def to_order_request(self, intent: OrderIntent, *, now: datetime) -> OrderRequest:
        intent.validate(now)
        if intent.order_type is OrderType.LIMIT:
            if intent.price is None or intent.price <= 0:
                raise ValueError("LIMIT_PRICE_REQUIRED")
            if not intent.time_in_force:
                raise ValueError("LIMIT_TIME_IN_FORCE_REQUIRED")
        elif intent.order_type is not OrderType.MARKET:
            raise ValueError("ORDER_TYPE_NOT_SUPPORTED")
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
            price=intent.price,
            time_in_force=intent.time_in_force,
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
        request = self.to_order_request(intent, now=now)
        return self._gateway.submit(request, credentials=credentials)
