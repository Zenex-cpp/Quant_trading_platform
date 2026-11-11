# Quant Trading Platform

**Repository release train:** `V4.29-RECOVERY`  
**Python distribution version:** `3.61.16` (a separate versioning scheme).

The current repository is a recovery extension based on the available V4.28 recovery archive. Byte-for-byte canonical lineage to V4.23 and V4.26 is **not established** because those source archives are not available in the project.

## Current state

- V4.29 hardens the external Ed25519 signer and requires the fixed milestone preflight, full regression, and release-hygiene checks.
- The follow-up hardens chronological label purging at every split boundary and makes the offline §178 acceptance gate require real SQLite recovery, failure-injection, and deployment-rollback proofs. The E2E run uses training labels only and leaves final-holdout targets untouched.
- Holdout incidents are reconciled from the durable event store at context startup, so an interrupted invalidation is completed before dependents can be used.
- M16 configuration authority is enforced at final Testnet dispatch and deployment activation. Resolution ID, fingerprint, status and expiry are checked against the durable ledger; failures stop dispatch or activation before the external action.
- The final dispatch boundary requires durable risk-decision, position, fresh-market and causal-TTL authorities for risk-increasing orders. Missing or expired authority blocks before the gateway.
- M1–M5 authority checks now cover the legacy V3.36/V3.79/V3.80/V3.84/V3.85 submit paths as well as the V3.11 dispatcher; unguarded adapters fail closed.
- V3.75 live/shadow prediction calls now require current durable compatibility authority across all seven runtime dimensions.
- Signed JSON model loading checks Ed25519 signature, content hash, schemas and runtime compatibility before inference; V3.75 binds the loaded model ID/hash to its M14 authorization. Trusted-key governance and production deployment remain open.
- Research credential scanning now traverses slotted objects, Python-mangled secret fields and NumPy object arrays; the direct tuning-data view applies the same boundary.
- Production credential storage now requires an explicit persistent backend; Windows Credential Manager stores secret blobs while the append-only ledger stores metadata only. M9 resolution and revocation are serialized and every access attempt is audited. M9 remains `TESTED` pending dedicated service identity, process-isolation and external operational evidence.
- M10 serializes concurrent access to each SQLite event-store connection, streams event iteration under the lock, and verifies concurrent appends preserve the hash chain. Independent storage tamper review remains open.
- The explicit market-data command imports checksummed USD-M Futures daily archives into immutable, audited snapshots. Public archive access is isolated from Research and requires a non-commercial research attestation.
- DATASET-01 provides a bounded local-only audit CLI for user/vendor OHLCV CSVs. It emits a DatasetContract and can compare a second CSV by UTC timestamp and symbol, reporting OHLCV divergences and coverage differences. Source independence, license assessment, and authority still require review. No actual user market-data CSV is present.
- Latest hosted validation of `main` before the local M14, M9, CLI and data-import changes, post-merge PR #20: successful ([run 43004773712](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/43004773712)).
- Hosted push CI for working-branch commit `30ba40e` passed ([run 43042509186](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/43042509186)) and uploaded the hashed preflight/governance artifact. It was not a protected-main run; artifact contents require connected-account access.
- Latest full local Windows/Python 3.14.4 validation on package `3.61.16`: **1,306 passed, 26 skipped**, `RELEASE_HYGIENE=PASS`; preflight `READY_FOR_MILESTONE`, `allowed=true`, no blocking reasons, with M9/M10/M14/M15 included. Audit: `.audit/V429_M9_M10_CREDENTIAL_FINAL2_20261111.json`. POSIX-only signer checks remain enabled in Linux CI; symlink checks skip only when the host cannot create symlinks.
- Validation does not execute exchange orders or certify production readiness. `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain in force.

The hosted governance audit is intentionally non-fatal while signed, trusted external evidence is absent. A green CI job does not mean the trust anchor, independent evidence, operational controls, or production approval have been satisfied.

## Validate the recovery release

Run the fixed milestone entrypoint from the repository root:

```powershell
python scripts/run_milestone_validation_v429.py
```

The runner checks the V4.29 compliance preflight, runs the complete test suite, and checks release hygiene. CI uses the same entrypoint and fixed contract.

From a source checkout, run the complete §178 offline acceptance flow and print its deterministic evidence report:

```powershell
python scripts/run_offline_acceptance.py
```

This command uses synthetic historical data and local SQLite stores. It makes no network calls, sends no exchange orders, and always reports `production_ready=false`.

After installing the package with `python -m pip install -e .`, the equivalent installed commands are `trading-platform offline-acceptance` and `python -m trading_platform offline-acceptance`.

## Import public historical data for non-commercial research

The optional importer reads daily USD-M Futures kline ZIPs and their SHA-256 sidecars from Binance Vision. It checks each checksum, validates the 12-column archive rows and OHLCV quality, records raw ZIPs and a manifest, and creates a new content-addressed snapshot without overwriting an existing one. The inclusive UTC request range is limited to 31 days.

Binance Vision's current dataset terms restrict this data to non-commercial historical research and exclude live proprietary/commercial trading, commercial order generation, and paid signal distribution. The CLI requires an explicit acknowledgement and records the scope and terms URL in the manifest. Do not use this source to train, validate, or operate a live/commercial trading strategy. Recheck the terms before every acquisition because they may change.

```text
trading-platform market-data download-um-klines --symbol BTCUSDT --interval 1h --start-date 2026-10-01 --end-date 2026-10-02 --output ..\binance-public-research --confirm-noncommercial-research
```

The generated snapshot contains raw ZIP archives, klines.csv, and manifest.json. Missing archives, checksum failures, redirects, unsafe ZIP members, malformed values, or invalid OHLCV stop the import. Partial candle coverage is marked WARNING. A successful import is not a proprietary research dataset, an edge claim, or production approval. Binance's checksum and archive are served by the same host, so their match is an integrity check rather than an independent authenticity anchor.

Store the output outside the repository checkout. The importer refuses to place these license-restricted source archives inside the code repository.

## Audit a user/vendor CSV for DATASET-01

The local-only `market-data audit-csv` command checks a user/vendor OHLCV CSV, writes a new JSON report, and creates a `DatasetContract` when every row has a valid timezone-aware event time. It records coverage, hashes, lineage and quality findings. Add `--compare-input` and `--compare-source-label` to compare a second local CSV by `(event_time normalized to UTC, symbol trimmed and uppercased)`, with exact values by default or explicitly bounded absolute/relative tolerances. Both datasets receive contracts when their time coverage is complete. The report lists per-field differences, unmatched rows, quality findings and operator anomaly notes for each source. Inputs are never copied and the command makes no network requests. The report path must be outside the repository and must not already exist.

```text
trading-platform market-data audit-csv --input ..\market-data\vendor-a.csv --source-label "Vendor A" --compare-input ..\market-data\vendor-b.csv --compare-source-label "Vendor B" --report ..\audit\DATASET-01-report.json --anomaly-note "Document known gaps or revisions" --compare-anomaly-note "Document comparator revisions"
```

The comparison can report agreement or divergence but cannot prove the sources are independent, infer licensing, or authorize definitive use. A nonzero command exit requires review of quality, coverage, or comparison findings. Reports keep `production_ready=false`. No user market-data CSV is currently present in this checkout, so DATASET-01 has not yet been audited against real sources.

## Source documents

- [`MASTER PROMPT.txt`](MASTER%20PROMPT.txt) is the normative system specification.
- [`V429_VERIFICATION_REPORT.md`](V429_VERIFICATION_REPORT.md) records the recovery build and verification boundary.
- [`V429_OPEN_GAPS_DELTA.md`](V429_OPEN_GAPS_DELTA.md) lists unresolved external and operational gates.
- [`V429_PIT_E2E_REMEDIATION_REPORT.md`](V429_PIT_E2E_REMEDIATION_REPORT.md) records the split-boundary and end-to-end acceptance correction.
- [`V429_M27_REMEDIATION_REPORT.md`](V429_M27_REMEDIATION_REPORT.md) records restart-safe invalidation of holdout dependents.
- [`V429_M16_REMEDIATION_REPORT.md`](V429_M16_REMEDIATION_REPORT.md) records durable configuration checks at order dispatch and deployment activation.
- [`V429_M2_REMEDIATION_REPORT.md`](V429_M2_REMEDIATION_REPORT.md) records fail-closed M1–M5 checks at the final order dispatcher.
- [`V429_M1_M5_TRANSPORT_REMEDIATION.md`](V429_M1_M5_TRANSPORT_REMEDIATION.md) records the alternate-transport bypass closure.
- [`V429_M7_REMEDIATION_REPORT.md`](V429_M7_REMEDIATION_REPORT.md) records durable PASS-gate binding for Champion promotion.
- [`V429_M14_REMEDIATION_REPORT.md`](V429_M14_REMEDIATION_REPORT.md) records runtime compatibility enforcement before prediction calls and its production integration boundary.
- [`V429_M9_REMEDIATION_REPORT.md`](V429_M9_REMEDIATION_REPORT.md) records credential-visibility bypass closure at research inputs and the remaining process-isolation evidence boundary.
- [`V429_M25_PUBLIC_DATA_REPORT.md`](V429_M25_PUBLIC_DATA_REPORT.md) records the isolated public archive importer, source terms, and the outstanding infrastructure route proof.
- [`V429_DATASET_01_CSV_AUDIT_REPORT.md`](V429_DATASET_01_CSV_AUDIT_REPORT.md) records the local user/vendor CSV audit path and the missing real dataset/source comparison.
- [`V429_RECONSTRUCTION_NOTE.md`](V429_RECONSTRUCTION_NOTE.md) records the available source lineage.
- [`docs/V429_EXTERNAL_SIGNER_HARDENING.md`](docs/V429_EXTERNAL_SIGNER_HARDENING.md) describes the external signer’s platform requirements.

The 3.61.4 safety patch restricts the legacy Testnet evidence session and runner to read-only `GET` requests and the approved Testnet host allowlist. Version 3.61.5 closed missing-authority bypasses at the V3.11 dispatcher; 3.61.6 closes alternate Testnet submit paths; 3.61.7 binds Champion promotion to exact durable PASS-gate runs and revalidates them at use; 3.61.8 guards V3.75 live/shadow prediction calls with current compatibility authority; 3.61.9 closes credential-scanning gaps for slotted wrappers and object arrays; 3.61.10 adds the installed CLI and offline §178 acceptance command; 3.61.11 adds checksummed historical archive import for non-commercial research; 3.61.12 adds DATASET-01 CSV audits; 3.61.13 adds bounded two-source comparison; 3.61.14 rejects malformed, duplicate, reordered, empty or hash-invalid backtest/live decision traces; 3.61.15 loads bounded signed model artifacts and binds them to M14 authorization; 3.61.16 adds persistent Windows Credential Manager storage and thread-safe durable event auditing. See [`V429_M1_REMEDIATION_REPORT.md`](V429_M1_REMEDIATION_REPORT.md), [`V429_M2_REMEDIATION_REPORT.md`](V429_M2_REMEDIATION_REPORT.md), [`V429_M1_M5_TRANSPORT_REMEDIATION.md`](V429_M1_M5_TRANSPORT_REMEDIATION.md), [`V429_M7_REMEDIATION_REPORT.md`](V429_M7_REMEDIATION_REPORT.md), [`V429_M14_REMEDIATION_REPORT.md`](V429_M14_REMEDIATION_REPORT.md), [`V429_M15_REMEDIATION_REPORT.md`](V429_M15_REMEDIATION_REPORT.md), [`V429_M9_REMEDIATION_REPORT.md`](V429_M9_REMEDIATION_REPORT.md), [`V429_M10_REMEDIATION_REPORT.md`](V429_M10_REMEDIATION_REPORT.md), [`V429_M25_PUBLIC_DATA_REPORT.md`](V429_M25_PUBLIC_DATA_REPORT.md), [`V429_DATASET_01_CSV_AUDIT_REPORT.md`](V429_DATASET_01_CSV_AUDIT_REPORT.md), and [`V429_PIT_E2E_REMEDIATION_REPORT.md`](V429_PIT_E2E_REMEDIATION_REPORT.md).

`package_manifest_v429.txt` is the immutable manifest for the historical V4.29 archive; it is not a manifest of later changes on `main`.
