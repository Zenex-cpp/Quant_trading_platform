# V3.65 Change Impact Record

## Change
`RELEASE_ARTIFACT_HYGIENE -> MACHINE_CHECKED_TRANSIENT_EXCLUSION`

## Changed components
- `scripts/validate_release_hygiene.py`
- `tests/test_v365_release_hygiene.py`
- `README.md`
- release notes / verification / compliance metadata
- release staging procedure

## Affected contracts
- reproducibility
- artifact integrity
- deployment artifact provenance
- release packaging

## Safety effect
Fail-closed at release creation: transient build/test artifacts prevent release validation and therefore block publication of the release artifact.

## Non-affected semantics
No change to signal, portfolio, risk, order, execution, accounting, reconciliation, model, state-machine, or production activation semantics.

## Historical immutability
V3.64 and earlier artifacts remain unchanged.
