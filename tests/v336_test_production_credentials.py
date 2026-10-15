from __future__ import annotations

import pytest

from trading_platform.v21.event_store import EventStore
from trading_platform.security.credentials import (
    ProductionCredentialAccessError,
    ProductionCredentialRef,
    ProductionCredentialVault,
    CredentialStatus,
    assert_research_arguments,
    assert_research_safe,
)
from trading_platform.v35.binance_execution import RuntimeCredentialValues


def vault_and_ref():
    store = EventStore()
    vault = ProductionCredentialVault(store=store)
    ref = vault.register(
        credential_id="prod-primary",
        version="v1",
        api_key="PROD_API_KEY",
        api_secret=b"PROD_API_SECRET",
        valid_from_ms=10,
        ttl_ms=100,
        actor_role="SECURITY_ADMIN",
    )
    return store, vault, ref


def test_research_cannot_register_or_revoke_production_credentials():
    vault = ProductionCredentialVault()
    with pytest.raises(ProductionCredentialAccessError, match="RESEARCH_FORBIDDEN"):
        vault.register(credential_id="p", version="v1", api_key="K", api_secret=b"S", valid_from_ms=1, actor_role="RESEARCH")


def test_research_cannot_resolve_production_credentials():
    store, vault, ref = vault_and_ref()
    with pytest.raises(ProductionCredentialAccessError, match="RESEARCH_FORBIDDEN"):
        vault.resolve(ref, actor_role="RESEARCH", now_ms=20)
    assert store.verify_chain()
    deny = next(e for e in store.iter_events() if e.event_type == vault.DENY_EVENT)
    assert "PROD_API_KEY" not in str(deny.payload)
    assert "PROD_API_SECRET" not in str(deny.payload)


def test_rotation_is_a_new_audited_version():
    _, vault, ref1 = vault_and_ref()
    ref2 = vault.rotate(credential_id="prod-primary", new_version="v2", api_key="NEW_KEY", api_secret=b"NEW_SECRET", valid_from_ms=200, actor_role="SECURITY_ADMIN")
    assert ref2.version == "v2" and ref2.fingerprint != ref1.fingerprint
    assert vault.metadata(ref2).status is CredentialStatus.ACTIVE


def test_only_production_trading_can_resolve_runtime_material():
    _, vault, ref = vault_and_ref()
    creds = vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=20)
    assert creds.values() == ("PROD_API_KEY", b"PROD_API_SECRET")


def test_research_boundary_rejects_runtime_credentials_and_reference():
    _, _, ref = vault_and_ref()
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        assert_research_safe(RuntimeCredentialValues("K", b"S"))
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        assert_research_safe(ref)


def test_research_boundary_rejects_credential_bearing_mapping():
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        assert_research_safe({"features": [1, 2], "api_secret": "PROD_SECRET"})


def test_research_boundary_allows_normal_research_inputs():
    assert_research_arguments(
        [1, 2, 3],
        {"dataset_version": "ds-1", "feature_version": "fx-1"},
        model=type("ModelConfig", (), {"version": "m1"})(),
    )


def test_tuning_session_rejects_credentials_in_inputs():
    from datetime import datetime, timezone
    from trading_platform.research.pipeline import SplitSpec, TuningSession

    t = lambda i: datetime(2026, 1, 1, 0, i, tzinfo=timezone.utc)
    spec = SplitSpec(t(1), t(2), t(3), t(4), t(5), "1h", "2h", "s1")
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        TuningSession(times=[t(0), t(1)], spec=spec, rows=[{"api_key": "X"}, {"x": 1}])


def test_tuning_evaluator_cannot_receive_credentials():
    from datetime import datetime, timezone
    from trading_platform.research.pipeline import SplitSpec, TuningSession

    t = lambda i: datetime(2026, 1, 1, 0, i, tzinfo=timezone.utc)
    spec = SplitSpec(t(1), t(2), t(3), t(4), t(5), "1h", "2h", "s1")
    session = TuningSession(times=[t(i) for i in range(4)], spec=spec, rows=list(range(4)))
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        session.evaluate_split("TRAIN", lambda data, **kwargs: 1, api_key="X")


def test_expired_and_revoked_credentials_fail_closed():
    _, vault, ref = vault_and_ref()
    with pytest.raises(ProductionCredentialAccessError, match="EXPIRED"):
        vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=110)
    _, vault, ref = vault_and_ref()
    vault.revoke(credential_id=ref.credential_id, version=ref.version, now_ms=20, actor_role="PRODUCTION_TRADING")
    assert vault.metadata(ref).status is CredentialStatus.REVOKED
    with pytest.raises(ProductionCredentialAccessError, match="REVOKED"):
        vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=21)


def test_event_payloads_never_contain_credential_material():
    store, vault, ref = vault_and_ref()
    vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=20)
    raw = "\n".join(str(e.payload) for e in store.iter_events())
    assert "PROD_API_KEY" not in raw
    assert "PROD_API_SECRET" not in raw
    assert "PROD" in raw  # fingerprint/identifier may remain, secret material may not.


def test_forged_reference_fails_closed():
    _, vault, ref = vault_and_ref()
    forged = ProductionCredentialRef(ref.credential_id, ref.version, ref.valid_from_ms, ref.expires_at_ms, "not-the-fingerprint")
    with pytest.raises(ProductionCredentialAccessError, match="REFERENCE_MISMATCH"):
        vault.resolve(forged, actor_role="PRODUCTION_TRADING", now_ms=20)
