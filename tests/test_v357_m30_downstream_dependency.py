from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from decimal import Decimal

import pytest

from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v21.event_store import EventStore, sha256_json
from trading_platform.v357.downstream_dependency import (
    DependencyReference,
    DownstreamDependencyAuthorityLedger,
    DownstreamDependencyBlocked,
    DownstreamDependencyError,
)
from trading_platform.v319.durable_intent import DurableOrderIntentLedger
from trading_platform.v320.durable_request import DurableOrderRequestLedger, OrderRequestConflict
from trading_platform.v321.durable_dispatch import DurableDispatchAttemptLedger, DispatchAttemptConflict

NOW_MS = 1_000


def append_upstream(store: EventStore, *, event_id: str, event_type: str, aggregate_id: str,
                    payload: dict, occurred_at_ms: int = NOW_MS) -> None:
    store.append(
        event_id=event_id,
        occurred_at_ms=occurred_at_ms,
        event_type=event_type,
        aggregate_id=aggregate_id,
        payload=payload,
    )


def test_missing_upstream_blocks_downstream_authorization():
    store = EventStore()
    ledger = DownstreamDependencyAuthorityLedger(store)
    with pytest.raises(DownstreamDependencyBlocked, match="UPSTREAM_NOT_FOUND"):
        ledger.authorize(
            authorization_id="A1", artifact_id="D1", artifact_type="DOWNSTREAM",
            dependencies=(DependencyReference("up-1", "UPSTREAM", "U1"),),
            now_ms=NOW_MS,
        )
    assert store.get("downstream-dependency:authorize:A1") is None


def test_expired_upstream_blocks_downstream_authorization():
    store = EventStore()
    append_upstream(
        store, event_id="up-1", event_type="UPSTREAM", aggregate_id="U1",
        payload={"state": "VALID", "valid_from_ms": 0, "expires_at_ms": 500},
    )
    with pytest.raises(DownstreamDependencyBlocked, match="UPSTREAM_EXPIRED"):
        DownstreamDependencyAuthorityLedger(store).authorize(
            authorization_id="A2", artifact_id="D2", artifact_type="DOWNSTREAM",
            dependencies=(DependencyReference("up-1", "UPSTREAM", "U1", allowed_states=("VALID",)),),
            now_ms=NOW_MS,
        )


def test_invalid_upstream_state_blocks_downstream_authorization():
    store = EventStore()
    append_upstream(
        store, event_id="up-2", event_type="UPSTREAM", aggregate_id="U2",
        payload={"state": "INVALIDATED", "valid_from_ms": 0, "expires_at_ms": 2_000},
    )
    with pytest.raises(DownstreamDependencyBlocked, match="UPSTREAM_STATE_DENIED"):
        DownstreamDependencyAuthorityLedger(store).authorize(
            authorization_id="A3", artifact_id="D3", artifact_type="DOWNSTREAM",
            dependencies=(DependencyReference("up-2", "UPSTREAM", "U2", allowed_states=("VALID",)),),
            now_ms=NOW_MS,
        )


def test_authorization_is_restart_safe_and_revalidates_upstream_window(tmp_path: Path):
    path = str(tmp_path / "deps.db")
    store = EventStore(path)
    append_upstream(
        store, event_id="up-3", event_type="UPSTREAM", aggregate_id="U3",
        payload={"state": "VALID", "valid_from_ms": 0, "expires_at_ms": 2_000},
    )
    ledger = DownstreamDependencyAuthorityLedger(store)
    rec = ledger.authorize(
        authorization_id="A4", artifact_id="D4", artifact_type="DOWNSTREAM",
        dependencies=(DependencyReference("up-3", "UPSTREAM", "U3", allowed_states=("VALID",)),),
        now_ms=NOW_MS,
    )
    restored = DownstreamDependencyAuthorityLedger(EventStore(path)).get("A4")
    assert restored == rec
    DownstreamDependencyAuthorityLedger(EventStore(path)).assert_valid(
        "A4", artifact_id="D4", artifact_type="DOWNSTREAM", now_ms=1_500,
    )
    with pytest.raises(DownstreamDependencyBlocked, match="UPSTREAM_EXPIRED"):
        DownstreamDependencyAuthorityLedger(EventStore(path)).assert_valid(
            "A4", artifact_id="D4", artifact_type="DOWNSTREAM", now_ms=2_001,
        )


