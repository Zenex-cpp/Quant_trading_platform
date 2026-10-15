from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class AcceptanceStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    NOT_VERIFIED = "NOT_VERIFIED"


@dataclass(frozen=True)
class AcceptanceItem:
    requirement_id: str
    status: AcceptanceStatus
    evidence_ref: str
    blocking: bool


@dataclass(frozen=True)
class AcceptanceReport:
    items: tuple[AcceptanceItem, ...]
    acceptance_passed: bool

    @property
    def production_ready(self) -> bool:
        """Deprecated compatibility field: §178 acceptance never establishes production readiness."""
        return False


def build_acceptance(items: list[AcceptanceItem]) -> AcceptanceReport:
    acceptance_passed = bool(items) and all(
        i.status is AcceptanceStatus.PASS for i in items if i.blocking
    )
    return AcceptanceReport(tuple(items), acceptance_passed)
