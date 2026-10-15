from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import pytest

from trading_platform.v389 import (
    CredentialScopeV389,
    CredentialSourceV389,
    TestnetCredentialErrorV389,
    TestnetRuntimeCredentialAuthorityV389,
)

BASE = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)
ENV = {"BINANCE_TESTNET_API_KEY": "TESTNET_KEY_ONLY", "BINANCE_TESTNET_API_SECRET": "TESTNET_SECRET_ONLY"}


def test_issue_requires_dedicated_testnet_environment_credentials():
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    assert cap.metadata.scope is CredentialScopeV389.TESTNET
    assert cap.metadata.source is CredentialSourceV389.ENVIRONMENT
    assert "TESTNET_SECRET_ONLY" not in repr(cap)
    assert "TESTNET_SECRET_ONLY" not in json.dumps(cap.metadata.safe_payload(), sort_keys=True)


def test_missing_testnet_credentials_blocks():
    with pytest.raises(TestnetCredentialErrorV389, match="TESTNET_RUNTIME_CREDENTIALS_MISSING"):
        TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ={})


def test_any_production_credential_presence_blocks_even_when_testnet_credentials_exist():
    env = dict(ENV, BINANCE_API_KEY="PROD_KEY")
    with pytest.raises(TestnetCredentialErrorV389, match="PRODUCTION_CREDENTIAL_PRESENCE_BLOCKED"):
        TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=env)


def test_only_https_testnet_endpoint_is_allowed():
    with pytest.raises(TestnetCredentialErrorV389, match="TESTNET_CREDENTIAL_ENDPOINT_NOT_ALLOWED"):
        TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, endpoint="https://fapi.binance.com", environ=ENV)
    with pytest.raises(TestnetCredentialErrorV389, match="TESTNET_CREDENTIAL_ENDPOINT_TLS_REQUIRED"):
        TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, endpoint="http://testnet.binancefuture.com", environ=ENV)


def test_capability_is_one_shot_and_endpoint_bound():
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    creds = cap.consume(now=BASE + timedelta(seconds=1), endpoint="https://testnet.binancefuture.com")
    assert creds.values() == ("TESTNET_KEY_ONLY", b"TESTNET_SECRET_ONLY")
    with pytest.raises(TestnetCredentialErrorV389, match="TESTNET_CREDENTIAL_CAPABILITY_CONSUMED"):
        cap.consume(now=BASE + timedelta(seconds=2), endpoint="https://testnet.binancefuture.com")


def test_endpoint_mismatch_fails_before_secret_release():
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    with pytest.raises(TestnetCredentialErrorV389, match="TESTNET_CREDENTIAL_ENDPOINT_NOT_ALLOWED"):
        cap.consume(now=BASE, endpoint="https://testnet.binancefuture.com.evil.example")
    assert not cap.consumed


def test_ttl_expiry_fails_closed():
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, ttl_s=1, environ=ENV)
    with pytest.raises(TestnetCredentialErrorV389, match="TESTNET_CREDENTIAL_EXPIRED"):
        cap.consume(now=BASE + timedelta(seconds=1), endpoint="https://testnet.binancefuture.com")


def test_reference_window_and_fingerprint_are_machine_checkable():
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    cap.metadata.safe_payload()
    assert len(cap.metadata.key_fingerprint) == 64
    assert cap.metadata.expires_at > cap.metadata.issued_at


def test_runtime_capability_repr_excludes_secret_material():
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    raw = repr(cap)
    assert "TESTNET_SECRET_ONLY" not in raw
    assert "TESTNET_KEY_ONLY" not in raw


def test_capability_is_not_released_until_v387_submit_preconditions_are_armed():
    from unittest.mock import Mock
    runner = Mock()
    runner.state = type("State", (), {"name": "BLOCKED"})()
    from trading_platform.v389 import CredentialBoundFirstTestnetSubmitV389
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    adapter = CredentialBoundFirstTestnetSubmitV389(runner=runner)
    with pytest.raises(PermissionError, match="FIRST_TESTNET_ORDER_NOT_ARMED"):
        adapter.submit_once(
            preparation=type("Prep", (), {"allowed": False})(),
            gate=type("Gate", (), {"allowed": False})(),
            intent=None,
            capability=cap,
            pre_trade_snapshot=None,
            now=BASE,
        )
    assert not cap.consumed


def test_armed_submit_consumes_capability_and_delegates_once():
    from types import SimpleNamespace
    from unittest.mock import Mock
    from trading_platform.v389 import CredentialBoundFirstTestnetSubmitV389
    runner = Mock()
    runner.state = SimpleNamespace(name="ARMED")
    runner.submit_once.return_value = "SUBMIT_RESULT"
    gate = SimpleNamespace(allowed=True)
    preparation = SimpleNamespace(allowed=True)
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    adapter = CredentialBoundFirstTestnetSubmitV389(runner=runner)
    result = adapter.submit_once(
        preparation=preparation,
        gate=gate,
        intent="INTENT",
        capability=cap,
        pre_trade_snapshot="SNAPSHOT",
        now=BASE,
    )
    assert result == "SUBMIT_RESULT"
    assert cap.consumed
    runner.submit_once.assert_called_once()


def test_research_boundary_rejects_runtime_testnet_capability():
    from trading_platform.security.credentials import ProductionCredentialAccessError, assert_research_safe
    cap = TestnetRuntimeCredentialAuthorityV389.issue_from_environment(now=BASE, environ=ENV)
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        assert_research_safe(cap)
