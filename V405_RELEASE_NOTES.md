# V4.5 Release Notes

## Scope
V4.5 closes the application-level integration gap between external readiness revocation and the evidence dependency graph.

## Change
`RevocationDependencyBridgeV405` consumes a durably accepted V4.4 revocation and creates an immutable dependency-invalidation incident rooted at the revoked witness. Propagation follows the existing `EvidenceDependencyGraph` and `DependencyInvalidationLedger` semantics.

## Guarantees
- durable revocation must exist before propagation;
- exact witness fingerprint/bundle/evidence-snapshot/release-hash binding;
- witness must be represented as a dependency-graph root;
- append-only, idempotent invalidation incident;
- existing gates/candidates/promotions can be blocked through the dependency ledger;
- shared EventStore is mandatory;
- no network/process egress;
- no evidence artifact is synthesized.

## Verification
- V4.5 focused tests: 5/5 PASS;
- V4.4 regression baseline before change: 961/961 PASS;
- final full regression reported separately.
