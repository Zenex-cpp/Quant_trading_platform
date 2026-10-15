from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping, Protocol
import hashlib, json, uuid

from trading_platform.v17.workflow import TestnetWorkflow, MutationApproval, WorkflowStatus
from trading_platform.v17.evidence import EvidenceArtifact, canonical_json, utc_now

class OrderMode(str, Enum): TEST_ONLY = "TEST_ONLY"

class OrderTransport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str,str] | None=None, params: Mapping[str,Any] | None=None) -> Mapping[str,Any]: ...

@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: str
    order_type: str
    quantity: str
    price: str | None = None
    position_side: str = "BOTH"
    reduce_only: bool = False
    time_in_force: str = "GTC"
    client_order_id: str = ""
    mode: OrderMode = OrderMode.TEST_ONLY

    def validate(self, hard_cap_usdt: float, reference_price: Decimal | None = None) -> None:
        if not self.symbol or not self.symbol.isalnum(): raise ValueError("INVALID_SYMBOL")
        if self.side not in {"BUY", "SELL"}: raise ValueError("INVALID_SIDE")
        if self.order_type not in {"LIMIT", "MARKET"}: raise ValueError("UNSUPPORTED_ORDER_TYPE")
        try: qty=Decimal(self.quantity)
        except InvalidOperation: raise ValueError("INVALID_QUANTITY")
        if qty <= 0: raise ValueError("INVALID_QUANTITY")
        if self.order_type == "LIMIT":
            if not self.price: raise ValueError("LIMIT_PRICE_REQUIRED")
            try: px=Decimal(self.price)
            except InvalidOperation: raise ValueError("INVALID_PRICE")
            if px <= 0: raise ValueError("INVALID_PRICE")
            notional=qty*px
        else:
            if reference_price is None: raise ValueError("MARKET_REFERENCE_PRICE_REQUIRED")
            if reference_price <= 0: raise ValueError("INVALID_REFERENCE_PRICE")
            notional=qty*reference_price
        if notional > Decimal(str(hard_cap_usdt)):
            raise PermissionError("ORDER_NOTIONAL_CAP_EXCEEDED")
        if len(self.client_order_id) > 32 or (self.client_order_id and not all(c.isalnum() or c in '._:/-' for c in self.client_order_id)):
            raise ValueError("INVALID_CLIENT_ORDER_ID")

    @classmethod
    def deterministic(cls, *, symbol: str, side: str, order_type: str, quantity: str,
                      price: str | None = None, sequence: int = 1, **kwargs: Any) -> "OrderIntent":
        seed = canonical_json({"symbol":symbol,"side":side,"order_type":order_type,"quantity":quantity,"price":price,"sequence":sequence})
        cid = "tp18-" + hashlib.sha256(seed).hexdigest()[:20]
        return cls(symbol, side, order_type, quantity, price, client_order_id=cid, **kwargs)

    def params(self) -> dict[str,Any]:
        p={"symbol":self.symbol,"side":self.side,"type":self.order_type,"quantity":self.quantity,"positionSide":self.position_side,
           "reduceOnly":"true" if self.reduce_only else "false","newClientOrderId":self.client_order_id,"newOrderRespType":"ACK"}
        if self.order_type == "LIMIT":
            p["timeInForce"]=self.time_in_force
            p["price"]=self.price
        return p

@dataclass(frozen=True)
class OrderObservation:
    status: str
    order_id: str | None
    client_order_id: str | None
    raw_hash: str

