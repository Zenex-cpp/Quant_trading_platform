from __future__ import annotations

from threading import Event, Thread

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
from trading_platform.security.credential_backends import (
    CredentialBackendError,
    InMemoryCredentialSecretBackend,
)
from trading_platform.v35.binance_execution import RuntimeCredentialValues


def vault_and_ref():
    store = EventStore()
    vault = ProductionCredentialVault.for_testing(store=store)
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
    vault = ProductionCredentialVault.for_testing()
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


def test_research_boundary_traverses_slotted_wrappers_and_mangled_secret_names():
    class SlottedWrapper:
        __slots__ = ("payload",)

        def __init__(self):
            self.payload = RuntimeCredentialValues("K", b"S")

    class SlottedSecretName:
        __slots__ = ("__api_secret",)

        def __init__(self):
            self.__api_secret = "S"

    for value in (SlottedWrapper(), SlottedSecretName()):
        with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
            assert_research_safe(value)


def test_research_boundary_traverses_numpy_object_arrays():
    import numpy as np

    values = np.empty(1, dtype=object)
    values[0] = RuntimeCredentialValues("K", b"S")
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        assert_research_safe(values)


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
    forged = ProductionCredentialRef(ref.credential_id, ref.version, ref.valid_from_ms, ref.expires_at_ms, "0" * 64)
    with pytest.raises(ProductionCredentialAccessError, match="REFERENCE_MISMATCH"):
        vault.resolve(forged, actor_role="PRODUCTION_TRADING", now_ms=20)


def test_production_vault_requires_a_persistent_backend_by_default():
    with pytest.raises(ProductionCredentialAccessError, match="BACKEND_REQUIRED"):
        ProductionCredentialVault()
    with pytest.raises(ProductionCredentialAccessError, match="EPHEMERAL_BACKEND_FORBIDDEN"):
        ProductionCredentialVault(secret_backend=InMemoryCredentialSecretBackend())


def test_metadata_and_revocation_replay_from_durable_ledger(tmp_path):
    path = tmp_path / "credential-ledger.sqlite3"
    backend = InMemoryCredentialSecretBackend()
    store = EventStore(str(path))
    vault = ProductionCredentialVault.for_testing(store=store, secret_backend=backend)
    ref = vault.register(
        credential_id="restart-test",
        version="v1",
        api_key="RESTART_KEY",
        api_secret=b"RESTART_SECRET",
        valid_from_ms=10,
        ttl_ms=100,
        actor_role="SECURITY_ADMIN",
    )
    store.close()

    reopened_store = EventStore(str(path))
    reopened = ProductionCredentialVault.for_testing(store=reopened_store, secret_backend=backend)
    assert reopened.metadata(ref).status is CredentialStatus.ACTIVE
    assert reopened.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=20).values() == (
        "RESTART_KEY",
        b"RESTART_SECRET",
    )
    reopened.revoke(
        credential_id=ref.credential_id,
        version=ref.version,
        now_ms=21,
        actor_role="PRODUCTION_TRADING",
    )
    reopened_store.close()

    final_store = EventStore(str(path))
    restored = ProductionCredentialVault.for_testing(store=final_store, secret_backend=backend)
    assert restored.metadata(ref).status is CredentialStatus.REVOKED
    with pytest.raises(ProductionCredentialAccessError, match="REVOKED"):
        restored.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=22)
    final_store.close()


def test_unrecognized_actor_role_is_never_copied_to_the_audit_ledger():
    store, vault, ref = vault_and_ref()
    marker = "DO_NOT_LOG_THIS_ROLE_SECRET"
    with pytest.raises(ProductionCredentialAccessError, match="RESEARCH_FORBIDDEN"):
        vault.resolve(ref, actor_role=marker, now_ms=20)
    assert marker not in "\n".join(str(event.payload) for event in store.iter_events())


def test_runtime_credential_representation_redacts_secret_material():
    creds = RuntimeCredentialValues("DO_NOT_LOG_KEY", b"DO_NOT_LOG_SECRET")
    assert "DO_NOT_LOG_KEY" not in repr(creds)
    assert "DO_NOT_LOG_SECRET" not in repr(creds)


def test_repeated_resolutions_at_same_timestamp_have_distinct_audit_events():
    store, vault, ref = vault_and_ref()
    vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=20)
    vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=20)

    events = [event for event in store.iter_events() if event.event_type == vault.RESOLVE_EVENT]
    assert len(events) == 2
    assert len({event.event_id for event in events}) == 2


class _BlockingSnapshotBackend(InMemoryCredentialSecretBackend):
    def __init__(self):
        super().__init__()
        self.read_started = Event()
        self.continue_read = Event()

    def get(self, *, credential_id: str, version: str, fingerprint: str):
        material = super().get(credential_id=credential_id, version=version, fingerprint=fingerprint)
        self.read_started.set()
        if not self.continue_read.wait(timeout=5):
            raise CredentialBackendError("TEST_BACKEND_READ_TIMEOUT")
        return material


def test_revocation_serializes_after_in_flight_credential_resolution():
    store = EventStore()
    backend = _BlockingSnapshotBackend()
    vault = ProductionCredentialVault.for_testing(store=store, secret_backend=backend)
    ref = vault.register(
        credential_id="concurrent-revoke",
        version="v1",
        api_key="CONCURRENT_KEY",
        api_secret=b"CONCURRENT_SECRET",
        valid_from_ms=10,
        ttl_ms=100,
        actor_role="SECURITY_ADMIN",
    )
    resolved = []
    errors = []
    revoke_started = Event()
    revoke_completed = Event()

    def resolve():
        try:
            resolved.append(vault.resolve(ref, actor_role="PRODUCTION_TRADING", now_ms=20))
        except Exception as exc:  # surfaced in the main test thread below
            errors.append(exc)

    def revoke():
        try:
            revoke_started.set()
            vault.revoke(
                credential_id=ref.credential_id,
                version=ref.version,
                now_ms=21,
                actor_role="PRODUCTION_TRADING",
            )
        except Exception as exc:  # surfaced in the main test thread below
            errors.append(exc)
        finally:
            revoke_completed.set()

    resolve_thread = Thread(target=resolve)
    revoke_thread = Thread(target=revoke)
    resolve_thread.start()
    assert backend.read_started.wait(timeout=2)
    revoke_thread.start()
    assert revoke_started.wait(timeout=2)
    try:
        assert not revoke_completed.wait(timeout=0.25)
    finally:
        backend.continue_read.set()
    resolve_thread.join(timeout=5)
    revoke_thread.join(timeout=5)

    assert not resolve_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert errors == []
    assert len(resolved) == 1
    event_types = [event.event_type for event in store.iter_events()]
    assert event_types.index(vault.RESOLVE_EVENT) < event_types.index(vault.REVOKE_EVENT)
    assert backend.get(
        credential_id=ref.credential_id,
        version=ref.version,
        fingerprint=ref.fingerprint,
    ) is None
