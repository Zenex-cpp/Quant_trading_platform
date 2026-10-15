# V3.59 Operational Runbooks — §185

This document turns Master Prompt §185 into an operational control package. It does not claim production readiness; each runbook requires current evidence, an owner, and a completed recovery proof before controlled re-entry.

Common incident flow:
`DETECT → CONTAIN → SET STATE → PRESERVE EVIDENCE → RECONCILE → RECOVER/ROLLBACK → VERIFY → RE-APPROVE`

For every incident, preserve the immutable EventStore chain head, current Operational Truth hash, active risk decision IDs, deployment/bundle IDs, and all relevant reconciliation evidence before changing state.

## 1. Stale Data
Trigger: market/source data exceeds its Decision TTL or fails freshness/PIT checks.
Containment: block new risk-increasing entries; existing risk may only reduce/close under the active policy.
Recovery: restore a verified source, establish a new PIT-valid observation, rerun downstream causal TTL checks.
Exit: new evidence snapshot and risk authority are issued; no reuse of stale decision IDs.

## 2. Exchange Disconnect
Trigger: required REST/WS connectivity is lost or sequence continuity becomes UNKNOWN.
Containment: freeze new dispatch; enter reconciliation-required state.
Recovery: reconnect, recover sequence/gap, reconcile orders/positions/accounting, then issue fresh runtime authorities.
Exit: reconciliation is GREEN and a recovery proof is recorded.

## 3. Unknown Order
Trigger: external acknowledgement/execution status cannot be proven.
Containment: no retry of the same OrderRequest; mark dispatch state UNKNOWN.
Recovery: venue reconciliation establishes whether the order exists and its terminal/working state.
Exit: only a new authorized execution identity may dispatch any follow-up action.

## 4. Unknown Position
Trigger: local position state differs from authoritative evidence or cannot be reconstructed.
Containment: block all new entries; allow only explicitly authorized containment actions.
Recovery: reconcile fills, balances and position snapshot; issue fresh Position Authority.
Exit: position authority is durable, current, and bound to reconciliation evidence.

## 5. Reconciliation Mismatch
Trigger: REST/WebSocket/venue/accounting reconciliation is RED, BLOCKED or UNKNOWN.
Containment: block activation and new risk-increasing execution.
Recovery: isolate the mismatch scope, reconcile, record immutable evidence and re-authorize affected dependencies.
Exit: only a current GREEN reconciliation authority may support activation.

## 6. Risk Halt
Trigger: risk engine, kill-switch, budget, reservation or state monotonicity guard blocks a decision.
Containment: preserve blocking state; do not bypass by replay or manual flag changes.
Recovery: resolve the causal blocker and issue a new RiskDecision/Reservation where permitted.
Exit: hard constraints are green and the new authority is current.

## 7. Model Degradation
Trigger: ModelHealth assessment is UNKNOWN/unsafe, drifted, stale or below the registered applicability threshold.
Containment: lower/zero new risk according to the active cap; no silent fallback to a stronger exposure.
Recovery: validate a new model-health assessment or switch to an explicitly authorized safer mode.
Exit: current model-health authority and risk decision are durable.

## 8. Deployment Failure
Trigger: compatibility, integrity, promotion, readiness or activation authority fails.
Containment: keep deployment in non-active/containment state.
Recovery: identify the failed dependency; invalidate stale downstream artifacts; rebuild only from valid upstreams.
Exit: new compatibility/integrity/promotion/recovery/human-review evidence is current.

## 9. Rollback
Trigger: deployment failure, critical incident or explicit rollback decision.
Containment: stop rollout and preserve current state/audit chain.
Recovery: execute only the tested rollback target bound to the Promotion Bundle and state transition contract.
Exit: rollback outcome is reconciled, audited and followed by a new readiness/recovery proof when re-entry is attempted.

## 10. Database Recovery
Trigger: database corruption, loss or restore event.
Containment: prevent authorization from an unverified restored snapshot.
Recovery: restore backup, verify chain/checkpoints, reconcile durable state against external truth where required.
Exit: recovery proof validates invariants, state compatibility and audit continuity.

## 11. Disaster Recovery
Trigger: loss of primary execution environment or critical dependency.
Containment: move to controlled recovery mode; do not infer readiness from process restart alone.
Recovery: restore infrastructure, secrets through the approved vault path, state, dependencies and observability; execute failure-injection/restore evidence.
Exit: current recovery proof + operational readiness + human review are re-established.

## 12. Security Incident
Trigger: credential exposure, authorization anomaly, network-boundary violation or suspected tampering.
Containment: revoke affected authority/capabilities, isolate the component, preserve forensic evidence.
Recovery: rotate/reissue credentials through the production vault, invalidate dependent artifacts, complete security review.
Exit: security evidence, dependency revalidation and approval are current.

## 13. Epistemic Incident
Trigger: methodology assumption failure, evidence contamination, Final Holdout improper access or material research integrity incident.
Containment: mark affected evidence/gates/candidates/promotion artifacts invalid.
Recovery: follow the relevant immutable compromise/invalidation workflow; create a new holdout/evidence set where required.
Exit: only new valid Evidence Snapshot + Promotion Bundle + human review may re-enter promotion.

## Runbook completion record
Every completed runbook instance must record: `incident_id`, trigger, initial state, containment action, evidence refs, current truth hash, affected dependencies, recovery action, recovery proof ID, rollback outcome (if any), reviewer(s), revalidation status, and final authorization IDs.
