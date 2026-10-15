from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.core.ttl import ValidWindow
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v384 import (
    ActivationStatusV384,
    BinanceTestnetExecutionAdapterV384,
    ConnectivityProofV384,
    OperatorApprovalV384,
    TestnetExecutionActivationAuthorityV384,
    TestnetExecutionActivationConfigV384 as ActivationConfigV384,
)

BASE = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def proof(status="VERIFIED", *, expiry_seconds=600, hash_value="EV-HASH"):
    return ConnectivityProofV384(
        status=status,
        evidence_hash=hash_value,
        verified_at=BASE,
        expires_at=BASE + timedelta(seconds=expiry_seconds),
        rest_endpoint="https://testnet.binancefuture.com",
        clock_skew_ms=25,
    )


def approval(scope="TESTNET_ORDER_MUTATION", *, expiry_seconds=600):
    return OperatorApprovalV384(
        approval_id="APR-1",
        actor="operator-1",
        scope=scope,
        approved_at=BASE,
        expires_at=BASE + timedelta(seconds=expiry_seconds),
        reason="controlled testnet verification",
    )


def intent(quantity=Decimal("0.0002"), symbol="BTCUSDT", order_type=OrderType.LIMIT, price=Decimal("50000")):
    return OrderIntent(
        intent_id="I-384-1",
        decision_id="D-384-1",
        portfolio_decision_id="P-384-1",
        risk_decision_id="R-384-1",
        strategy_id="S-384-1",
        model_id="M-384-1",
        execution_version="V384-1",
        symbol=symbol,
        side=Side.BUY,
        action=OrderAction.OPEN,
        quantity=quantity,
        order_type=order_type,
        window=ValidWindow(BASE, BASE + timedelta(minutes=5)),
        price=price,
        time_in_force="GTC" if order_type is OrderType.LIMIT else None,
        risk_reservation_id="RR-384-1",
    )


class FakeGateway:
    def __init__(self):
        self.calls = []

    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        return SubmitObservation(ExchangeOutcome.ACKNOWLEDGED, order.client_order_id, "TEST-1", raw={"status": "NEW"})


def authority(*, ttl=300):
    return TestnetExecutionActivationAuthorityV384(
        ActivationConfigV384(activation_ttl_s=ttl, max_notional=Decimal("25")),
        clock=lambda: BASE,
    )


def activate(a):
    return a.activate(connectivity=proof(), approval=approval(), reconciliation_state="GREEN", now=BASE)


def test_not_verified_connectivity_cannot_activate():
    a = authority()
    with pytest.raises(PermissionError, match="CONNECTIVITY_PROOF_NOT_VERIFIED"):
        a.activate(connectivity=proof("NOT_VERIFIED"), approval=approval(), reconciliation_state="GREEN", now=BASE)


def test_red_reconciliation_cannot_activate():
    a = authority()
    with pytest.raises(PermissionError, match="RECONCILIATION_NOT_GREEN"):
        a.activate(connectivity=proof(), approval=approval(), reconciliation_state="RED", now=BASE)


def test_scope_or_expired_approval_blocks_activation():
    a = authority()
    with pytest.raises(PermissionError, match="OPERATOR_APPROVAL_SCOPE_INVALID"):
        a.activate(connectivity=proof(), approval=approval("READ_ONLY"), reconciliation_state="GREEN", now=BASE)
    with pytest.raises(PermissionError, match="OPERATOR_APPROVAL_EXPIRED"):
        a.activate(connectivity=proof(), approval=approval(expiry_seconds=1), reconciliation_state="GREEN", now=BASE + timedelta(seconds=1))


def test_activation_binds_evidence_and_expires_by_shortest_window():
    a = authority(ttl=300)
    snap = a.activate(connectivity=proof(expiry_seconds=120), approval=approval(expiry_seconds=180), reconciliation_state="GREEN", now=BASE)
    assert snap.status is ActivationStatusV384.ACTIVE
    assert snap.connectivity_evidence_hash == "EV-HASH"
    assert snap.expires_at == BASE + timedelta(seconds=120)
    assert snap.activation_id


def test_notional_and_symbol_hard_guards():
    a = authority()
    activate(a)
    assert a.authorize(intent=intent(quantity=Decimal("0.0002")), now=BASE).allowed
    assert a.authorize(intent=intent(quantity=Decimal("0.001"), price=Decimal("50000")), now=BASE).reason == "TESTNET_NOTIONAL_LIMIT_EXCEEDED"
    assert a.authorize(intent=intent(symbol="ETHUSDT"), now=BASE).reason == "SYMBOL_NOT_ALLOWLISTED"


def test_expiration_and_halt_block_new_risk():
    a = authority(ttl=2)
    activate(a)
    expired = a.snapshot(BASE + timedelta(seconds=2))
    assert expired.status is ActivationStatusV384.EXPIRED
    assert not a.authorize(intent=intent(), now=BASE + timedelta(seconds=2)).allowed
    a = authority()
    activate(a)
    halted = a.halt("RECONCILIATION_DRIFT", now=BASE + timedelta(seconds=1))
    assert halted.status is ActivationStatusV384.HALTED
    assert not a.authorize(intent=intent(), now=BASE + timedelta(seconds=1)).allowed


def test_deactivation_records_activation_before_clearing_runtime_binding():
    a = authority()
    activate(a)
    activation_id = a.snapshot(BASE).activation_id
    snap = a.deactivate("OPERATOR_STOP", now=BASE + timedelta(seconds=1))
    assert snap.status is ActivationStatusV384.INACTIVE
    assert snap.activation_id is None
    events = a.audit_events()
    assert events[-1]["event_type"] == "ACTIVATION_REVOKED"
    assert events[-1]["activation_id"] == activation_id


def test_adapter_blocks_gateway_until_activation_and_forwards_credentials_only_on_submit():
    a = authority()
    gateway = FakeGateway()
    adapter = BinanceTestnetExecutionAdapterV384(gateway, a)  # type: ignore[arg-type]
    creds = RuntimeCredentialValues(api_key="KEY", api_secret=b"SECRET")
    with pytest.raises(PermissionError, match="ACTIVATION_NOT_ACTIVE"):
        adapter.submit(intent(), credentials=creds, now=BASE)
    activate(a)
    obs = adapter.submit(intent(), credentials=creds, now=BASE)
    assert obs.outcome is ExchangeOutcome.ACKNOWLEDGED
    assert len(gateway.calls) == 1
    assert gateway.calls[0][1].api_key == "KEY"


def test_production_connectivity_endpoint_cannot_be_bound_as_testnet_proof():
    a = authority()
    bad = ConnectivityProofV384(
        status="VERIFIED",
        evidence_hash="EV-HASH",
        verified_at=BASE,
        expires_at=BASE + timedelta(minutes=5),
        rest_endpoint="https://fapi.binance.com",
        clock_skew_ms=0,
    )
    with pytest.raises(PermissionError, match="NETWORK_POLICY_DENIED"):
        a.activate(connectivity=bad, approval=approval(), reconciliation_state="GREEN", now=BASE)
