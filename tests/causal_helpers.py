from datetime import datetime, timezone

from trading_platform.v21.event_store import EventStore
from trading_platform.v333 import CausalArtifactState, CausalArtifactType, CausalTTLAuthorityLedger
from trading_platform.execution.models import OrderIntent


def causal_authority_for_intent(intent: OrderIntent, *, store=None) -> CausalTTLAuthorityLedger:
    ledger = CausalTTLAuthorityLedger(store or EventStore())
    vf = int(intent.window.valid_from.timestamp() * 1000)
    ex = int(intent.window.expires_at.timestamp() * 1000)
    record_at = vf
    prediction_id = f"{intent.intent_id}:prediction"
    signal_id = f"{intent.intent_id}:signal"
    opportunity_id = f"{intent.intent_id}:opportunity"
    portfolio_id = intent.portfolio_decision_id
    risk_id = intent.risk_decision_id
    ledger.record_artifact(
        artifact_id=prediction_id, artifact_type=CausalArtifactType.PREDICTION,
        version="test", state=CausalArtifactState.VALID,
        valid_from_ms=vf, expires_at_ms=ex, recorded_at_ms=record_at,
    )
    ledger.record_artifact(
        artifact_id=signal_id, artifact_type=CausalArtifactType.SIGNAL,
        version="test", state=CausalArtifactState.VALID,
        valid_from_ms=vf, expires_at_ms=ex,
        dependencies=(prediction_id,), recorded_at_ms=record_at,
    )
    ledger.record_artifact(
        artifact_id=opportunity_id, artifact_type=CausalArtifactType.OPPORTUNITY,
        version="test", state=CausalArtifactState.VALID,
        valid_from_ms=vf, expires_at_ms=ex,
        dependencies=(signal_id,), recorded_at_ms=record_at,
    )
    ledger.record_artifact(
        artifact_id=portfolio_id, artifact_type=CausalArtifactType.PORTFOLIO_DECISION,
        version="test", state=CausalArtifactState.ACTIVE,
        valid_from_ms=vf, expires_at_ms=ex,
        dependencies=(opportunity_id,), recorded_at_ms=record_at,
    )
    ledger.record_artifact(
        artifact_id=risk_id, artifact_type=CausalArtifactType.RISK_DECISION,
        version="test", state=CausalArtifactState.APPROVED,
        valid_from_ms=vf, expires_at_ms=ex,
        dependencies=(portfolio_id,), recorded_at_ms=record_at,
    )
    ledger.record_artifact(
        artifact_id=intent.intent_id, artifact_type=CausalArtifactType.ORDER_INTENT,
        version=intent.execution_version, state=CausalArtifactState.ACTIVE,
        valid_from_ms=vf, expires_at_ms=ex,
        dependencies=(risk_id,), recorded_at_ms=record_at,
    )
    return ledger
