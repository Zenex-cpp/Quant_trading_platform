# Testnet Verification Contract

The execution adapter remains testnet-only unless an explicit environment policy enables another adapter.

Required future evidence:
1. authenticated connectivity without exposing credentials in source/logs;
2. exchange rule snapshot and hash;
3. order placement acknowledgement;
4. cancellation acknowledgement;
5. partial and full fills;
6. unknown-order reconciliation;
7. restart/reconnect behavior;
8. account/position reconciliation;
9. fee/funding accounting reconciliation;
10. failure injection and recovery proof.

No testnet evidence implies live permission.
