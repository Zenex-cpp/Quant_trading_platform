# V4.25 Read-only GitHub Governance Capture and Independent Signing

## Purpose

The existing `scripts/verify_repository_governance.py` validates a signed snapshot; it intentionally does not fetch live GitHub state. V4.25 adds a separate, explicitly read-only collector so provider claims are gathered from actual endpoints rather than filled by hand. The collector never changes GitHub settings and never signs evidence itself.

## Required environment

Run from the exact checkout whose `HEAD` should be attested. The collector requires the GitHub CLI (`gh`), an authenticated session, and access sufficient to read repository metadata, branch administration/protection, repository and inherited rulesets, contents, workflow runs/jobs/artifacts, pull requests, and CODEOWNERS user/team identities. The repository and selected branch must match the local `git rev-parse HEAD`; the branch must be the configured default branch and protected.

GitHub's branch protection read endpoint requires repository `Administration: read` permission; workflow-run reads require the appropriate Actions/metadata visibility. See the official API documentation:

- [REST API: protected branches](https://docs.github.com/en/rest/branches/branch-protection)
- [REST API: workflow runs](https://docs.github.com/en/rest/actions/workflow-runs)
- [GitHub CODEOWNERS](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)

## Before capture

The target repository must contain `.github/CODEOWNERS`, and that file must include an explicit `/.github/CODEOWNERS @org/team` self-ownership rule. Every user/team handle appearing in the file must resolve via GitHub APIs. The workflow at remote protected HEAD must match the local checkout byte-for-byte and the latest successful `push` run must match the same HEAD, workflow path, required job context, and current run attempt. The run artifact must contain both `V425_MILESTONE_PREFLIGHT.json` and `.sqlite3`; the workflow explicitly enables hidden-file upload but restricts the paths to these known audit files. The collector hashes the downloaded file bytes, not the artifact label.

The collector is conservative for rulesets: it reads repository and inherited rulesets and records active bypass actors. Any bypass actor causes the existing policy evaluator to block until an independent reviewer evaluates whether and how that ruleset applies. Incomplete pagination, unavailable ruleset details, unknown identities, duplicate/missing artifacts or scope drift abort capture.

## Capture

```bash
python scripts/capture_github_governance.py \
  --repository OWNER/REPOSITORY \
  --branch main \
  --output .audit/V425_REPOSITORY_GOVERNANCE_UNSIGNED.json
```

The collector writes an unsigned provider payload. It does not configure the trust file and does not imply `VERIFIED`. Keep the raw capture read-only and preserve it for review.

## Independent signing

Move the capture to the independent reviewer's workstation. The private key must live outside this repository. The reviewer must validate the source snapshot, repository/branch scope, branch protection/ruleset semantics, owner/team identity mappings, hosted run and artifacts before signing.

```bash
python scripts/sign_github_governance_evidence.py \
  --evidence /secure/review/V425_REPOSITORY_GOVERNANCE_UNSIGNED.json \
  --private-key-pem /secure/keys/repository-governance-reviewer.pem \
  --key-id REVIEWER_KEY_ID \
  --signer-id INDEPENDENT_REVIEWER_ID \
  --output /secure/review/V425_REPOSITORY_GOVERNANCE_SIGNED.json
```

The signer utility refuses a private-key path inside the checkout. Its output is not trusted merely because it is signed: the public key, exact key fingerprint, reviewer identity/role and ceremony reference must be reviewed and configured separately in `config/repository_governance_trust_v424.json` through an independent approval process. Never commit a private key or synthetic test key.

## Verify

After the target repo has the signed evidence, use the existing read-only verifier. A missing/mismatched trust anchor, stale evidence, mismatch in local workflow hash, weak branch settings, unresolved owners, active bypass actor, failed hosted run, or bad artifact hashes must remain `BLOCKED`.

No capture, signature or local test sets `production_ready`; operational production blockers remain separate.
