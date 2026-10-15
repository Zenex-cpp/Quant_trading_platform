from __future__ import annotations

import pytest

from trading_platform.v392.secret_store_operational import (
    SecretLeaseV392,
    SecretLeaseStateV392,
    SecretStoreAttestationV392,
    SecretStoreBackendV392,
    SecretStoreBoundaryErrorV392,
    SecretStoreOperationalPolicyV392,
    assert_no_secret_material,
    assert_production_secret_store_ready,
    configuration_fingerprint,
)

NOW = 1_000_000


def attestation(*, backend=SecretStoreBackendV392.EXTERNAL_VAULT):
    return SecretStoreAttestationV392(
        backend=backend,
        backend_id="vault-prod",
        backend_version="1.2.3",
        attested_at_ms=NOW - 100,
        expires_at_ms=NOW + 3_600_000,
        configuration_fingerprint=configuration_fingerprint({"cluster": "prod", "namespace": "trading"}),
        reviewer_id="reviewer-1",
        review_reference="SEC-REVIEW-392",
    )


def lease(*, backend=SecretStoreBackendV392.EXTERNAL_VAULT, expires_at=NOW + 900_000, state=SecretLeaseStateV392.ISSUED):
    return SecretLeaseV392("lease-1", "prod-primary", "v7", backend, NOW - 10, expires_at, "f" * 64, state)


def test_external_attested_store_is_admitted():
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=attestation(), lease=lease(), now_ms=NOW)
    assert d.allowed is True
    assert d.reason == "SECRET_STORE_READY"


def test_missing_attestation_fails_closed():
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=None, lease=lease(), now_ms=NOW)
    assert d.allowed is False and d.reason == "SECRET_STORE_ATTESTATION_REQUIRED"


def test_environment_and_in_memory_backends_cannot_be_production_backends():
    with pytest.raises(SecretStoreBoundaryErrorV392, match="PRODUCTION_SECRET_BACKEND_NOT_OPERATIONAL"):
        SecretStoreOperationalPolicyV392(production_backend=SecretStoreBackendV392.ENVIRONMENT).validate()
    with pytest.raises(SecretStoreBoundaryErrorV392, match="PRODUCTION_SECRET_BACKEND_NOT_OPERATIONAL"):
        SecretStoreOperationalPolicyV392(production_backend=SecretStoreBackendV392.IN_MEMORY_DEV).validate()


def test_backend_mismatch_fails_closed():
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=attestation(), lease=lease(backend=SecretStoreBackendV392.KMS_WRAPPED), now_ms=NOW)
    assert d.allowed is False and d.reason == "SECRET_STORE_BACKEND_MISMATCH"


def test_attestation_backend_mismatch_fails_closed():
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=attestation(backend=SecretStoreBackendV392.KMS_WRAPPED), lease=lease(), now_ms=NOW)
    assert d.allowed is False and d.reason == "SECRET_STORE_ATTESTATION_BACKEND_MISMATCH"


def test_attestation_expiry_fails_closed():
    a = SecretStoreAttestationV392(SecretStoreBackendV392.EXTERNAL_VAULT, "vault", "1", NOW - 10, NOW, "f" * 64, "r", "ref")
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=a, lease=lease(), now_ms=NOW)
    assert d.allowed is False and d.reason == "SECRET_STORE_ATTESTATION_EXPIRED"


def test_lease_expiry_fails_closed():
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=attestation(), lease=lease(expires_at=NOW), now_ms=NOW)
    assert d.allowed is False and d.reason == "SECRET_LEASE_EXPIRED"


def test_lease_ttl_ceiling_is_machine_checkable():
    d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(max_lease_ttl_ms=100), attestation=attestation(), lease=lease(expires_at=NOW + 900_000), now_ms=NOW)
    assert d.allowed is False and d.reason == "SECRET_LEASE_TTL_EXCEEDS_POLICY"


def test_revoked_or_consumed_lease_cannot_authorize_production():
    for state in (SecretLeaseStateV392.REVOKED, SecretLeaseStateV392.CONSUMED, SecretLeaseStateV392.EXPIRED):
        d = assert_production_secret_store_ready(policy=SecretStoreOperationalPolicyV392(), attestation=attestation(), lease=lease(state=state), now_ms=NOW)
        assert d.allowed is False and d.reason == "SECRET_LEASE_NOT_ACTIVE"


def test_evidence_contract_rejects_secret_material():
    with pytest.raises(SecretStoreBoundaryErrorV392, match="SECRET_MATERIAL_IN_EVIDENCE"):
        assert_no_secret_material({"backend_id": "vault", "api_secret": "DO_NOT_STORE"})


def test_safe_payloads_do_not_contain_secret_material():
    a = attestation()
    l = lease()
    assert "secret" not in str(a.safe_payload()).lower()
    assert "secret" not in str(l.safe_payload()).lower()


def test_configuration_fingerprint_is_deterministic_and_secret_free():
    a = configuration_fingerprint({"namespace": "trading", "cluster": "prod"})
    b = configuration_fingerprint({"cluster": "prod", "namespace": "trading"})
    assert a == b and len(a) == 64


def test_configuration_fingerprint_rejects_secret_fields():
    with pytest.raises(SecretStoreBoundaryErrorV392, match="SECRET_MATERIAL_IN_REVIEW_CONFIGURATION"):
        configuration_fingerprint({"cluster": "prod", "api_secret": "x"})


def test_policy_forbids_production_secret_fallbacks():
    with pytest.raises(SecretStoreBoundaryErrorV392, match="PRODUCTION_SECRET_FALLBACK_FORBIDDEN"):
        SecretStoreOperationalPolicyV392(allow_environment_production=True).validate()
