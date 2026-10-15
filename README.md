# Trading Platform — V4.5

Current repository release train: **V4.5**. Production readiness remains **FALSE** until the external operational evidence, independent review, recovery, security, approval and rollback requirements are actually satisfied.

## V4.5 — Revocation-to-dependency invalidation

V4.5 connects durable external-readiness revocation to the existing evidence dependency graph and `DependencyInvalidationLedger`. A revoked revalidation witness must be represented in the immutable dependency graph; otherwise propagation is refused fail-closed. When connected, the bridge records the computed blast radius so dependent evidence, gates, candidates and promotions become blocked until explicit revalidation.

Verification: **967/967 PASS**. See `V405_RELEASE_NOTES.md` and `V405_VERIFICATION_REPORT.md`.

# Trading Platform V3.93

Current repository release train: **V3.93**. Production readiness remains **FALSE** until external operational evidence and independent review are actually supplied.

## V3.93 — External evidence independent-review authority

V3.93 adds a durable, machine-checkable admission boundary connecting an EXTERNAL evidence package to an independent reviewer. It enforces exact subject coverage, reviewer independence, scope, validity, provenance, signature/hash metadata, idempotent audit persistence, and secret-free review payloads. It explicitly does not claim cryptographic PKI verification or external operational evidence.

Verification: focused **13/13 PASS**; full regression pending release freeze.

Current repository release train: **V3.75**; Python package version remains **3.61.0**.

## V3.75 — Decision-stage backtest/live parity

V3.75 adds a machine-checkable decision-stage parity contract. The live/shadow
decision runner consumes the same `BacktestStageFunctions` used by the
backtest engine, and deterministic traces are compared before any execution
integration is introduced.

Verification: **706 passed**. Production readiness remains **FALSE**.


V3.4 closes the execution commit boundary between Operational Truth authorization and order lifecycle.

## Runtime path
`OperationalTruth -> AuthorityDecision -> TradeCapability -> CommitCoordinator -> OrderRequest -> Lifecycle`

An open UNKNOWN state never permits a new dispatch. It forces reconciliation first. Idempotency prevents the same execution intent from creating multiple committed order requests.

## Verification
Current repository release: **V3.65**; Python package version: **3.61.0**.

Run:

```bash
PYTHONPATH=src pytest -q
```

Current release verification: **656 passed**.

No live exchange execution is performed by the verification suite. `production_ready = FALSE` remains mandatory until real external evidence and independent review satisfy the Master Prompt.




## V3.65 — Release artifact hygiene hardening

