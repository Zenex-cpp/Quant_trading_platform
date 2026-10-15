# Execution and Accounting Contracts

Execution separates OrderIntent, OrderRequest, ExchangeOrder and Fill.

New-risk guard chain requires:
1. valid position state;
2. fresh market window;
3. fresh upstream decision windows;
4. valid risk decision;
5. valid intent window.

FillLedger de-duplicates by immutable fill_id.
PositionLedger is a derived accounting projection and must be reconciled against venue/account events in later milestones.
