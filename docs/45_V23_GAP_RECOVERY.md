# V2.3 — Gap Recovery Contract

La recovery segue questa sequenza obbligatoria:

1. Verifica della hash-chain del ledger.
2. Verifica crittografica dello snapshot REST.
3. Verifica che `snapshot.last_event_sequence <= latest_sequence`.
4. Identificazione del suffix `snapshot_sequence + 1 ... latest_sequence`.
5. Verifica della contiguità delle sequence e dei `prev_hash`.
6. Replay deterministico del suffix sopra lo stato dello snapshot.
7. Se disponibile, confronto esatto dello stato ricostruito con il `target_state`.
8. Solo se tutto passa: `RecoveryState.VERIFIED` e `trading_allowed=True`.

Qualunque failure produce `BLOCKED`; non è previsto un fallback silenzioso a dati non verificati.