The governed source release now has a reusable machine-checkable hygiene validator. Release artifacts must contain no `__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `.pyc`, or `.pyo` transient artifacts. The Python distribution version remains `3.61.0`; V3.65 is the repository/release train identifier. See `scripts/validate_release_hygiene.py` and `V365_VERIFICATION_REPORT.md`.

## V3.68 — Controlled rollback exercise

V3.68 adds a reusable rollback drill over the governed deployment path. The drill proves zero residual deployment risk, trading denial after rollback, audit-chain integrity, and terminal close semantics. Evidence is explicitly `INTERNAL`; the external operational rollback gap remains OPEN. See `V368_RELEASE_NOTES.md`, `V368_VERIFICATION_REPORT.md`, and `V368_ROLLBACK_DRILL.json`.

## V3.64 — External evidence provenance hardening

Production-readiness evidence now carries explicit `source_kind` provenance. Only `EXTERNAL` evidence can become `VERIFIED`; legacy evidence without provenance is `UNKNOWN` and remains blocked. See `V364_RELEASE_NOTES.md`, `V364_VERIFICATION_REPORT.md`, and `src/trading_platform/v364/external_evidence.py`.

## V3.63 — Source-layout migration

The runtime package is now canonical under `src/trading_platform/`. The previous root-level `trading_platform/` duplicate has been removed. `pyproject.toml` explicitly configures setuptools discovery from `src`, and the full suite is verified through that import path. See `docs/00_REPOSITORY_SOURCE_OF_TRUTH.md` and `V363_VERIFICATION_REPORT.md`.

## V3.4
Execution-to-accounting bridge: OrderRequest → exchange observation → fill → PositionLedger → PnLLedger, with UNKNOWN-to-reconciliation fail-closed handling.

## V3.10
V3.10 adds the deterministic end-to-end user-data lifecycle supervisor. See `V310_RELEASE_NOTES.md` and `V310_VERIFICATION_REPORT.md`.

## V3.16
Accounting is now an explicit risk-increasing dispatch gate. Durable reconstruction remains non-authorizing until explicit reconciliation evidence is recorded; `UNKNOWN` and `UNRECONCILED` fail closed.

## V3.16
Accounting is now an explicit risk-increasing dispatch gate. Durable reconstruction remains non-authorizing until explicit reconciliation evidence is recorded; `UNKNOWN` and `UNRECONCILED` fail closed.

## V3.17
Risk reservations are now durable and replayable. A configured final dispatch gate requires an existing reservation bound to the exact intent, risk decision and current accounting projection hash; consumption is persisted before external transport and cannot be reused after ambiguity.

## V3.18
Risk decisions are now durable, replayable, TTL-bound, version-bound, provenance-bound artifacts. The final dispatch guard captures one clock sample and uses it for OrderIntent freshness, OrderRequest deadline, risk-decision TTL, and risk-reservation consumption.

## V3.18
Durable `RiskDecision` records and final pre-transport freshness/identity gates are enforced on the opt-in V3.18 dispatcher path. The dispatcher captures one timestamp for all freshness checks and rejects payload substitution against the committed authority fingerprint.

## V3.19
`OrderIntent` is now optionally backed by a durable, immutable, hash-chained ledger at the final dispatch boundary. Missing or mismatching persisted intent identity fails closed before risk gates and external transport.


## V3.20
Committed `AuthorizedOrderRequest` is now optionally backed by a durable, immutable, hash-chained ledger. The record binds the exact `OrderIntent` fingerprint, authority decision, request identity, client order id, deadline, execution version and quantity. The final dispatcher can require the durable request before any risk gate or external transport. Missing, corrupt, or mismatching request authority fails closed.

## V3.21
The final dispatch boundary now supports a durable pre-transport attempt ledger. The exact OrderRequest is marked PENDING before external transport; a restart/crash or transport ambiguity therefore cannot silently retry the same side effect. Resolved attempts are immutable and a second submission of the same OrderRequest is blocked until a separate reconciliation path establishes a new authorized execution identity.


## V3.22
Durable reconciliation closure for PENDING/UNKNOWN dispatch attempts. Reconciliation records closure evidence without enabling retry of the original OrderRequest.


## V3.23
Durable Commit Authority: CommitCoordinator commit claims are persisted and restart-safe before capability consumption; duplicate reuse returns the original request and conflicting reuse fails closed.

## V3.24
Recovery proof is now a durable, immutable evidence artifact. `CANARY` and `LIVE` readiness requires a valid, unexpired proof bound to the current state fingerprint; `CLOSING_ONLY` remains a containment path. See `54_V324_RECOVERY_PROOF_AUTHORITY.md` and `V324_VERIFICATION_REPORT.md`.


## V3.25
Durable deployment activation authority. `CANARY`/`LIVE` activation now requires current recovery proof, Operational Truth, approval and promotion-dependency fingerprints, with a durable EventStore authorization and a final canary activation wrapper. See `55_V325_DEPLOYMENT_ACTIVATION_AUTHORITY.md` and `V325_VERIFICATION_REPORT.md`.

## V3.26
The final deployment state transition is now machine-guarded. Direct V3.28 `DeploymentOrchestrator.activate()` calls are blocked unless a validated V3.25 activation capability is present. V3.26 also records a durable final-transition authorization in the existing hash-chained EventStore. See `56_V326_STATE_TRANSITION_AUTHORITY.md` and `V326_VERIFICATION_REPORT.md`.

## V3.27
V3.27 hardens the V3.26 deployment activation capability with explicit validity windows, unique capability identity, single-use consumption and removal of the public issuer API. See `V327_RELEASE_NOTES.md` and `V327_VERIFICATION_REPORT.md`.


## V3.28
V3.28 adds a separate durable `DEPLOYMENT_STATE_TRANSITION_EXECUTED` event and replayable immutable post-state, closing the crash window between transition planning and durable execution evidence.

## V3.28
V3.28 closes the durable final-transition execution boundary. The final activation path deterministically plans the immutable `DeploymentEvent`, persists a separate append-only `DEPLOYMENT_STATE_TRANSITION_EXECUTED` record, consumes the V3.27 activation capability only after that durable commit, and can replay the same post-state after a process crash without issuing a second activation.

See `trading_platform/v328/durable_transition.py`, `V328_RELEASE_NOTES.md`, `V328_VERIFICATION_REPORT.md`, and `compliance_master_m30_v328.csv`.


## V3.29
V3.29 adds a durable dependency invalidation authority for evidence, gates, candidates and promotions. Dependency changes are recorded append-only in the existing hash-chained EventStore and remain blocking until an explicit revalidation event closes the incident. The final deployment activation authority now fails closed when an active invalidation touches the bundle, evidence snapshot, gates or promoted artifact versions.

The release deliberately does not claim that every legacy evidence producer is already wired into every authority: M17 remains subject to broader review, while M27 is machine-enforced on the holdout, dependency-invalidation and evidence-snapshot boundaries.

See `trading_platform/v329/dependency_authority.py`, `V329_RELEASE_NOTES.md`, `V329_VERIFICATION_REPORT.md`, and `compliance_master_m30_v329.csv`.

## V3.30

V3.30 makes the V3.29 dependency invalidation authority mandatory on the gate-reuse and promotion path. `GateSummary` and `promotion_allowed()` require explicit dependency authority; the V3.28 deployment orchestrator requires the same authority to be injected rather than creating an isolated fallback ledger.

Final Holdout access is now governed by `HoldoutAccessContext`: every access is durably logged, and improper tuning access emits a violation and an invalidation incident that blocks dependent evidence/gates/promotions until explicit revalidation.

M17 and M27 are tested end-to-end. They are not labeled VERIFIED because the Master Prompt requires independent review in addition to automated evidence.


## V3.32
V3.32 adds a durable Position Authority boundary for M3. Reconciliation remains the evidence source, while `PositionAuthorityLedger` is the persisted, TTL-bound position authorization consulted by the final dispatch runtime. Unknown, mismatched, expired or corrupted position authority fails closed before transport. The runtime clock is propagated into the dispatch guard to preserve deterministic TTL semantics. M3 is TESTED, not VERIFIED. See `57_V331_POSITION_AUTHORITY.md`, `V331_RELEASE_NOTES.md`, `V331_VERIFICATION_REPORT.md`, and `compliance_master_m30_v331.csv`.


## V3.33
V3.33 adds a durable `CausalTTLAuthorityLedger` for the Prediction → Signal → Opportunity → Portfolio → Risk → Intent chain. A risk-increasing runtime dispatch is fail-closed when any required upstream artifact is missing, expired, invalidated, corrupted, mismatched or has a TTL shorter than the downstream artifact. M5 is TESTED, not VERIFIED. See `trading_platform/v333/causal_ttl.py`, `58_V333_CAUSAL_TTL_AUTHORITY.md`, `V333_RELEASE_NOTES.md`, `V333_VERIFICATION_REPORT.md`, and `compliance_master_m30_v333.csv`.


## V3.41
V3.41 adds a durable artifact-compatibility authority for M14. Artifact execution now requires a restart-safe, artifact-bound `CompatibilityAuthorityLedger` record; `INCOMPATIBLE`, `UNKNOWN`, expired, mismatched or dependency-invalidated compatibility evidence fails closed across prepare, activation and final transition. M14 is TESTED, not VERIFIED. See `trading_platform/v341/compatibility_authority.py`, `V341_RELEASE_NOTES.md`, `V341_VERIFICATION_REPORT.md`, `59_V341_ARTIFACT_COMPATIBILITY_AUTHORITY.md`, and `compliance_master_m30_v341.csv`.


## V3.42
V3.42 adds the durable `ArtifactIntegrityAuthorityLedger` for M15. Deployment preparation and activation now require an artifact-bound integrity authorization proving exact observed hashes, manifest identity and signature verification. Missing, expired, mismatched, unsigned or dependency-invalidated integrity evidence fails closed across V3.28 preparation, V3.25 activation and the final activation controller. M15 is TESTED, not VERIFIED. See `trading_platform/v342/artifact_integrity.py`, `V342_RELEASE_NOTES.md`, `V342_VERIFICATION_REPORT.md`, `60_V342_ARTIFACT_INTEGRITY_AUTHORITY.md`, and `compliance_master_m30_v342.csv`.

## V3.48 M21
The production uncertainty-risk mapping is registered in `v348_uncertainty_risk_registry.csv` and enforced by `trading_platform/v348/uncertainty_risk_authority.py`.

## V3.49 M22

M22 adds a production liquidity-risk authority. Higher liquidity stress can only preserve or reduce the allowed risk/exposure. The mapping is versioned and registry-bound, applied by `RuntimeAuthority`, enforced by durable risk decisions, and propagated into the risk monotonicity and capacity primitives. Unregistered methods and stale liquidity provenance fail closed.


## V3.54
V3.54 closes M27. Final Holdout improper access now produces a durable `COMPROMISED` state, invalidates dependent evidence/gates/candidates/promotions, blocks pre-issued and new capabilities for the compromised holdout, requires a registered versioned replacement holdout, and requires new evidence for revalidation. Evidence identities contaminated by `FINAL_HOLDOUT_IMPROPER_ACCESS` cannot be reused for later Evidence Snapshots, even after incident revalidation. See `trading_platform/v354/holdout_compromise.py`, `V354_RELEASE_NOTES.md`, `V354_VERIFICATION_REPORT.md`, and `compliance_master_m30_v354.csv`.

V3.55 adds a durable Recovery Readiness Authority so controlled post-recovery activation cannot rely on an in-memory readiness boolean alone.


## V3.59
V3.59 implements Master Prompt §185/§186. LIVE activation now requires a durable human-review authorization bound to the exact Promotion Bundle and Evidence Snapshot; V3.59 also adds the operational runbook package and explicit open-gaps register. No automated path creates human approval, so `production_ready` remains false until independent review and operational evidence are present.

## V3.69 Monitoring/Alerting Drill

V3.69 adds a deterministic application-level monitoring/alerting drill with fail-safe severity routing, monitoring-unavailable fail-closed behavior, and idempotent alert deduplication. The resulting evidence is INTERNAL and does not satisfy production infrastructure observability evidence.

## V3.81

V3.81 adds the deterministic Testnet end-to-end acceptance harness covering:

`OrderIntent -> OrderRequest -> simulated ACK -> ORDER_TRADE_UPDATE -> ACCOUNT_UPDATE -> REST/WS reconciliation -> FillLedger -> PositionLedger -> Accounting`.

It also adds a read-only external Testnet preflight. Real network/authenticated execution remains separately classified as NOT_VERIFIED when external connectivity or credentials are unavailable.


V3.89 adds a one-shot Testnet runtime credential capability boundary.


## V3.90
V3.90 adds an application-level Testnet egress isolation boundary for M25. Credentialed REST requests are bound to the exact Testnet host, HTTPS, default port and no embedded userinfo; ambient proxy configuration is blocked, the stdlib transport uses an explicit empty proxy map, redirects are rejected, and the target is revalidated on every request. V3.90 does not claim infrastructure-level routing isolation or real Testnet mutation evidence.

## V3.91
V3.91 adds the machine-checkable network-segmentation contract for M25. It enforces deny-by-default directional isolation between RESEARCH, TESTNET_EXECUTION and PRODUCTION_TRADING with exact host allowlists and no wildcard routes. Infrastructure-level firewall/VPC/container evidence remains external and `production_ready` stays false until that evidence is independently reviewed.

## V3.94
V3.94 adds real in-process Ed25519 verification for the V3.93 independent-review path. The signed canonical binding covers exact package/review hashes and scope; trust-anchor validity, revocation, scope and fingerprint are fail-closed; verification is durable and idempotent. This proves the cryptographic operation in-process but does not claim external PKI/HSM or trust-anchor custody evidence, so production readiness remains false. See `trading_platform/v394/cryptographic_attestation.py`, `V394_RELEASE_NOTES.md`, `V394_VERIFICATION_REPORT.md`, and `V394_TRUST_ANCHOR_REGISTRY_SCHEMA.csv`.


## V4.7
V4.7 closes a critical-promotion freshness gap. `CriticalPromotionReadinessAuthorityV398` now requires a durable Evidence Snapshot authorization bound to the exact bundle, model, gates, artifacts, versions, approval and scope. The snapshot authority also includes `snapshot_id` in its dependency freshness set, so direct snapshot invalidation fails closed. Application verification is **979/979 PASS**; production readiness remains blocked pending real external operational evidence.

## V4.8
V4.8 closes the critical-promotion gate freshness gap. Each gate in a critical promotion bundle now requires durable V4.8 authorization bound to the exact gate fingerprint and dependency checkpoint. `CriticalPromotionReadinessAuthorityV398` directly revalidates every authorized gate before accepting readiness. Application verification is **985/985 PASS**; production readiness remains blocked pending real external operational evidence.


## V4.18 — Mandatory Machine Checks

V4.18 adds `MachineCheckReadinessAuthorityV418` for Master Prompt §177 M1–M30. It requires exact coverage of the thirty normative checks, required matrix fields, closed per-check gaps, a durable V3.93 external review for the exact bundle-bound `MP177-{bundle_id}` evidence package, and a V4.13 cryptographic review decision tied to the same package/review hashes through the V3.94/V3.95 chain. Evidence payload hashes must match the canonical reviewed matrix rows. Decisions are durable, fingerprinted and fail closed on drift.

The checked-in `compliance_v418.csv` remains blocked: 27 checks are `TESTED`, 2 `IMPLEMENTED`, and 1 `PARTIAL`; all unresolved gaps remain open and there is no external M1–M30 review attached to this release. No production activation path is added and `production_ready = FALSE`. See `60_V418_MACHINE_CHECK_AUTHORITY.md`, `V418_RELEASE_NOTES.md`, `V418_VERIFICATION_REPORT.md`, `V418_OPEN_GAPS_DELTA.md`, and `V418_EXTERNAL_EVIDENCE.json`.
