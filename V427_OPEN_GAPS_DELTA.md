# V4.27 Open Gaps Delta

## Closed locally

- Permissive Base64 decoder replaced by strict validation after whitespace normalization.
- Governance capture artifact consumption has explicit per-file and aggregate byte limits and bounded reads.
- New hardening module and tests are included in the mandatory preflight contract fingerprint set.

## Still open

- No real `OWNER/REPOSITORY` was connected or queried.
- GitHub-hosted Actions remains `NOT_RUN` in this session.
- Branch protection/rulesets/CODEOWNERS remain `NOT_VERIFIED` for a target repository.
- Independent reviewer public key and trust ceremony remain `NOT_CONFIGURED`.
- Artifact provenance and API pagination are covered only by fixtures, not a real provider capture.
- Canonical V4.23 lineage remains `NOT_ESTABLISHED`; V4.26 source archive was not available in this runtime.
- Operational evidence for security assessment, monitoring/on-call, network segmentation, secret management, backup/DR, rollback, authenticated Testnet, approvals and production sign-off remains `NOT_VERIFIED`.
