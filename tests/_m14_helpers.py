from datetime import datetime, timedelta, timezone

from trading_platform.promotion.compatibility import Compatibility, CompatibilityReport
from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v341.compatibility_authority import CompatibilityAuthorityLedger

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
