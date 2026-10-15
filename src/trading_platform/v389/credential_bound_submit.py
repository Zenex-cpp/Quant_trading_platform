"""V3.89 integration adapter between the runtime credential capability and V3.87."""
from __future__ import annotations

from datetime import datetime

from trading_platform.v35.binance_execution import RuntimeCredentialValues
from trading_platform.v386.operator_runbook import GateResultV386
from trading_platform.v385.controlled_testnet_submit import ControlledSubmitResultV385, PreTradeSnapshotV385
from trading_platform.v387.first_testnet_order import FirstTestnetOrderRunnerV387, V387PreparationResult
from trading_platform.execution.models import OrderIntent
from .testnet_runtime_capability import TestnetRuntimeCredentialCapabilityV389


class CredentialBoundFirstTestnetSubmitV389:
    """Releases Testnet credentials only after the V3.87 pure submit preconditions pass."""

    __test__ = False

    def __init__(self, *, runner: FirstTestnetOrderRunnerV387, endpoint: str = "https://testnet.binancefuture.com") -> None:
        self.runner = runner
        self.endpoint = endpoint

    def submit_once(
        self,
        *,
        preparation: V387PreparationResult,
        gate: GateResultV386,
        intent: OrderIntent,
        capability: TestnetRuntimeCredentialCapabilityV389,
        pre_trade_snapshot: PreTradeSnapshotV385,
        now: datetime,
        reference_price=None,
    ) -> ControlledSubmitResultV385:
        if not preparation.allowed or not gate.allowed:
            raise PermissionError("FIRST_TESTNET_ORDER_NOT_ARMED")
        if self.runner.state.name != "ARMED":
            raise PermissionError("FIRST_TESTNET_ORDER_NOT_ARMED")
        credentials: RuntimeCredentialValues = capability.consume(now=now, endpoint=self.endpoint)
        return self.runner.submit_once(
            preparation=preparation,
            gate=gate,
            intent=intent,
            credentials=credentials,
            pre_trade_snapshot=pre_trade_snapshot,
            now=now,
            reference_price=reference_price,
        )
