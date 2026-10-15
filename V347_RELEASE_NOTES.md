# V3.47 Release Notes

## M20 — No risk reservation double consumption

V3.47 chiude il race condition tra terminal transitions della stessa risk reservation.

`EventStore.append_exclusive()` usa una transazione SQLite `BEGIN IMMEDIATE` per rendere atomici il controllo dello stato terminale e l'append. `DurableRiskReservationBook.consume/release/expire/override` usano ora la stessa primitive e rendono mutuamente esclusive le quattro terminal transitions.

Quindi due writer concorrenti non possono più produrre una combinazione `CONSUMED + RELEASED`, `CONSUMED + EXPIRED`, `CONSUMED + OVERRIDDEN` o due `CONSUMED` per la stessa reservation. Un retry dello stesso `event_id` resta idempotente; un diverso terminal event perde la race in modo fail-closed.
