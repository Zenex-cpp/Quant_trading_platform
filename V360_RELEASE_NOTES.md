# V3.60 Release Notes

## Scope
§176 production-readiness evidence gating.

## Implementation
- Added durable ReadinessEvidenceLedger.
- Evidence is distinct from verification: SUBMITTED is not sufficient for production readiness.
- Only externally sourced evidence with a non-synthetic source reference can be verified.
- Verification requires reviewer identity, review reference, freshness and validity window.
- ProductionReadinessAssessor requires a current VERIFIED/PASS artifact for every required evidence class.
- Assessment is fail-closed and reports missing evidence classes explicitly.

## Important
This release does not fabricate operational evidence or production approval.
`production_ready` remains FALSE until real evidence and human review are supplied.
