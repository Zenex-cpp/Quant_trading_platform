from datetime import datetime, timezone, timedelta
import numpy as np
import pytest
from sklearn.linear_model import LogisticRegression
from trading_platform.research.pipeline import SplitSpec, chronological_split, assert_no_holdout_in_tuning, ExperimentSpec, fit_on_train_only
from trading_platform.validation.robustness import evaluate_degradation
from trading_platform.validation.adversarial import AdversarialFinding, require_all_checks
from trading_platform.research.multiple_testing import ExperimentRecord, summarize_family

UTC=timezone.utc

def t(i): return datetime(2026,1,1,0,i,tzinfo=UTC)

def spec(): return SplitSpec(t(2),t(4),t(6),t(7),t(9),'1h','2h','s1')

def test_temporal_split_is_disjoint():
    out=chronological_split([t(i) for i in range(10)],spec())
    sets=[set(v.tolist()) for k,v in out.items()]
    assert len(set.union(*sets))==10
    assert sum(len(s) for s in sets)==10

def test_holdout_tuning_forbidden():
    with pytest.raises(PermissionError, match='FINAL_HOLDOUT_TUNING_FORBIDDEN'):
        assert_no_holdout_in_tuning('FINAL_HOLDOUT')

def test_experiment_fingerprint_stable():
    e=ExperimentSpec('e1','f1','d1','feat1','t1','m1','1','s1',0,'c1','cfg1')
    assert e.fingerprint()==e.fingerprint()

def test_fit_only_train():
    X=np.array([[0],[1],[2],[3]])
    y=np.array([0,1,0,1])
    m=fit_on_train_only(LogisticRegression(),X,y,[0,1])
    assert m.classes_.tolist()==[0,1]
    assert len(m.coef_.ravel())==1

def test_robustness_degradation():
    r=evaluate_degradation(.10,.06,.05,'cost_stress')
    assert r.passed is True and r.degradation==pytest.approx(.04)

def test_adversarial_requires_all_categories():
    fs=[AdversarialFinding(str(i),c,'HIGH','f','e','r') for i,c in enumerate((
        'LEAKAGE','OVERFIT','FRAGILE_PARAMETERS','REGIME_DEPENDENCE','COST_DEPENDENCE','CAPACITY','LUCKY_SEQUENCE','SUSPICIOUS_FEATURE_DEPENDENCE','TEMPORAL_INSTABILITY'))]
    require_all_checks(fs)

def test_research_family_summary():
    rs=[ExperimentRecord('e1','f','FAILED',False,'v1','d','x','t','1','r1'), ExperimentRecord('e2','f','PASS',True,'v2','d','x','t','1','r2')]
    s=summarize_family(rs,'f')
    assert (s.total_experiments,s.failed,s.selected,s.discarded)==(2,1,1,1)
