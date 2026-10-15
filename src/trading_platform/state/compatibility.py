from dataclasses import dataclass
from .enums import *

@dataclass(frozen=True)
class OrthogonalState:
    lifecycle: Lifecycle
    mode: OperationalMode
    health: Health
    approval: Approval
    deployment: Deployment
    role: Role

def validate_state(s: OrthogonalState) -> tuple[bool, tuple[str, ...]]:
    errors=[]
    operational={OperationalMode.SHADOW,OperationalMode.CANARY,OperationalMode.LIVE,OperationalMode.CLOSING_ONLY}
    if s.lifecycle == Lifecycle.EXPERIMENTAL and s.mode in operational: errors.append("EXPERIMENTAL cannot be operational")
    if s.lifecycle == Lifecycle.RETIRED and s.mode in operational: errors.append("RETIRED cannot be operational")
    if s.health == Health.FAILED and s.mode in operational: errors.append("FAILED health blocks operational mode")
    if s.mode in {OperationalMode.CANARY,OperationalMode.LIVE,OperationalMode.CLOSING_ONLY} and s.approval != Approval.APPROVED: errors.append("approval must be APPROVED for controlled/live operation")
    if s.mode in {OperationalMode.CANARY,OperationalMode.LIVE,OperationalMode.CLOSING_ONLY} and s.deployment != Deployment.ACTIVE: errors.append("controlled/live operation requires ACTIVE deployment")
    if s.role == Role.CHAMPION and s.deployment == Deployment.NOT_DEPLOYED: errors.append("CHAMPION cannot be NOT_DEPLOYED")
    if s.mode == OperationalMode.SHADOW and s.role == Role.CHAMPION: errors.append("SHADOW reserved for challengers")
    if s.role == Role.CHALLENGER and s.mode == OperationalMode.LIVE: errors.append("CHALLENGER cannot be LIVE")
    return not errors, tuple(errors)
