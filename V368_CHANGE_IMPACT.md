# V3.68 Change Impact

## Change
Add a reusable controlled rollback exercise at `src/trading_platform/v368/rollback_exercise.py`.

## Motivation
Master Prompt §185 requires controlled rollback evidence. The existing deployment state machine already implements rollback, but the production-readiness register previously had only ordinary unit-test coverage. V3.68 turns the rollback flow into a reusable, deterministic internal drill.

## Affected components
- Deployment orchestration verification.
- Release evidence.
- Compliance mapping for §185 rollback evidence.

## Non-affected production contracts
- No live/testnet transport code changed.
- No production credentials are introduced.
- No risk ceilings are increased.
- No deployment activation policy is weakened.
- `production_ready` remains `FALSE`.

## Evidence boundary
`V368_ROLLBACK_DRILL.json` is `source_kind=INTERNAL`. It proves application rollback postconditions only. External infrastructure/operational rollback evidence remains required.
