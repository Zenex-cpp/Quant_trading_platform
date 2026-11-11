from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import hashlib

from trading_platform.execution.models import OrderIntent, PositionState
from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState
from trading_platform.v21.event_store import EventStore
from trading_platform.v318.durable_decision import (
    DurableRiskDecisionLedger,
    RiskDecisionAction,
    RiskDecisionRecord,
    RiskSystemState,
)
from trading_platform.v331.position_authority import PositionAuthorityLedger
from trading_platform.v332.market_authority import MarketDataAuthorityLedger
from trading_platform.v333.causal_ttl import CausalTTLAuthorityLedger
from trading_platform.v385.controlled_testnet_submit import PreTradeSnapshotV385
from tests.causal_helpers import causal_authority_for_intent


@dataclass(frozen=True)
class V385SubmitAuthorities:
    risk_decision_ledger: DurableRiskDecisionLedger
    position_authority: PositionAuthorityLedger
    market_data_authority: MarketDataAuthorityLedger
    causal_ttl_authority: CausalTTLAuthorityLedger
    truth_hash: str
    requested_exposure: Decimal
    risk_hash: str

    def snapshot(self, intent: OrderIntent, snapshot_id: str) -> PreTradeSnapshotV385:
        request_id = "or-" + hashlib.sha256(
            (intent.intent_id + intent.execution_version).encode()
        ).hexdigest()[:24]
        chain_hash = sha256(f"decision-chain:{intent.intent_id}".encode()).hexdigest()
        return PreTradeSnapshotV385(
            snapshot_id=snapshot_id,
            captured_at=datetime.fromtimestamp(
                self.risk_decision_ledger.get(intent.risk_decision_id).created_at_ms / 1000,
                tz=intent.window.valid_from.tzinfo,
            ),
            intent_id=intent.intent_id,
            order_request_id=request_id,
            decision_chain_hash=chain_hash,
            positions_hash="positions:" + intent.intent_id,
            portfolio_hash="portfolio:" + intent.portfolio_decision_id,
            risk_hash=self.risk_hash,
            limits_hash="limits:" + intent.risk_decision_id,
            market_hash="market:" + intent.symbol,
            liquidity_hash="liquidity:" + intent.symbol,
            model_health_hash="model-health:" + intent.model_id,
            strategy_health_hash="strategy-health:" + intent.strategy_id,
            versions_hash="versions:" + intent.execution_version,
            position_state="FLAT",
            accounting_state="RECONCILED",
            reconciliation_state="GREEN",
            market_stale=False,
            truth_hash=self.truth_hash,
            requested_exposure=self.requested_exposure,
        )


def build_v385_submit_authorities(
    intent: OrderIntent,
    now: datetime,
    *,
    risk_expires_at_ms: int | None = None,
) -> V385SubmitAuthorities:
    now_ms = int(now.timestamp() * 1000)
    if intent.price is None:
        raise ValueError("test fixture requires a price-bound order intent")
    requested_exposure = intent.quantity * intent.price
    truth_hash = sha256(f"truth:{intent.intent_id}".encode()).hexdigest()

    risk_ledger = DurableRiskDecisionLedger(EventStore())
    decision = RiskDecisionRecord(
        decision_id=intent.risk_decision_id,
        action=RiskDecisionAction.ALLOW,
        risk_state=RiskSystemState.NORMAL,
        requested_exposure=requested_exposure,
        allowed_exposure=requested_exposure,
        active_limits={"notional": requested_exposure},
        multipliers={"uncertainty": Decimal("1")},
        rejection_reason=None,
        reservation_id=intent.risk_reservation_id,
        intent_id=intent.intent_id,
        created_at_ms=now_ms - 1,
        valid_from_ms=now_ms - 1,
        expires_at_ms=risk_expires_at_ms if risk_expires_at_ms is not None else now_ms + 60_000,
        configuration_version="test-config-v1",
        risk_state_version="test-risk-state-v1",
        portfolio_version="test-portfolio-v1",
        position_version="test-position-v1",
        provenance_id=f"test-provenance:{intent.intent_id}",
        truth_hash=truth_hash,
        input_fingerprint=f"test-input:{intent.intent_id}",
    )
    risk_ledger.record(decision)

    position = PositionAuthorityLedger(EventStore())
    reconciliation = ReconciliationResult(
        ReconciliationState.GREEN,
        ReconciliationDiff(),
        f"rest:{intent.intent_id}",
        f"stream:{intent.intent_id}",
        "TEST_RECONCILED",
    )
    position.record_reconciliation(
        symbol=intent.symbol,
        local_quantity=Decimal("0"),
        exchange_quantity=Decimal("0"),
        reconciliation=reconciliation,
        observed_at_ms=now_ms,
        ttl_ms=60_000,
        position_state=PositionState.FLAT,
    )

    market = MarketDataAuthorityLedger(EventStore())
    market.record_observation(
        symbol=intent.symbol,
        feed_id="primary",
        event_time_ms=now_ms,
        receive_time_ms=now_ms,
        processing_time_ms=now_ms,
        max_age_ms=60_000,
        source="test",
        sequence_number=1,
    )
    causal = causal_authority_for_intent(intent)
    return V385SubmitAuthorities(
        risk_decision_ledger=risk_ledger,
        position_authority=position,
        market_data_authority=market,
        causal_ttl_authority=causal,
        truth_hash=truth_hash,
        requested_exposure=requested_exposure,
        risk_hash=decision.fingerprint,
    )
