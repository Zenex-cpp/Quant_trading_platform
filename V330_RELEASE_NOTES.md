# V3.30 Release Notes

V3.30 completes the machine-enforcement work started in V3.29 for M17 and M27.

## M17 — gate reuse after invalidating change

- `GateSummary.all_required_passed()` now requires an explicit `DependencyInvalidationLedger`.
- `promotion_allowed()` now requires the same authority and checks the complete promotion dependency set before accepting gates.
- `DeploymentOrchestrator` requires an explicitly injected dependency authority; no private in-memory fallback remains.
- The deployment preparation path therefore cannot silently bypass an active dependency invalidation.
- Missing authority fails closed at the API boundary.

## M27 — Final Holdout improper access

- Final Holdout access now requires an explicit `HoldoutAccessContext`.
- Every authorized access is durably recorded as `FINAL_HOLDOUT_ACCESS_ATTEMPTED`.
- A forbidden tuning access additionally emits `FINAL_HOLDOUT_ACCESS_VIOLATION` and creates a durable dependency-invalidation incident.
- The invalidation propagates from the Holdout dependency into directly dependent evidence and downstream gates/candidates/promotions.
- Missing access context fails closed; it is no longer possible to silently access the Final Holdout outside the governed path.
- Restart reconstruction preserves the active invalidation.

## Verification boundary

M17 and M27 are `TESTED`, not `VERIFIED`: the Master Prompt defines `VERIFIED` as test + evidence + review. Independent review remains a governance activity.

`production_ready = FALSE`.

Automated verification: **432/432 tests passed**.
