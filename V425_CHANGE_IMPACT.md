# V4.25 Change Impact

## Changed
- Remote governance evidence collection now has an explicit read-only provider adapter in `src/trading_platform/v425/github_capture.py` and `scripts/capture_github_governance.py`.
- Codeowners evidence must include provider-resolved owner user/team IDs and an explicit self-ownership rule for `.github/CODEOWNERS`.
- Required source refs include the repository/inherited rulesets endpoint; actor ID sets must be non-empty and unique.
- Independent signing is a separate CLI using an external Ed25519 PEM key; private key paths inside the checkout are rejected.
- CI runner identity, matrix, baseline file, artifacts and fixed impacted control set are advanced to V4.25-RECOVERY.

## Not changed
- No trading logic, order, execution, exchange or production activation capability was introduced.
- The remote governance verifier remains read-only and trust-anchor gated.
- No provider-side settings were modified and no production flag was enabled.

## Risk controls
- All provider requests use `gh api` GET calls; artifact retrieval uses `gh run download` for one exact run/artifact.
- The CLI uses fixed argument vectors with `shell=False`; output paths are constrained to the checkout for capture, downloaded artifact paths are confined to a temporary directory, and hash inputs are file bytes.
- Capture and signer outputs remain unsigned/untrusted until the separate independent reviewer and trust ceremony are complete.
