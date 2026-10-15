# V2.4 Accounting / P&L

Il modello V2.4 applica la specifica: `LOCAL P&L ↔ EXCHANGE P&L ↔ RECONSTRUCTED P&L`.

Ogni snapshot è canonico e hashabile. La riconciliazione distingue:
- `EXPECTED`: le tre viste sono entro tolleranza;
- `WARNING`: la vista locale diverge, mentre exchange e reconstructed concordano;
- `CRITICAL`: exchange e reconstructed divergono.

I costi sono mantenuti separati: `trading_fee`, `funding`, `execution_impact`, `slippage`, `market_impact`, `carrying_cost`.

La distinzione è intenzionale: non comprimere costi ed effetti di execution in un unico numero evita di perdere la spiegabilità del P&L.
