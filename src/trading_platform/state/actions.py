from .compatibility import OrthogonalState
from .enums import *

NEW_RISK_ACTIONS = {"OPEN", "INCREASE"}


def action_decision(state: OrthogonalState, action: str, *, guards_pass: bool = True) -> Decision:
    if action in NEW_RISK_ACTIONS:
        if not guards_pass:
            return Decision.BLOCK
        if state.mode == OperationalMode.CLOSING_ONLY:
            return Decision.BLOCK
        if state.health in {Health.FAILED, Health.FROZEN}:
            return Decision.BLOCK
        if state.mode == OperationalMode.LIVE and state.approval != Approval.APPROVED:
            return Decision.BLOCK
    if action == "RETRAIN" and state.mode == OperationalMode.LIVE:
        return Decision.CONDITIONAL
    if action == "DEPLOY" and (state.approval != Approval.APPROVED or state.health == Health.FAILED):
        return Decision.BLOCK
    if action == "ROLLBACK":
        return Decision.ALLOW
    if action in {"CLOSE", "DECREASE", "CANCEL", "RECONCILE"}:
        return Decision.ALLOW if guards_pass else Decision.CONDITIONAL
    return Decision.ALLOW if guards_pass else Decision.BLOCK
