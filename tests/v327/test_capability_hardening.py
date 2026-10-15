from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from trading_platform.v28.deployment_authority import (
    ActivationCapabilityError,
    DeploymentActivationCapability,
    _issue_activation_capability,
    activation_capability_context,
    assert_activation_capability,
    consume_activation_capability,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def cap(**overrides):
    values = dict(
        deployment_id="D1",
        activation_fingerprint="AF1",
        target_mode="CANARY",
        effective_risk=Decimal("10"),
        valid_from=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(minutes=10),
    )
    values.update(overrides)
    return _issue_activation_capability(**values)


def test_capability_has_unique_identity_and_valid_window():
    a = cap()
    b = cap()
    assert a.capability_id != b.capability_id
    assert a.valid_from < a.expires_at
    assert a.active_at(NOW)


def test_public_constructor_cannot_create_valid_capability():
    forged = DeploymentActivationCapability(
        "D1", "AF1", "CANARY", Decimal("10"), NOW, NOW + timedelta(minutes=1), "fake", object()
    )
    with pytest.raises(ActivationCapabilityError, match="INVALID"):
        with activation_capability_context(forged):
            assert_activation_capability(
                deployment_id="D1", target_mode="CANARY", allocated_risk=Decimal("1"), now=NOW
            )


def test_expired_capability_is_blocked():
    a = cap(expires_at=NOW + timedelta(seconds=1))
    with activation_capability_context(a):
        with pytest.raises(ActivationCapabilityError, match="EXPIRED"):
            assert_activation_capability(
                deployment_id="D1", target_mode="CANARY", allocated_risk=Decimal("1"), now=NOW + timedelta(seconds=2)
            )


def test_not_yet_valid_capability_is_blocked():
    a = cap(valid_from=NOW + timedelta(seconds=1))
    with activation_capability_context(a):
        with pytest.raises(ActivationCapabilityError, match="EXPIRED"):
            assert_activation_capability(
                deployment_id="D1", target_mode="CANARY", allocated_risk=Decimal("1"), now=NOW
            )


def test_consumed_capability_cannot_be_reused():
    a = cap()
    with activation_capability_context(a):
        assert_activation_capability(
            deployment_id="D1", target_mode="CANARY", allocated_risk=Decimal("1"), now=NOW
        )
        consume_activation_capability(a)
        with pytest.raises(ActivationCapabilityError, match="ALREADY_CONSUMED"):
            assert_activation_capability(
                deployment_id="D1", target_mode="CANARY", allocated_risk=Decimal("1"), now=NOW
            )


def test_legacy_public_issuer_api_is_absent():
    import trading_platform.v28.deployment_authority as authority
    assert not hasattr(authority, "issue_activation_capability")
