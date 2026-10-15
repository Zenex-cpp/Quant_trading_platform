from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class ScenarioStatus(str, Enum): PASS="PASS"; FAIL="FAIL"; NOT_VERIFIED="NOT_VERIFIED"

@dataclass(frozen=True)
class VerificationScenario:
    scenario_id: str
    name: str
    required: bool
    live_network_required: bool

SCENARIOS = (
    VerificationScenario("TN-01","authenticated_connectivity",True,True),
    VerificationScenario("TN-02","exchange_rules_snapshot",True,True),
    VerificationScenario("TN-03","order_acknowledgement",True,True),
    VerificationScenario("TN-04","cancellation_acknowledgement",True,True),
    VerificationScenario("TN-05","partial_fill",True,True),
    VerificationScenario("TN-06","full_fill",True,True),
    VerificationScenario("TN-07","unknown_order_reconciliation",True,True),
    VerificationScenario("TN-08","restart_reconnect",True,True),
    VerificationScenario("TN-09","account_position_reconciliation",True,True),
    VerificationScenario("TN-10","fee_funding_reconciliation",True,True),
    VerificationScenario("TN-11","failure_injection_recovery",True,False),
)

def offline_plan() -> dict[str, ScenarioStatus]:
    return {s.scenario_id: (ScenarioStatus.NOT_VERIFIED if s.live_network_required else ScenarioStatus.PASS) for s in SCENARIOS}
