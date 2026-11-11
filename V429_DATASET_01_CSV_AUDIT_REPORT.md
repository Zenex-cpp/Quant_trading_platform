# V4.29 DATASET-01 CSV Audit Path

## Scope

The project folder contains no user/vendor historical market-data CSV. DATASET-01 has therefore not been audited and no real dataset coverage, source comparison, source license, or market-data anomaly state is asserted by this report.

This change implements the local audit path required by prompt sections 36–37:

- validates UTF-8 CSV headers and required OHLCV fields;
- bounds input to 32 MiB and 250,000 rows, reads a regular file, and checks file identity before and after the read;
- audits required values, OHLCV semantics, duplicate observations, timezone-aware timestamps, ordering and missing values;
- creates a `DatasetContract` with source label, raw snapshot hash, parsed content hash, schema hash, coverage, quality report, lineage, retention policy and ingestion time when timestamp coverage is complete;
- emits a new, exclusive JSON report without copying source rows into the report;
- does not use the network, infer a license, compare independent sources, or authorize definitive use.

## Command

```text
trading-platform market-data audit-csv --input <user.csv> --source-label <source> --report <outside-repository.json> [--dataset-id DATASET-01] [--anomaly-note <note>]
```

The report refuses a destination inside the repository, an existing report, or a destination equal to the source. Critical data or incomplete temporal coverage produces a nonzero result while preserving the audit report where parsing succeeded. A report with one source always contains `source_comparison=NOT_PERFORMED_SINGLE_SOURCE`, `source_license_assessment=NOT_ASSESSED`, and `dataset_authority=NOT_AUTHORIZED_BY_SINGLE_SOURCE_AUDIT`.

## Verification boundary

Automated tests use synthetic temporary CSV fixtures. They establish command behavior and report integrity, not the quality or provenance of any actual market dataset. DATASET-01 remains open until the user/vendor CSV is supplied, audited, compared against an independent source, and its license and anomalies are reviewed.

Focused CSV/CLI/release-integrity verification passed **15 tests**. The mandatory Windows/Python 3.14.7 runner passed with **1,262 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight was `READY_FOR_MILESTONE`, `allowed=true`, with no blockers.

`external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET` remain unchanged.
