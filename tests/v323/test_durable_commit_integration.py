
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from trading_platform.v21.event_store import EventStore
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority
from trading_platform.v33.commit import CommitCoordinator, CommitStatus
from trading_platform.v323.durable_commit import DurableCommitLedger
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 13, tzinfo=timezone.utc)
WIN = ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))
AX = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")


def truth():
    return build_truth(
        observed_at_ns=1,
        axes=AX,
        components=tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health", "provenance", "governance", "reconciliation", "accounting", "ledger")),
        requested_risk=Decimal("100"),
        caps={k: Decimal("100") for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")},
    )


def intent():
    return OrderIntent("IBRIDGE323", "DBRIDGE323", "PBRIDGE323", "RBRIDGE323", "S", "M", "E", "BTCUSDT", Side.BUY, OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET, WIN)


def payload():
    return {"intent_id":"IBRIDGE323","decision_id":"DBRIDGE323","risk_decision_id":"RBRIDGE323","portfolio_decision_id":"PBRIDGE323","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E"}


def test_commitcoordinator_with_durable_ledger_survives_restart(tmp_path: Path):
    db = tmp_path / "bridge-commit.db"
    t = truth()
    ledger = DurableCommitLedger(EventStore(str(db)))
    first = CommitCoordinator(capabilities=CapabilityAuthority(), durable_ledger=ledger)
    cap = first.capabilities.issue(truth=t, requested_risk=Decimal("10"), decision_id="DBRIDGE323", intent_payload=payload(), expires_at=NOW+timedelta(minutes=1))
    committed = first.commit(capability=cap, intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    assert committed.status is CommitStatus.COMMITTED

    fresh = CommitCoordinator(capabilities=CapabilityAuthority(), durable_ledger=DurableCommitLedger(EventStore(str(db))))
    cap2 = fresh.capabilities.issue(truth=t, requested_risk=Decimal("10"), decision_id="DBRIDGE323", intent_payload=payload(), expires_at=NOW+timedelta(minutes=1))
    duplicate = fresh.commit(capability=cap2, intent=intent(), truth=t, now=NOW, position_state=PositionState.FLAT, market_window=WIN, upstream_windows=[WIN], risk_valid=True)
    assert duplicate.status is CommitStatus.DUPLICATE
    assert duplicate.request.request == committed.request.request
