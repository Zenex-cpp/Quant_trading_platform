from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import pytest

from trading_platform.core.ttl import ValidWindow
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.v21.event_store import EventStore
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v384 import (
    ConnectivityProofV384,
    OperatorApprovalV384,
    TestnetExecutionActivationAuthorityV384,
    TestnetExecutionActivationConfigV384 as ActivationConfigV384,
)
from trading_platform.v317 import DurableRiskReservationBook, RiskReservationGate
from trading_platform.v385 import ControlledSubmitError, ControlledTestnetSubmitAuthorityV385
from trading_platform.v379 import TestnetMutationGate
from trading_platform.v380 import BinanceTestnetOrderAdapterV380
from tests.v385_submit_support import build_v385_submit_authorities


BASE = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


class Gateway:
    def __init__(self, fail: bool = False):
        self.calls = []
        self.fail = fail

    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        if self.fail:
            raise TimeoutError("timeout")
        return SubmitObservation(
            ExchangeOutcome.ACKNOWLEDGED,
            order.client_order_id,
            "EX-1",
            raw={"status": "NEW"},
        )


def test_v380_adapter_cannot_submit_around_authority_boundary():
    gateway = Gateway()
    adapter = BinanceTestnetOrderAdapterV380(
        gateway=gateway,
        mutation_gate=TestnetMutationGate(
            mutation_enabled=True,
            operator_approval=True,
            max_notional=Decimal("25"),
        ),
    )
    with pytest.raises(PermissionError, match="CONTROLLED_SUBMIT_AUTHORITY_REQUIRED"):
        adapter.submit(
            intent(),
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            now=BASE,
            reference_price=Decimal("50000"),
        )
    assert gateway.calls == []


def intent():
    return OrderIntent(
        "I-385", "D-385", "P-385", "R-385", "S-385", "M-385", "V385",
        "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.0002"), OrderType.LIMIT,
        ValidWindow(BASE, BASE + timedelta(minutes=5)), Decimal("50000"), "GTC", "RR-385",
    )


def activation():
    auth = TestnetExecutionActivationAuthorityV384(
        ActivationConfigV384(max_notional=Decimal("25")), clock=lambda: BASE,
    )
    auth.activate(
        connectivity=ConnectivityProofV384(
            "VERIFIED", "EV-385", BASE, BASE + timedelta(minutes=5),
            "https://testnet.binancefuture.com", 0,
        ),
        approval=OperatorApprovalV384(
            "APR-385", "operator", "TESTNET_ORDER_MUTATION", BASE,
            BASE + timedelta(minutes=5), "controlled",
        ),
        reconciliation_state="GREEN",
        now=BASE,
    )
    return auth


def control(
    *,
    tmp_path,
    fail=False,
    risk_expires_at_ms=None,
    missing_authority=None,
):
    order_intent = intent()
    authorities = build_v385_submit_authorities(
        order_intent,
        BASE,
        storage_dir=tmp_path,
        risk_expires_at_ms=risk_expires_at_ms,
    )
    authority_args = {
        "risk_decision_ledger": authorities.risk_decision_ledger,
        "accounting_authority": authorities.accounting_authority,
        "risk_reservation_gate": authorities.risk_reservation_gate,
        "position_authority": authorities.position_authority,
        "market_data_authority": authorities.market_data_authority,
        "causal_ttl_authority": authorities.causal_ttl_authority,
    }
    if missing_authority is not None:
        authority_args[missing_authority] = None
    store = EventStore(str(tmp_path / "submit.db"))
    gateway = Gateway(fail=fail)
    submitter = ControlledTestnetSubmitAuthorityV385(
        activation=activation(), gateway=gateway, event_store=store,
        clock=lambda: BASE, **authority_args,
    )
    snapshot = authorities.snapshot(order_intent, "SNP-385")
    return order_intent, snapshot, store, gateway, submitter


def test_happy_path_has_durable_snapshot_and_dispatch_claim(tmp_path):
    order_intent, snapshot, store, gateway, submitter = control(tmp_path=tmp_path)
    result = submitter.submit(
        order_intent,
        credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
        pre_trade_snapshot=snapshot,
        now=BASE,
    )
    assert result.status == "ACKNOWLEDGED" and len(gateway.calls) == 1
    assert any(e.event_type == "PRE_TRADE_SNAPSHOT_CAPTURED" for e in store.iter_events())
    assert any(e.event_type == "ORDER_DISPATCH_ATTEMPTED" for e in store.iter_events())
    assert any(e.event_type == "ORDER_DISPATCH_OBSERVED" for e in store.iter_events())
    restored = submitter.snapshot_ledger.get(snapshot.snapshot_id)
    assert restored == snapshot


