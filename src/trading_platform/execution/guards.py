from datetime import datetime
from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderIntent, OrderRequest, PositionState

def validate_new_entry(*, position_state: PositionState, market_window: ValidWindow, decision_windows: list[ValidWindow], risk_valid: bool, now: datetime) -> None:
    if position_state == PositionState.UNKNOWN:
        raise ValueError("POSITION_UNKNOWN_BLOCKS_NEW_RISK")
    market_window.assert_valid(now)
    for w in decision_windows:
        w.assert_valid(now)
    if not risk_valid:
        raise ValueError("RISK_DECISION_INVALID")

def build_order_request(intent: OrderIntent, *, now: datetime, position_state: PositionState, market_window: ValidWindow, upstream_windows: list[ValidWindow], risk_valid: bool) -> OrderRequest:
    intent.validate(now)
    if intent.action in {intent.action.OPEN, intent.action.INCREASE}:
        validate_new_entry(position_state=position_state, market_window=market_window, decision_windows=upstream_windows, risk_valid=risk_valid, now=now)
    return OrderRequest(
        order_request_id=f"req:{intent.intent_id}", correlation_id=f"corr:{intent.intent_id}",
        idempotency_key=f"order:{intent.intent_id}", client_order_id=f"cid:{intent.intent_id}",
        intent_id=intent.intent_id, risk_decision_id=intent.risk_decision_id, execution_version=intent.execution_version,
        timestamp=now, deadline=intent.window.expires_at, symbol=intent.symbol, side=intent.side,
        order_type=intent.order_type, quantity=intent.quantity)
