# V4.29 Open Gaps Delta

## Closed locally

- M1–M5 gates are fail-closed across the V3.11 dispatcher and legacy V3.36/V3.79/V3.80/V3.84/V3.85 Testnet submit paths. The V3.85 runner checks the same durable RiskDecision, position, market-data and causal-TTL authorities; direct legacy adapters cannot submit; V3.36 accepts only the guarded dispatcher. See `V429_M1_M5_TRANSPORT_REMEDIATION.md`.
- M7 Champion authorization now requires durable PASS-gate records in the shared event store, binds the exact gate run IDs and fingerprints, and rechecks them after invalidation or replacement at promotion/use. See `V429_M7_REMEDIATION_REPORT.md`.
- M14 now checks current compatibility authority immediately before every V3.75 live/shadow prediction call. All seven compatibility dimensions block on `INCOMPATIBLE` or `UNKNOWN`; the actual production inference adapter remains unimplemented. See `V429_M14_REMEDIATION_REPORT.md`.
- M9's scanner now rejects credential-bearing objects hidden in slots and NumPy object arrays, and direct tuning-data views validate their inputs. See `V429_M9_REMEDIATION_REPORT.md`.
- External reviewer key and unsigned evidence are read with POSIX directory descriptors and `O_NOFOLLOW` on every path component.
- Input is required to be a regular file and bounded (1 MiB key, 16 MiB evidence); metadata is checked before and after the read.
- Reviewer output paths reject symlinked ancestors, traversal, paths inside the checkout, and existing targets.
- Signed output is created exclusively with mode `0600`; pre-existing content cannot be overwritten.
- V4.29 milestone runner/matrix/baseline and workflow contract are aligned, while V4.28 audit artifact names remain compatible with the existing provider snapshot schema.
- Chronological target intervals are purged at the train/validation, validation/OOS, and OOS/final-holdout boundaries; purged splits require event timestamps, and an empty post-purge split fails closed.
- The offline §178 acceptance path trains only on training targets, tests duplicate/conflicting fills and expired risk after restart, reconstructs accounting from SQLite, and requires the deployment rollback drill artifacts in its evidence snapshot and gate.
- M16 has durable configuration-resolution checks at the final Testnet dispatch and deployment activation boundaries. The resolution ID and fingerprint are bound into Operational Truth, authority decisions and durable request/commit/activation records. Dispatch and activation validate ledger presence, status, fingerprint and expiry; conflict, mismatch, missing records and expiry fail closed. See `V429_M16_REMEDIATION_REPORT.md`.
- M26 has a durable statistical-method registry and hash-bound applicability ledger. Registry records survive restart, failed assumptions are durably recorded as `METHOD_NOT_APPLICABLE`, and the guarded executor blocks the evaluator before it can produce a result.
- M27 now replays durable holdout-compromise incidents when the access context starts, completing interrupted dependency invalidation before the context is returned. Restart coverage checks persisted blocking through evidence, gates, candidates and promotions.
- M25 now has an application-level public archive zone and a bounded, checksummed, immutable USD-M kline importer. Research still has no egress; the importer requires explicit acknowledgement for non-commercial historical research. The current public-data terms exclude live proprietary/commercial use, so this source cannot be used for the intended live trading path.

## Still open

- A GitHub provider capture was performed on 2026-11-04, but it is unsigned, stale and bound to an older commit; it is not accepted as current trusted evidence. The current branch-protection API read was denied with HTTP 403, so effective settings remain `NOT_VERIFIED`.
- Before this remediation, the latest verified hosted PR regression was PR #14, run [42039306544](https://github.com/Zenex-cpp/Quant_trading_platform/actions/runs/42039306544): 1,191 passed, 2 skipped, `RELEASE_HYGIENE=PASS`. Hosted CI confirms code checks only; it does not certify provider governance or trading operations.
- Effective branch protection/rulesets/CODEOWNERS: `NOT_VERIFIED` until a fresh, independently signed and trusted provider capture is accepted.
- Independent reviewer identity, public-key trust ceremony and trust anchor: `NOT_CONFIGURED`.
- Canonical V4.23 and V4.26 byte-for-byte lineage: `NOT_ESTABLISHED`.
- Production security assessment, monitoring/on-call, network segmentation, secret store, backup/DR, authenticated Testnet, production rollback, independent approval and production sign-off: `NOT_VERIFIED`.
- M25 remains `TESTED`, not `VERIFIED`: actual host/VPC/container routing enforcement is not configured or independently evidenced. A commercially licensed market-data source is required before any production or commercial strategy use; the public archive importer's non-commercial scope is recorded in its manifest.
- Independent review and broader production integration of all configuration sources are still required to promote M16 from `TESTED` to `VERIFIED`.
- Independent review and operational promotion evidence are still required to promote M7 from `TESTED` to `VERIFIED`.
- M14 production inference integration and independent runtime review remain unverified; V3.75 is decision-only and no production model inference adapter exists in this checkout.
- M9's production credential vault remains in-process and in-memory in this recovery build. External credential-store, separate-process isolation and operational proof are required for `VERIFIED`.
- Independent methodology review and operational evidence are still required to promote M26 from `TESTED` to `VERIFIED`.
- Independent review of holdout replacement/revalidation and external operational audit evidence for M27: `NOT_VERIFIED`; M27 is `TESTED`, not `VERIFIED`.
