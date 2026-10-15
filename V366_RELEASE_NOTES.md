# V3.66 Release Notes

V3.66 strengthens the §186 human-review boundary for controlled LIVE promotion.

The runtime now rejects a LIVE human-review package when any reviewer is also:
- the reviewer that authorized the upstream Promotion Bundle; or
- an identity listed in `Approval.approved_by`.

This is a machine-checkable minimum independence boundary. It does not create or imply real-world independent approval, organizational separation, or actual human sign-off.

Verification:
- full suite: 659/659 PASS;
- collision with upstream Promotion Bundle author: PASS;
- collision with Approval actor: PASS;
- disjoint reviewer: PASS;
- reproducible wheel: PASS, identical SHA-256 across two builds;
- release hygiene: PASS.

`production_ready = FALSE` remains mandatory until external operational evidence and actual human sign-off are present.
