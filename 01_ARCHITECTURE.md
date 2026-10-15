# 01 — System Architecture

## Normative flow
DATA → EVENTS → FEATURES → REGIME → RESEARCH/MODELS → PREDICTION → SIGNAL → OPPORTUNITY → PORTFOLIO → RISK → ORDER INTENT → ORDER → FILL → POSITION → ACCOUNTING → P&L

Parallel governance flow:
ARTIFACTS → DEPENDENCY GRAPH → EVIDENCE → GATES → PROMOTION → DEPLOYMENT

## V0.1 boundaries

### Included
- domain contracts;
- deterministic state validation;
- event normalization;
- immutable audit-oriented records;
- causal dependency checks;
- PIT metadata contracts;
- replay/event offset primitives;
- accounting invariant checks;
- compliance/test scaffolding.

### Excluded
- live exchange connectivity;
- real credential handling;
- production order submission;
- ML training/promotion;
- autonomous research agents;
- capital allocation optimization.

## Boundary rule
Venue-specific semantics belong under a future `adapters/<venue>` boundary. Core contracts must not depend on Binance field names or transport details.

## Safety authority
Security > Data Integrity > Reconciliation > Risk > Execution > Model > Performance.
New-entry default is fail-closed.
