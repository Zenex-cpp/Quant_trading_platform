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
    assert r.sample_size==4 and r.state=='UNKNOWN'
    assert r.calibration_drift is None


def test_calibration_report_tracks_reliability_and_reference_drift():
    probabilities = [.02] * 15 + [.98] * 15
    outcomes = [0] * 15 + [1] * 15
    r=calibration_report(
        probabilities, outcomes, source_id='window-current',
        reference_probabilities=probabilities, reference_outcomes=outcomes,
        reference_source_id='window-reference',
    )
    assert r.sample_size==30 and r.reference_sample_size==30
    assert r.state=='CALIBRATED'
    assert r.calibration_drift==0
    assert sum(item.sample_count for item in r.reliability)==30


def test_calibration_report_distinguishes_acceptable_and_poor():
    probabilities = [.5] * 30
    outcomes = [0, 1] * 15
    acceptable = calibration_report(
        probabilities, outcomes, source_id='current-acceptable',
        reference_probabilities=probabilities, reference_outcomes=outcomes,
        reference_source_id='reference-acceptable',
    )
    assert acceptable.state=='ACCEPTABLE'

    poor_probabilities = [.9] * 30
    poor_outcomes = [0] * 30
    poor = calibration_report(
        poor_probabilities, poor_outcomes, source_id='current-poor',
        reference_probabilities=poor_probabilities, reference_outcomes=poor_outcomes,
        reference_source_id='reference-poor',
    )
    assert poor.state=='POOR'


def test_calibration_rejects_nonprobabilities_and_invalid_outcomes():
    with pytest.raises(ValueError, match='CALIBRATION_INPUT_INVALID'):
        calibration_report([1.1, .2], [1, 0])
    with pytest.raises(ValueError, match='CALIBRATION_INPUT_INVALID'):
        calibration_report([.1, .2], [1, 2])

def test_uncertainty_monotonicity():
    low=conservative_risk_factor(.1)
    high=conservative_risk_factor(.8)
    assert high <= low

def test_uncertainty_primitives():
    assert bernoulli_entropy(.5) > bernoulli_entropy(.99)
    assert bernoulli_entropy(.5) == 1
    assert ensemble_dispersion([0, 1]) == .25
    assert ensemble_dispersion([1,1,1]) == 0
    with pytest.raises(ValueError, match='INVALID_ENSEMBLE_PROBABILITY'):
        ensemble_dispersion([.2, 1.1])

def test_artifact_preload_rejects_hash():
    s1=SchemaContract('features','1',('x',))
    s2=SchemaContract('output','1',('p',))
    m=ModelArtifactContract('m','1','good',s1,s2,'f1','py','deps','cfg')
    with pytest.raises(ValueError, match='ARTIFACT_INTEGRITY_FAILURE'):
        m.pre_load_validate(actual_hash='bad',feature_version='f1',runtime_compatibility='py',dependency_compatibility='deps',configuration_compatibility='cfg')

def test_prediction_ttl_and_timezone():
    p=Prediction('p','m','1',ts(0),'f1','t1',.5,.5,None,None,.1,'ACCEPTABLE',ts(0),ts(1))
    p.validate()
