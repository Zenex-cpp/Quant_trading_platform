# V3.68 Release Notes — Controlled Rollback Exercise

V3.68 adds a reusable, deterministic rollback drill for the existing deployment state machine.

The drill exercises the actual deployment path:

`PREPARE → STAGE → CANARY → ACTIVATE → ROLLBACK → CLOSE`

and verifies:

- rollback is accepted only from a rollback-eligible deployment phase;
- rollback emits a durable audit event;
- deployment risk becomes exactly zero;
- trading is no longer allowed after rollback;
- the audit chain remains valid after rollback;
- the terminal close preserves zero residual risk;
- the resulting evidence is explicitly classified `source_kind=INTERNAL`.

The drill does not use real credentials, network I/O, or production infrastructure.
It therefore does not close the external §185 rollback evidence requirement.
`production_ready = FALSE` remains mandatory.
