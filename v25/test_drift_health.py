from decimal import Decimal
import pytest
from trading_platform.v25.drift import DetectorConfig, MeanShiftDetector, PopulationStabilityDetector, DriftSeverity, DriftReport, detector_fingerprint, DriftMetric
from trading_platform.v25.health import EvidenceFreshness, HealthState, assess_health
from trading_platform.v25.freeze import FreezeController, FreezeState

CFG = DetectorConfig("psi", "1.0.0", Decimal("0.1"), Decimal("0.25"), min_observations=5)

def test_mean_shift_stable():
    d=MeanShiftDetector(CFG)
    r=d.compare("x", [Decimal("1"),Decimal("1")], [Decimal("1.01"),Decimal("0.99"),Decimal("1")])
    assert r.severity is DriftSeverity.NONE

def test_mean_shift_critical_and_missingness():
    d=MeanShiftDetector(CFG)
    r=d.compare("x", [Decimal("1")]*5, [Decimal("2")]*5)
    assert r.severity is DriftSeverity.CRITICAL
    r=d.compare("x", [Decimal("1")]*5, [Decimal("1")]*5, missing_rate=Decimal("0.2"))
    assert r.severity is DriftSeverity.CRITICAL and r.reason == "MISSINGNESS_CRITICAL"

def test_psi_detects_distribution_change():
    d=PopulationStabilityDetector(CFG)
    r=d.compare("x", [Decimal(i) for i in range(10)], [Decimal("0")]*10)
    assert r.score > 0

def test_insufficient_observations_is_critical():
    d=PopulationStabilityDetector(CFG)
    r=d.compare("x", [Decimal("1")]*10, [Decimal("1")])
    assert r.severity is DriftSeverity.CRITICAL


def test_detector_fingerprint_is_order_stable():
    c2=DetectorConfig("mean","1.0.0",Decimal("0.1"),Decimal("0.2"))
    assert detector_fingerprint([CFG,c2]) == detector_fingerprint([c2,CFG])

def test_evidence_ttl():
    e=EvidenceFreshness("e",100,10)
    assert e.valid_at(110)
    assert not e.valid_at(111)
    assert not EvidenceFreshness("e",100,10,verified=False).valid_at(105)

def test_health_expires_and_blocks():
    e=EvidenceFreshness("e",100,10)
    h=assess_health(assessment_id="a", now_ns=111, evidence=e, drift_critical=False)
    assert h.state is HealthState.BLOCKED
    assert not h.trading_allowed

def test_health_unknown_without_evidence():
    h=assess_health(assessment_id="a", now_ns=1, evidence=None, drift_critical=False)
    assert h.state is HealthState.UNKNOWN


def test_freeze_on_critical_drift():
    m=DriftMetric("x",Decimal("1"),Decimal("2"),Decimal("1"),DriftSeverity.CRITICAL,10)
    report=DriftReport("r",1,(m,),"fp")
    h=assess_health(assessment_id="a", now_ns=100, evidence=EvidenceFreshness("e",100,100), drift_critical=True)
    dec=FreezeController().evaluate(report=report,health=h,current_risk_cap="25")
    assert dec.state is FreezeState.FROZEN and dec.risk_cap == "0"
    with pytest.raises(PermissionError, match="TRADING_FROZEN"):
        FreezeController().require_active(dec)
