from __future__ import annotations
from enum import Enum

class Capability(str, Enum):
    RESEARCH="RESEARCH"
    TRAINING="TRAINING"
    BACKTEST="BACKTEST"
    SHADOW="SHADOW"
    CANARY="CANARY"
    PRODUCTION_TRADING="PRODUCTION_TRADING"
    DEPLOYMENT="DEPLOYMENT"
    CONFIGURATION="CONFIGURATION"
    SECURITY_ADMIN="SECURITY_ADMIN"

# Research capabilities intentionally exclude production trading/deployment.
RESEARCH_FORBIDDEN={Capability.PRODUCTION_TRADING, Capability.SECURITY_ADMIN}

def assert_capability(role: str, capability: Capability)->None:
    if role.upper()=="RESEARCH" and capability in RESEARCH_FORBIDDEN:
        raise PermissionError("RESEARCH_TO_PRODUCTION_FORBIDDEN")
