from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v31.router import ExecutionRouter
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v319 import DurableOrderIntentLedger
from trading_platform.v320 import DurableOrderRequestLedger, OrderRequestConflict, OrderRequestReplayError

NOW = datetime(2026, 9, 18, tzinfo=timezone.utc)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))


def intent():
    return OrderIntent("I320", "D320", "P320", "R320", "S320", "M320", "E320", "BTCUSDT",
                       Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN,
                       risk_reservation_id="RR320")


def truth():
    axes = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")
    return build_truth(
        observed_at_ns=1, axes=axes,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in
                         ("health", "provenance", "governance", "reconciliation", "accounting", "ledger")),
        requested_risk=Decimal("10"),
        caps={k: Decimal("10") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")},
    )


def authorized():
    i = intent(); t = truth()
    cap_auth = CapabilityAuthority()
    cap = cap_auth.issue(truth=t, requested_risk=Decimal("3"), decision_id="R320",
                         intent_payload=DurableOrderIntentLedger.payload(i), expires_at=NOW + timedelta(minutes=1))
    router = ExecutionRouter(authority=cap_auth.authority)
    return router.route(intent=i, truth=t, now=NOW, position_state=__import__("trading_platform.execution.models", fromlist=["PositionState"]).PositionState.FLAT,
                        market_window=WIN, upstream_windows=[WIN], risk_valid=True,
                        requested_risk=Decimal("3"), decision_id="R320",
                        input_payload=DurableOrderIntentLedger.payload(i))


def test_request_persists_and_replays(tmp_path: Path):
    path = str(tmp_path / "request.db")
    req = authorized()
    fp = DurableOrderIntentLedger.fingerprint(intent())
    ledger = DurableOrderRequestLedger(EventStore(path))
    first = ledger.record(req, intent_fingerprint=fp, recorded_at_ms=100)
    second = DurableOrderRequestLedger(EventStore(path)).get("I320")
    assert second == first
    assert second.request == req.request
    assert second.authority == req.authority


def test_conflicting_request_reuse_fails_closed(tmp_path: Path):
    ledger = DurableOrderRequestLedger(EventStore(str(tmp_path / "request.db")))
    req = authorized(); fp = DurableOrderIntentLedger.fingerprint(intent())
    ledger.record(req, intent_fingerprint=fp, recorded_at_ms=100)
    tampered = type(req)(req.authority, type(req.request)(**{**req.request.__dict__, "quantity": Decimal("0.002")}))
    with pytest.raises(OrderRequestConflict, match="ORDER_REQUEST_ID_PAYLOAD_CONFLICT"):
        ledger.record(tampered, intent_fingerprint=fp, recorded_at_ms=101)


def test_request_assertion_requires_exact_intent_fingerprint(tmp_path: Path):
    ledger = DurableOrderRequestLedger(EventStore(str(tmp_path / "request.db")))
    req = authorized(); fp = DurableOrderIntentLedger.fingerprint(intent())
    ledger.record(req, intent_fingerprint=fp, recorded_at_ms=100)
    with pytest.raises(OrderRequestConflict, match="ORDER_REQUEST_INTENT_FINGERPRINT_MISMATCH"):
        ledger.assert_matches(intent_id="I320", authorized=req, intent_fingerprint="stale")


def test_corrupted_event_chain_fails_closed(tmp_path: Path):
    path = str(tmp_path / "request.db")
    store = EventStore(path)
    ledger = DurableOrderRequestLedger(store)
    req = authorized(); fp = DurableOrderIntentLedger.fingerprint(intent())
    ledger.record(req, intent_fingerprint=fp, recorded_at_ms=100)
    tamper_event_store(store, "UPDATE events SET payload_json='{}' WHERE event_id='order-request:commit:req:I320'")
    with pytest.raises(OrderRequestReplayError, match="ORDER_REQUEST_EVENT_CHAIN_INVALID"):
        ledger.restore()


def test_persisted_payload_contains_no_credentials_or_transport_state(tmp_path: Path):
    path = str(tmp_path / "request.db")
    store = EventStore(path)
    ledger = DurableOrderRequestLedger(store)
    req = authorized(); fp = DurableOrderIntentLedger.fingerprint(intent())
    ledger.record(req, intent_fingerprint=fp, recorded_at_ms=100)
    event = next(store.iter_events())
    raw = str(event.payload).lower()
    assert "credential" not in raw
    assert "secret" not in raw
    assert "transport" not in raw
