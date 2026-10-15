# V4.28 Change Impact

**Milestone:** `V4.28-RECOVERY`  
**Baseline:** `V4.27-RECOVERY`  
**Baseline archive SHA-256:** `3e0409eebb3edeebc7a336aa6dc666bef9287cf8abdf45a2ac0f4adff6ca70ac`

## Impacted controls

- `CI-PREFLIGHT-01`: current milestone ID, matrix, baseline hash and contract fingerprints are required before tests run.
- `REPO-GOV-CAPTURE-01`: provider capture output path is constrained before network/auth actions.
- `REPO-GOV-SIGN-01`: independent signing output is prevented from overwriting input or key artifacts.
- `REPO-GOV-PATH-01`: repository path confinement and symlink rejection.
- `REPO-GOV-PATH-02`: output collision prevention and audit path restrictions.

## Failure behavior

Malformed paths, symlink components, out-of-scope output paths, collision with inputs, invalid workflow/artifact naming or stale preflight input hashes fail closed. No network permissions, production activation or trading mutation are added.
