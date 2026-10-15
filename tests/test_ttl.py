from datetime import datetime, timezone, timedelta
from trading_platform.core.ttl import ValidWindow

def test_ttl_expires():
    now = datetime.now(timezone.utc)
    w = ValidWindow(now - timedelta(seconds=1), now + timedelta(seconds=1))
    assert w.is_valid(now)
