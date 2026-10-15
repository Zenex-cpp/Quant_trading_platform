from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass(frozen=True)
class ValidWindow:
    valid_from: datetime
    expires_at: datetime

    def is_valid(self, now: datetime) -> bool:
        if self.valid_from.tzinfo is None or self.expires_at.tzinfo is None or now.tzinfo is None:
            raise ValueError("all timestamps must be timezone-aware")
        return self.valid_from <= now < self.expires_at

    def assert_valid(self, now: datetime) -> None:
        if not self.is_valid(now):
            raise ValueError("EXPIRED_OR_NOT_YET_VALID")
