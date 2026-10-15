from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class DecisionTTL:
    decision_id: str
    created_at: datetime
    valid_from: datetime
    expires_at: datetime
    configuration_version: str
    portfolio_version: str | None = None
    position_version: str | None = None
    reservation_id: str | None = None

    def validate(self, now: datetime) -> None:
        if any(x.tzinfo is None for x in (self.created_at, self.valid_from, self.expires_at, now)):
            raise ValueError("TIMEZONE_AWARENESS_REQUIRED")
        if self.created_at > self.valid_from or self.valid_from >= self.expires_at:
            raise ValueError("INVALID_DECISION_WINDOW")
        if not (self.valid_from <= now < self.expires_at):
            raise ValueError("DECISION_EXPIRED")
