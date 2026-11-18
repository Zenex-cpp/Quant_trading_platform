from datetime import datetime, timedelta, timezone
from typing import Callable

from trading_platform.promotion.compatibility import Compatibility, CompatibilityReport
from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v341.compatibility_authority import (
    CompatibilityAuthorityLedger,
    CompatibilityGuardedArtifactExecutor,
)

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def compatible_report() -> CompatibilityReport:
    return CompatibilityReport(*(Compatibility.COMPATIBLE for _ in range(7)))


def incompatible_report(kind: Compatibility = Compatibility.INCOMPATIBLE) -> CompatibilityReport:
    return CompatibilityReport(kind, *(Compatibility.COMPATIBLE for _ in range(6)))


def authorize_compatibility(store: EventStore, bundle: PromotionBundle, *, authorization_id: str = "COMPAT-1", now: datetime = NOW):
    return CompatibilityAuthorityLedger(store).authorize(
        authorization_id=authorization_id,
        artifact_id=bundle.bundle_id,
        artifact_hashes=bundle.artifact_hashes,
        code_version=bundle.code_version,
        configuration_version=bundle.configuration_version,
        execution_model_version=bundle.execution_model_version,
        report=compatible_report(),
        valid_from=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=30),
        reviewer="compatibility-reviewer",
        recorded_at_ms=int(now.timestamp() * 1000),
    )[0]


def authorize_runtime_executor(
    now: datetime,
    *,
    report_provider: Callable[[], CompatibilityReport] = compatible_report,
    authorization_id: str = "RUNTIME-COMPAT-1",
    expires_at: datetime | None = None,
    artifact_id: str = "MODEL-ARTIFACT-1",
    artifact_hashes: tuple[str, ...] = ("sha256:model-artifact-1",),
) -> CompatibilityGuardedArtifactExecutor:
    store = EventStore()
    dependencies = DependencyInvalidationLedger(store)
    ledger = CompatibilityAuthorityLedger(store)
    valid_from = now - timedelta(minutes=1)
    expires_at = expires_at or now + timedelta(hours=2)
    record, _ = ledger.authorize(
        authorization_id=authorization_id,
        artifact_id=artifact_id,
        artifact_hashes=artifact_hashes,
        code_version="CODE-1",
        configuration_version="CONFIG-1",
        execution_model_version="PARITY-BASE",
        report=compatible_report(),
        valid_from=valid_from,
        expires_at=expires_at,
        reviewer="compatibility-reviewer",
        recorded_at_ms=int(now.timestamp() * 1000),
        dependency_authority=dependencies,
    )
    return CompatibilityGuardedArtifactExecutor(
        ledger=ledger,
        authorization_id=record.authorization_id,
        artifact_id=record.artifact_id,
        artifact_hashes=record.artifact_hashes,
        code_version=record.code_version,
        configuration_version=record.configuration_version,
        execution_model_version=record.execution_model_version,
        report_provider=report_provider,
        dependency_authority=dependencies,
    )
