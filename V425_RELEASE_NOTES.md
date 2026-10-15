# V4.25 Recovery Build — Release Notes

V4.25 adds a read-only GitHub governance capture and an independent signing utility around the V4.24 signed-snapshot verifier.

- Capture queries the exact repository/default branch, protected HEAD, branch protection, repository and parent rulesets, pinned workflow bytes, CODEOWNERS file and owner identity mappings, commit author IDs, merge actor IDs, successful workflow/job and preflight artifacts.
- Capture is read-only and fails closed on branch/HEAD mismatch, incomplete pagination, unresolvable user/team handles, missing self-ownership rule, failed workflow/job, missing or duplicate audit files, and unavailable provider responses.
- Ruleset bypass actors are conservatively recorded; the existing policy verifier blocks them rather than asserting non-applicability.
- The separate signer accepts a private key only from outside the repository and signs payload plus reviewer metadata using Ed25519. Trust configuration remains a separate independent act.
- The mandatory milestone runner and workflow are versioned as V4.25-RECOVERY and bind both capture/signing utilities into their contract hashes.
- No actual target GitHub repository was queried and no hosted workflow was launched by this local build. Test fixtures and temporary keys are synthetic and not operational evidence.

This is a Recovery Build based on the available V4.24 Recovery Build archive and preserves the upstream V4.23 source-lineage limitation.

## Measured local verification (2026-10-12)

- Controlled full regression: **1,101/1,101 PASS**.
- Targeted V4.25 capture/signing/runner tests: **27/27 PASS**.
- Release hygiene: **PASS**.
- Mandatory preflight: `READY_FOR_MILESTONE` (not production approval).
- Actual GitHub capture and hosted Actions: `NOT_RUN`.
- Remote settings and independent trust anchor: `NOT_VERIFIED` / `NOT_CONFIGURED`.
- `external_evidence=false`; `production_ready=false`.
