from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.realtime.orderbook import OrderBookSnapshot
from trading_platform.v373.backtest_engine import BacktestStageFunctions, DeterminismClass, MarketEvent
from trading_platform.v378 import (
    BinanceTimeInForce,
    BinanceVenueExecutionEngine,
    BinanceVenueExecutionModelConfig,
    MarketTrade,
    VenueMarketEvent,
    VenueRejectReason,
)

ROOT = Path(__file__).resolve().parent
SYMBOL = "BTCUSDT"
TS = datetime(2026, 1, 1, tzinfo=timezone.utc)


def market(offset: int) -> MarketEvent:
    p = Decimal("100")
    return MarketEvent(offset, TS, SYMBOL, p, p, p, p, Decimal("100"))


def wrap(offset: int, bid_qty: str = "10", ask_qty: str = "10", trades=()):
    return VenueMarketEvent(
        market=market(offset),
        book=OrderBookSnapshot(
            last_update_id=100 + offset,
            bids=((Decimal("99"), Decimal(bid_qty)), (Decimal("98"), Decimal("20"))),
            asks=((Decimal("101"), Decimal(ask_qty)), (Decimal("102"), Decimal("20"))),
        ),
        trades=tuple(trades),
    )


def intent(qty: str = "5", order_type=OrderType.MARKET, side=Side.BUY, price=None, tif=None):
    return OrderIntent(
        intent_id="I1",
        decision_id="D1",
        portfolio_decision_id="P1",
        risk_decision_id="R1",
        strategy_id="S1",
        model_id="M1",
        execution_version="VX-1",
        symbol=SYMBOL,
        side=side,
        action=OrderAction.OPEN,
        quantity=Decimal(qty),
        order_type=order_type,
        price=Decimal(price) if price is not None else None,
        time_in_force=tif,
        window=ValidWindow(TS, datetime(2030, 1, 1, tzinfo=timezone.utc)),
    )


def stages(order):
    return BacktestStageFunctions(
        feature_fn=lambda e: None,
        regime_fn=lambda e, f: None,
        prediction_fn=lambda e, f, r: None,
        signal_fn=lambda e, p: None,
        opportunity_fn=lambda e, s, r: None,
        portfolio_fn=lambda e, o, q: None,
        risk_fn=lambda e, p, q: None,
        intent_fn=lambda e, r: order if e.event_offset == 0 else None,
    )


def model():
    return BinanceVenueExecutionModelConfig(
        version="VX-1",
        venue="BINANCE_USDM",
        symbol=SYMBOL,
        maker_fee_bps=Decimal("1"),
        taker_fee_bps=Decimal("2"),
    )


def check(name, value, expected=None):
    passed = value if expected is None else value == expected
    return {"check": name, "pass": bool(passed), "value": value if expected is None else None, "expected": expected}


