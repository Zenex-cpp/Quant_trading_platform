# Quant Trading Platform

**Repository release train:** `V4.29-RECOVERY`  
**Python distribution version:** `3.61.37` (a separate versioning scheme).

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
- The V2.7–V2.9 governance, deployment, and provenance streams now have 19 registered event types with versioned JSON payload schemas. Realtime events share the canonical envelope validator; generic EventStore and later authority-ledger types remain outside this registry.
- FD-16 now maps 25 cross-domain authorities, their version/hash bindings, conflict actions, and external or unconfigured boundaries. Raw market/account authority, trusted identity, and production integrations remain unverified.
- M11 retry/replay protection now requires a disk-backed side-effect journal before exchange transport. The V3.12 execution runtime accepts a durable dispatch-attempt ledger; without persistent storage, the dispatcher fails closed. External venue exactly-once behavior remains unverified.
- The source-checkout §178 acceptance launcher disables bytecode writes before project imports, so running it does not create cache directories that fail release hygiene.
- M22 derives source-bound liquidity stress from visible order-book depth utilization, spread and order-size VWAP impact; it binds the exact order-book sequence and market-data record through runtime risk, capability, durable decision and final dispatch checks. M22 remains `TESTED` pending authenticated live feeds and independent real-market calibration.
- M21 binds uncertainty and a separately computed calibration report to a signed prediction through runtime risk, capability, durable decision and final dispatch. Manifest calibration state alone maps to `UNKNOWN` and a 25% factor cap; `ACCEPTABLE` caps at 50%. Report fingerprints bind metrics and declared data-source IDs but do not authenticate the report producer or dataset. Real-data multiplier ablation and independent calibration remain open.
- M24 carries model-health source identity, capture time, TTL and verification state into authority and capability fingerprints and durable risk records. Commit and restart-safe risk gates reject changed or expired evidence; signed source identity and live health-source integration remain open.
- M23 derives dynamic drawdown from a hash-chained equity history with an explicit opening record and binds its identity/freshness through runtime risk authority, execution capabilities and durable decisions. Independent history authentication and live accounting integration remain open.
- M18 now propagates dependency invalidation transitively across registered artifacts, evidence, gates, candidates and promotions, and records exact revalidation targets. M18 remains `TESTED` pending production registry completeness and independent review.
- M25 application policy restricts allowlisted zone endpoints to the default TLS port and rejects URL userinfo and malformed inputs. Research remains deny-all; independent firewall and routing evidence remains open.
- The explicit market-data command imports checksummed USD-M Futures daily archives into immutable, audited snapshots. Public archive access is isolated from Research and requires a non-commercial research attestation.
- DATASET-01 provides a bounded local-only audit CLI for user/vendor OHLCV CSVs. It emits a DatasetContract and can compare a second CSV by UTC timestamp and symbol, reporting OHLCV divergences and coverage differences. Source independence, license assessment, and authority still require review. No actual user market-data CSV is present.
- Latest hosted validation of `main` before the local M14, M9, CLI and data-import changes, post-merge PR #20: successful ([run 43004773712](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/43004773712)).
- Hosted push CI for working-branch commit `30ba40e` passed ([run 43042509186](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/43042509186)) and uploaded the hashed preflight/governance artifact. It was not a protected-main run; artifact contents require connected-account access.
- Latest full local validation is recorded in `V429_VERIFICATION_REPORT.md`; M18, M21 and M25 remain `TESTED`, and the network policy still requires independent infrastructure proof. `external_evidence=false`, `activation_flag=NOT_SET`, and `production_ready=false` remain in force. POSIX-only signer checks remain enabled in Linux CI; symlink checks skip only when the host cannot create symlinks.
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

After installing the package with `python -m pip install -e .`, run the module entrypoint as `python -B -m trading_platform offline-acceptance`. If using the generated `trading-platform offline-acceptance` command from an editable checkout, set `PYTHONDONTWRITEBYTECODE=1` first so imports do not create bytecode under `src`.

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

- [Idempotency Contract](docs/06_IDEMPOTENCY.md)

- [V5.0 §179 First Delivery Traceability](docs/60_V5_FIRST_DELIVERY_TRACEABILITY.md)
- [V5.0 Model Card and Strategy Card Templates](docs/61_V5_MODEL_AND_STRATEGY_CARDS.md)
- [V5.0 Safety and Incident Matrices](docs/62_V5_SAFETY_AND_INCIDENT_MATRICES.md)
- [V5.0 Research Registries](docs/63_V5_RESEARCH_REGISTRIES.md)
- [V5.0 Permission Model](docs/64_V5_PERMISSION_MODEL.md)
- [V5.0 Security Threat Model](docs/65_V5_SECURITY_THREAT_MODEL.md)
- [V5.0 Repository Structure](docs/66_V5_REPOSITORY_STRUCTURE.md)
- [V5.0 State Transition Tables](docs/67_V5_STATE_TRANSITION_TABLES.md)
- [V5.0 Safety Monotonicity Matrix](docs/68_V5_SAFETY_MONOTONICITY.md)
- [V5.0 Event Schemas and Registry](docs/69_V5_EVENT_SCHEMAS_AND_REGISTRY.md)
- [V5.0 Source-of-Truth Matrix](docs/70_V5_SOURCE_OF_TRUTH.md)
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

