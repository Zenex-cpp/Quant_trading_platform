from datetime import datetime, timedelta

from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState
from trading_platform.v340.reconciliation_authority import ReconciliationAuthorityLedger


def green_reconciliation(store, *, now: datetime, authorization_id: str = "RECON-GREEN", scope_id: str = "PRODUCTION", case_id: str = "CASE-GREEN", rest_hash: str = "REST-GREEN", stream_hash: str = "STREAM-GREEN"):
    result = ReconciliationResult(
        state=ReconciliationState.GREEN,
        diff=ReconciliationDiff(),
        rest_hash=rest_hash,
        stream_hash=stream_hash,
        reason="REST_WS_MATCH",
    )
    return ReconciliationAuthorityLedger(store).record_result(
        authorization_id=authorization_id,
        scope_id=scope_id,
        case_id=case_id,
        result=result,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
        observed_at_ms=int(now.timestamp() * 1000),
        operator="reconciler",
    )[0]


def red_reconciliation(store, *, now: datetime, authorization_id: str = "RECON-RED", scope_id: str = "PRODUCTION", case_id: str = "CASE-RED"):
    result = ReconciliationResult(
        state=ReconciliationState.RED,
        diff=ReconciliationDiff(quantity_mismatches=("ORDER-1",)),
        rest_hash="REST-RED",
        stream_hash="STREAM-RED",
        reason="REST_WS_DIVERGENCE",
    )
    return ReconciliationAuthorityLedger(store).record_result(
        authorization_id=authorization_id,
        scope_id=scope_id,
        case_id=case_id,
        result=result,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
        observed_at_ms=int(now.timestamp() * 1000),
        operator="reconciler",
    )[0]
