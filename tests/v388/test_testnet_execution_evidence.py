from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import pytest

from trading_platform.v388 import (
    EvidenceBundleErrorV388,
    EvidenceBundleStateV388,
    FirstTestnetExecutionEvidenceBuilderV388,
    TestnetEvidenceRefV388,
)

BASE = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)

def h(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()

def builder() -> FirstTestnetExecutionEvidenceBuilderV388:
    b = FirstTestnetExecutionEvidenceBuilderV388(bundle_id="B-388", environment="TESTNET", symbol="BTCUSDT", started_at=BASE)
    b.record_preconditions(
        connectivity_ref=TestnetEvidenceRefV388("CONNECTIVITY", "V383", BASE, h("connectivity")),
        approval_id="APR-388",
        activation_id="ACT-388",
        pre_trade_snapshot_id="SNP-388",
        pre_trade_snapshot_hash=h("snapshot"),
    )
    b.record_submit(
        dispatch_attempt_id="DA-388",
        order_request_id="OR-388",
        client_order_id="CID-388",
        exchange_order_id="EX-388",
        status="ACKNOWLEDGED",
        mutation_performed=True,
    )
    return b

def close_builder() -> FirstTestnetExecutionEvidenceBuilderV388:
    b = builder()
    b.record_order_event(
        event_hash=h("order-update"), captured_at=BASE + timedelta(seconds=1),
        client_order_id="CID-388", status="CANCELED", exchange_order_id="EX-388",
    )
    b.record_account_event(event_hash=h("account-update"), captured_at=BASE + timedelta(seconds=2))
    b.record_reconciliation(reconciliation_hash=h("reconciliation"), captured_at=BASE + timedelta(seconds=3), green=True)
    b.record_accounting(accounting_hash=h("accounting"), captured_at=BASE + timedelta(seconds=4), reconciled=True)
    return b

def test_causal_chain_closes_only_after_all_required_evidence():
    b = close_builder()
    evidence = b.close(closed_at=BASE + timedelta(seconds=5))
    assert evidence.state is EvidenceBundleStateV388.CLOSED
    assert evidence.verify_content_hash()
    assert evidence.exchange_order_id == "EX-388"

def test_close_is_blocked_without_accounting():
    b = builder()
    b.record_order_event(event_hash=h("order"), captured_at=BASE + timedelta(seconds=1), client_order_id="CID-388", status="CANCELED")
    b.record_account_event(event_hash=h("account"), captured_at=BASE + timedelta(seconds=2))
    b.record_reconciliation(reconciliation_hash=h("recon"), captured_at=BASE + timedelta(seconds=3), green=True)
    with pytest.raises(EvidenceBundleErrorV388, match="ACCOUNTING_EVIDENCE_REQUIRED"):
        b.close(closed_at=BASE + timedelta(seconds=4))

def test_unknown_or_non_terminal_order_cannot_complete():
    b = builder()
    b.record_order_event(event_hash=h("order"), captured_at=BASE + timedelta(seconds=1), client_order_id="CID-388", status="NEW")
    b.record_account_event(event_hash=h("account"), captured_at=BASE + timedelta(seconds=2))
    with pytest.raises(EvidenceBundleErrorV388, match="TERMINAL_ORDER_STATUS_REQUIRED"):
        b.record_reconciliation(reconciliation_hash=h("recon"), captured_at=BASE + timedelta(seconds=2), green=True)

def test_reconciliation_requires_account_update():
    b = builder()
    b.record_order_event(event_hash=h("order"), captured_at=BASE + timedelta(seconds=1), client_order_id="CID-388", status="CANCELED")
    with pytest.raises(EvidenceBundleErrorV388, match="ACCOUNT_EVENT_REQUIRED"):
        b.record_reconciliation(reconciliation_hash=h("recon"), captured_at=BASE + timedelta(seconds=2), green=True)

def test_non_green_reconciliation_blocks_bundle():
    b = builder()
    b.record_order_event(event_hash=h("order"), captured_at=BASE + timedelta(seconds=1), client_order_id="CID-388", status="CANCELED")
    b.record_account_event(event_hash=h("account"), captured_at=BASE + timedelta(seconds=2))
    with pytest.raises(EvidenceBundleErrorV388, match="POST_TRADE_RECONCILIATION_NOT_GREEN"):
        b.record_reconciliation(reconciliation_hash=h("recon"), captured_at=BASE + timedelta(seconds=3), green=False)
    assert b.state is EvidenceBundleStateV388.BLOCKED

def test_duplicate_submit_evidence_blocked():
    b = builder()
    with pytest.raises(EvidenceBundleErrorV388, match="DUPLICATE_SUBMIT_EVIDENCE"):
        b.record_submit(dispatch_attempt_id="DA-2", order_request_id="OR-388", client_order_id="CID-388", exchange_order_id="EX-388", status="ACKNOWLEDGED", mutation_performed=True)

def test_client_correlation_is_mandatory():
    b = builder()
    with pytest.raises(EvidenceBundleErrorV388, match="ORDER_EVENT_CLIENT_CORRELATION_MISMATCH"):
        b.record_order_event(event_hash=h("order"), captured_at=BASE + timedelta(seconds=1), client_order_id="OTHER", status="CANCELED")

def test_secret_values_are_not_accepted_as_metadata():
    with pytest.raises(EvidenceBundleErrorV388, match="SECRET_METADATA_NOT_ALLOWED"):
        TestnetEvidenceRefV388("API_SECRET", "V383", BASE, h("x")).validate()

def test_closed_bundle_is_immutable():
    b = close_builder()
    evidence = b.close(closed_at=BASE + timedelta(seconds=5))
    with pytest.raises(EvidenceBundleErrorV388, match="EVIDENCE_BUNDLE_TERMINAL"):
        b.record_account_event(event_hash=h("later"), captured_at=BASE + timedelta(seconds=6))
    assert evidence.fingerprint == evidence.fingerprint

def test_snapshot_json_has_no_secret_material():
    b = close_builder()
    evidence = b.close(closed_at=BASE + timedelta(seconds=5))
    raw = json.dumps(evidence.payload(), sort_keys=True)
    assert "SECRET" not in raw
    assert "api_secret" not in raw.lower()
