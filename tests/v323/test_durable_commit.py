from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from trading_platform.v21.event_store import EventStore
from tests._immutable_test_helpers import tamper_event_store
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v33.commit import CommitCoordinator, CommitStatus
from trading_platform.v323.durable_commit import (
    DurableCommitConflict,
    DurableCommitLedger,
    DurableCommitReplayError,
)
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth(observed=1):
    return build_truth(
        observed_at_ns=observed,
        axes=AX,
        components=tuple(
            TruthComponent(n, TruthStatus.VERIFIED, "OK")
            for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger")
        ),
        requested_risk=Decimal("100"),
        caps={k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")},
    )


def intent():
    return OrderIntent(
        "I323", "D323", "P323", "R323", "S323", "M323", "E323", "BTCUSDT",
        Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN,
    )


def payload():
    return {
        "intent_id": "I323", "decision_id": "D323", "risk_decision_id": "R323", "portfolio_decision_id": "P323",
        "symbol": "BTCUSDT", "side": "BUY", "action": "OPEN", "quantity": "0.001", "order_type": "MARKET",
        "price": None, "execution_version": "E323",
    }


def coordinator(store):
    return CommitCoordinator(
        capabilities=CapabilityAuthority(),
        durable_ledger=DurableCommitLedger(store),
    )


def issue(cc, t):
    return cc.capabilities.issue(
        truth=t, requested_risk=Decimal("10"), decision_id="D323",
        intent_payload=payload(), expires_at=NOW + timedelta(minutes=1),
    )


def commit(cc, t):
    return cc.commit(
        capability=issue(cc, t), intent=intent(), truth=t, now=NOW,
        position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True,
    )


def test_restart_returns_same_durable_commit_without_new_consumption(tmp_path: Path):
    db = tmp_path / "commit.db"
    t = truth()
    first_cc = coordinator(EventStore(str(db)))
    first = commit(first_cc, t)
    assert first.status is CommitStatus.COMMITTED

    # Fresh process, fresh capability object: durable commit authority wins.
    second_cc = coordinator(EventStore(str(db)))
    second = commit(second_cc, t)
    assert second.status is CommitStatus.DUPLICATE
    assert second.request == first.request
    assert second.capability is not None and second.capability.consumed


def test_same_intent_with_changed_truth_or_risk_conflicts(tmp_path: Path):
    db = tmp_path / "commit.db"
    first_cc = coordinator(EventStore(str(db)))
    commit(first_cc, truth(observed=1))

    second_cc = coordinator(EventStore(str(db)))
    changed_truth = truth(observed=2)
    with pytest.raises(DurableCommitConflict, match="PAYLOAD_MISMATCH"):
        commit(second_cc, changed_truth)


def test_claim_crash_window_is_recoverable_as_duplicate(tmp_path: Path):
    db = tmp_path / "commit.db"
    store = EventStore(str(db))
    ledger = DurableCommitLedger(store)
    cc = CommitCoordinator(capabilities=CapabilityAuthority(), durable_ledger=ledger)
    t = truth()
    cap = issue(cc, t)
    # Build the exact request but simulate a process crash before capability consumption.
    payload_local = cc._payload(intent())
    out = cc.router.route(
        intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT,
        market_window=WIN, upstream_windows=[WIN], risk_valid=True,
        requested_risk=cap.authority.requested_risk, decision_id=cap.authority.decision_id,
        input_payload=payload_local,
    )
    commit_fp = cc._fp({"intent": payload_local, "truth_hash": t.state_hash, "requested_risk": str(cap.authority.requested_risk)})
    record, created = ledger.claim_record(
        intent_id=intent().intent_id, commit_fingerprint=commit_fp, capability=cap,
        authorized=out, recorded_at_ms=int(NOW.timestamp() * 1000),
    )
    assert created and record.order_request_id == "req:I323"

    fresh = coordinator(EventStore(str(db)))
    duplicate = commit(fresh, t)
    assert duplicate.status is CommitStatus.DUPLICATE
    assert duplicate.request.request == out.request


def test_conflicting_reuse_same_intent_fails_closed(tmp_path: Path):
    db = tmp_path / "commit.db"
    first_cc = coordinator(EventStore(str(db)))
    commit(first_cc, truth())

    fresh = coordinator(EventStore(str(db)))
    with pytest.raises(DurableCommitConflict):
        # Mutate exact intent contents while retaining the same intent_id.
        mutated = OrderIntent(
            "I323", "D323", "P323", "R323", "S323", "M323", "E-CHANGED", "BTCUSDT",
            Side.BUY, OrderAction.OPEN, Decimal("0.002"), OrderType.MARKET, WIN,
        )
        t = truth()
        cap = fresh.capabilities.issue(
            truth=t, requested_risk=Decimal("10"), decision_id="D323",
            intent_payload={**payload(), "quantity": "0.002", "execution_version": "E-CHANGED"},
            expires_at=NOW + timedelta(minutes=1),
        )
        fresh.commit(
            capability=cap, intent=mutated, truth=t, now=NOW, position_state=PositionState.FLAT,
            market_window=WIN, upstream_windows=[WIN], risk_valid=True,
        )


def test_corrupt_chain_prevents_restart_reuse(tmp_path: Path):
    db = tmp_path / "commit.db"
    first_cc = coordinator(EventStore(str(db)))
    commit(first_cc, truth())
    store = EventStore(str(db))
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}', 'order-commit:record:I323'))
    with pytest.raises(DurableCommitReplayError, match="DURABLE_COMMIT_EVENT_CHAIN_INVALID"):
        DurableCommitLedger(EventStore(str(db))).restore()


def test_corrupt_chain_blocks_commit_reuse_before_new_authority(tmp_path: Path):
    db = tmp_path / "commit.db"
    first_cc = coordinator(EventStore(str(db)))
    commit(first_cc, truth())
    store = EventStore(str(db))
    tamper_event_store(store, "UPDATE events SET payload_json=? WHERE event_id=?", ('{}', 'order-commit:record:I323'))
    fresh = coordinator(EventStore(str(db)))
    with pytest.raises(DurableCommitReplayError, match="DURABLE_COMMIT_EVENT_CHAIN_INVALID"):
        commit(fresh, truth())
