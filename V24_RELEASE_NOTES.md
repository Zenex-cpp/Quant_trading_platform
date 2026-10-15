# V2.4 — Deterministic Accounting & P&L Truth

V2.4 estende il ledger con un modello accounting esplicito e machine-checkable.

## Added
- `AccountingSnapshot` con stato canonico e hash SHA-256.
- `CashComponents` per P&L, fee, funding, deposit/withdrawal e altri eventi.
- `PnLView` separando realized/unrealized e cost buckets.
- `PnLReconciliation`: LOCAL ↔ EXCHANGE ↔ RECONSTRUCTED.
- Classificazione `EXPECTED / WARNING / CRITICAL`.
- Invarianti su valori non-finitezza, timestamp e saldi di rischio.
- `PnLLedger` idempotente per-fill con anti-ID-reuse.
- Attribuzione separata di trading fee, funding, execution impact, slippage, market impact e carrying cost.

## Safety
- Divergenza EXCHANGE ↔ RECONSTRUCTED => `CRITICAL` e riconciliazione non valida.
- Valori NaN/+Inf/-Inf => blocco.
- Nessuna chiamata di rete o uso di credenziali nei test.
- Nessun cambiamento alla policy Mainnet/Testnet.

## Verification
- Full regression: **167 passed**.
- Network: non richiesta.
- Credentials: non richieste.
- Live mutation: non eseguita.
- Production readiness: `FALSE`.
