from decimal import Decimal
from pathlib import Path

from trading_platform.v21.event_store import EventStore
from trading_platform.risk.budget import BudgetScope
from trading_platform.v315 import DurableAccountingLedger, DurableFill
from trading_platform.v316 import DurableAccountingAuthority
from trading_platform.v317 import DurableRiskReservationBook, RiskReservationGate, RiskReservationRecord
from trading_platform.v318.durable_decision import (
    DurableRiskDecisionLedger,
    RiskDecisionAction,
    RiskDecisionRecord,
    RiskSystemState,
)
from trading_platform.execution.models import PositionState
from trading_platform.v20.reconciliation import ReconciliationDiff, ReconciliationResult, ReconciliationState
from trading_platform.v331.position_authority import PositionAuthorityLedger
from trading_platform.v332.market_authority import MarketDataAuthorityLedger
from tests.causal_helpers import causal_authority_for_intent


def risk_decision_ledger_for(bridge, intent, *, now_ms: int, expires_at_ms: int | None = None):
    committed = bridge.committed_request(intent.intent_id)
    exposure = Decimal(str(committed.authority.requested_risk))
    ledger = DurableRiskDecisionLedger(EventStore())
    ledger.record(RiskDecisionRecord(
        decision_id=intent.risk_decision_id,
        action=RiskDecisionAction.ALLOW,
        risk_state=RiskSystemState.NORMAL,
        requested_exposure=exposure,
        allowed_exposure=exposure,
        active_limits={"order": exposure},
        multipliers={"uncertainty": Decimal("1")},
        rejection_reason=None,
        reservation_id=intent.risk_reservation_id,
        intent_id=intent.intent_id,
        created_at_ms=now_ms - 1,
        valid_from_ms=now_ms - 1,
        expires_at_ms=expires_at_ms if expires_at_ms is not None else now_ms + 60_000,
        configuration_version="test-config-v1",
        risk_state_version="test-risk-state-v1",
        portfolio_version="test-portfolio-v1",
        position_version="test-position-v1",
        provenance_id=f"test-provenance:{intent.intent_id}",
        truth_hash=committed.authority.truth_hash,
        input_fingerprint=f"test-input:{intent.intent_id}",
    ))
    return ledger


def execution_authorities_for(intent, *, now_ms: int):
    position = PositionAuthorityLedger()
    reconciliation = ReconciliationResult(
        ReconciliationState.GREEN,
        ReconciliationDiff(),
        "test-rest-hash",
        "test-stream-hash",
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
    market = MarketDataAuthorityLedger()
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
    return {
        "position_authority": position,
        "market_data_authority": market,
        "causal_ttl_authority": causal,
    }


def risk_accounting_reservation_for(
    bridge, intent, *, now_ms: int, directory: str | Path,
    accounting_authority: DurableAccountingAuthority | None = None,
):
    """Build disk-backed, reconciled accounting and a bound order reservation."""
    if not intent.risk_reservation_id:
        raise ValueError("TEST_INTENT_RISK_RESERVATION_ID_REQUIRED")
    root = Path(directory)
    committed = bridge.committed_request(intent.intent_id)
    requested_risk = Decimal(str(committed.authority.requested_risk))

    accounting = accounting_authority
    if accounting is None:
        accounting_ledger = DurableAccountingLedger(EventStore(str(root / "risk-accounting.db")))
        accounting_ledger.append_fill(DurableFill(
            f"test-fill:{intent.intent_id}", f"test-order:{intent.intent_id}",
            intent.symbol, intent.side.value, Decimal("1"), Decimal("100"),
        ))
        accounting = DurableAccountingAuthority(accounting_ledger)
        accounting.restore()
        accounting.mark_reconciled(evidence_id=f"test-reconciliation:{intent.intent_id}")
    accounting_hash = accounting.snapshot().projection_hash
    if not accounting_hash:
        raise AssertionError("TEST_ACCOUNTING_PROJECTION_HASH_REQUIRED")

    book = DurableRiskReservationBook(
        EventStore(str(root / "risk-reservations.db")), allocated=requested_risk,
    )
    book.reserve(RiskReservationRecord(
        intent.risk_reservation_id, BudgetScope.ORDER, requested_risk, requested_risk,
        intent.intent_id, intent.risk_decision_id, accounting_hash,
        now_ms - 1, now_ms + 60_000,
    ))
    return accounting, RiskReservationGate(book)
