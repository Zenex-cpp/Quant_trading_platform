from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest
from trading_platform.v30.truth import AxisSnapshot, TruthComponent, TruthStatus, build_truth
from trading_platform.v32.capability import CapabilityAuthority, CapabilityError

NOW=datetime(2026,9,13,tzinfo=timezone.utc)
AX=AxisSnapshot("ACTIVE","LIVE","HEALTHY","APPROVED","ACTIVE","CHAMPION")
def caps(v="100"): return {k:Decimal(v) for k in ("health_cap","deployment_cap","accounting_cap","reconciliation_cap","provenance_cap","operator_cap")}
def truth(status=TruthStatus.VERIFIED):
    cs=tuple(TruthComponent(n,status,"OK") for n in ("health","provenance","governance","reconciliation","accounting","ledger"))
    return build_truth(observed_at_ns=1,axes=AX,components=cs,requested_risk=Decimal("100"),caps=caps())
def payload(): return {"intent_id":"I1","decision_id":"D1","risk_decision_id":"R1","symbol":"BTCUSDT","side":"BUY","action":"OPEN","quantity":"0.001","order_type":"MARKET","price":None,"execution_version":"E1"}

def test_issue_and_one_shot_consume():
    ca=CapabilityAuthority(); c=ca.issue(truth=truth(),requested_risk=Decimal("10"),decision_id="D1",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    used=ca.consume(c,now=NOW,truth=truth(),intent_payload=payload()); assert used.consumed
    with pytest.raises(CapabilityError, match="CAPABILITY_ALREADY_CONSUMED"): ca.consume(c,now=NOW,truth=truth(),intent_payload=payload())

def test_hash_change_blocks():
    ca=CapabilityAuthority(); c=ca.issue(truth=truth(),requested_risk=Decimal("10"),decision_id="D1",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    with pytest.raises(CapabilityError, match="TRUTH_HASH_CHANGED"): ca.consume(c,now=NOW,truth=truth(TruthStatus.DEGRADED),intent_payload=payload())

def test_intent_change_blocks():
    ca=CapabilityAuthority(); c=ca.issue(truth=truth(),requested_risk=Decimal("10"),decision_id="D1",intent_payload=payload(),expires_at=NOW+timedelta(seconds=10))
    p=payload(); p["quantity"]="0.002"
    with pytest.raises(CapabilityError, match="INTENT_FINGERPRINT_MISMATCH"): ca.consume(c,now=NOW,truth=truth(),intent_payload=p)

def test_expired_blocks():
    ca=CapabilityAuthority(); c=ca.issue(truth=truth(),requested_risk=Decimal("10"),decision_id="D1",intent_payload=payload(),expires_at=NOW)
    with pytest.raises(CapabilityError, match="CAPABILITY_EXPIRED"): ca.consume(c,now=NOW,truth=truth(),intent_payload=payload())
