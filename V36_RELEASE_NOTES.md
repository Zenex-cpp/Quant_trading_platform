# Trading Platform V3.6 — Release Notes

## Scope
V3.6 estende il boundary V3.5 Binance USDⓈ-M Testnet con correlazione completa tra ordine locale e osservazioni exchange:

`clientOrderId ↔ intent_id ↔ exchangeOrderId ↔ ORDER_TRADE_UPDATE ↔ Fill`

## Added
- Parsing del payload Binance `ORDER_TRADE_UPDATE` con estrazione di client order id, exchange order id, execution type, order status, trade id, last fill quantity/price, cumulative quantity e commission.
- Correlazione bidirezionale `clientOrderId` / `exchangeOrderId` verso l'intent locale.
- Protezione fail-closed contro conflitti di correlazione.
- Deduplica degli update utente e dei trade tramite chiave stabile.
- Generazione di `Fill` da `executionType=TRADE` senza sintetizzare fill da solo stato REST.
- Helper di submit con comportamento `one POST -> on ambiguity one GET reconciliation`, senza retry automatico del POST.
- Reconciliation REST conservativa: `FILLED` resta `UNKNOWN` quando la quantità eseguita REST supera i fill contabili già osservati; il sistema richiede evidenza trade-level dal user stream.
- Estensione del lifecycle per consentire osservazioni dirette `SUBMITTED -> PARTIALLY_FILLED/FILLED` quando il user stream fornisce il primo evento utile.

## Corrective change
- `UnknownOrderResolver.resolve()` ora ha una risoluzione predefinita coerente con i call-site esistenti.
- Il bridge espone un controllo separato per distinguere un case `UNKNOWN` aperto da un retry cieco.

## Safety boundary
- Il package continua a operare sul solo environment `TESTNET`.
- Nessuna credenziale è inclusa nei sorgenti o negli artifact.
- Nessuna chiamata exchange reale è stata eseguita durante la verifica.
- `production_ready = FALSE`.

## Evidence
La struttura `ORDER_TRADE_UPDATE` e i campi di ordine/trade sono allineati alla documentazione Binance user-data stream verificata durante l'implementazione. La documentazione corrente specifica ordering per gli eventi dello stesso tipo e raccomanda il WebSocket user-data stream per ordini e posizioni. 
