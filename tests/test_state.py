from trading_platform.state import *

def test_experimental_live_invalid():
    s = OrthogonalState(Lifecycle.EXPERIMENTAL, OperationalMode.LIVE, Health.HEALTHY, Approval.APPROVED, Deployment.ACTIVE, Role.CHALLENGER)
    ok, _ = validate_state(s)
    assert not ok

def test_approved_live_champion_valid():
    s = OrthogonalState(Lifecycle.APPROVED, OperationalMode.LIVE, Health.HEALTHY, Approval.APPROVED, Deployment.ACTIVE, Role.CHAMPION)
    ok, errors = validate_state(s)
    assert ok, errors

def test_closing_only_blocks_entry():
    s = OrthogonalState(Lifecycle.APPROVED, OperationalMode.CLOSING_ONLY, Health.HEALTHY, Approval.APPROVED, Deployment.ACTIVE, Role.CHAMPION)
    assert action_decision(s, "OPEN") == Decision.BLOCK
    assert action_decision(s, "CLOSE") == Decision.ALLOW