def test_repeat_submit_is_blocked_and_does_not_duplicate_side_effect(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    submitter.submit(
        order_intent,
        credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
        pre_trade_snapshot=snapshot,
        now=BASE,
    )
    with pytest.raises(Exception):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert len(gateway.calls) == 1


def test_transport_exception_becomes_unknown_and_blocks_retry(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path, fail=True)
    with pytest.raises(ControlledSubmitError, match="UNKNOWN"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert len(gateway.calls) == 1
    with pytest.raises(Exception):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert len(gateway.calls) == 1


@pytest.mark.parametrize(
    ("missing_authority", "reason"),
    [
        ("risk_decision_ledger", "RISK_DECISION_LEDGER_REQUIRED"),
        ("accounting_authority", "RISK_ACCOUNTING_AUTHORITY_REQUIRED"),
        ("risk_reservation_gate", "RISK_RESERVATION_GATE_REQUIRED"),
        ("position_authority", "POSITION_AUTHORITY_REQUIRED"),
        ("market_data_authority", "MARKET_DATA_AUTHORITY_REQUIRED"),
        ("causal_ttl_authority", "CAUSAL_TTL_AUTHORITY_REQUIRED"),
    ],
)
def test_missing_m1_m5_authority_blocks_before_gateway(missing_authority, reason, tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path, missing_authority=missing_authority)
    with pytest.raises(ControlledSubmitError, match=reason):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_expired_risk_decision_blocks_before_gateway(tmp_path):
    expired_at = int(BASE.timestamp() * 1000)
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path, risk_expires_at_ms=expired_at)
    with pytest.raises(ControlledSubmitError, match="RISK_DECISION_DENIED:RISK_DECISION_EXPIRED_OR_NOT_YET_VALID"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_snapshot_risk_hash_mismatch_blocks_before_gateway(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    snapshot = type(snapshot)(**{**snapshot.__dict__, "risk_hash": "wrong-risk-hash"})
    with pytest.raises(ControlledSubmitError, match="PRE_TRADE_RISK_DECISION_FINGERPRINT_MISMATCH"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_snapshot_exposure_mismatch_blocks_before_gateway(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    snapshot = type(snapshot)(**{**snapshot.__dict__, "requested_exposure": Decimal("1")})
    with pytest.raises(ControlledSubmitError, match="PRE_TRADE_RISK_EXPOSURE_MISMATCH"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_unknown_position_blocks_before_external_submit(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    snapshot = type(snapshot)(**{**snapshot.__dict__, "position_state": "UNKNOWN"})
    with pytest.raises(ControlledSubmitError, match="POSITION_UNKNOWN"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_position_authority_from_missing_history_blocks_before_submit(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path, missing_authority="position_authority")
    with pytest.raises(ControlledSubmitError, match="POSITION_AUTHORITY_REQUIRED"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_stale_market_snapshot_blocks_before_external_submit(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    snapshot = type(snapshot)(**{**snapshot.__dict__, "market_stale": True})
    with pytest.raises(ControlledSubmitError, match="MARKET_DATA_STALE"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_expired_market_authority_blocks_even_with_fresh_snapshot_before_submit(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    now_ms = int(BASE.timestamp() * 1000)
    submitter.market_data_authority.record_observation(
        symbol=order_intent.symbol,
        feed_id="primary",
        event_time_ms=now_ms - 120_000,
        receive_time_ms=now_ms - 120_000,
        processing_time_ms=now_ms - 120_000,
        max_age_ms=60_000,
        source="stale-test-observation",
        sequence_number=2,
    )
    with pytest.raises(ControlledSubmitError, match="MARKET_DATA_AUTHORITY_DENIED:MARKET_DATA_STALE"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_snapshot_binding_conflict_blocks_submit(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    snapshot = type(snapshot)(**{**snapshot.__dict__, "order_request_id": "wrong"})
    with pytest.raises(ControlledSubmitError, match="ORDER_REQUEST_MISMATCH"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_stale_accounting_snapshot_blocks_before_gateway(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    snapshot = type(snapshot)(**{**snapshot.__dict__, "accounting_projection_hash": "stale-accounting"})
    with pytest.raises(ControlledSubmitError, match="PRE_TRADE_ACCOUNTING_HASH_STALE"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_ephemeral_dispatch_store_blocks_before_gateway(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    submitter.store = EventStore()
    with pytest.raises(ControlledSubmitError, match="DISPATCH_EVENT_STORE_NOT_PERSISTENT"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []


def test_ephemeral_reservation_store_blocks_before_gateway(tmp_path):
    order_intent, snapshot, _, gateway, submitter = control(tmp_path=tmp_path)
    submitter.risk_reservation_gate = RiskReservationGate(
        DurableRiskReservationBook(EventStore(), allocated=Decimal("25")),
    )
    with pytest.raises(ControlledSubmitError, match="RISK_RESERVATION_LEDGER_NOT_PERSISTENT"):
        submitter.submit(
            order_intent,
            credentials=RuntimeCredentialValues("TEST_KEY_SENTINEL", b"TEST_SECRET_SENTINEL"),
            pre_trade_snapshot=snapshot,
            now=BASE,
        )
    assert gateway.calls == []
