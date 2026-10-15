# Trading Platform V3.7 — Release Notes

Date: 2026-09-13

## Scope

V3.7 porta il user-data stream da un semplice normalizzatore a un runtime operativo durevole e fail-closed:

`Stream session → durable journal/checkpoint → ORDER_TRADE_UPDATE → correlation → accounting evidence`

con riconnessione e recovery espliciti:

`DISCONNECT / EXPIRY / ORDER-EVENT-OUT-OF-ORDER → RECOVERING → REST reconciliation proof → ACTIVE`

## Added

- SQLite durable journal per user-stream event evidence, dedupe e checkpoint per event type.
- Persistenza della sessione operativa senza persistenza di credenziali o socket state.
- State machine `NEW → ACTIVE → RECONNECTING → RECOVERING → ACTIVE/BLOCKED` con `EXPIRED` e `CLOSED`.
- Reconnect come transizione non-trading: una nuova connessione non riabilita il trading finché la riconciliazione non è verificata.
- `listenKeyExpired` come evento distinto dalla disconnessione; entrambe le condizioni bloccano il trading fino al recovery.
- Keepalive success path con aggiornamento del listen key runtime senza conservarne la semantica come credential store.
- Ordering guard persistente usando `(T, E)` per lo stesso event type, coerente con la garanzia Binance verificata.
- Recovery assessment che richiede contemporaneamente coerenza ordini, posizioni e accounting per riabilitare il trading.
- Recovery callback tipizzato con causa esplicita (`DISCONNECT`, `LISTEN_KEY_EXPIRED`, `ORDER_EVENT_OUT_OF_ORDER`, ecc.).
- Dedupe cross-restart tramite hash canonico del payload persistito.

## Safety rules

1. Un disconnect non può lasciare `trading_allowed=True`.
2. Una nuova connessione entra in `RECOVERING`, non direttamente in `ACTIVE`.
3. Un recovery parziale o con mismatch porta a `BLOCKED`.
4. Un evento out-of-order non viene applicato allo stato operativo e apre recovery.
5. Nessun retry POST viene introdotto: l'ambiguità esecutiva resta gestita da V3.6 tramite query di riconciliazione.
6. Il runtime non crea fill sintetici da soli status REST.

## Binance reference validation

La documentazione corrente Binance USDⓈ-M User Data Streams verifica che il flusso WebSocket user-data usi `userDataStream.start`/`userDataStream.ping`, che il listen key scada dopo 60 minuti senza keepalive e che il ping serva a estenderne la validità. La stessa documentazione richiede API key per queste operazioni. Questi dettagli restano confinati al boundary adapter e non vengono importati nel core venue-agnostic.

Il contratto V3.7 non assume un sequence number Binance che non sia documentato: per lo stesso tipo di evento sulla stessa connessione utilizza quindi l'ordering `T/E` verificato e, dopo reconnect/disconnect, impone una riconciliazione esplicita prima di riabilitare il trading.

## Verification

- Full test suite: **262 passed**
- Tarball extraction test: **PASS**
- Live exchange execution: **NOT RUN**
- Credentials: **NONE**
- Production readiness: **FALSE**
