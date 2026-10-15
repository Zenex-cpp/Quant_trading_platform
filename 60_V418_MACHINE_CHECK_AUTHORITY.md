# V4.18 — Mandatory Machine Check Readiness Authority

## Normative basis

V4.18 implements a machine-checkable application contract for Master Prompt §177, M1–M30. It supplements the §174–§176 readiness-compliance gate introduced in V4.17; it does not replace the full production-readiness decision or redefine the Master Prompt status vocabulary.

## Authority

`trading_platform.v418.machine_check_readiness.MachineCheckReadinessAuthorityV418` evaluates:

1. A durable V4.17 compliance decision for the same promotion bundle.
2. Exactly one row for each mandatory machine check M1–M30, including the required §175 matrix columns.
3. The normative check description for every M-code and an allowed implementation status.
4. Code, test, evidence and owner references; a non-empty unresolved gap, missing review reference or non-`VERIFIED` status keeps that check blocking.
5. A durable V3.93 external-review acceptance for the exact `MP177-{bundle_id}` package, with package evidence covering exactly M1–M30.
6. A durable V4.13 cryptographic review decision tied to the same review ID/hash, package ID/hash and bundle; that predecessor binds to the V3.94 Ed25519 verifier and V3.95 trust-anchor attestation path.
7. Evidence content hashes that match the canonical form of the reviewed matrix rows.

The decision is append-only through the shared EventStore, fingerprinted, idempotent for identical inputs and conflict-failing if the same decision ID is reused with changed inputs.

## Fail-closed outcomes

The authority emits `VERIFIED` only when all machine checks are represented and closed, upstream V4.17 compliance is `VERIFIED`, and the external review plus cryptographic predecessor chain all match. Missing external review, stale/expired attestations, mismatched scope, bundle, package, fingerprints, evidence coverage or content hashes result in `BLOCKED` or a validation error. This release does not invent an independent review or turn internally generated test fixtures into external evidence.

The current checked-in `compliance_v418.csv` intentionally remains `BLOCKED`: it carries the inherited M1–M30 implementation statuses and their unresolved gaps, and has no independently accepted review references. Schema-reference values are present as columns but blank where no explicit schema mapping was supplied. The package therefore does not claim M1–M30 are `VERIFIED`.

## Safety boundary

V4.18 performs application-level validation only. It does not create signatures, issue credentials, contact exchanges, invoke subprocesses, perform Testnet/Production mutation or activate a runtime. `production_ready` remains `FALSE` until independent evidence and all applicable operational, security, recovery and approval gates are genuinely closed.
