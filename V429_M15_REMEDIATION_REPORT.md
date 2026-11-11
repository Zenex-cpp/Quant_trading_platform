# V4.29 M15 Signed Model Artifact Runtime

**Status:** `TESTED`; trusted-key governance and production deployment evidence remain open.

## Finding

The existing deployment-integrity authority prevented activation after a failed integrity decision, but the checkout had no bounded model loader that verified a concrete inference artifact before making it callable. The separate `signature_verified` record in the integrity ledger is an authority assertion; by itself it does not prove that the bytes loaded by a runtime are the bytes covered by the signature.

## Changes

- Added `load_signed_linear_model_v1`, a bounded (2 MiB) JSON-only loader for a deliberately small logistic-regression format. It rejects executable object formats, duplicate JSON keys, non-standard numeric constants, unknown manifest fields, mismatched schemas/versions, non-finite coefficients, and invalid prediction TTLs.
- The loader verifies a detached Ed25519 signature over the exact artifact bytes, computes SHA-256 over those bytes, and applies `ModelArtifactContract.pre_load_validate` for artifact hash, feature version, runtime, dependencies, and configuration before parsing model parameters.
- The immutable loaded model emits the repository `Prediction` contract and accepts only the exact declared feature keys. Its inference output and prediction ID are deterministic for identical bytes, inputs, and timestamp.
- When this model object is used as the V3.75 prediction stage, M14 now checks its model ID and content hash against the exact durable compatibility grant before invocation. A grant for another artifact fails closed.
- Added M15 to the fixed V4.29 preflight and CI workflow contract. The compliance row remains `TESTED` and identifies the trust-root gap.

## Verification boundary

Tests generate ephemeral Ed25519 keys and synthetic artifacts. They demonstrate signature and hash rejection, compatibility mismatch rejection, strict schema checks, input validation, bounded size/TTL and M14 ID/hash binding. They do not establish reviewer identity, key custody, revocation or rotation policy, independent cryptographic review, production storage provenance, or deployment safety. The trusted public key is supplied by the caller; this repository does not yet bind it to an independently governed trust root.

Focused Windows/Python 3.14.7 verification passed **76 tests** across the artifact loader, M14 runtime, decision parity, workflow contract, milestone matrix, release integrity and release hygiene. The mandatory full V4.29 runner passed with **1,291 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; its final preflight is `READY_FOR_MILESTONE`, `allowed=true`, with M14/M15 in the impact set and no blockers. Audit report: `.audit/V429_M15_FINAL3_PREFLIGHT_20261111.json`.

The adapter does not place or authorize exchange orders. No Testnet/Production deployment was performed. `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.
