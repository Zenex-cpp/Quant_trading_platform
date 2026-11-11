# Trading Platform V4.29 Recovery — Release Notes

## Summary

V4.29 hardens the independent Ed25519 signer against symlinked ancestor paths, input-file replacement during reads, unbounded external evidence inputs, and accidental overwrite of a pre-existing signed output. It also creates a V4.29-specific mandatory milestone runner and CI workflow contract.

Python package `3.61.5` makes the final dispatcher require current risk, position, market-data, and causal-TTL authorities before a new risk-increasing order can reach its gateway. The runtime now passes the durable RiskDecision ledger, and V4.29 CI preflights M1–M5 for this boundary. See `V429_M2_REMEDIATION_REPORT.md`.

Python package `3.61.6` closes alternate Testnet submit paths through the V3.36/V3.79/V3.80/V3.84/V3.85 adapters. The V3.85 controlled submit shares the final M1–M5 authority checks; older direct-submit adapters fail closed. See `V429_M1_M5_TRANSPORT_REMEDIATION.md`.

At package `3.61.5`, the mandatory Windows/Python 3.14.7 runner completed with **1,190 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`. On the current `3.61.6` tree, it completed with **1,200 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`, preflight `READY_FOR_MILESTONE`. These local results do not replace hosted CI or external review.

## Verification contract

- Full regression runs through `scripts/run_milestone_validation_v429.py`.
- CI invokes the same fixed-command runner and requires the governance audit artifact set to be present.
- V4.28 governance snapshot schema and two preflight artifact names are retained solely for compatibility; this does not establish remote evidence.
- `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain unchanged.

## Provenance

Direct baseline: `trading_platform_v4_28_recovery.tar.gz`, SHA-256 `c04b3584d9c5de21bd57c22f491895101da5fb7f3d5d99c034a9b77c5f8b09a4`.
Canonical continuity to V4.23/V4.26 is `NOT_ESTABLISHED` due unavailable original archives.
