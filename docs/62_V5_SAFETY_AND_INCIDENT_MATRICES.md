# V5.0 Error, Failure, and Incident Contracts

This document defines repository-level default responses for the §179 error taxonomy, fail-safe matrix, failure-precedence matrix, and incident severity-by-scope matrix. The machine-readable registries are under schemas/v5_*.

## Error taxonomy

Error codes identify the failing boundary and class. Existing exception strings and classes are not automatically renamed; integrations may map them to this taxonomy. Unmapped or unclassifiable errors take the CRITICAL fail-safe path until reviewed. Error classification is diagnostic and never grants permission.

## Fail-safe behavior

The fail-safe matrix is action-specific. BLOCK is the default for new or increased exposure when a required source, clock, state, dependency, authorization, reconciliation, or recovery proof is unknown. ALLOW_IF_AUTHORITATIVE requires current trusted state and a valid action-specific authority. ALLOW_READ_ONLY permits evidence gathering but no state-changing side effect.

Risk reduction, closure, and cancellation are not unconditional exceptions: they require an authoritative position/order identity, fresh decision scope, and valid execution control. If those conditions are unavailable, reconcile first and remain blocked.

## Failure precedence

Apply the fixed order in schemas/v5_failure_precedence.csv: Security, Data Integrity, Reconciliation, Risk, Execution, Model/Strategy, Performance. When failures conflict, the higher-precedence failure controls. Equal-rank conflicts choose the more restrictive action. A lower-precedence success cannot clear a higher-precedence failure.

## Incident severity by scope

The matrix covers INSTRUMENT, STRATEGY, PORTFOLIO, and SYSTEM scope at CRITICAL, HIGH, MEDIUM, and LOW severity. If severity or scope is unknown, contain at the broader plausible scope and use CRITICAL handling until an operator classifies it. Resume requires the matrix's stated condition and every ordinary risk, compatibility, reconciliation, and evidence gate.

These are software control contracts. They do not replace an on-call organization, venue incident response, infrastructure enforcement, or independent security assessment.
