from __future__ import annotations

from typing import Any, Mapping

from trading_platform.v360.readiness_evidence import (
    EvidenceSourceKind,
    REQUIRED_EVIDENCE_CLASSES,
    ReadinessEvidenceInvalid,
)
from trading_platform.v361.evidence_package import (
    EvidencePackageImporter,
    EvidencePackageInvalid,
    validate_package,
)


class ExternalEvidencePackageInvalid(EvidencePackageInvalid):
    pass


class ExternalEvidencePackageImporter(EvidencePackageImporter):
    """V3.64 package boundary: only explicitly EXTERNAL evidence may enter
    the production-readiness verification path.

    Legacy V3.61 packages remain importable but contain UNKNOWN provenance and
    therefore cannot be verified by the hardened V3.64 verification gate.
    """

    def import_package(self, package: Mapping[str, Any]):
        package_id, scope, items, _ = validate_package(package)
        for item in items:
            try:
                kind = EvidenceSourceKind(str(item.get("source_kind", EvidenceSourceKind.UNKNOWN.value)))
            except ValueError as exc:
                raise ExternalEvidencePackageInvalid("SOURCE_KIND_INVALID") from exc
            if kind is not EvidenceSourceKind.EXTERNAL:
                raise ExternalEvidencePackageInvalid("EXTERNAL_EVIDENCE_REQUIRED")
            if not str(item.get("source_system", "")).strip():
                raise ExternalEvidencePackageInvalid("EXTERNAL_SOURCE_SYSTEM_REQUIRED")
            if str(item.get("source_ref", "")).startswith(("demo:", "synthetic:")):
                raise ExternalEvidencePackageInvalid("SYNTHETIC_EVIDENCE_SOURCE_FORBIDDEN")

        # Use the parent importer after validation; v3.61 now persists source_kind.
        return super().import_package(package)


def assert_external_evidence(evidence) -> None:
    """Fail closed unless the record explicitly carries EXTERNAL provenance."""
    if getattr(evidence, "source_kind", EvidenceSourceKind.UNKNOWN) is not EvidenceSourceKind.EXTERNAL:
        raise ReadinessEvidenceInvalid("EXTERNAL_READINESS_EVIDENCE_REQUIRED")
