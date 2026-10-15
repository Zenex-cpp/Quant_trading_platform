# V4.29 Open Gaps Delta

## Closed locally

- External reviewer key and unsigned evidence are read with POSIX directory descriptors and `O_NOFOLLOW` on every path component.
- Input is required to be a regular file and bounded (1 MiB key, 16 MiB evidence); metadata is checked before and after the read.
- Reviewer output paths reject symlinked ancestors, traversal, paths inside the checkout, and existing targets.
- Signed output is created exclusively with mode `0600`; pre-existing content cannot be overwritten.
- V4.29 milestone runner/matrix/baseline and workflow contract are aligned, while V4.28 audit artifact names remain compatible with the existing provider snapshot schema.

## Still open

- Real GitHub provider capture: `NOT_RUN`.
- Hosted GitHub Actions run in the target repository: `NOT_RUN`.
- Effective branch protection/rulesets/CODEOWNERS: `NOT_VERIFIED`.
- Independent reviewer identity, public-key trust ceremony and trust anchor: `NOT_CONFIGURED`.
- Canonical V4.23 and V4.26 byte-for-byte lineage: `NOT_ESTABLISHED`.
- Production security assessment, monitoring/on-call, network segmentation, secret store, backup/DR, authenticated Testnet, production rollback, independent approval and production sign-off: `NOT_VERIFIED`.
