from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from decimal import Decimal
from typing import Mapping, Any
from .event_store import sha256_json

class TemporalReconciliationState(str, Enum):
    VERIFIED="VERIFIED"
    DIVERGENT="DIVERGENT"
    UNKNOWN="UNKNOWN"
    RECOVERY_REQUIRED="RECOVERY_REQUIRED"

@dataclass(frozen=True)
class TemporalReconciliation:
    state: TemporalReconciliationState
    rest_hash: str
    stream_hash: str
    ledger_hash: str
    divergent_entities: tuple[str, ...] = ()
    reason: str = ""

    @property
    def trading_allowed(self) -> bool:
        return self.state is TemporalReconciliationState.VERIFIED


def reconcile_timeline(*, rest_snapshot: Mapping[str, Any], stream_snapshot: Mapping[str, Any], ledger_projection: Mapping[str, Any], stream_healthy: bool, gap_free: bool) -> TemporalReconciliation:
    if not stream_healthy:
        return TemporalReconciliation(TemporalReconciliationState.UNKNOWN, sha256_json(rest_snapshot), sha256_json(stream_snapshot), sha256_json(ledger_projection), reason="STREAM_UNHEALTHY")
    if not gap_free:
        return TemporalReconciliation(TemporalReconciliationState.RECOVERY_REQUIRED, sha256_json(rest_snapshot), sha256_json(stream_snapshot), sha256_json(ledger_projection), reason="STREAM_GAP")
    r_orders = {str(x.get("orderId")): x for x in rest_snapshot.get("openOrders", [])}
    s_orders = {str(x.get("orderId")): x for x in stream_snapshot.get("openOrders", [])}
    divergences=[]
    for key in sorted(set(r_orders) | set(s_orders)):
        if r_orders.get(key) != s_orders.get(key): divergences.append(f"order:{key}")
    r_pos = {str(x.get("symbol")): str(x.get("positionAmt", "0")) for x in rest_snapshot.get("positions", [])}
    s_pos = {str(x.get("symbol")): str(x.get("positionAmt", "0")) for x in stream_snapshot.get("positions", [])}
    l_pos = {str(x.get("symbol")): str(x.get("quantity", "0")) for x in ledger_projection.get("positions", [])}
    for key in sorted(set(r_pos) | set(s_pos) | set(l_pos)):
        if not (r_pos.get(key, "0") == s_pos.get(key, "0") == l_pos.get(key, "0")):
            divergences.append(f"position:{key}")
    state = TemporalReconciliationState.VERIFIED if not divergences else TemporalReconciliationState.DIVERGENT
    reason = "REST_STREAM_LEDGER_MATCH" if not divergences else "TEMPORAL_DIVERGENCE"
    return TemporalReconciliation(state, sha256_json(rest_snapshot), sha256_json(stream_snapshot), sha256_json(ledger_projection), tuple(divergences), reason)
