from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.portfolio.config import ConfigValue, Precedence, resolve_config
from trading_platform.v343.config_authority import (
    ConfigurationAuthorityError,
    ConfigurationAuthorityLedger,
    ConfigurationResolutionStatus,
    candidate_fingerprint,
)
from trading_platform.v30.truth import (
    AxisSnapshot,
    CanonicalAction,
    ConfigurationStatus,
    TruthComponent,
    TruthStatus,
    build_truth,
)
from trading_platform.v31.authority import AuthorityStatus, RuntimeAuthority
from trading_platform.v31.router import ExecutionRouter
from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, PositionState, Side
from trading_platform.core.ttl import ValidWindow

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
AXES_LIVE = AxisSnapshot("ACTIVE", "LIVE", "HEALTHY", "APPROVED", "ACTIVE", "CHAMPION")

def caps(v="100"):
    return {k: Decimal(v) for k in ("health_cap", "deployment_cap", "accounting_cap", "reconciliation_cap", "provenance_cap", "operator_cap")}

def truth(config_status=ConfigurationStatus.RESOLVED, fp=""):
    components = tuple(TruthComponent(n, TruthStatus.VERIFIED, "OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    return build_truth(
        observed_at_ns=1,
        axes=AXES_LIVE,
        components=components,
        requested_risk=Decimal("100"),
        caps=caps(),
        configuration_status=config_status,
        configuration_fingerprint=fp,
    )

def config_values():
    return [
        ConfigValue("max_position", Decimal("10"), Precedence.RUNTIME, "runtime-a", "r1"),
        ConfigValue("max_position", Decimal("20"), Precedence.RUNTIME, "runtime-b", "r1"),
    ]

def resolved_values():
    return [ConfigValue("max_position", Decimal("10"), Precedence.RUNTIME, "runtime", "r1")]

def test_live_trade_denied_on_config_conflict():
    decision = RuntimeAuthority().evaluate(
        truth=truth(ConfigurationStatus.CONFLICT), action=CanonicalAction.TRADE,
        requested_risk=Decimal("1"), decision_id="m16-trade-conflict",
    )
    assert decision.status is AuthorityStatus.DENIED
    assert decision.reason == "CONFIG_CONFLICT"

def test_live_deploy_denied_on_config_conflict():
    decision = RuntimeAuthority().evaluate(
        truth=truth(ConfigurationStatus.CONFLICT), action=CanonicalAction.DEPLOY,
        requested_risk=Decimal("1"), decision_id="m16-deploy-conflict",
    )
    assert decision.status is AuthorityStatus.DENIED
    assert decision.reason == "CONFIG_CONFLICT"

def test_config_conflict_is_canonicalized_in_truth_hash():
    clean = truth(ConfigurationStatus.RESOLVED)
    blocked = truth(ConfigurationStatus.CONFLICT)
    assert clean.state_hash != blocked.state_hash
    assert blocked.trading_allowed is False
    assert blocked.effective_risk == Decimal("0")

def test_configuration_authority_records_conflict_without_raw_values():
    ledger = ConfigurationAuthorityLedger()
    record, created = ledger.record(
        resolution_id="cfg-conflict-1",
        config_name="max_position",
        values=config_values(),
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=5),
        recorded_at_ms=1,
        operator="system",
    )
    assert created is True
    assert record.status is ConfigurationResolutionStatus.CONFIG_CONFLICT
    event = ledger.store.get("configuration-resolution:cfg-conflict-1")
    assert event is not None
    payload_text = str(event.payload)
    assert "runtime-a" not in payload_text
    assert "runtime-b" not in payload_text
    assert "value" not in event.payload
    assert "source" not in event.payload
    assert "precedence" not in event.payload
    with pytest.raises(ConfigurationAuthorityError, match="CONFIG_CONFLICT"):
        ledger.assert_live_safe(record.resolution_id, now=NOW)

def test_configuration_authority_resolved_path_is_live_safe():
    ledger = ConfigurationAuthorityLedger()
    values = resolved_values()
    record, _ = ledger.record(
        resolution_id="cfg-ok-1",
        config_name="max_position",
        values=values,
        valid_from=NOW,
        expires_at=NOW + timedelta(minutes=5),
        recorded_at_ms=2,
        operator="system",
    )
    assert record.status is ConfigurationResolutionStatus.RESOLVED
    assert ledger.assert_live_safe(record.resolution_id, now=NOW, expected_candidates_fingerprint=candidate_fingerprint(values)).resolution_id == record.resolution_id

def test_configuration_authority_survives_restart():
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".sqlite") as f:
        first = ConfigurationAuthorityLedger(__import__('trading_platform.v21.event_store', fromlist=['EventStore']).EventStore(f.name))
        record, _ = first.record(
            resolution_id="cfg-restart-1", config_name="max_position", values=resolved_values(),
            valid_from=NOW, expires_at=NOW + timedelta(minutes=5), recorded_at_ms=3,
        )
        second = ConfigurationAuthorityLedger(__import__('trading_platform.v21.event_store', fromlist=['EventStore']).EventStore(f.name))
        restored = second.get(record.resolution_id)
        assert restored is not None
        assert restored.fingerprint == record.fingerprint

def test_execution_router_blocks_live_order_on_config_conflict():
    intent = OrderIntent(
        "I-M16", "D-M16", "P1", "R1", "S1", "M1", "E1", "BTCUSDT", Side.BUY,
        OrderAction.OPEN, Decimal("0.001"), OrderType.MARKET,
        ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5)),
    )
    with pytest.raises(PermissionError, match="CONFIG_CONFLICT"):
        ExecutionRouter().route(
            intent=intent,
            truth=truth(ConfigurationStatus.CONFLICT),
            now=NOW,
            position_state=PositionState.FLAT,
            market_window=ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5)),
            upstream_windows=[ValidWindow(NOW - timedelta(seconds=1), NOW + timedelta(minutes=5))],
            risk_valid=True,
            requested_risk=Decimal("1"),
            decision_id="m16-router",
        )
