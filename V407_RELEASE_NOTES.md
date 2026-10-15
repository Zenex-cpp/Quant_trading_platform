# V4.7 Release Notes

V4.7 closes a promotion-path freshness gap. `CriticalPromotionReadinessAuthorityV398` now requires `EvidenceSnapshotAuthorityLedger.assert_valid(...)` with exact bundle, model, gates, artifacts, versions, approval, scope and dependency bindings.

`EvidenceSnapshotAuthorityLedger` now includes `snapshot_id` in its dependency freshness set, so a direct invalidation of the immutable snapshot cannot be bypassed by a later promotion check.

Production readiness remains blocked by the previously documented external operational evidence requirements.
