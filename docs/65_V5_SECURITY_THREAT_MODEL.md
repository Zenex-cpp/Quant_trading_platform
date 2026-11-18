# V5.0 §153 Security Threat Model

This is the repository's canonical threat inventory for the ten threat classes listed in `MASTER PROMPT.txt` §153. The machine-readable record is `schemas/v5_threat_model.csv`; tests require every prompt threat to have prevention, detection, remediation, and a responsible owner.

## Trust boundaries and response rule

The model covers the local software controls and their operator-facing limits. Research, model loading, credential management, configuration, deployment, order dispatch, and durable audit each have separate control boundaries. Unknown, stale, inconsistent, or unauthenticated authority blocks new risk and deployment. Incident handling must preserve available evidence, contain the affected authority, reconcile external state before any recovery action, and re-run ordinary approval and safety gates before resuming.

The `control_status` field distinguishes controls with bounded local test coverage from partial controls and specification-only protections. A local test does not prove that host identity, network isolation, dependency origin, exchange behavior, external audit storage, or incident response is secure. The `residual_risk` field records the remaining exposure for each threat. No row claims an independent penetration test or production verification.

## Threat ownership and escalation

Owners in the registry name accountable functions, not currently provisioned people or on-call rotations. If the owner, scope, or evidence is unknown, halt affected state-changing actions and escalate to Security Operations and the Platform Owner. Credential, configuration, deployment, duplicate-order, replay, and audit-integrity incidents require preservation of the durable ledger and reconciliation of venue state before recovery. The response must not erase or rewrite suspected evidence.

This artifact completes the §179 Threat Model deliverable. It does not assert that every listed control is deployed or that the threat has been eliminated.
