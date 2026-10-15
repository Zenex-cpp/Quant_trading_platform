# V0.6 — Portfolio, Allocation, Capacity, Turnover & Risk Budget

V0.6 implements the portfolio layer after model/research foundations. Portfolio allocation is downstream of Prediction/Signal/Opportunity and upstream of RiskDecision.

## Hard hierarchy
HARD CONSTRAINTS → FEASIBILITY → SAFETY FILTER → RISK FILTER → DYNAMIC RISK ADJUSTMENT → OPTIMIZATION → RANKING.

Historical return is never a direct allocation rule.

## Allocation candidates
EQUAL_WEIGHT, INVERSE_VOL, RISK_PARITY, VOL_TARGET, MEAN_VARIANCE, CVAR, ROBUST, REGIME_CONDITIONED.

V0.6 implements deterministic primitives for the first two; the remaining methods are registry targets and remain unimplemented until evidence justifies them.

## Capacity
Capacity is constrained by participation and impact budgets. Capacity breaches are hard failures.

## Turnover
Turnover budget, minimum trade threshold and estimated transaction-cost threshold are evaluated before rebalancing.

## Risk budget
Portfolio allocation never increases risk budget. Reservations remain atomic and cannot be consumed twice or reused after release.
