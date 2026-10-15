# V2.2 — Checkpoint e replay incrementale

Il ledger event-sourced resta la fonte autorevole. Un checkpoint è solo una proiezione persistita, ancorata a una sequenza e all'hash dell'evento corrispondente.

Un checkpoint valido richiede simultaneamente:
1. chain del ledger valida;
2. evento di ancoraggio presente;
3. `event_hash` identico;
4. `state_hash` persistito identico al digest del `state_json`.

Quando il checkpoint è valido, il replayer ripristina lo stato e applica soltanto gli eventi successivi (`INCREMENTAL`). Quando non esiste alcun checkpoint utilizza il replay completo (`FULL`). Quando un checkpoint esiste ma non è verificabile, il sistema non lo sostituisce silenziosamente e termina con `CHECKPOINT_INVALID`.

Questo preserva l'integrità della catena e impedisce che un checkpoint corrotto diventi una nuova fonte di verità.
