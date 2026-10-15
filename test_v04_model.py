from datetime import datetime, timezone, timedelta
import pytest
from trading_platform.model.target import TargetSpec, future_return_labels
from trading_platform.model.calibration import calibration_report
from trading_platform.model.uncertainty import bernoulli_entropy, ensemble_dispersion, conservative_risk_factor
from trading_platform.model.contracts import SchemaContract, ModelArtifactContract, Prediction

UTC=timezone.utc

def ts(i): return datetime(2026,1,1,0,i,tzinfo=UTC)

def test_target_label_is_only_available_at_horizon_end():
    spec=TargetSpec('t','1',timedelta(minutes=2),'close','future_close','0bps','forward_return','ALLOW','numeric','DROP')
    labels=future_return_labels([100,101,102,103], [ts(i) for i in range(4)], spec)
    assert labels[0].label_end == ts(2)
    assert labels[0].available_at == ts(2)

def test_target_length_mismatch_blocks():
    spec=TargetSpec('t','1',timedelta(minutes=1),'x','y','0','x','x','x','DROP')
    with pytest.raises(ValueError, match='TARGET_INPUT_LENGTH_MISMATCH'):
        future_return_labels([1,2],[ts(0)],spec)

def test_calibration_report():
    r=calibration_report([.95,.9,.05,.1],[1,1,0,0])
    assert r.sample_size==4 and r.state=='CALIBRATED'

def test_uncertainty_monotonicity():
    low=conservative_risk_factor(.1)
    high=conservative_risk_factor(.8)
    assert high <= low

def test_uncertainty_primitives():
    assert bernoulli_entropy(.5) > bernoulli_entropy(.99)
    assert ensemble_dispersion([1,1,1]) == 0

def test_artifact_preload_rejects_hash():
    s1=SchemaContract('features','1',('x',))
    s2=SchemaContract('output','1',('p',))
    m=ModelArtifactContract('m','1','good',s1,s2,'f1','py','deps','cfg')
    with pytest.raises(ValueError, match='ARTIFACT_INTEGRITY_FAILURE'):
        m.pre_load_validate(actual_hash='bad',feature_version='f1',runtime_compatibility='py',dependency_compatibility='deps',configuration_compatibility='cfg')

def test_prediction_ttl_and_timezone():
    p=Prediction('p','m','1',ts(0),'f1','t1',.5,.5,None,None,.1,'ACCEPTABLE',ts(0),ts(1))
    p.validate()
