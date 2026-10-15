# V4.8 Release Notes

V4.8 closes the remaining critical-promotion gate freshness gap.

`GatePromotionAuthorizationLedgerV408` records an exact PASS `Gate` together with its dependency checkpoint and a canonical gate fingerprint. `CriticalPromotionReadinessAuthorityV398` now consults this durable authority for every gate in the critical promotion bundle before accepting readiness.

A critical promotion therefore cannot reuse a gate merely by gate identifier. Missing authorization, non-PASS state, fingerprint mismatch, active dependency invalidation, or an invalidation after the gate checkpoint fails closed with `CRITICAL_PROMOTION_GATE_REVALIDATION_REQUIRED`.

The gate authorization persists enough gate metadata to survive restart and revalidation without trusting in-memory state. V4.8 remains verification-only and does not create production approvals or execute network/process side effects.

Production readiness remains blocked by previously documented external operational evidence requirements.
