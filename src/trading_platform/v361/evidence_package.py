from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Mapping, Sequence
import json

from trading_platform.v21.event_store import EventStore, canonical_json, sha256_json
from trading_platform.v360.readiness_evidence import (
    EvidenceResult,
    REQUIRED_EVIDENCE_CLASSES,
    ReadinessEvidenceError,
    ReadinessEvidenceInvalid,
    ReadinessEvidenceLedger,
)


class EvidencePackageError(RuntimeError):
    pass


class EvidencePackageInvalid(EvidencePackageError):
    pass


@dataclass(frozen=True)
class ImportedEvidencePackage:
    package_id: str
    scope: str
    package_hash: str
    evidence_ids: tuple[str, ...]
    imported_event_id: str

    @property
    def fingerprint(self) -> str:
        return sha256_json({
            "package_id": self.package_id,
            "scope": self.scope,
            "package_hash": self.package_hash,
            "evidence_ids": self.evidence_ids,
            "imported_event_id": self.imported_event_id,
        })


_FORBIDDEN_KEYS = {
    "secret", "secrets", "api_key", "api_secret", "private_key", "credential",
    "credentials", "access_token", "refresh_token", "password", "token", "raw_secret",
}


def _reject_sensitive_keys(value: Any, path: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            key_lower = str(key).lower()
            if key_lower in _FORBIDDEN_KEYS or any(fragment in key_lower for fragment in ("secret", "private_key", "password")):
                raise EvidencePackageInvalid(f"SENSITIVE_FIELD_FORBIDDEN:{path}.{key}")
            _reject_sensitive_keys(nested, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, nested in enumerate(value):
            _reject_sensitive_keys(nested, f"{path}[{index}]")


def canonical_package_body(package: Mapping[str, Any]) -> dict[str, Any]:
    body = dict(package)
    body.pop("package_hash", None)
    return body


def compute_package_hash(package: Mapping[str, Any]) -> str:
    return sha256(canonical_json(canonical_package_body(package))).hexdigest()


def validate_package(package: Mapping[str, Any]) -> tuple[str, str, list[dict[str, Any]], str]:
    _reject_sensitive_keys(package)
    required = {"package_id", "scope", "created_at_ms", "source_system", "evidence", "package_hash"}
    missing = sorted(required - set(package))
    if missing:
        raise EvidencePackageInvalid(f"PACKAGE_FIELDS_MISSING:{','.join(missing)}")
    if not isinstance(package["evidence"], list) or not package["evidence"]:
        raise EvidencePackageInvalid("PACKAGE_EVIDENCE_REQUIRED")
    package_hash = str(package["package_hash"])
    computed = compute_package_hash(package)
    if package_hash != computed:
        raise EvidencePackageInvalid("PACKAGE_HASH_MISMATCH")
    package_id = str(package["package_id"])
    scope = str(package["scope"])
    if not package_id or not scope or not str(package["source_system"]):
        raise EvidencePackageInvalid("PACKAGE_IDENTIFIERS_REQUIRED")
    items: list[dict[str, Any]] = []
    seen = set()
    for raw in package["evidence"]:
        if not isinstance(raw, Mapping):
            raise EvidencePackageInvalid("EVIDENCE_ITEM_NOT_OBJECT")
        item = dict(raw)
        required_item = {
            "evidence_id", "evidence_class", "scope", "result", "observed_at_ms", "valid_from_ms",
            "expires_at_ms", "source_system", "source_ref", "content_hash",
        }
        item_missing = sorted(required_item - set(item))
        if item_missing:
            raise EvidencePackageInvalid(f"EVIDENCE_FIELDS_MISSING:{','.join(item_missing)}")
        evidence_id = str(item["evidence_id"])
        if evidence_id in seen:
            raise EvidencePackageInvalid("DUPLICATE_EVIDENCE_ID")
        seen.add(evidence_id)
        if str(item["scope"]) != scope:
            raise EvidencePackageInvalid("EVIDENCE_SCOPE_MISMATCH")
        if str(item["evidence_class"]) not in REQUIRED_EVIDENCE_CLASSES:
            raise EvidencePackageInvalid("EVIDENCE_CLASS_NOT_REQUIRED")
        if str(item["result"]) != EvidenceResult.PASS.value:
            raise EvidencePackageInvalid("EVIDENCE_RESULT_NOT_PASS")
        source_ref = str(item["source_ref"])
        if source_ref.startswith("demo:") or source_ref.startswith("synthetic:"):
            raise EvidencePackageInvalid("SYNTHETIC_EVIDENCE_SOURCE_FORBIDDEN")
        if any(not isinstance(item[field], int) for field in ("observed_at_ms", "valid_from_ms", "expires_at_ms")):
            raise EvidencePackageInvalid("EVIDENCE_TIME_FIELDS_MUST_BE_INT")
        items.append(item)
    return package_id, scope, items, package_hash


class EvidencePackageImporter:
    IMPORT_EVENT_TYPE = "READINESS_EVIDENCE_PACKAGE_IMPORTED"

    def __init__(self, store: EventStore):
        self.store = store
        self.ledger = ReadinessEvidenceLedger(store)

    def import_package(self, package: Mapping[str, Any]) -> ImportedEvidencePackage:
        package_id, scope, items, package_hash = validate_package(package)
        evidence_ids = tuple(sorted(str(item["evidence_id"]) for item in items))
        imported_event_id = f"readiness-package:{package_id}:imported"
        specs = [{
            "event_id": imported_event_id,
            "occurred_at_ms": int(package["created_at_ms"]),
            "event_type": self.IMPORT_EVENT_TYPE,
            "aggregate_id": package_id,
            "payload": {
                "package_id": package_id,
                "scope": scope,
                "package_hash": package_hash,
                "evidence_ids": list(evidence_ids),
                "source_system": str(package["source_system"]),
            },
        }]
        for item in items:
            evidence_id = str(item["evidence_id"])
            specs.append({
                "event_id": f"readiness-evidence:{evidence_id}:submitted",
                "occurred_at_ms": int(package["created_at_ms"]),
                "event_type": ReadinessEvidenceLedger.SUBMIT_EVENT,
                "aggregate_id": evidence_id,
                "payload": {
                    "evidence_id": evidence_id,
                    "evidence_class": str(item["evidence_class"]),
                    "scope": scope,
                    "result": EvidenceResult.PASS.value,
                    "observed_at_ms": int(item["observed_at_ms"]),
                    "valid_from_ms": int(item["valid_from_ms"]),
                    "expires_at_ms": int(item["expires_at_ms"]),
                    "source_system": str(item["source_system"]),
                    "source_ref": str(item["source_ref"]),
                    "source_kind": str(item.get("source_kind", "UNKNOWN")),
                    "content_hash": str(item["content_hash"]),
                    "submitted_at_ms": int(package["created_at_ms"]),
                },
            })
        try:
            self.store.append_atomic(specs)
        except RuntimeError as exc:
            if "PARTIAL_BATCH" in str(exc):
                raise EvidencePackageError("READINESS_EVIDENCE_PACKAGE_PARTIAL_IMPORT") from exc
            raise
        return ImportedEvidencePackage(
            package_id=package_id,
            scope=scope,
            package_hash=package_hash,
            evidence_ids=evidence_ids,
            imported_event_id=imported_event_id,
        )

    def package_was_imported(self, package_id: str) -> bool:
        event_id = f"readiness-package:{package_id}:imported"
        event = self.store.get(event_id)
        return event is not None and event.event_type == self.IMPORT_EVENT_TYPE


def build_template() -> dict[str, Any]:
    return {
        "package_id": "REPLACE_WITH_EXTERNAL_PACKAGE_ID",
        "scope": "PRODUCTION",
        "created_at_ms": 0,
        "source_system": "REPLACE_WITH_REAL_SOURCE_SYSTEM",
        "evidence": [
            {
                "evidence_id": "REPLACE_WITH_REAL_EVIDENCE_ID",
                "evidence_class": REQUIRED_EVIDENCE_CLASSES[0],
                "scope": "PRODUCTION",
                "result": "PASS",
                "observed_at_ms": 0,
                "valid_from_ms": 0,
                "expires_at_ms": 0,
                "source_system": "REPLACE_WITH_REAL_SOURCE_SYSTEM",
                "source_ref": "REPLACE_WITH_EXTERNAL_REFERENCE",
                "content_hash": "REPLACE_WITH_64_HEX_SHA256",
                "source_kind": "EXTERNAL",
            }
        ],
    }
