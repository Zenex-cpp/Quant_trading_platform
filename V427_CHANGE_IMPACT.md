# V4.27 Change Impact

Impacted controls:

- `REPO-GOV-CAPTURE-01`: capture uses strict content decoding and size bounds.
- `REPO-GOV-CAPTURE-STRICT-01`: malformed Base64 must fail closed.
- `REPO-GOV-CAPTURE-BOUNDS-01`: audit downloads must remain within per-file and total byte limits.
- `CI-PREFLIGHT-01`: hardening module and tests are bound into the preflight input fingerprint set.

Preserved invariants: read-only provider capture; no HTTP writes or repository setting mutation; private reviewer key remains outside the checkout; synthetic fixtures remain test-only; `external_evidence=false`; `activation_flag=NOT_SET`; `production_ready=false`.
