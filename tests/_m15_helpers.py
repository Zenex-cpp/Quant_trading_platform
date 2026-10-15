from datetime import datetime, timedelta, timezone

from trading_platform.promotion.contracts import PromotionBundle
from trading_platform.v21.event_store import EventStore
from trading_platform.v342.artifact_integrity import ArtifactIntegrityAuthorityLedger

NOW = datetime(2026, 9, 23, 9, 0, tzinfo=timezone.utc)


def authorize_artifact_integrity(
    store: EventStore,
    bundle: PromotionBundle,
    *,
    authorization_id: str = "INTEGRITY-1",
    now: datetime = NOW,
    manifest_hash: str = "manifest-1",
):
    return ArtifactIntegrityAuthorityLedger(store).authorize(
        authorization_id=authorization_id,
        artifact_id=bundle.bundle_id,
        artifact_hashes=bundle.artifact_hashes,
        observed_artifact_hashes=bundle.artifact_hashes,
        manifest_hash=manifest_hash,
        signature_verified=True,
        valid_from=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=30),
        reviewer="integrity-reviewer",
        recorded_at_ms=int(now.timestamp() * 1000),
    )[0]
