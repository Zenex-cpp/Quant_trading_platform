from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import FrozenSet
from trading_platform.core.ttl import ValidWindow

class OrderAction(str, Enum):
    OPEN="OPEN"
    INCREASE="INCREASE"
    DECREASE="DECREASE"
    CLOSE="CLOSE"
    NO_ACTION="NO_ACTION"

class Side(str, Enum):
    BUY="BUY"
    SELL="SELL"

class OrderType(str, Enum):
    MARKET="MARKET"
    LIMIT="LIMIT"

class OrderState(str, Enum):
    CREATED="CREATED"
    SUBMITTED="SUBMITTED"
    ACKNOWLEDGED="ACKNOWLEDGED"
    PARTIALLY_FILLED="PARTIALLY_FILLED"
    FILLED="FILLED"
    CANCEL_REQUESTED="CANCEL_REQUESTED"
    CANCELLED="CANCELLED"
    REJECTED="REJECTED"
    EXPIRED="EXPIRED"
    UNKNOWN="UNKNOWN"

class PositionState(str, Enum):
    FLAT="FLAT"
    OPENING="OPENING"
    OPEN="OPEN"
    REDUCING="REDUCING"
    CLOSING="CLOSING"
    CLOSED="CLOSED"
    UNKNOWN="UNKNOWN"

@dataclass(frozen=True)
class OrderIntent:
    intent_id: str
    decision_id: str
    portfolio_decision_id: str
    risk_decision_id: str
    strategy_id: str
    model_id: str
    execution_version: str
    symbol: str
    side: Side
    action: OrderAction
    quantity: Decimal
    order_type: OrderType
    window: ValidWindow
    price: Decimal | None=None
    time_in_force: str | None=None
    risk_reservation_id: str | None=None

    def validate(self, now):
        self.window.assert_valid(now)
        if self.quantity <= 0:
            raise ValueError("INVALID_ORDER_QUANTITY")
        if self.order_type == OrderType.LIMIT and (self.price is None or self.price <= 0):
            raise ValueError("INVALID_LIMIT_PRICE")

@dataclass(frozen=True)
class OrderRequest:
    order_request_id: str
    correlation_id: str
    idempotency_key: str
    client_order_id: str
    intent_id: str
    risk_decision_id: str
    execution_version: str
    timestamp: object
    deadline: object
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    time_in_force: str | None = None

@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_request_id: str
    exchange_order_id: str
    quantity: Decimal
    price: Decimal
    fee: Decimal
    funding: Decimal=Decimal("0")
    slippage: Decimal=Decimal("0")
    market_impact: Decimal=Decimal("0")
    event_time: object=None
    trade_id: str | None=None
    venue: str="UNKNOWN"
