from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any, Mapping

from trading_platform.realtime.orderbook import OrderBook, OrderBookSnapshot
from trading_platform.v21.event_store import sha256_json


class LiquidityAssessmentError(ValueError):
    """Raised when a source-bound order-book liquidity assessment is invalid."""


def _decimal(value: Decimal | int | float | str, reason: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise LiquidityAssessmentError(reason) from exc
    if not result.is_finite():
        raise LiquidityAssessmentError(reason)
    return result


@dataclass(frozen=True)
class LiquidityAssessment:
    symbol: str
    assessment_id: str
    source_evidence_id: str
    side: str
    requested_quantity: Decimal
    observed_at_ns: int
    valid_until_ns: int
    depth_levels: int
    max_spread_bps: Decimal
    max_impact_bps: Decimal
    last_update_id: int
    bids: tuple[tuple[Decimal, Decimal], ...]
    asks: tuple[tuple[Decimal, Decimal], ...]
    orderbook_hash: str
    mid_price: Decimal
    spread_bps: Decimal
    side_depth_notional: Decimal
    executed_notional: Decimal
    execution_vwap: Decimal
    market_impact_bps: Decimal
    depth_utilization: Decimal
    liquidity_stress: Decimal

    @staticmethod
    def _book_payload(
        *, symbol: str, last_update_id: int,
        bids: tuple[tuple[Decimal, Decimal], ...],
        asks: tuple[tuple[Decimal, Decimal], ...],
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "last_update_id": last_update_id,
            "bids": [[str(price), str(quantity)] for price, quantity in bids],
            "asks": [[str(price), str(quantity)] for price, quantity in asks],
        }

    @classmethod
    def assess(
        cls,
        *,
        symbol: str,
        source_evidence_id: str,
        verified: bool,
        side: str,
        requested_quantity: Decimal | int | float | str,
        snapshot: OrderBookSnapshot,
        observed_at_ns: int,
        ttl_ns: int,
        depth_levels: int = 5,
        max_spread_bps: Decimal | int | float | str,
        max_impact_bps: Decimal | int | float | str,
    ) -> "LiquidityAssessment":
        if (
            not isinstance(symbol, str) or not symbol.strip()
            or not isinstance(source_evidence_id, str) or not source_evidence_id.strip()
            or verified is not True
            or side not in {"BUY", "SELL"}
        ):
            raise LiquidityAssessmentError("LIQUIDITY_SOURCE_IDENTITY_REQUIRED")
        if not isinstance(observed_at_ns, int) or isinstance(observed_at_ns, bool) or observed_at_ns < 0:
            raise LiquidityAssessmentError("INVALID_LIQUIDITY_ASSESSMENT_TIME")
        if not isinstance(ttl_ns, int) or isinstance(ttl_ns, bool) or ttl_ns <= 0:
            raise LiquidityAssessmentError("INVALID_LIQUIDITY_ASSESSMENT_TTL")
        if not isinstance(depth_levels, int) or isinstance(depth_levels, bool) or not 1 <= depth_levels <= 100:
            raise LiquidityAssessmentError("INVALID_LIQUIDITY_DEPTH_LEVELS")
        quantity = _decimal(requested_quantity, "INVALID_LIQUIDITY_ORDER_QUANTITY")
        spread_limit = _decimal(max_spread_bps, "INVALID_LIQUIDITY_SPREAD_LIMIT")
        impact_limit = _decimal(max_impact_bps, "INVALID_LIQUIDITY_IMPACT_LIMIT")
        if quantity <= 0 or spread_limit <= 0 or impact_limit <= 0:
            raise LiquidityAssessmentError("INVALID_LIQUIDITY_ASSESSMENT_LIMIT")
        if not isinstance(snapshot, OrderBookSnapshot) or snapshot.last_update_id < 0:
            raise LiquidityAssessmentError("INVALID_ORDERBOOK_SNAPSHOT")
        book = OrderBook(symbol=symbol)
        try:
            book.load_snapshot(snapshot)
        except (TypeError, ValueError) as exc:
            raise LiquidityAssessmentError("INVALID_ORDERBOOK_SNAPSHOT") from exc
        if book.status.value != "SYNCHRONIZED":
            raise LiquidityAssessmentError("ORDERBOOK_NOT_SYNCHRONIZED")
        best_bid, best_ask = book.best_bid(), book.best_ask()
        if best_bid is None or best_ask is None:
            raise LiquidityAssessmentError("ORDERBOOK_TWO_SIDED_DEPTH_REQUIRED")
        bids = tuple(sorted(book.bids.items(), reverse=True)[:depth_levels])
        asks = tuple(sorted(book.asks.items())[:depth_levels])
        return cls._from_levels(
            symbol=symbol.strip().upper(), source_evidence_id=source_evidence_id.strip(), side=side,
            requested_quantity=quantity, observed_at_ns=observed_at_ns,
            valid_until_ns=observed_at_ns + ttl_ns, depth_levels=depth_levels,
            max_spread_bps=spread_limit, max_impact_bps=impact_limit,
            last_update_id=snapshot.last_update_id, bids=bids, asks=asks,
        )

    @classmethod
    def _from_levels(
        cls,
        *,
        symbol: str,
        source_evidence_id: str,
        side: str,
        requested_quantity: Decimal,
        observed_at_ns: int,
        valid_until_ns: int,
        depth_levels: int,
        max_spread_bps: Decimal,
        max_impact_bps: Decimal,
        last_update_id: int,
        bids: tuple[tuple[Decimal, Decimal], ...],
        asks: tuple[tuple[Decimal, Decimal], ...],
    ) -> "LiquidityAssessment":
        if (
            not isinstance(symbol, str) or not symbol.strip() or symbol != symbol.strip().upper()
            or not isinstance(source_evidence_id, str) or not source_evidence_id.strip()
            or side not in {"BUY", "SELL"}
            or not isinstance(observed_at_ns, int) or isinstance(observed_at_ns, bool) or observed_at_ns < 0
            or not isinstance(valid_until_ns, int) or isinstance(valid_until_ns, bool) or valid_until_ns <= observed_at_ns
            or not isinstance(depth_levels, int) or isinstance(depth_levels, bool) or not 1 <= depth_levels <= 100
            or not isinstance(last_update_id, int) or isinstance(last_update_id, bool) or last_update_id < 0
            or not isinstance(requested_quantity, Decimal) or not requested_quantity.is_finite() or requested_quantity <= 0
            or not isinstance(max_spread_bps, Decimal) or not max_spread_bps.is_finite() or max_spread_bps <= 0
            or not isinstance(max_impact_bps, Decimal) or not max_impact_bps.is_finite() or max_impact_bps <= 0
            or len(bids) > depth_levels or len(asks) > depth_levels
        ):
            raise LiquidityAssessmentError("INVALID_LIQUIDITY_ASSESSMENT_INPUT")
        validator = OrderBook(symbol=symbol)
        try:
            validator.load_snapshot(OrderBookSnapshot(last_update_id=last_update_id, bids=bids, asks=asks))
        except (TypeError, ValueError) as exc:
            raise LiquidityAssessmentError("INVALID_ORDERBOOK_SNAPSHOT") from exc
        if tuple(sorted(validator.bids.items(), reverse=True)) != bids or tuple(sorted(validator.asks.items())) != asks:
            raise LiquidityAssessmentError("INVALID_ORDERBOOK_LEVELS")
        if not bids or not asks:
            raise LiquidityAssessmentError("ORDERBOOK_TWO_SIDED_DEPTH_REQUIRED")
        best_bid, best_ask = bids[0][0], asks[0][0]
        if best_bid <= 0 or best_ask <= 0 or best_bid > best_ask:
            raise LiquidityAssessmentError("INVALID_ORDERBOOK_MARKET")
        mid = (best_bid + best_ask) / Decimal("2")
        spread_bps = (best_ask - best_bid) / mid * Decimal("10000")
        levels = asks if side == "BUY" else bids
        available_notional = sum((price * amount for price, amount in levels), Decimal("0"))
        remaining = requested_quantity
        executed_notional = Decimal("0")
        for price, amount in levels:
            take = min(remaining, amount)
            executed_notional += price * take
            remaining -= take
            if remaining == 0:
                break
        if remaining > 0:
            raise LiquidityAssessmentError("LIQUIDITY_DEPTH_INSUFFICIENT")
        execution_vwap = executed_notional / requested_quantity
        market_impact_bps = (
            (execution_vwap - mid) / mid if side == "BUY" else (mid - execution_vwap) / mid
        ) * Decimal("10000")
        market_impact_bps = max(Decimal("0"), market_impact_bps)
        depth_utilization = executed_notional / available_notional if available_notional > 0 else Decimal("1")
        stress = min(Decimal("1"), max(
            depth_utilization,
            spread_bps / max_spread_bps,
            market_impact_bps / max_impact_bps,
        ))
        book_body = cls._book_payload(symbol=symbol, last_update_id=last_update_id, bids=bids, asks=asks)
        orderbook_hash = sha256_json(book_body)
        identity = {
            "symbol": symbol,
            "source_evidence_id": source_evidence_id,
            "side": side,
            "requested_quantity": str(requested_quantity),
            "observed_at_ns": observed_at_ns,
            "valid_until_ns": valid_until_ns,
            "depth_levels": depth_levels,
            "max_spread_bps": str(max_spread_bps),
            "max_impact_bps": str(max_impact_bps),
            "orderbook_hash": orderbook_hash,
        }
        assessment_id = f"LQ-{sha256_json(identity)[:24]}"
        return cls(
            symbol=symbol, assessment_id=assessment_id, source_evidence_id=source_evidence_id,
            side=side, requested_quantity=requested_quantity, observed_at_ns=observed_at_ns,
            valid_until_ns=valid_until_ns, depth_levels=depth_levels,
            max_spread_bps=max_spread_bps, max_impact_bps=max_impact_bps,
            last_update_id=last_update_id, bids=bids, asks=asks, orderbook_hash=orderbook_hash,
            mid_price=mid, spread_bps=spread_bps, side_depth_notional=available_notional,
            executed_notional=executed_notional, execution_vwap=execution_vwap,
            market_impact_bps=market_impact_bps, depth_utilization=depth_utilization,
            liquidity_stress=stress,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "assessment_id": self.assessment_id,
            "source_evidence_id": self.source_evidence_id,
            "side": self.side,
            "requested_quantity": str(self.requested_quantity),
            "observed_at_ns": self.observed_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "depth_levels": self.depth_levels,
            "max_spread_bps": str(self.max_spread_bps),
            "max_impact_bps": str(self.max_impact_bps),
            "last_update_id": self.last_update_id,
            "bids": [[str(p), str(q)] for p, q in self.bids],
            "asks": [[str(p), str(q)] for p, q in self.asks],
            "orderbook_hash": self.orderbook_hash,
            "mid_price": str(self.mid_price),
            "spread_bps": str(self.spread_bps),
            "side_depth_notional": str(self.side_depth_notional),
            "executed_notional": str(self.executed_notional),
            "execution_vwap": str(self.execution_vwap),
            "market_impact_bps": str(self.market_impact_bps),
            "depth_utilization": str(self.depth_utilization),
            "liquidity_stress": str(self.liquidity_stress),
        }

    @property
    def source_fingerprint(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "LiquidityAssessment":
        try:
            bids = tuple((Decimal(str(row[0])), Decimal(str(row[1]))) for row in payload["bids"])
            asks = tuple((Decimal(str(row[0])), Decimal(str(row[1]))) for row in payload["asks"])
            assessment = cls._from_levels(
                symbol=str(payload["symbol"]), source_evidence_id=str(payload["source_evidence_id"]),
                side=str(payload["side"]), requested_quantity=Decimal(str(payload["requested_quantity"])),
                observed_at_ns=int(payload["observed_at_ns"]), valid_until_ns=int(payload["valid_until_ns"]),
                depth_levels=int(payload["depth_levels"]), max_spread_bps=Decimal(str(payload["max_spread_bps"])),
                max_impact_bps=Decimal(str(payload["max_impact_bps"])), last_update_id=int(payload["last_update_id"]),
                bids=bids, asks=asks,
            )
            # Preserve the persisted assessment ID for comparison after recomputing all metrics.
            assessment = cls(**{**assessment.__dict__, "assessment_id": str(payload["assessment_id"])})
            if not assessment.is_valid():
                raise ValueError("INVALID_LIQUIDITY_ASSESSMENT")
            supplied = dict(payload)
            supplied.pop("source_fingerprint", None)
            if supplied != assessment.payload():
                raise ValueError("LIQUIDITY_ASSESSMENT_PAYLOAD_MISMATCH")
            if str(payload.get("source_fingerprint", assessment.source_fingerprint)) != assessment.source_fingerprint:
                raise ValueError("LIQUIDITY_SOURCE_FINGERPRINT_MISMATCH")
            return assessment
        except Exception as exc:
            raise LiquidityAssessmentError("INVALID_LIQUIDITY_ASSESSMENT_PAYLOAD") from exc

    def is_valid(self) -> bool:
        try:
            if (
                not self.symbol or not self.source_evidence_id or self.side not in {"BUY", "SELL"}
                or not isinstance(self.observed_at_ns, int) or isinstance(self.observed_at_ns, bool)
                or self.observed_at_ns < 0 or not isinstance(self.valid_until_ns, int)
                or isinstance(self.valid_until_ns, bool) or self.valid_until_ns <= self.observed_at_ns
                or not isinstance(self.depth_levels, int) or isinstance(self.depth_levels, bool)
                or not 1 <= self.depth_levels <= 100 or self.last_update_id < 0
                or len(self.bids) > self.depth_levels or len(self.asks) > self.depth_levels
            ):
                return False
            recomputed = self._from_levels(
                symbol=self.symbol, source_evidence_id=self.source_evidence_id, side=self.side,
                requested_quantity=self.requested_quantity, observed_at_ns=self.observed_at_ns,
                valid_until_ns=self.valid_until_ns, depth_levels=self.depth_levels,
                max_spread_bps=self.max_spread_bps, max_impact_bps=self.max_impact_bps,
                last_update_id=self.last_update_id, bids=self.bids, asks=self.asks,
            )
            return (
                self.assessment_id == recomputed.assessment_id
                and self.orderbook_hash == recomputed.orderbook_hash
                and self.mid_price == recomputed.mid_price
                and self.spread_bps == recomputed.spread_bps
                and self.side_depth_notional == recomputed.side_depth_notional
                and self.executed_notional == recomputed.executed_notional
                and self.execution_vwap == recomputed.execution_vwap
                and self.market_impact_bps == recomputed.market_impact_bps
                and self.depth_utilization == recomputed.depth_utilization
                and self.liquidity_stress == recomputed.liquidity_stress
            )
        except (ArithmeticError, AttributeError, LiquidityAssessmentError, TypeError, ValueError):
            return False

    def source_fresh_at(self, now_ns: int) -> bool:
        return (
            isinstance(now_ns, int) and not isinstance(now_ns, bool)
            and self.is_valid() and self.observed_at_ns <= now_ns < self.valid_until_ns
        )

    def matches_order(self, *, symbol: str, side: str, quantity: Decimal | int | float | str) -> bool:
        try:
            return (
                self.symbol == str(symbol).strip().upper()
                and self.side == str(getattr(side, "value", side)).strip().upper()
                and self.requested_quantity == _decimal(quantity, "INVALID_LIQUIDITY_ORDER_QUANTITY")
            )
        except LiquidityAssessmentError:
            return False