The 3.61.4 safety patch restricts the legacy Testnet evidence session and runner to read-only `GET` requests and the approved Testnet host allowlist. Version 3.61.5 closed missing-authority bypasses at the V3.11 dispatcher; 3.61.6 closes alternate Testnet submit paths; 3.61.7 binds Champion promotion to exact durable PASS-gate runs and revalidates them at use; 3.61.8 guards V3.75 live/shadow prediction calls with current compatibility authority; 3.61.9 closes credential-scanning gaps for slotted wrappers and object arrays; 3.61.10 adds the installed CLI and offline §178 acceptance command; 3.61.11 adds checksummed historical archive import for non-commercial research; 3.61.12 adds DATASET-01 CSV audits; 3.61.13 adds bounded two-source comparison; 3.61.14 rejects malformed, duplicate, reordered, empty or hash-invalid backtest/live decision traces; 3.61.15 loads bounded signed model artifacts and binds them to M14 authorization; 3.61.16 adds persistent Windows Credential Manager storage and thread-safe durable event auditing; 3.61.17 binds model-health source freshness and identity through runtime capabilities and durable risk decisions; 3.61.18 binds dynamic drawdown to durable equity history and source freshness through runtime and durable risk gates; 3.61.19 adds source-bound order-book liquidity risk; 3.61.20 binds model uncertainty and calibration state to a signed prediction source through the final risk gate; 3.61.21 requires a separate empirical calibration report at the risk boundary; 3.61.22 propagates evidence invalidation through registered dependencies and downstream decisions; 3.61.23 restricts M25 allowlisted endpoints to the default TLS port and rejects URL credentials; 3.61.24 requires persistent side-effect state for retry/replay before final order dispatch; 3.61.25 keeps the source-checkout §178 acceptance launcher from creating bytecode that fails release hygiene; 3.61.26 restores Python 3.10-compatible source syntax and adds a minimum-version parser check to CI; 3.61.27 prevents direct or copied signed-model objects from bypassing signature verification in the M14 inference path; 3.61.28 aligns the offline §178 stage artifacts with the required Validation, Model, Accounting and P&L steps and binds them into replay/evidence/gate. See [`V429_M1_REMEDIATION_REPORT.md`](V429_M1_REMEDIATION_REPORT.md), [`V429_M2_REMEDIATION_REPORT.md`](V429_M2_REMEDIATION_REPORT.md), [`V429_M1_M5_TRANSPORT_REMEDIATION.md`](V429_M1_M5_TRANSPORT_REMEDIATION.md), [`V429_M7_REMEDIATION_REPORT.md`](V429_M7_REMEDIATION_REPORT.md), [`V429_M14_REMEDIATION_REPORT.md`](V429_M14_REMEDIATION_REPORT.md), [`V429_M15_REMEDIATION_REPORT.md`](V429_M15_REMEDIATION_REPORT.md), [`V429_M11_REMEDIATION_REPORT.md`](V429_M11_REMEDIATION_REPORT.md), [`V429_M21_REMEDIATION_REPORT.md`](V429_M21_REMEDIATION_REPORT.md), [`V429_M23_REMEDIATION_REPORT.md`](V429_M23_REMEDIATION_REPORT.md), [`V429_M9_REMEDIATION_REPORT.md`](V429_M9_REMEDIATION_REPORT.md), [`V429_M10_REMEDIATION_REPORT.md`](V429_M10_REMEDIATION_REPORT.md), [`V429_M24_REMEDIATION_REPORT.md`](V429_M24_REMEDIATION_REPORT.md), [`V429_M25_PUBLIC_DATA_REPORT.md`](V429_M25_PUBLIC_DATA_REPORT.md), [`V429_DATASET_01_CSV_AUDIT_REPORT.md`](V429_DATASET_01_CSV_AUDIT_REPORT.md), and [`V429_PIT_E2E_REMEDIATION_REPORT.md`](V429_PIT_E2E_REMEDIATION_REPORT.md).


## V5.0 first-delivery work

Version 3.61.29 added the prompt §179 traceability register, the immutable machine-readable Strategy Card template, and safety/research registries. Version 3.61.30 binds state-transition idempotency keys to the full transition specification and rejects conflicting reuse. Version 3.61.31 makes §155 role/capability checks fail closed, publishes and tests the full 9 × 9 matrix, and separates credential configuration from production-trading access. Version 3.61.32 adds the complete §153 threat inventory with control evidence and residual risks. Version 3.61.33 adds a filesystem-checked repository map. Version 3.61.34 publishes pairwise default-reject transition tables and makes the base transition engine accept only its registered `START_BACKTEST` edge. Version 3.61.35 traces eight safety monotonicity rules to implementation and tests; execution-risk and correlated-exposure enforcement remain gaps. Version 3.61.36 adds versioned payload schemas and registry enforcement for 19 typed V2.7–V2.9 event types; generic EventStore and later authority-ledger events remain unregistered. Version 3.61.37 publishes a tested 25-domain cross-domain source-of-truth matrix with explicit external authority, persistence, and production integration boundaries. §179 is now 42 PRESENT, 13 PARTIAL, 0 OPEN. FD-06 remains PARTIAL because positive lifecycle/risk paths and durable atomic side-effect handling are not defined. FD-08 remains PARTIAL because execution risk, correlated exposure, and platform-wide hard-ceiling binding are incomplete. FD-10/FD-11 remain PARTIAL because legacy and later event streams are not fully registered. FD-44 remains PARTIAL because resource-wide entitlement and trusted identity assignment are not present. These changes do not claim production readiness or external verification.

On package 3.61.37, the final local V4.29 runner passed with 1,398 passed, 26 skipped, and `RELEASE_HYGIENE=PASS`. Preflight was `READY_FOR_MILESTONE`, `allowed=true`, with 230 input hashes and zero blockers. It remains offline: `external_evidence=false`, `production_ready=false`, and `activation_flag=NOT_SET`.

`package_manifest_v429.txt` is the immutable manifest for the historical V4.29 archive; it is not a manifest of later changes on `main`.
