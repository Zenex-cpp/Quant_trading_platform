from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from trading_platform.execution.models import OrderIntent
from trading_platform.v310.runtime_orchestrator import V310RuntimeOrchestrator, RuntimeCycleSnapshot
from trading_platform.v311.dispatch_guard import (
    DispatchGuardDenied,
    GuardedExecutionDispatcher,
    DispatchReceipt,
)
from trading_platform.v35.binance_execution import (
    BinanceTestnetExecutionGateway,
    ExchangeUncertain,
    RuntimeCredentialValues,
)
from trading_platform.v34.execution_bridge import ExecutionBridge
from trading_platform.v310.runtime_orchestrator import OrchestrationState
from trading_platform.v331.position_authority import PositionAuthorityLedger, PositionAuthorityConflict
from trading_platform.v332.market_authority import MarketDataAuthorityLedger
from trading_platform.v333.causal_ttl import CausalTTLAuthorityLedger


@dataclass(frozen=True)
class V312DispatchResult:
    receipt: DispatchReceipt | None
    runtime_snapshot: RuntimeCycleSnapshot
    submitted: bool
    exchange_uncertain: bool
    recovery_required: bool
    reason: str


class ExecutionRuntimeIntegration:
    """Integrate V3.10 runtime authority with the committed ExecutionBridge and V3.5 gateway.

    The integration deliberately does not own strategy/risk decisions. It only controls
    the final dispatch boundary and converts transport uncertainty into an explicit UNKNOWN
    lifecycle that must be reconciled before another risk-increasing dispatch.

    A permission change observed during/after transport is treated conservatively: the
    exchange result is not discarded, but the runtime remains safety-blocked and the caller
    receives a recovery-required result. This avoids claiming that an already-issued network
    request can be revoked retroactively.
    """

    def __init__(
        self,
        *,
        orchestrator: V310RuntimeOrchestrator,
        bridge: ExecutionBridge,
        gateway: BinanceTestnetExecutionGateway | None = None,
        position_authority: PositionAuthorityLedger | None = None,
        market_data_authority: MarketDataAuthorityLedger | None = None,
        causal_ttl_authority: CausalTTLAuthorityLedger | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.bridge = bridge
        self.gateway = gateway or BinanceTestnetExecutionGateway()
        self.position_authority = position_authority or PositionAuthorityLedger()
        self.market_data_authority = market_data_authority or MarketDataAuthorityLedger()
        self.causal_ttl_authority = causal_ttl_authority or CausalTTLAuthorityLedger()
        self.dispatcher = GuardedExecutionDispatcher(
            bridge=bridge,
            gateway=self.gateway,
            permission_snapshot=lambda: orchestrator.snapshot(self._clock_epoch()),
            position_authority=self.position_authority,
            market_data_authority=self.market_data_authority,
            causal_ttl_authority=self.causal_ttl_authority,
            clock_ms=lambda: int(self._clock_epoch() * 1000),
        )
        self._now_epoch: float = 0.0

    def set_clock(self, now_epoch: float) -> None:
        self._now_epoch = now_epoch

    def _clock_epoch(self) -> float:
        return self._now_epoch

    def dispatch(
        self,
        *,
        intent: OrderIntent,
        credentials: RuntimeCredentialValues,
        now_epoch: float,
    ) -> V312DispatchResult:
        self.set_clock(now_epoch)
        before = self.orchestrator.snapshot(now_epoch)
        if not before.trading_allowed:
            return V312DispatchResult(None, before, False, False, True, "TRADING_NOT_ALLOWED")
        try:
            receipt = self.dispatcher.dispatch_submit(intent=intent, credentials=credentials)
        except ExchangeUncertain:
            # The exchange may have accepted the request. Preserve the local UNKNOWN state.
            req = self.bridge.committed_request(intent.intent_id)
            self.bridge.mark_unknown(
                intent.intent_id,
                client_order_id=req.request.client_order_id,
                exchange_order_id=None,
            )
            after = self.orchestrator.snapshot(now_epoch)
            return V312DispatchResult(None, after, False, True, True, "SUBMIT_OUTCOME_UNKNOWN")
        except DispatchGuardDenied as exc:
            after = self.orchestrator.snapshot(now_epoch)
            return V312DispatchResult(None, after, False, False, True, str(exc))

        after = self.orchestrator.snapshot(now_epoch)
        if not after.trading_allowed:
            # The request has already crossed the network boundary. Do not fabricate a
            # cancellation; require reconciliation before any further risk-increasing action.
            return V312DispatchResult(receipt, after, True, False, True, "PERMISSION_LOST_DURING_CYCLE")
        return V312DispatchResult(receipt, after, True, False, False, "DISPATCH_OK")
