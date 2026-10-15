# V3.78 Verification Report

## Automated verification

- Full suite: **729/729 PASS**.
- Pre-existing suite from v3.77: 719 PASS.
- New v3.78 venue-execution tests: 10 PASS.
- No regression introduced in prior tests.

## Machine-checkable execution evidence

The evidence runner covers:

1. multi-level market-order sweep;
2. taker fee application;
3. GTX/Post Only reject and code `-5022`;
4. FOK reject and code `-5021`;
5. IOC partial fill plus explicit canceled remainder;
6. resting GTC queue-ahead consumption;
7. queue remainder preservation when aggressor volume is insufficient;
8. RPI fail-closed behavior;
9. order-book update-id regression rejection;
10. deterministic state hash across identical runs.

## Boundary

This release verifies the simulation layer against its declared inputs and
external venue references. It does not establish exact exchange matching-engine
behavior, production live parity, or production readiness.
