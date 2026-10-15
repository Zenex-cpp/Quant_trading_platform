# Trading Platform V2.3 — Release Notes

## Focus
Recovery deterministico dei gap tramite snapshot REST verificato + replay contiguo degli eventi successivi + prova di equivalenza dello stato finale.

## Added
- `trading_platform.v23.recovery.RestSnapshot` con `source_hash` verificabile
- `GapRecoveryCoordinator` fail-closed
- controllo che lo snapshot non sia ahead del ledger
- controllo di contiguità e hash-link del suffix post-snapshot
- replay deterministico del suffix sopra lo stato REST
- confronto opzionale con `target_state` e hash finale esatto
- `RecoveryResult` con stato `BLOCKED`/`VERIFIED`, range di replay e `trading_allowed`
- `RecoveryProof` per audit esplicito di chain, contiguità ed exact match

## Safety properties
- Ledger chain invalid -> recovery blocked.
- Snapshot tampered/invalid -> recovery blocked.
- Snapshot ahead of ledger -> recovery blocked.
- Suffix non-contiguo -> recovery blocked.
- Stato ricostruito diverso dal target -> recovery blocked.
- Solo una recovery `VERIFIED` abilita il passaggio `require_verified()`.
- Nessuna credenziale o rete reale è necessaria per la suite.

## Verification
`161 passed`

## Live status
Nessuna mutazione live eseguita. Nessuna credenziale usata. Production readiness rimane `FALSE`.
