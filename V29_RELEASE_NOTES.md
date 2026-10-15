# V2.9 Release Notes

V2.9 adds a deployment provenance ledger binding release artifact, code fingerprint, configuration fingerprint, approval, evidence set, deployment identifier and rollback references.

Hard rules:
- provenance is append-only and hash chained;
- missing/invalid approval, evidence or configuration blocks deployment;
- revocation forces deployable=false;
- deployment linkage is allowed only after all provenance prerequisites pass;
- tampering or sequence gaps are fail-closed.

No live exchange mutations are part of this release verification.
