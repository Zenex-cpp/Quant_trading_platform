# V4.29 Open Gaps Delta

## Closed locally

- External reviewer key and unsigned evidence are read with POSIX directory descriptors and `O_NOFOLLOW` on every path component.
- Input is required to be a regular file and bounded (1 MiB key, 16 MiB evidence); metadata is checked before and after the read.
- Reviewer output paths reject symlinked ancestors, traversal, paths inside the checkout, and existing targets.
- Signed output is created exclusively with mode `0600`; pre-existing content cannot be overwritten.
- V4.29 milestone runner/matrix/baseline and workflow contract are aligned, while V4.28 audit artifact names remain compatible with the existing provider snapshot schema.
- Chronological target intervals are purged at the train/validation, validation/OOS, and OOS/final-holdout boundaries; purged splits require event timestamps, and an empty post-purge split fails closed.
- The offline §178 acceptance path trains only on training targets, tests duplicate/conflicting fills and expired risk after restart, reconstructs accounting from SQLite, and requires the deployment rollback drill artifacts in its evidence snapshot and gate.
- M16 has a durable configuration-resolution ledger. Conflicts are recorded without raw values, bound into Operational Truth, and deny LIVE trade/deploy decisions through RuntimeAuthority and ExecutionRouter; the SQLite record survives restart.
- M26 has a durable statistical-method registry and hash-bound applicability ledger. Registry records survive restart, failed assumptions are durably recorded as `METHOD_NOT_APPLICABLE`, and the guarded executor blocks the evaluator before it can produce a result.
- M27 now replays durable holdout-compromise incidents when the access context starts, completing interrupted dependency invalidation before the context is returned. Restart coverage checks persisted blocking through evidence, gates, candidates and promotions.

## Still open

- Real GitHub provider capture: `NOT_RUN`.
- Hosted GitHub Actions run in the target repository: `NOT_RUN`.
- Effective branch protection/rulesets/CODEOWNERS: `NOT_VERIFIED`.
- Independent reviewer identity, public-key trust ceremony and trust anchor: `NOT_CONFIGURED`.
- Canonical V4.23 and V4.26 byte-for-byte lineage: `NOT_ESTABLISHED`.
- Production security assessment, monitoring/on-call, network segmentation, secret store, backup/DR, authenticated Testnet, production rollback, independent approval and production sign-off: `NOT_VERIFIED`.
- Independent review and broader production integration of all configuration sources are still required to promote M16 from `TESTED` to `VERIFIED`.
- Independent methodology review and operational evidence are still required to promote M26 from `TESTED` to `VERIFIED`.
- Independent review of holdout replacement/revalidation and external operational audit evidence for M27: `NOT_VERIFIED`; M27 is `TESTED`, not `VERIFIED`.
