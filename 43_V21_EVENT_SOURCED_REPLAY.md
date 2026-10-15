# V2.1 — Event-sourced ledger, deterministic replay, temporal integrity

V2.1 chiude il passaggio da riconciliazione puntuale a integrità temporale.

Il ledger è append-only, idempotente per `event_id` e protetto da una catena SHA-256 (`GENESIS -> event_n`). La proiezione accounting è ricostruibile esclusivamente dagli eventi; non viene mantenuto uno stato “autorevole” separato che possa divergere dal log.

Il replay verifica prima la catena e poi ricostruisce cash, posizioni, average entry, realized P&L e fee. La stessa sequenza deve produrre lo stesso `state_hash`.

La temporal integrity distingue `CONTIGUOUS`, `GAP_SUSPECTED` e `RECOVERY_REQUIRED`. Un gap non è trattato come un semplice warning: fino a recovery e successiva riconciliazione REST↔WebSocket↔ledger, il trading rimane bloccato.

La riconciliazione temporale richiede tre viste coerenti: REST snapshot, stream snapshot e ledger projection. `VERIFIED` è l'unico stato che autorizza il trading. Stream unhealthy e gap producono rispettivamente `UNKNOWN` e `RECOVERY_REQUIRED`.

Riferimento operativo Binance: la documentazione USDⓈ-M descrive `ACCOUNT_UPDATE`, `ORDER_TRADE_UPDATE` e `listenKeyExpired`, con ordinamento dei messaggi user-data per singola connessione e necessità di mantenere il flusso attivo. Questa versione tratta tali eventi come input a un ledger temporale, non come verità sostitutiva della riconciliazione completa. 
