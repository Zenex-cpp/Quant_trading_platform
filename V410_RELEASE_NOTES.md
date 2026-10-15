# V4.10 Release Notes

V4.10 hardens the V4.9 production-readiness binding with exact scope and exact evidence identity/fingerprint revalidation.

`ProductionReadinessRevalidationAuthorityV410` composes the existing V4.9 authority and adds a durable binding for:

- the exact Promotion Bundle and Evidence Snapshot;
- the exact readiness `scope`;
- the exact set of external, verified evidence IDs;
- the fingerprint of every evidence record at the time of readiness assessment;
- the V4.9 application-preflight fingerprint;
- the independent human-review ID and approval ID;
- the dependency checkpoint used for the assessment.

Revalidation fails closed if scope changes, an evidence record changes, an evidence item expires or loses its verified/external/pass state, the evidence set changes, the V4.9 preflight changes, the dependency graph is invalidated, or the event chain is corrupted.

V4.10 does not create external operational evidence, human approval, security evidence, infrastructure evidence, Testnet evidence, or production credentials.
