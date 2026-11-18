import os

import pytest

from trading_platform.security.credential_backends import (
    CredentialBackendError,
    MAX_CREDENTIAL_FIELD_BYTES,
    WindowsCredentialManagerApi,
    WindowsCredentialManagerBackend,
)
from trading_platform.v35.binance_execution import RuntimeCredentialValues


class _FakeCredentialManagerApi:
    def __init__(self):
        self.records = {}
        self.targets = []

    def read(self, target):
        self.targets.append(target)
        return self.records.get(target)

    def write(self, target, blob):
        self.records[target] = bytes(blob)

    def delete(self, target):
        self.records.pop(target, None)


def _backend():
    api = _FakeCredentialManagerApi()
    return WindowsCredentialManagerBackend(api=api), api


def test_windows_backend_round_trips_secret_bytes_and_uses_opaque_target_names():
    backend, api = _backend()
    backend.put(
        credential_id="prod-primary",
        version="v7",
        fingerprint="a" * 64,
        api_key="API_KEY_SENTINEL",
        api_secret=b"secret\x00\xff",
    )

    result = backend.get(credential_id="prod-primary", version="v7", fingerprint="a" * 64)

    assert result == RuntimeCredentialValues("API_KEY_SENTINEL", b"secret\x00\xff")
    target = next(iter(api.records))
    assert target.startswith("trading-platform:")
    assert "prod-primary" not in target and "v7" not in target and "secret" not in target
    assert len(target.rsplit(":", 1)[1]) == 64


def test_windows_backend_put_is_idempotent_and_never_overwrites_a_version_blob():
    backend, api = _backend()
    values = {
        "credential_id": "prod-primary",
        "version": "v7",
        "fingerprint": "b" * 64,
        "api_key": "KEY",
        "api_secret": b"SECRET",
    }
    backend.put(**values)
    first = dict(api.records)
    backend.put(**values)
    assert api.records == first

    changed = dict(values, api_key="DIFFERENT_KEY")
    with pytest.raises(CredentialBackendError, match="VERSION_CONFLICT"):
        backend.put(**changed)
    assert api.records == first


def test_windows_backend_rejects_duplicate_fields_and_binding_mismatch():
    backend, api = _backend()
    backend.put(
        credential_id="prod-primary",
        version="v7",
        fingerprint="c" * 64,
        api_key="KEY",
        api_secret=b"SECRET",
    )
    target = next(iter(api.records))
    api.records[target] = b'{"credential_id":"a","credential_id":"b"}'
    with pytest.raises(CredentialBackendError, match="DUPLICATE_FIELD"):
        backend.get(credential_id="prod-primary", version="v7", fingerprint="c" * 64)

    api.records[target] = b'{"credential_id":"other","version":"v7","fingerprint":"' + b"c" * 64 + b'","api_key":"K","api_secret_b64":"Uw=="}'
    with pytest.raises(CredentialBackendError, match="BINDING_MISMATCH"):
        backend.get(credential_id="prod-primary", version="v7", fingerprint="c" * 64)


def test_windows_backend_bounds_secret_fields_before_os_call():
    backend, api = _backend()
    with pytest.raises(CredentialBackendError, match="FIELD_SIZE_LIMIT_EXCEEDED"):
        backend.put(
            credential_id="prod-primary",
            version="v7",
            fingerprint="d" * 64,
            api_key="K" * (MAX_CREDENTIAL_FIELD_BYTES + 1),
            api_secret=b"SECRET",
        )
    assert api.records == {}


def test_windows_backend_delete_is_idempotent():
    backend, api = _backend()
    backend.put(
        credential_id="prod-primary",
        version="v7",
        fingerprint="e" * 64,
        api_key="KEY",
        api_secret=b"SECRET",
    )
    backend.delete(credential_id="prod-primary", version="v7", fingerprint="e" * 64)
    backend.delete(credential_id="prod-primary", version="v7", fingerprint="e" * 64)
    assert api.records == {}


@pytest.mark.skipif(os.name != "nt", reason="Native API binding exists only on Windows")
def test_windows_native_credential_manager_api_binds_without_touching_credentials():
    WindowsCredentialManagerApi()
