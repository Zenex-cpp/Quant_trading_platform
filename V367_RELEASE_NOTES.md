# V3.67 Release Notes

V3.67 introduces an application-level backup/restore drill contract.

Implemented:
- deterministic backup manifest and content hashing;
- fail-closed secret-like path exclusion;
- restore path-safety checks;
- clean-destination restore requirement;
- RPO/RTO target enforcement;
- explicit `INTERNAL_TEST_EVIDENCE` classification;
- automated regression tests.

Production readiness remains FALSE.
