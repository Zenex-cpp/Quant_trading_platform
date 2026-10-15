# V3.78 Release Notes

## Scope

V3.78 closes the next §86 execution-simulation gap on the verified v3.77 base:
order-book depth, conservative queue-position estimation, maker/taker fee
semantics, time-in-force behavior, and selected Binance USDⓈ-M rejection codes.
Historical v3.73-v3.77 implementations remain immutable.

## Implemented

- Multi-level order-book consumption for market and marketable limit orders.
- GTC resting orders with explicit displayed queue-ahead quantity.
- Deterministic queue advancement using explicit aggressor trade prints at the
  resting price.
- Maker/taker fee separation.
- GTC / IOC / FOK / GTX semantics.
- Binance-style GTX rejection code `-5022` and FOK rejection code `-5021`.
- Fail-closed RPI behavior because RPI liquidity is separate from ordinary L2
  order-book liquidity in the current Binance reference.
- Order-book update-id monotonicity guard.
- State hashing over fills, rejections, cancellations, open orders, ledger,
  execution model, queue model and seed.

## Explicit limitations

- Queue position is `PRICE_TIME_L2_V1`, a conservative approximation rather
  than exact exchange queue reconstruction.
- L2 cancellations/reorders and hidden liquidity are not inferred as queue
  advancement.
- RPI liquidity is not modeled.
- Actual Binance maker/taker rates are configuration references, not hard-coded
  economic truth.
- This is a backtest/simulation engine; it does not claim live-exchange parity.
- `production_ready = FALSE`.

## Master Prompt alignment

- §86 execution model: expanded with depth, queue, fees, latency boundary and
  venue semantics.
- §87 simulation assumptions remain explicit and versioned.
- §89 determinism is `EXACT` for this model.
- §90 venue-specific assumptions remain confined to the v3.78 simulation
  module and registry.
- §160/158 provenance and reproducibility are preserved through configuration,
  queue-model version, seed, external-reference record and state hash.