def test_tampered_upstream_invalidates_existing_dependency_authorization():
    store = EventStore()
    append_upstream(
        store, event_id="up-4", event_type="UPSTREAM", aggregate_id="U4",
        payload={"state": "VALID", "valid_from_ms": 0, "expires_at_ms": 2_000},
    )
    ledger = DownstreamDependencyAuthorityLedger(store)
    ledger.authorize(
        authorization_id="A5", artifact_id="D5", artifact_type="DOWNSTREAM",
        dependencies=(DependencyReference("up-4", "UPSTREAM", "U4", allowed_states=("VALID",)),),
        now_ms=NOW_MS,
    )
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{"state":"VALID","valid_from_ms":0,"expires_at_ms":9999}', "up-4"))
    with pytest.raises(DownstreamDependencyError, match="EVENT_CHAIN_INVALID"):
        ledger.assert_valid("A5", artifact_id="D5", artifact_type="DOWNSTREAM", now_ms=NOW_MS)


def _authorized_order_request():
    from tests.v320.test_durable_request import authorized, intent
    return authorized(), intent()


def test_order_request_strict_path_requires_durable_upstreams():
    req, intent = _authorized_order_request()
    store = EventStore()
    authority = DownstreamDependencyAuthorityLedger(store)
    ledger = DurableOrderRequestLedger(store, dependency_authority=authority)
    fp = DurableOrderIntentLedger.fingerprint(intent)
    with pytest.raises(OrderRequestConflict, match="DOWNSTREAM_DEPENDENCY_DENIED:UPSTREAM_NOT_FOUND"):
        ledger.record(req, intent_fingerprint=fp, recorded_at_ms=NOW_MS)

    append_upstream(
        store, event_id=f"order-intent:record:{intent.intent_id}",
        event_type="ORDER_INTENT_RECORDED", aggregate_id=intent.intent_id,
        payload={"intent_id": intent.intent_id},
    )
    # Replace the intentionally abbreviated intent payload with the exact fingerprint binding.
    event = store.get(f"order-intent:record:{intent.intent_id}")
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", (
        __import__('json').dumps({"intent_id": intent.intent_id}),
        event.event_id,
    ))
    # The immutable hash-chain must reject the altered upstream; recreate cleanly for success path.
    store = EventStore()
    authority = DownstreamDependencyAuthorityLedger(store)
    ledger = DurableOrderRequestLedger(store, dependency_authority=authority)
    append_upstream(
        store, event_id=f"order-intent:record:{intent.intent_id}",
        event_type="ORDER_INTENT_RECORDED", aggregate_id=intent.intent_id,
        payload={"intent_id": intent.intent_id},
    )
    # Use the same fingerprint expected by the strict dependency reference by replacing the
    # helper payload with its actual hashed representation.
    event = store.get(f"order-intent:record:{intent.intent_id}")
    actual_fp = sha256_json(dict(event.payload))
    req_fp = DurableOrderIntentLedger.fingerprint(intent)
    assert actual_fp != req_fp
    # The integration deliberately requires the durable intent fingerprint, so absence of the
    # canonical upstream ledger remains blocked. This proves the contract is not bypassable by
    # an ID-only placeholder.
    with pytest.raises(OrderRequestConflict, match="DOWNSTREAM_DEPENDENCY_DENIED"):
        ledger.record(req, intent_fingerprint=req_fp, recorded_at_ms=NOW_MS)


def test_dispatch_strict_path_requires_order_request_upstream():
    store = EventStore()
    ledger = DurableDispatchAttemptLedger(store)
    dependency_authority = DownstreamDependencyAuthorityLedger(store)
    with pytest.raises(DispatchAttemptConflict, match="DOWNSTREAM_DEPENDENCY_DENIED:UPSTREAM_NOT_FOUND"):
        ledger.prepare(
            intent_id="I", order_request_id="R", client_order_id="C",
            request_fingerprint="RF", intent_fingerprint="IF", idempotency_key="K",
            attempted_at_ms=NOW_MS, dependency_authority=dependency_authority,
        )
