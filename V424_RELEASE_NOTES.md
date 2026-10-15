# V4.24 Recovery Build — Release Notes

V4.24 makes local milestone validation mandatory and introduces a fail-closed, read-only verifier for remote repository governance.

- Preflight is bound to the exact baseline archive hash, compliance matrix, impacted controls and pipeline contract file hashes.
- The runner executes only the fixed complete regression and release-hygiene commands; it checks freshness before every command and stops on any drift/failure.
- GitHub Actions runs the same entrypoint and pins checkout, setup-python and upload-artifact to full commit SHAs.
- Remote branch protection, required status checks, CODEOWNERS provenance and a successful hosted run are accepted only from a current Ed25519-signed provider snapshot whose signature covers both the payload and signer/validity metadata.
- The trust configuration remains `NOT_CONFIGURED`, so the bundled template correctly evaluates as `BLOCKED`.

## Verification

The recovered source tree passed 18/18 focused tests and 1,084/1,084 full regression tests through the controlled entrypoint; release hygiene passed. The final archive's independently extracted verification is recorded in `V424_ARCHIVE_VERIFICATION.json`.

## Important provenance note

This release is a **Recovery Build**, not a canonical V4.23-to-V4.24 continuation. The actual V4.23 source archive was not available in the build runtime; code was restored from the available V4.18 archive, using V4.22/V4.23 reports as design references. The V4.23 report's historical test count is not claimed for the reconstructed source.
