# V3.67 Change Impact

| Item | Change | Impact | Verification |
|---|---|---|---|
| Backup contract | Added governed local backup/restore drill | Enables deterministic application-level restore proof | V3.67 tests |
| Secret boundary | Reject secret-like backup paths | Prevents accidental secret inclusion | backup rejection test |
| Restore boundary | Reject non-empty destination, traversal, links, undeclared members | Fail-closed restore semantics | restore tests |
| RPO/RTO | Enforced target checks | Prevents false PASS when drill misses stated target | RPO/RTO regression test |
| Evidence semantics | Explicit INTERNAL_TEST_EVIDENCE | Prevents external-readiness conflation | report/compliance |
