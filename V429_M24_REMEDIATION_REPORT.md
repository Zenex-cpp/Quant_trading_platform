# V4.29 M24 Model-Health Source Binding

**Status:** `TESTED`; signed source identity and live operational health integration remain open.

## Finding

Model-health risk decisions checked an assessment ID and summary booleans, but did not retain the evidence ID, capture time, TTL, verification state, or assessment time throughout the runtime capability and restart-safe risk-decision paths. A reused assessment ID could therefore stand in for changed source evidence, and a capability could outlive the evidence freshness window.

## Changes

- `HealthAssessment` now retains the immutable `EvidenceFreshness` input and assessment timestamp and computes a canonical source fingerprint from the source identity, freshness window, verification state, and assessment outcome.
- The model-health risk authority requires complete source provenance, verifies the evidence was fresh when assessed and when the canonical operational truth was observed, and includes the source fingerprint in the authority decision fingerprint.
- Capability IDs include the source fingerprint. Commit revalidation compares the exact assessment and rejects evidence that has expired since capability issuance.
- Durable risk decisions persist the source evidence fields and fingerprint. Record validation recomputes the fingerprint; restart-safe authorization requires the same source assessment and rejects mismatched or expired evidence.
- The fixed V4.29 preflight and CI workflow now include M24. The compliance row points to the implementation, tests, and this report.

## Verification boundary

The focused M24, health freshness, durable-decision, release-integrity, release-hygiene and V4.29 contract suites passed **51 tests** on Windows/Python 3.14.4. The mandatory V4.29 runner on package 3.61.17 passed **1,307 tests, 26 skipped**, with `RELEASE_HYGIENE=PASS`; `.audit/V429_M24_SOURCE_BINDING_FINAL3_20261111.json` records `READY_FOR_MILESTONE`, `allowed=true`, pipeline PASS, and no blockers with M24 in the impact set. These are local synthetic source records. `verified=true` is an input assertion, not a cryptographic attestation; this change does not establish trusted source identity, independent review, production health-source integration, or live operational evidence. M24 remains `TESTED`, not `VERIFIED`.

`external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain in force.
