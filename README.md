# Quant Trading Platform

**Repository release train:** `V4.29-RECOVERY`  
**Python distribution version:** `3.61.5` (a separate versioning scheme).

The current repository is a recovery extension based on the available V4.28 recovery archive. Byte-for-byte canonical lineage to V4.23 and V4.26 is **not established** because those source archives are not available in the project.

## Current state

- V4.29 hardens the external Ed25519 signer and requires the fixed milestone preflight, full regression, and release-hygiene checks.
- The follow-up hardens chronological label purging at every split boundary and makes the offline §178 acceptance gate require real SQLite recovery, failure-injection, and deployment-rollback proofs. The E2E run uses training labels only and leaves final-holdout targets untouched.
- Holdout incidents are reconciled from the durable event store at context startup, so an interrupted invalidation is completed before dependents can be used.
- M16 configuration authority is enforced at final Testnet dispatch and deployment activation. Resolution ID, fingerprint, status and expiry are checked against the durable ledger; failures stop dispatch or activation before the external action.
- The final dispatch boundary requires durable risk-decision, position, fresh-market and causal-TTL authorities for risk-increasing orders. Missing or expired authority blocks before the gateway.
- Hosted regression for the previous main before this remediation, PR #14: **1,191 passed, 2 skipped**, `RELEASE_HYGIENE=PASS` ([run 42039306544](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/42039306544)).
- Current Windows/Python 3.14.7 validation: **1,190 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. POSIX-only signer checks remain enabled in Linux CI; symlink checks skip only when the host cannot create symlinks.
- Validation does not execute exchange orders or certify production readiness. `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain in force.

The hosted governance audit is intentionally non-fatal while signed, trusted external evidence is absent. A green CI job does not mean the trust anchor, independent evidence, operational controls, or production approval have been satisfied.

## Validate the recovery release

Run the fixed milestone entrypoint from the repository root:

```powershell
python scripts/run_milestone_validation_v429.py
```

The runner checks the V4.29 compliance preflight, runs the complete test suite, and checks release hygiene. CI uses the same entrypoint and fixed contract.

## Source documents

- [`MASTER PROMPT.txt`](MASTER%20PROMPT.txt) is the normative system specification.
- [`V429_VERIFICATION_REPORT.md`](V429_VERIFICATION_REPORT.md) records the recovery build and verification boundary.
- [`V429_OPEN_GAPS_DELTA.md`](V429_OPEN_GAPS_DELTA.md) lists unresolved external and operational gates.
- [`V429_PIT_E2E_REMEDIATION_REPORT.md`](V429_PIT_E2E_REMEDIATION_REPORT.md) records the split-boundary and end-to-end acceptance correction.
- [`V429_M27_REMEDIATION_REPORT.md`](V429_M27_REMEDIATION_REPORT.md) records restart-safe invalidation of holdout dependents.
- [`V429_M16_REMEDIATION_REPORT.md`](V429_M16_REMEDIATION_REPORT.md) records durable configuration checks at order dispatch and deployment activation.
- [`V429_M2_REMEDIATION_REPORT.md`](V429_M2_REMEDIATION_REPORT.md) records fail-closed M1–M5 checks at the final order dispatcher.
- [`V429_RECONSTRUCTION_NOTE.md`](V429_RECONSTRUCTION_NOTE.md) records the available source lineage.
- [`docs/V429_EXTERNAL_SIGNER_HARDENING.md`](docs/V429_EXTERNAL_SIGNER_HARDENING.md) describes the external signer’s platform requirements.

The 3.61.4 safety patch restricts the legacy Testnet evidence session and runner to read-only `GET` requests and the approved Testnet host allowlist. The 3.61.5 safety patch closes missing-authority bypasses at the final order dispatcher. See [`V429_M1_REMEDIATION_REPORT.md`](V429_M1_REMEDIATION_REPORT.md) and [`V429_M2_REMEDIATION_REPORT.md`](V429_M2_REMEDIATION_REPORT.md).

`package_manifest_v429.txt` is the immutable manifest for the historical V4.29 archive; it is not a manifest of later changes on `main`.