class SafeTestnetExecution:
    """Execution-safe Testnet adapter. It exposes TEST_ORDER by default; live order submission is explicit."""
    def __init__(self, workflow: TestnetWorkflow, *, transport: OrderTransport | None=None):
        self.workflow=workflow
        self.transport=transport or workflow.transport

    @staticmethod
    def _hash(v: Any)->str:
        return hashlib.sha256(canonical_json(v)).hexdigest()

    def _call(self, method: str, path: str, params: Mapping[str,Any]) -> Mapping[str,Any]:
        return self.transport.request(method, self.workflow.config.base_url.rstrip('/') + path, params=params, headers={'Accept':'application/json'})

    def test_order(self, intent: OrderIntent, *, reference_price: Decimal | None=None) -> OrderObservation:
        intent.validate(self.workflow.config.hard_mutation_cap_usdt, reference_price)
        if intent.mode is not OrderMode.TEST_ONLY:
            raise PermissionError("TESTNET_ONLY_ORDER_MODE_REQUIRED")
        started=utc_now()
        try:
            resp=self._call("POST", "/fapi/v1/order/test", intent.params())
            raw_hash=self._hash(resp)
            status="PASS"
            order_id=str(resp.get("orderId")) if resp.get("orderId") is not None else None
            cid=resp.get("clientOrderId", intent.client_order_id)
            obs=("test_order_acknowledged","mutation=false")
        except Exception as exc:
            raw_hash=self._hash({"error":type(exc).__name__,"message":str(exc)})
            status="FAIL"; order_id=None; cid=intent.client_order_id; obs=(type(exc).__name__+":"+str(exc),)
        art=EvidenceArtifact(
            evidence_id=f"TN-04-{uuid.uuid4().hex[:12]}", scenario_id="TN-04", status=status,
            environment=self.workflow.config.environment.value, started_at=started, completed_at=utc_now(),
            correlation_id=self.workflow.correlation_id, operator_id=self.workflow.operator_id,
            endpoint=self.workflow.config.base_url+"/fapi/v1/order/test",
            request_hash=self._hash({"method":"POST","path":"/fapi/v1/order/test","params":intent.params()}),
            response_hash=raw_hash, pre_snapshot_hash=None, post_snapshot_hash=None,
            reconciliation="NOT_APPLICABLE", observations=obs,
            references=("https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api/New-Order-Test",),
        ).sealed()
        self.workflow.evidence.append(art)
        return OrderObservation(status, order_id, cid, raw_hash)

    def authorize_mutation(self, approval: MutationApproval, *, decision_fresh: bool=True):
        decision=self.workflow.mutation_gate(approval, decision_fresh=decision_fresh)
        if not decision.allowed:
            raise PermissionError("MUTATION_BLOCKED:"+"|".join(decision.reasons))
        return decision

    def place_order(self, intent: OrderIntent, approval: MutationApproval, *, decision_fresh: bool=True,
                    reference_price: Decimal | None=None) -> OrderObservation:
        self.authorize_mutation(approval, decision_fresh=decision_fresh)
        intent.validate(self.workflow.config.hard_mutation_cap_usdt, reference_price)
        started=utc_now()
        resp=self._call("POST", "/fapi/v1/order", intent.params())
        raw_hash=self._hash(resp)
        art=EvidenceArtifact(
            evidence_id=f"TN-05-{uuid.uuid4().hex[:12]}", scenario_id="TN-05", status="PASS",
            environment=self.workflow.config.environment.value, started_at=started, completed_at=utc_now(),
            correlation_id=self.workflow.correlation_id, operator_id=self.workflow.operator_id,
            endpoint=self.workflow.config.base_url+"/fapi/v1/order", request_hash=self._hash(intent.params()),
            response_hash=raw_hash, pre_snapshot_hash=None, post_snapshot_hash=None,
            reconciliation="PENDING", observations=("controlled_order_submitted", "notional_cap_enforced"),
            references=("https://developers.binance.com/docs/derivatives/usds-margined-futures/trade/rest-api",),
        ).sealed()
        self.workflow.evidence.append(art)
        return OrderObservation("PASS", str(resp.get("orderId")) if resp.get("orderId") is not None else None,
                                resp.get("clientOrderId", intent.client_order_id), raw_hash)

    def query_order(self, *, symbol: str, order_id: str | None=None, client_order_id: str | None=None) -> Mapping[str,Any]:
        if not order_id and not client_order_id: raise ValueError("ORDER_IDENTIFIER_REQUIRED")
        p={"symbol":symbol}
        if order_id: p["orderId"]=order_id
        else: p["origClientOrderId"]=client_order_id
        return self._call("GET", "/fapi/v1/order", p)

    def cancel_order(self, *, symbol: str, order_id: str | None=None, client_order_id: str | None=None,
                     approval: MutationApproval | None=None, decision_fresh: bool=True) -> Mapping[str,Any]:
        if approval is None: raise PermissionError("EXPLICIT_APPROVAL_REQUIRED")
        self.authorize_mutation(approval, decision_fresh=decision_fresh)
        if not order_id and not client_order_id: raise ValueError("ORDER_IDENTIFIER_REQUIRED")
        p={"symbol":symbol}
        if order_id: p["orderId"]=order_id
        else: p["origClientOrderId"]=client_order_id
        return self._call("DELETE", "/fapi/v1/order", p)
