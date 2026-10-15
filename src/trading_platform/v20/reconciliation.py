from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping
import hashlib, json

class ReconciliationState(str, Enum): GREEN='GREEN'; RED='RED'; UNKNOWN='UNKNOWN'; BLOCKED='BLOCKED'

@dataclass(frozen=True)
class OrderSnapshot:
    order_id: str
    client_order_id: str | None
    symbol: str
    status: str
    executed_qty: str
    avg_price: str | None = None
    event_time_ms: int | None = None

@dataclass(frozen=True)
class PositionSnapshot:
    symbol: str
    position_amt: str
    entry_price: str | None = None
    unrealized_pnl: str | None = None
    update_time_ms: int | None = None

@dataclass(frozen=True)
class AccountSnapshot:
    wallet_balance: str | None
    available_balance: str | None
    positions: tuple[PositionSnapshot, ...]
    open_orders: tuple[OrderSnapshot, ...]

@dataclass(frozen=True)
class ReconciliationDiff:
    missing_in_rest: tuple[str, ...] = ()
    missing_in_stream: tuple[str, ...] = ()
    status_mismatches: tuple[str, ...] = ()
    quantity_mismatches: tuple[str, ...] = ()
    position_mismatches: tuple[str, ...] = ()
    stale_stream: bool = False
    stream_unhealthy: bool = False

    @property
    def clean(self) -> bool:
        return not (self.missing_in_rest or self.missing_in_stream or self.status_mismatches or
                    self.quantity_mismatches or self.position_mismatches or self.stale_stream or self.stream_unhealthy)

@dataclass(frozen=True)
class ReconciliationResult:
    state: ReconciliationState
    diff: ReconciliationDiff
    rest_hash: str
    stream_hash: str
    reason: str

    @property
    def trading_allowed(self) -> bool:
        return self.state is ReconciliationState.GREEN and self.diff.clean


def _hash(v: Any) -> str:
    b=json.dumps(v, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(b).hexdigest()


def _order_key(o: Mapping[str, Any]) -> str:
    return str(o.get('orderId') if o.get('orderId') is not None else o.get('clientOrderId'))


def compare_order_sets(rest_orders: list[Mapping[str, Any]], stream_orders: list[Mapping[str, Any]], *, stream_healthy: bool=True, stream_stale: bool=False) -> ReconciliationDiff:
    r={_order_key(x):x for x in rest_orders}; s={_order_key(x):x for x in stream_orders}
    missing_r=tuple(sorted(set(r)-set(s)))
    missing_s=tuple(sorted(set(s)-set(r)))
    status=[]; qty=[]
    for k in sorted(set(r)&set(s)):
        if str(r[k].get('status')) != str(s[k].get('status')): status.append(k)
        rq=str(r[k].get('executedQty', r[k].get('executed_qty','')))
        sq=str(s[k].get('executedQty', s[k].get('executed_qty','')))
        if rq != sq: qty.append(k)
    return ReconciliationDiff(missing_r, missing_s, tuple(status), tuple(qty), (), stream_stale, not stream_healthy)


def compare_positions(rest_positions: list[Mapping[str, Any]], stream_positions: list[Mapping[str, Any]]) -> tuple[str, ...]:
    r={str(x.get('symbol')):str(x.get('positionAmt', x.get('position_amt',''))) for x in rest_positions}
    s={str(x.get('symbol')):str(x.get('positionAmt', x.get('position_amt',''))) for x in stream_positions}
    out=[]
    for k in sorted(set(r)|set(s)):
        if r.get(k) != s.get(k): out.append(k)
    return tuple(out)

class RestWebSocketReconciler:
    def reconcile(self, *, rest_account: Mapping[str, Any], stream_account: Mapping[str, Any],
                  stream_healthy: bool=True, stream_stale: bool=False, blocked_reason: str | None=None) -> ReconciliationResult:
        if blocked_reason:
            return ReconciliationResult(ReconciliationState.BLOCKED,
                ReconciliationDiff(stream_unhealthy=not stream_healthy, stale_stream=stream_stale),
                _hash(rest_account), _hash(stream_account), blocked_reason)
        ro=list(rest_account.get('openOrders', rest_account.get('orders', [])) or [])
        so=list(stream_account.get('openOrders', stream_account.get('orders', [])) or [])
        diff=compare_order_sets(ro, so, stream_healthy=stream_healthy, stream_stale=stream_stale)
        p_diff=compare_positions(list(rest_account.get('positions',[]) or []), list(stream_account.get('positions',[]) or []))
        diff=ReconciliationDiff(diff.missing_in_rest,diff.missing_in_stream,diff.status_mismatches,diff.quantity_mismatches,p_diff,diff.stale_stream,diff.stream_unhealthy)
        state=ReconciliationState.GREEN if diff.clean else ReconciliationState.RED
        reason='REST_WS_MATCH' if diff.clean else 'REST_WS_DIVERGENCE'
        return ReconciliationResult(state,diff,_hash(rest_account),_hash(stream_account),reason)
