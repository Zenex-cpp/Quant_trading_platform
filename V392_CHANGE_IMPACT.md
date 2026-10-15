# V3.92 Change Impact

| Changed component | Impacted components | Required retests | Deployment impact |
|---|---|---|---|
| Production secret admission | Credential boundary, production activation | v336 credential tests + v392 contract tests | Production activation remains blocked without attestation |
| Secret lease policy | Credential lifecycle | expiry/revocation/TTL tests | Fail closed on invalid lease |
| Evidence payload validation | Audit/evidence generation | secret-material rejection tests | No secret-bearing evidence accepted |

No existing production credential material was accessed or changed.
