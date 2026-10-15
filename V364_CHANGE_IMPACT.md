# V3.64 Change Impact Record

## Change
`READINESS_EVIDENCE_PROVENANCE -> EXPLICIT_EXTERNAL_PROVENANCE`

## Changed components
- `trading_platform/v360/readiness_evidence.py`
- `trading_platform/v361/evidence_package.py`
- `trading_platform/v364/external_evidence.py`
- readiness evidence tests
- evidence package template

## Affected contracts
- §176 production-readiness evidence verification
- external evidence package import
- readiness evidence fingerprints
- legacy package revalidation behavior

## Safety effect
The change is fail-closed. Existing evidence without explicit provenance becomes `UNKNOWN` and cannot be promoted to `VERIFIED`.

## Dependency impact
No trading signal, portfolio, risk, order, execution, accounting, or live state machine semantics are broadened. The affected graph is limited to readiness evidence ingestion and verification.

## Historical immutability
Historical V3.58/V3.60/V3.61 evidence artifacts are not rewritten. Existing imported records remain replayable; missing provenance is interpreted as `UNKNOWN` for the new verification gate.

## Revalidation
- Unit tests: COMPLETE.
- Full suite: COMPLETE.
- Packaging/import verification: required for release completion.
- Independent review: still required by §176.
