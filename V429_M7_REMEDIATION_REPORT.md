# V4.29 M7 Champion Gate Remediation

**Status:** `TESTED`; independent review and operational promotion evidence remain open.

## Finding

`ChampionGateAuthorityLedger.authorize` accepted caller-supplied `passed_gate_ids` without requiring durable PASS gate records. A caller could therefore construct a durable Champion authorization by naming required gates that had never passed. The authorization did not retain the identity or fingerprint of the gate run used to support it.

## Changes

- Removed caller-supplied pass claims. Authorization now requires every required gate to have a reusable record in the durable V4.08 gate-promotion ledger.
- Bound each Champion authorization to the exact gate authorization ID and fingerprint, and required each gate's candidate version to match the model version.
- Rechecked those exact gate runs, dependency checkpoints and event-chain integrity whenever a Champion authorization is used for registry promotion or LIVE deployment.
- A missing, changed, invalidated, stale, or mismatched gate fails closed. Revalidated dependencies require a newly authorized gate run before a new Champion authorization can be issued.
- Distinguished an active invalidation from a revalidation that requires a rerun in the V4.08 gate-reuse authority.

## Verification

Focused Windows/Python 3.14.7 regressions across Champion governance, M17 invalidation, M18 evidence snapshots, M19 promotion bundles, V4.08 gate reuse, critical promotion and LIVE activation: **78 passed**. The mandatory V4.29 runner completed with **1,201 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight `READY_FOR_MILESTONE` with no blocking reason.

Tests use durable local event stores and synthetic gate/evidence records. No deployment was activated. M7 remains `TESTED`, not `VERIFIED`; independent review and operational evidence remain required. `external_evidence=false`, `production_ready=false`, `activation_flag=NOT_SET`.
