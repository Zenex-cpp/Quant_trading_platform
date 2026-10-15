from datetime import datetime, timedelta
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger


def authorize_promotion_bundle(store, bundle, *, authorization_id=None, now=None, valid_for_hours=1, reviewer="reviewer"):
    now = now or bundle.created_at
    dep = DependencyInvalidationLedger(store)
    ledger = PromotionBundleAuthorityLedger(store)
    return ledger.authorize(
        authorization_id=authorization_id or f"PB-{bundle.bundle_id}",
        bundle=bundle,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(hours=valid_for_hours),
        reviewer=reviewer,
        recorded_at_ms=max(1, int(now.timestamp() * 1000)),
        dependency_authority=dep,
        store=store,
    )[0]
