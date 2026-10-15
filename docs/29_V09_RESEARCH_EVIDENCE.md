# V0.9 — Research Lab / Evidence Graph / Invalidation / Knowledge Base

## Scope
V0.9 formalizes the research-governance layer required by MASTER PROMPT v5.0.

Research artifacts are separate from promotion and deployment. A research decision cannot itself activate production.

## Research structures
- Hypothesis Ledger: statement, mechanism, falsification criteria, status, owner, timestamp.
- Research Branch: parent, hypothesis, purpose, type, status.
- Research Decision: CONTINUE / CHANGE_HYPOTHESIS / PAUSE / STOP / PROMOTE_TO_VALIDATION / RETIRE.
- Merge Record: parent branches, lineage, conflicts, selection rationale and new candidate.
- Research Cost: compute, data, storage, training, inference, engineering and operational costs.
- Anti-Duplication Gate: similarity over hypothesis/dataset/features/target/strategy/genealogy.
- Knowledge Base: SUPPORTED / DISPROVED / UNCERTAIN / OBSOLETE.
- Stopping controls explicitly support diminishing returns, repeated variants, excessive data mining, exhausted budget and no incremental information.
- Decision Bias Log records discretionary selection effects.
- Edge Registry and decay observations support DISCOVERY → ADOPTION → PEAK → DECAY → RETIREMENT.

## Evidence
Evidence carries state, scope, validity window, methodology, dependencies, owner and content hash.

Historical evidence is immutable by version. A dependency change creates a new graph version and triggers impact analysis.

The Evidence Snapshot is immutable evidence material for promotion. It contains evidence, metrics, gates, dependencies, versions, hashes, methodology, approvals and scope.

## Invalidation
Dependency blast radius is computed as:
changed component → affected artifacts → invalidated evidence → invalidated gates → affected candidates → affected promotions → required revalidation → deployment impact.

During investigation, evidence may be SUSPENDED before final INVALIDATED status.

## Promotion gate
Promotion is permitted only when bundle, compatibility, evidence, gates, approval, scope and integrity all pass. V0.9 itself does not activate production.
