# V4.24 — Remote Repository Governance Evidence Runbook

## Purpose

This runbook closes the local-code/remote-policy boundary left open by the V4.23 release notes. A checked-in workflow does not prove that the repository host requires its check, that administrators cannot bypass it, or that a hosted run passed on the protected branch. V4.24 therefore treats remote settings as signed external evidence rather than inferring them from local files.

## Workflow supply-chain pins

The workflow pins the GitHub actions to full commit SHAs, not mutable major-version tags: `actions/checkout` v7.0.1 (`3d3c42e5aac5ba805825da76410c181273ba90b1`), `actions/setup-python` v7.0.0 (`5fda3b95a4ea91299a34e894583c3862153e4b97`), and `actions/upload-artifact` v7.0.1 (`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`). See the corresponding upstream release/commit pages linked in the release report.

## Required provider-side configuration

Before attempting to attest the repository:

1. Commit `.github/workflows/ci.yml` to the target GitHub repository and run the workflow on the default branch.
2. Create a real `.github/CODEOWNERS` file with repository-specific, existing users/teams. The evidence snapshot must include its path and SHA-256. A local placeholder is not accepted as operational ownership evidence.
3. Enable branch protection or an equivalent ruleset for the protected default branch.
4. Require pull requests, at least one independent approval, stale-review dismissal, and Code Owner review. Enable administrator enforcement, strict required status checks, disable force-pushes and branch deletion, and remove bypass actors.
5. Require the exact status-check context `controlled-milestone-validation`.
6. Run `controlled-milestone-validation` on a push to the protected branch. Record the commit SHA and successful run, and preserve both `V424_MILESTONE_PREFLIGHT.json` and `V424_MILESTONE_PREFLIGHT.sqlite3` with their SHA-256 hashes.
7. Capture the branch-protection/ruleset and Actions-run state from GitHub's authenticated provider API. The evidence `source_refs` must identify the branch-protection resource and the exact workflow run resource.
8. Have an independent repository administrator/reviewer sign the canonical JSON payload with Ed25519, using a key whose trust ceremony is external to this archive. The signer must not be a workflow author, change author, or merge actor.

## Evidence payload and signature

The payload structure is documented by `schemas/v424_repository_governance_evidence.schema.json` and illustrated (intentionally incomplete) by `V424_REPOSITORY_GOVERNANCE_EVIDENCE_TEMPLATE.json`. The signature covers canonical UTF-8 JSON (sorted keys and compact separators) of `{ "payload": payload, "attestation": signed_metadata }`, where `signed_metadata` contains exactly `key_id`, `signer_id`, `signer_role`, `signed_at_ms`, and `expires_at_ms`; only `signature_b64` is excluded from the signed message. This prevents metadata such as signer identity or expiry from being edited without invalidating the signature.

The trust file `config/repository_governance_trust_v424.json` is intentionally `NOT_CONFIGURED`. Do not populate it with a test key. Change it to `VERIFIED` only after an independent key ceremony, with exact key ID, signer ID, key bytes, SHA-256 fingerprint and trust-ceremony reference. Private keys must never be placed in this repository.

To verify a captured and signed payload:

```bash
PYTHONDONTWRITEBYTECODE=1 python scripts/verify_repository_governance.py \
  --repository OWNER/REPOSITORY \
  --branch main \
  --evidence path/to/signed_repository_governance.json \
  --trust config/repository_governance_trust_v424.json \
  --report .audit/V424_REPOSITORY_GOVERNANCE.json \
  --event-store .audit/V424_REPOSITORY_GOVERNANCE.sqlite3 \
  --require-verified
```

Without a valid trust anchor and a fresh, signed provider snapshot the expected result is `BLOCKED`. The ordinary CI workflow runs this check in diagnostic mode so it can always publish the missing-evidence report; it does **not** claim remote governance is verified and does not use that report as a substitute for branch protection.

## Correct use of the required status check

The required branch status is the main workflow job `controlled-milestone-validation`, which runs the mandatory preflight, full regression and release hygiene. Do not make the remote-governance-evidence diagnostic itself a required status check: that would create a bootstrap cycle because the proof needs a successful hosted run on the protected branch. Once an independent reviewer has captured and signed the current provider state, the signed snapshot can be evaluated separately.

## Limitations

The verifier makes no network requests and cannot configure GitHub settings. The repository administrator must perform the provider-side changes. A successful cryptographic verification establishes that the signed evidence matches the configured key and that the payload is intact; it does not prove the claims are true unless the signing identity, source capture and trust ceremony are independently trustworthy.

This gate is about repository governance only. It never sets `production_ready`, never activates trading, and never upgrades operational controls to `VERIFIED` without corresponding external evidence.