def main():
    checks = []

    r = BinanceVenueExecutionEngine(stages(intent("15")), model(), SYMBOL).run([wrap(0)])
    checks.append(check("multi_level_market_sweep_quantities", [str(x.quantity) for x in r.fills], ["10", "5"]))
    checks.append(check("taker_fee_total", str(sum((f.fee for f in r.fills), Decimal("0"))), "0.304"))

    gtx = intent(order_type=OrderType.LIMIT, price="101", tif=BinanceTimeInForce.GTX.value)
    r = BinanceVenueExecutionEngine(stages(gtx), model(), SYMBOL).run([wrap(0)])
    checks.append(check("gtx_reject", r.rejections[0].reason.value, VenueRejectReason.GTX_ORDER_REJECT.value))
    checks.append(check("gtx_exchange_code", r.rejections[0].exchange_code, "-5022"))

    fok = intent(qty="12", order_type=OrderType.LIMIT, price="101", tif=BinanceTimeInForce.FOK.value)
    r = BinanceVenueExecutionEngine(stages(fok), model(), SYMBOL).run([wrap(0, ask_qty="10")])
    checks.append(check("fok_reject", r.rejections[0].reason.value, VenueRejectReason.FOK_ORDER_REJECT.value))
    checks.append(check("fok_exchange_code", r.rejections[0].exchange_code, "-5021"))

    ioc = intent(qty="12", order_type=OrderType.LIMIT, price="101", tif=BinanceTimeInForce.IOC.value)
    r = BinanceVenueExecutionEngine(stages(ioc), model(), SYMBOL).run([wrap(0, ask_qty="10")])
    checks.append(check("ioc_fill", str(sum((f.quantity for f in r.fills), Decimal("0"))), "10"))
    checks.append(check("ioc_cancel_remainder", [[a, str(q), reason] for a, q, reason in r.cancelled_remainders], [["I1", "2", "IOC_REMAINDER"]]))

    gtc = intent(qty="3", order_type=OrderType.LIMIT, price="99", tif=BinanceTimeInForce.GTC.value)
    events = [wrap(0), wrap(1, trades=(MarketTrade("T1", Decimal("99"), Decimal("13"), Side.SELL),))]
    r = BinanceVenueExecutionEngine(stages(gtc), model(), SYMBOL).run(events)
    checks.append(check("queue_ahead_then_maker_fill", str(r.fills[0].quantity), "3"))
    checks.append(check("maker_fee", str(r.fills[0].fee), "0.0297"))

    r = BinanceVenueExecutionEngine(stages(gtc), model(), SYMBOL).run(
        [wrap(0), wrap(1, trades=(MarketTrade("T2", Decimal("99"), Decimal("5"), Side.SELL),))]
    )
    checks.append(check("queue_remainder_preserved", [[a, str(q), str(ahead)] for a, q, ahead in r.open_orders], [["I1", "3", "5"]]))

    r = BinanceVenueExecutionEngine(stages(intent(order_type=OrderType.LIMIT, price="99", tif=BinanceTimeInForce.RPI.value)), model(), SYMBOL).run([wrap(0)])
    checks.append(check("rpi_fail_closed", r.rejections[0].reason.value, VenueRejectReason.RPI_LIQUIDITY_MODEL_UNSUPPORTED.value))

    # Determinism check.
    market_events = [wrap(0, ask_qty="4"), wrap(1)]
    r1 = BinanceVenueExecutionEngine(stages(intent("7")), model(), SYMBOL).run(market_events)
    r2 = BinanceVenueExecutionEngine(stages(intent("7")), model(), SYMBOL).run(market_events)
    checks.append(check("deterministic_state_hash", r1.state_hash, r2.state_hash))

    all_pass = all(x["pass"] for x in checks)
    payload = {
        "artifact_type": "BINANCE_VENUE_EXECUTION_EVIDENCE",
        "schema_version": "V378_BINANCE_VENUE_EXECUTION_1",
        "retrieved_at": "2026-10-02",
        "status": "PASS" if all_pass else "FAIL",
        "checks": checks,
        "external_references": [
            "https://developers.binance.com/en/docs/derivatives/usds-margined-futures/change-log",
            "https://developers.binance.com/en/docs/products/derivatives-trading-portfolio-margin/error-code",
            "https://developers.binance.com/en/docs/products/derivatives-trading-usds-futures/websocket-market-streams/Live-Subscribing-Unsubscribing-to-streams",
            "https://developers.binance.com/en/docs/products/derivatives-trading-coin-futures/user-data-streams",
        ],
        "scope": "APPLICATION_BACKTEST_BINANCE_USDM_VENUE_EXECUTION",
        "queue_model": "PRICE_TIME_L2_V1",
        "production_ready": False,
        "evidence_boundary": [
            "Exact exchange matching-engine queue reconstruction is not proven.",
            "RPI liquidity is intentionally not simulated.",
            "Maker/taker fee values are versioned inputs, not hard-coded live fee truth.",
            "No claim of live execution parity is made by this artifact.",
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    out = ROOT / "V378_BINANCE_EXECUTION_EVIDENCE.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if not all_pass:
        raise SystemExit("V378 evidence failed")
    print(out)
    print(payload["evidence_hash"])

if __name__ == "__main__":
    main()
