from enum import Enum

class Lifecycle(str, Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"

class OperationalMode(str, Enum):
    RESEARCH = "RESEARCH"
    BACKTEST = "BACKTEST"
    SIMULATION = "SIMULATION"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    LIVE = "LIVE"
    CLOSING_ONLY = "CLOSING_ONLY"

class Health(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    FROZEN = "FROZEN"

class Approval(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"

class Deployment(str, Enum):
    NOT_DEPLOYED = "NOT_DEPLOYED"
    STAGED = "STAGED"
    ACTIVE = "ACTIVE"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"

class Role(str, Enum):
    NONE = "NONE"
    CHALLENGER = "CHALLENGER"
    CHAMPION = "CHAMPION"

class Decision(str, Enum):
    ALLOW = "ALLOW"
    CONDITIONAL = "CONDITIONAL"
    BLOCK = "BLOCK"
