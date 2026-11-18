"""Versioned statistical-method catalog for §113/§179."""
from __future__ import annotations

import csv
from pathlib import Path

from trading_platform.research.methods import MethodSpec


class StatisticalMethodCatalogError(ValueError):
    """The statistical method catalog is incomplete or unsafe."""


class StatisticalMethodCatalog:
    def __init__(self, specs: tuple[MethodSpec, ...]):
        if not specs:
            raise StatisticalMethodCatalogError("METHOD_CATALOG_EMPTY")
        if any(
            not item.method_id
            or not item.version
            or not item.applicability
            or not item.output_semantics
            for item in specs
        ):
            raise StatisticalMethodCatalogError("METHOD_CATALOG_IDENTITY_OR_SEMANTICS_REQUIRED")
        identities = {(item.method_id, item.version) for item in specs}
        if len(identities) != len(specs):
            raise StatisticalMethodCatalogError("METHOD_CATALOG_DUPLICATE")
        if any(not item.assumptions or not item.limitations or not item.required_inputs for item in specs):
            raise StatisticalMethodCatalogError("METHOD_CATALOG_CONTRACT_INCOMPLETE")
        if any(not item.implementation_reference or not item.output_semantics for item in specs):
            raise StatisticalMethodCatalogError("METHOD_CATALOG_IMPLEMENTATION_REFERENCE_REQUIRED")
        self._specs = tuple(specs)
        self._by_identity = {(item.method_id, item.version): item for item in specs}

    @classmethod
    def from_csv(cls, path: Path) -> "StatisticalMethodCatalog":
        required = {
            "method_id", "version", "applicability", "assumptions", "limitations",
            "required_inputs", "output_semantics", "implementation_reference", "status",
        }
        try:
            with path.open(newline="", encoding="utf-8") as stream:
                reader = csv.DictReader(stream)
                if set(reader.fieldnames or ()) != required:
                    raise StatisticalMethodCatalogError("METHOD_CATALOG_SCHEMA_INVALID")
                specs = []
                for row in reader:
                    if row["status"] != "SPECIFICATION_ONLY":
                        raise StatisticalMethodCatalogError("METHOD_CATALOG_STATUS_INVALID")
                    specs.append(
                        MethodSpec(
                            method_id=row["method_id"],
                            version=row["version"],
                            assumptions=tuple(filter(None, row["assumptions"].split("|"))),
                            applicability=row["applicability"],
                            limitations=tuple(filter(None, row["limitations"].split("|"))),
                            implementation_reference=row["implementation_reference"],
                            required_inputs=tuple(filter(None, row["required_inputs"].split("|"))),
                            output_semantics=row["output_semantics"],
                        )
                    )
        except OSError as exc:
            raise StatisticalMethodCatalogError("METHOD_CATALOG_UNREADABLE") from exc
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, StatisticalMethodCatalogError):
                raise
            raise StatisticalMethodCatalogError("METHOD_CATALOG_ROW_INVALID") from exc
        return cls(tuple(specs))

    @property
    def specs(self) -> tuple[MethodSpec, ...]:
        return self._specs

    def get(self, method_id: str, version: str) -> MethodSpec:
        try:
            return self._by_identity[(method_id, version)]
        except KeyError as exc:
            raise StatisticalMethodCatalogError("METHOD_NOT_REGISTERED") from exc
