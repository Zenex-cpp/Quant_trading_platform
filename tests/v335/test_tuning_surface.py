from datetime import datetime, timezone, timedelta
import pytest
from trading_platform.research.pipeline import SplitSpec, TuningSession
from trading_platform.data.holdout import TuningDataView
from trading_platform.security.credentials import ProductionCredentialAccessError
from trading_platform.v35.binance_execution import RuntimeCredentialValues

UTC=timezone.utc

def t(i): return datetime(2026,1,1,0,i,tzinfo=UTC)

def test_tuning_session_excludes_final_holdout():
    spec=SplitSpec(t(2),t(4),t(6),t(7),t(9),'1h','2h','s1')
    rows=list(range(10))
    session=TuningSession(times=[t(i) for i in range(10)], spec=spec, rows=rows)
    assert session.data.train == (0,1,2)
    assert session.data.validation == (3,4)
    assert session.data.oos == (5,6)
    with pytest.raises(AttributeError, match="FINAL_HOLDOUT_NOT_EXPOSED_TO_TUNING"):
        _=session.data.final_holdout

def test_tuning_session_rejects_holdout_evaluation():
    spec=SplitSpec(t(2),t(4),t(6),t(7),t(9),'1h','2h','s1')
    session=TuningSession(times=[t(i) for i in range(10)], spec=spec, rows=list(range(10)))
    with pytest.raises(PermissionError, match="FINAL_HOLDOUT_TUNING_FORBIDDEN"):
        session.evaluate_split("FINAL_HOLDOUT", lambda _: 1)

def test_direct_tuning_data_view_rejects_runtime_credentials():
    with pytest.raises(ProductionCredentialAccessError, match="VISIBILITY_FORBIDDEN"):
        TuningDataView(
            train=(RuntimeCredentialValues("K", b"S"),),
            validation=(),
            oos=(),
        )
