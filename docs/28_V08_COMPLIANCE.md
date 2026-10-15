# V0.8 Compliance

| ID | Requirement | Status | Evidence |
|---|---|---|---|
| V08-001 | Separate Signal / Intent / Request / Exchange Order / Fill | IMPLEMENTED | execution models + adapter |
| V08-002 | Order lifecycle machine-checkable | TESTED | lifecycle tests |
| V08-003 | UNKNOWN order requires query/reconcile/decide | TESTED | unknown-order tests |
| V08-004 | No blind retry on UNKNOWN | TESTED | unknown-order guard |
| V08-005 | Partial fill quantities preserved | IMPLEMENTED | Fill contract + fill ledger |
| V08-006 | Venue precision rules explicit | TESTED | precision tests |
| V08-007 | Reconciliation triggers supported | IMPLEMENTED | reconciliation flow |
| V08-008 | Recovery proof formula implemented | TESTED | recovery tests |
| V08-009 | Testnet-only adapter guard | TESTED | adapter tests |
| V08-010 | Production credential isolation | PARTIAL | no credentials in package; deployment boundary remains future work |
| V08-011 | Real Binance connectivity | BLOCKED | no production/testnet transport shipped |
| V08-012 | Full live reconciliation against venue | BLOCKED | requires venue account/testnet integration |
| V08-013 | Production readiness | BLOCKED | V0.8 is not production |
