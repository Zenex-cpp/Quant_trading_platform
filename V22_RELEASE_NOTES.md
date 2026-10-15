# Trading Platform V2.2 — Release Notes

## Focus
Checkpoint atomici, replay incrementale da checkpoint, verifica dell'ancora hash e recovery fail-closed.

## Added
- `trading_platform.v22.checkpoint.CheckpointStore`
- `LedgerCheckpoint` con anchor su `event_sequence` + `event_hash` e `state_hash`
- verifica anti-tampering del checkpoint persistito
- `IncrementalReplayer` con modalità `INCREMENTAL` quando il checkpoint è valido
- fallback `FULL` solo quando non esiste un checkpoint
- blocco esplicito `CHECKPOINT_INVALID` quando un checkpoint presente non è verificabile
- test di equivalenza replay incrementale vs replay completo

## Safety properties
- La hash chain del ledger V2.1 rimane prerequisito del replay.
- Un checkpoint non verificabile non viene utilizzato.
- Nessun percorso V2.2 abilita ordini o modifica la policy di produzione.
- Nessuna credenziale o rete reale è necessaria per la suite di test.

## Verification
`156 passed`

## Live status
Nessuna verifica live è stata eseguita in questa release. Production readiness rimane `FALSE`.
