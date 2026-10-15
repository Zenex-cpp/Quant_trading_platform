# V3.16 — Accounting Gate

## Purpose
Rendere l'Accounting State una condizione machine-checkable del confine finale di dispatch per il nuovo rischio.

## States
- `UNRECONCILED`: replay disponibile ma non ancora riconciliato; nuovo rischio bloccato.
- `RECONCILED`: riconciliazione supportata da evidence; nuovo rischio consentito salvo altri guard.
- `ADJUSTED`: adjustment supportato da evidence; nuovo rischio consentito salvo altri guard.
- `UNKNOWN`: verità contabile non determinata; nuovo rischio bloccato.

## Invariants
1. Il replay non concede da solo trading permission.
2. Un nuovo accounting event invalida la riconciliazione precedente.
3. `UNKNOWN` e `UNRECONCILED` sono fail-closed per il rischio crescente.
4. Il gateway non viene chiamato quando il gate contabile nega.
5. Nessun credential o network state è persistito dal nuovo layer.

## Evidence
- `tests/v316/test_accounting_gate.py`
- `tests/v311/test_dispatch_guard.py`
- full regression: 310 passed
