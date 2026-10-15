# V0.3 Data Integrity / PIT / Leakage / Lineage Contract

## Scope
V0.3 implementa i contratti per DATA, POINT-IN-TIME, revision-aware data, quality, unknown semantics, dataset lineage e leakage scanning.

## Hard invariants
1. No feature may be consumed before `available_at <= consumer_time`.
2. No event may be used when `event_time > prediction_time`.
3. A revised dataset version is not backfilled into historical decisions unless it was available at the decision timestamp.
4. Dataset coverage must have `start < end`; dataset and availability timestamps are timezone-aware.
5. Duplicate observations are findings and must be remediated or explicitly rejected by downstream gates.
6. Temporal order is deterministic: out-of-order input is not silently accepted by the strict validator.
7. `UNKNOWN`, `NULL`, `NOT_APPLICABLE`, `NOT_PROVIDED`, and `NOT_YET_AVAILABLE` remain distinct semantics.
8. Every dataset contract carries source, snapshot, hashes, quality status, quality report and lineage.

## Availability vector
`available_at`, `availability_source`, `publication_delay_ms`, `revision_policy`.

The availability timestamp is the causal boundary used by PIT validation. Publication delay is represented explicitly and cannot be negative.

## Revision-aware data
`first_published_version`, `revised_version`, `revision_timestamp`, `as_of_availability`.

Historical research must use the latest version known at the relevant historical availability point, never a later revision merely because it is cleaner or more complete.

## Leakage taxonomy
The registry includes the Master Prompt categories: feature, target, timestamp, normalization, train/test overlap, label overlap, duplicates, survivorship, delisting, revision, corporate-action look-ahead, timezone/DST, cross-asset future information and selection leakage.

## Quality states
`VALID`, `WARNING`, `INVALID`, `CRITICAL`.

A quality report is mandatory whenever a DatasetContract is promoted through later gates.

## V0.3 limitation
The current implementation is a contract foundation. It does not yet claim a complete OHLC/order-book semantic validator, a full train/validation/OOS splitter, or a production dataset adapter. Those belong to subsequent V0.3 increments and must be added before the corresponding requirements can be VERIFIED.
