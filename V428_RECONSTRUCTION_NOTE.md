# V4.28 Recovery Build — Provenance Note

The source archive available for this milestone is `trading_platform_v4_27_recovery.tar.gz`, whose SHA-256 is recorded in `V427_BASELINE_ARCHIVE_SHA256.txt`. V4.28 is built from that verified source archive and adds path confinement for governance verifier/capture/signer/controlled validation CLIs, plus a V4.28-specific governance normalizer and remote-evidence authority.

The original canonical V4.23 and prior V4.26 source archives were not available in the current runtime. This release is therefore a recovery-line extension, not a byte-for-byte continuation of the claimed canonical V4.23/V4.26 lineage.

All GitHub integration tests use offline fixtures. No actual repository was queried and no hosted GitHub Actions run was observed. Remote branch protection, inherited rulesets, CODEOWNERS resolution, the provider artifact collection and the independent signer trust anchor remain `NOT_VERIFIED`/`NOT_CONFIGURED`.

`production_ready` remains false; no trading activation or production mutation is performed.
