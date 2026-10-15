# V1.0 — Promotion, Champion/Challenger, Shadow, Canary, Operational Readiness

V1.0 closes the promotion/deployment control plane without making deployment autonomous.

## Promotion invariant

Production promotion is allowed only when all required predicates hold:

`bundle_complete ∧ compatibility_pass ∧ evidence_valid ∧ required_gates_pass ∧ approval_valid ∧ scope_valid ∧ artifacts_integrity_valid`

The Promotion Bundle references strategy/model/feature/target/configuration/execution/code versions, Evidence Snapshot, gates, artifact hashes, approval, scope and rollback target.

## Champion / Challenger

`CHALLENGER` is competitive. `CHAMPION` is approved primary. A Challenger cannot self-promote or enter LIVE directly.

## Shadow

SHADOW is an operational mode. It must run with zero allocated risk and the order boundary is hard-disabled.

## Canary

CANARY has a dedicated risk budget and absolute exposure bound. Both are enforced before activation.

## Live

LIVE activation requires CHAMPION, valid approval, healthy state and all upstream promotion/readiness controls.

## Operational readiness

The readiness object explicitly covers data validation, invariants, state matrix, risk engine, kill switch, reconciliation, accounting, realistic execution, monitoring, security, permissions, network isolation, backup/restore, tested rollback, failure injection, recovery proof, evidence snapshot, promotion bundle and approval.

## Security boundary

Research capability cannot acquire production trading capability. Production credential handling is outside research scope.

## Safety posture

V1.0 remains a controlled-deployment framework. The implementation does not contain production credentials and does not autonomously promote or switch to live trading.
