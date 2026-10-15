from datetime import datetime, timedelta, timezone
import pytest
from trading_platform.data_v03 import *

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

def test_pit_rejects_feature_not_yet_available():
    with pytest.raises(ValueError, match="POINT_IN_TIME_LEAKAGE"):
        assert_point_in_time(feature_available_at=T0+timedelta(minutes=2), event_time=T0, prediction_time=T0+timedelta(minutes=1))

def test_pit_accepts_known_information():
    assert_point_in_time(feature_available_at=T0+timedelta(seconds=30), event_time=T0, prediction_time=T0+timedelta(minutes=1))

def test_revision_is_asof_safe():
    d=DataVersion("v1","v2",T0+timedelta(hours=2),T0+timedelta(hours=1))
    assert_as_of_version(data=d, consumer_time=T0+timedelta(hours=1, minutes=1))

def test_future_revision_rejected():
    d=DataVersion("v1","v2",T0+timedelta(hours=2),T0+timedelta(hours=1))
    with pytest.raises(ValueError, match="RETROACTIVE_REVISION_LEAKAGE"):
        assert_as_of_version(data=d, consumer_time=T0+timedelta(minutes=30))

def test_duplicate_scan():
    rows=[{"ts":1,"symbol":"BTCUSDT"},{"ts":1,"symbol":"BTCUSDT"}]
    findings=scan_duplicate_observations(rows,("ts","symbol"))
    assert findings and findings[0].category == "DUPLICATED_OBSERVATION"

def test_out_of_order_rejected():
    rows=[{"event_time":T0+timedelta(seconds=2)},{"event_time":T0+timedelta(seconds=1)}]
    with pytest.raises(ValueError, match="OUT_OF_ORDER_DATA"):
        validate_temporal_order(rows)

def test_dataset_contract_hashes_and_coverage():
    ds=DatasetContract("D1","1","1","CSV","S1",(),"abc","def",T0,T0+timedelta(days=1),QualityStatus.VALID,"ok","retain",datetime(2026,1,1,tzinfo=timezone.utc))
    ds.validate()

def test_unknown_semantics_distinct():
    assert UnknownSemantics.UNKNOWN != UnknownSemantics.NULL
