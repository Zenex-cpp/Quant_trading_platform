# V3.55 Release Notes

Requirement: M28 — Post-recovery state cannot be READY/LIVE without recovery proof.

V3.55 adds a durable Recovery Readiness Authority above the existing recovery proof. CANARY/LIVE activation now records and revalidates an immutable readiness authorization bound to the recovery proof, readiness fingerprint, target mode and current state fingerprint. The final V3.26 state-transition authority also persists the exact recovery proof ID/fingerprint used for the transition.

The legacy boolean readiness flags remain compatible, but they are no longer sufficient evidence for controlled activation: the durable recovery proof and recovery-readiness authorization must both validate.
