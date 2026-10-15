# Trading Platform V4.29 Recovery — Release Notes

## Summary

V4.29 hardens the independent Ed25519 signer against symlinked ancestor paths, input-file replacement during reads, unbounded external evidence inputs, and accidental overwrite of a pre-existing signed output. It also creates a V4.29-specific mandatory milestone runner and CI workflow contract.

## Verification contract

- Full regression runs through `scripts/run_milestone_validation_v429.py`.
- CI invokes the same fixed-command runner and requires the governance audit artifact set to be present.
- V4.28 governance snapshot schema and two preflight artifact names are retained solely for compatibility; this does not establish remote evidence.
- `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain unchanged.

## Provenance

Direct baseline: `trading_platform_v4_28_recovery.tar.gz`, SHA-256 `c04b3584d9c5de21bd57c22f491895101da5fb7f3d5d99c034a9b77c5f8b09a4`.
Canonical continuity to V4.23/V4.26 is `NOT_ESTABLISHED` due unavailable original archives.
