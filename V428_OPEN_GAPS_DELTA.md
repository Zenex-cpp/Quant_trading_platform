# V4.28 Open Gaps Delta

## Closed locally

- Governance CLI paths reject absolute paths, traversal, drive/UNC paths, symlink components and non-regular outputs.
- Verifier and controlled runner outputs are restricted to `.audit/`, with input/output and output/output collision checks.
- Capture validates output location before authenticating to GitHub and will not overwrite reserved audit artifacts.
- Independent signing output remains outside the checkout and cannot overwrite/alias the key or unsigned evidence.
- V4.28 capture normalizer, hosted workflow artifact names and V4.28 authority agree on required artifact filenames.
- Mandatory runner uses V4.28 matrix, V4.27 baseline hash and hashes the new path policy module/tests into the preflight input set.

## Still open

- Real GitHub capture: `NOT_RUN`.
- Hosted GitHub Actions: `NOT_RUN`.
- Branch protection, organization/repository rulesets and effective CODEOWNERS: `NOT_VERIFIED`.
- Independent reviewer public key/trust ceremony: `NOT_CONFIGURED`.
- Canonical V4.23 and V4.26 source continuity: `NOT_ESTABLISHED`.
- Operational proof for security assessment, monitoring/on-call, network segmentation, secret management, backup/DR, authenticated Testnet, production rollback, independent approval and production sign-off: `NOT_VERIFIED`.
