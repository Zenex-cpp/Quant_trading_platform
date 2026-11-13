"""Secret material backends for the production credential vault.

The Windows implementation stores encrypted generic credentials in the current
Windows security principal's Credential Manager. Deploy the trading worker under
a dedicated service identity; this backend does not itself create that identity
or establish process isolation from other software running as the same user.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
from abc import ABC, abstractmethod
from hashlib import sha256
import json
import os
import re
from typing import Any

from trading_platform.v35.binance_execution import RuntimeCredentialValues


MAX_CREDENTIAL_BLOB_BYTES = 2_500
MAX_CREDENTIAL_FIELD_BYTES = 900
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class CredentialBackendError(RuntimeError):
    """A secret backend failed without exposing secret material in its message."""


class CredentialSecretBackend(ABC):
    """Interface implemented by persistent production and ephemeral test stores."""

    backend_id: str
    persistent: bool

    @abstractmethod
    def put(
        self,
        *,
        credential_id: str,
        version: str,
        fingerprint: str,
        api_key: str,
        api_secret: bytes,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def get(
        self,
        *,
        credential_id: str,
        version: str,
        fingerprint: str,
    ) -> RuntimeCredentialValues | None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, *, credential_id: str, version: str, fingerprint: str) -> None:
        raise NotImplementedError


class InMemoryCredentialSecretBackend(CredentialSecretBackend):
    """Ephemeral backend reserved for explicitly constructed tests."""

    backend_id = "IN_MEMORY_TEST_ONLY"
    persistent = False

    def __init__(self) -> None:
        self.__values: dict[tuple[str, str, str], RuntimeCredentialValues] = {}

    def put(
        self,
        *,
        credential_id: str,
        version: str,
        fingerprint: str,
        api_key: str,
        api_secret: bytes,
    ) -> None:
        key = (credential_id, version, fingerprint)
        value = RuntimeCredentialValues(api_key, bytes(api_secret))
        prior = self.__values.get(key)
        if prior is not None and prior != value:
            raise CredentialBackendError("CREDENTIAL_BACKEND_VERSION_CONFLICT")
        self.__values[key] = value

    def get(
        self,
        *,
        credential_id: str,
        version: str,
        fingerprint: str,
    ) -> RuntimeCredentialValues | None:
        return self.__values.get((credential_id, version, fingerprint))

    def delete(self, *, credential_id: str, version: str, fingerprint: str) -> None:
        self.__values.pop((credential_id, version, fingerprint), None)


class WindowsCredentialManagerApi:
    """Small ctypes wrapper around Windows CredWrite/CredRead/CredDelete."""

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    def __init__(self) -> None:
        if os.name != "nt":
            raise CredentialBackendError("WINDOWS_CREDENTIAL_MANAGER_UNAVAILABLE")
        self.__advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)

        class _CREDENTIALW(ctypes.Structure):
            _fields_ = [
                ("Flags", wintypes.DWORD),
                ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR),
                ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME),
                ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD),
                ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR),
                ("UserName", wintypes.LPWSTR),
            ]

        self.__credential_type = _CREDENTIALW
        self.__advapi.CredWriteW.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
        self.__advapi.CredWriteW.restype = wintypes.BOOL
        self.__advapi.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CREDENTIALW)),
        ]
        self.__advapi.CredReadW.restype = wintypes.BOOL
        self.__advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.__advapi.CredDeleteW.restype = wintypes.BOOL
        self.__advapi.CredFree.argtypes = [ctypes.c_void_p]
        self.__advapi.CredFree.restype = None

    def write(self, target: str, blob: bytes) -> None:
        buffer = ctypes.create_string_buffer(blob, len(blob))
        record = self.__credential_type()
        record.Type = self.CRED_TYPE_GENERIC
        record.TargetName = target
        record.CredentialBlobSize = len(blob)
        record.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        record.Persist = self.CRED_PERSIST_LOCAL_MACHINE
        record.UserName = "trading-platform"
        if not self.__advapi.CredWriteW(ctypes.byref(record), 0):
            raise CredentialBackendError("WINDOWS_CREDENTIAL_WRITE_FAILED")

    def read(self, target: str) -> bytes | None:
        pointer = ctypes.POINTER(self.__credential_type)()
        ctypes.set_last_error(0)
        if not self.__advapi.CredReadW(target, self.CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
            if ctypes.get_last_error() == self.ERROR_NOT_FOUND:
                return None
            raise CredentialBackendError("WINDOWS_CREDENTIAL_READ_FAILED")
        try:
            record = pointer.contents
            if record.CredentialBlobSize > MAX_CREDENTIAL_BLOB_BYTES:
                raise CredentialBackendError("WINDOWS_CREDENTIAL_SIZE_LIMIT_EXCEEDED")
            if record.CredentialBlobSize and not record.CredentialBlob:
                raise CredentialBackendError("WINDOWS_CREDENTIAL_BLOB_INVALID")
            return ctypes.string_at(record.CredentialBlob, record.CredentialBlobSize)
        finally:
            self.__advapi.CredFree(pointer)

    def delete(self, target: str) -> None:
        ctypes.set_last_error(0)
        if not self.__advapi.CredDeleteW(target, self.CRED_TYPE_GENERIC, 0):
            if ctypes.get_last_error() != self.ERROR_NOT_FOUND:
                raise CredentialBackendError("WINDOWS_CREDENTIAL_DELETE_FAILED")


def _validate_identity(credential_id: str, version: str, fingerprint: str) -> None:
    if not isinstance(credential_id, str) or not _IDENTIFIER.fullmatch(credential_id):
        raise CredentialBackendError("CREDENTIAL_ID_INVALID")
    if not isinstance(version, str) or not _IDENTIFIER.fullmatch(version):
        raise CredentialBackendError("CREDENTIAL_VERSION_INVALID")
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise CredentialBackendError("CREDENTIAL_FINGERPRINT_INVALID")


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CredentialBackendError("CREDENTIAL_BACKEND_DUPLICATE_FIELD")
        result[key] = value
    return result


class WindowsCredentialManagerBackend(CredentialSecretBackend):
    """Persistent per-Windows-user store backed by encrypted generic credentials.

    Credential target names reveal only a SHA-256 locator. Material is stored in
    the Credential Manager blob and is not included in ledger events or errors.
    The caller must run the production worker as a dedicated OS service identity
    to obtain an operating-system principal boundary from Research.
    """

    backend_id = "WINDOWS_CREDENTIAL_MANAGER"
    persistent = True
    _PAYLOAD_FIELDS = {"credential_id", "version", "fingerprint", "api_key", "api_secret_b64"}

    def __init__(self, *, api: Any | None = None, target_prefix: str = "trading-platform") -> None:
        if not isinstance(target_prefix, str) or not _IDENTIFIER.fullmatch(target_prefix):
            raise CredentialBackendError("CREDENTIAL_TARGET_PREFIX_INVALID")
        self.__api = api or WindowsCredentialManagerApi()
        self.__target_prefix = target_prefix

    def _target(self, credential_id: str, version: str, fingerprint: str) -> str:
        _validate_identity(credential_id, version, fingerprint)
        locator = sha256(f"{credential_id}\0{version}\0{fingerprint}".encode("utf-8")).hexdigest()
        return f"{self.__target_prefix}:{locator}"

    def put(
        self,
        *,
        credential_id: str,
        version: str,
        fingerprint: str,
        api_key: str,
        api_secret: bytes,
    ) -> None:
        if not isinstance(api_key, str) or not api_key or "\0" in api_key:
            raise CredentialBackendError("CREDENTIAL_API_KEY_INVALID")
        if not isinstance(api_secret, bytes) or not api_secret:
            raise CredentialBackendError("CREDENTIAL_API_SECRET_INVALID")
        if len(api_key.encode("utf-8")) > MAX_CREDENTIAL_FIELD_BYTES or len(api_secret) > MAX_CREDENTIAL_FIELD_BYTES:
            raise CredentialBackendError("CREDENTIAL_FIELD_SIZE_LIMIT_EXCEEDED")
        payload = {
            "credential_id": credential_id,
            "version": version,
            "fingerprint": fingerprint,
            "api_key": api_key,
            "api_secret_b64": base64.b64encode(api_secret).decode("ascii"),
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(blob) > MAX_CREDENTIAL_BLOB_BYTES:
            raise CredentialBackendError("CREDENTIAL_BACKEND_SIZE_LIMIT_EXCEEDED")
        target = self._target(credential_id, version, fingerprint)
        try:
            existing = self.__api.read(target)
        except CredentialBackendError:
            raise
        except Exception:
            raise CredentialBackendError("CREDENTIAL_BACKEND_READ_FAILED") from None
        if existing is not None:
            decoded = self._decode(existing)
            if decoded != payload:
                raise CredentialBackendError("CREDENTIAL_BACKEND_VERSION_CONFLICT")
            return
        try:
            self.__api.write(target, blob)
        except CredentialBackendError:
            raise
        except Exception:
            raise CredentialBackendError("CREDENTIAL_BACKEND_WRITE_FAILED") from None

    def get(
        self,
        *,
        credential_id: str,
        version: str,
        fingerprint: str,
    ) -> RuntimeCredentialValues | None:
        target = self._target(credential_id, version, fingerprint)
        try:
            blob = self.__api.read(target)
        except CredentialBackendError:
            raise
        except Exception:
            raise CredentialBackendError("CREDENTIAL_BACKEND_READ_FAILED") from None
        if blob is None:
            return None
        payload = self._decode(blob)
        if (
            payload["credential_id"] != credential_id
            or payload["version"] != version
            or payload["fingerprint"] != fingerprint
        ):
            raise CredentialBackendError("CREDENTIAL_BACKEND_BINDING_MISMATCH")
        return RuntimeCredentialValues(payload["api_key"], base64.b64decode(payload["api_secret_b64"], validate=True))

    def delete(self, *, credential_id: str, version: str, fingerprint: str) -> None:
        target = self._target(credential_id, version, fingerprint)
        try:
            self.__api.delete(target)
        except CredentialBackendError:
            raise
        except Exception:
            raise CredentialBackendError("CREDENTIAL_BACKEND_DELETE_FAILED") from None

    @classmethod
    def _decode(cls, blob: bytes) -> dict[str, Any]:
        if not isinstance(blob, bytes) or not blob or len(blob) > MAX_CREDENTIAL_BLOB_BYTES:
            raise CredentialBackendError("CREDENTIAL_BACKEND_BLOB_INVALID")
        try:
            payload = json.loads(blob.decode("utf-8"), object_pairs_hook=_unique_pairs)
        except CredentialBackendError:
            raise
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CredentialBackendError("CREDENTIAL_BACKEND_BLOB_INVALID") from None
        if not isinstance(payload, dict) or set(payload) != cls._PAYLOAD_FIELDS:
            raise CredentialBackendError("CREDENTIAL_BACKEND_SCHEMA_INVALID")
        credential_id = payload["credential_id"]
        version = payload["version"]
        fingerprint = payload["fingerprint"]
        api_key = payload["api_key"]
        api_secret_b64 = payload["api_secret_b64"]
        _validate_identity(credential_id, version, fingerprint)
        if not isinstance(api_key, str) or not api_key or "\0" in api_key:
            raise CredentialBackendError("CREDENTIAL_BACKEND_API_KEY_INVALID")
        if not isinstance(api_secret_b64, str):
            raise CredentialBackendError("CREDENTIAL_BACKEND_API_SECRET_INVALID")
        try:
            secret = base64.b64decode(api_secret_b64, validate=True)
        except (ValueError, base64.binascii.Error):
            raise CredentialBackendError("CREDENTIAL_BACKEND_API_SECRET_INVALID") from None
        if not secret or len(api_key.encode("utf-8")) > MAX_CREDENTIAL_FIELD_BYTES or len(secret) > MAX_CREDENTIAL_FIELD_BYTES:
            raise CredentialBackendError("CREDENTIAL_BACKEND_FIELD_INVALID")
        return payload
