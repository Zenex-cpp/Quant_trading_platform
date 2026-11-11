# M22 remediation — source-bound order-book liquidity risk

**Status: `TESTED`; not `VERIFIED` or production-ready.**

## Implemented

- `LiquidityAssessment` derives stress from a synchronized two-sided order book and the exact proposed order. It records visible side depth, depth utilization, quoted spread, side-aware execution VWAP and estimated market impact. The score is the bounded maximum of depth utilization and the configured spread/impact ratios; insufficient visible depth is rejected.
- The assessment fingerprint binds the market-data evidence ID, snapshot sequence and levels, symbol, side, quantity, limits, computed metrics and validity window. Payload replay recomputes the metrics and rejects altered derived fields.
- Runtime authority derives the liquidity score from the assessment and rejects scalar-only or source-unbound values. The registered conservative-linear risk factor cannot increase allowed risk as stress rises.
- Execution routing and one-shot capabilities bind the assessment to the exact intent and freshness window. Durable risk decisions persist and replay the assessment and revalidate its fingerprint and expiry. The final dispatch guard checks the same market-data authority record, source fingerprint, sequence and order immediately before transport.
- Focused verification across M22, the combined M21/M22/M23 risk path and final dispatch: **38 passed**. Fixtures use synthetic order books and market-data records.

## Remaining evidence

- The `verified=True` bootstrap value is an application input, not an authenticated feed signature or independent attestation.
- No production venue depth adapter, authenticated live feed evidence or commercially licensed order-book dataset is present in the project.
- Spread and impact limits, depth levels, freshness TTL and the linear mapping require calibration against real market data and independent review. The implementation is not evidence that those thresholds are profitable or safe for a particular venue, symbol or order size.

M22 therefore remains `TESTED`. `external_evidence=false`, `production_ready=false` and `activation_flag=NOT_SET` remain in force.
