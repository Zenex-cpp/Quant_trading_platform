"""V3.86 controlled Testnet operator session boundary.

This module turns the already-verified V3.83/V3.84/V3.85 components into one
explicit operational gate for the first authenticated Testnet mutation.

Contract:
    CONNECTIVITY VERIFIED
    + USER-DATA STREAM HEALTHY
    + RECONCILIATION GREEN
    + ACTIVATION ACTIVE
    + OPERATOR APPROVAL PRESENT
    + RUNTIME CREDENTIALS PRESENT (never persisted)
    -> mutation allowed

Post-submit, ACKNOWLEDGED/REJECTED is not sufficient to declare the trade
complete. A separate reconciliation cycle must close the operational loop.
UNKNOWN always blocks further mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from trading_platform.v383_connectivity import ConnectivityEvidenceV383, PreflightStatus
from trading_platform.v384 import ActivationStatusV384, TestnetExecutionActivationAuthorityV384
from trading_platform.v385.controlled_testnet_submit import (
    ControlledSubmitError,
    ControlledSubmitResultV385,
    ControlledTestnetSubmitAuthorityV385,
    PreTradeSnapshotV385,
)
from trading_platform.execution.models import OrderIntent
from trading_platform.v35.binance_execution import RuntimeCredentialValues, ExchangeOutcome


class OperatorSessionStateV386(str, Enum):
    PRECHECK = "PRECHECK"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


@dataclass(frozen=True)
class UserDataHealthV386:
    control_healthy: bool
    websocket_healthy: bool
    listen_key_present: bool
    last_event_epoch: float | None
    reason: str

    @property
    def healthy(self) -> bool:
        return bool(self.control_healthy and self.websocket_healthy and self.listen_key_present)


@dataclass(frozen=True)
class OperatorSessionConfigV386:
    require_user_data_stream: bool = True
    max_event_age_s: float = 15.0
    environment: str = "TESTNET"

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise PermissionError("NON_TESTNET_OPERATOR_SESSION")
        if self.max_event_age_s <= 0:
            raise ValueError("INVALID_USER_DATA_STALE_THRESHOLD")


@dataclass(frozen=True)
class GateResultV386:
    allowed: bool
    reason: str
    state: OperatorSessionStateV386
    activation_id: str | None
    checks: tuple[tuple[str, bool], ...]


class OperatorSessionAuthorityV386:
    """Operational gate immediately above the V3.85 mutation boundary."""

    __test__ = False

    def __init__(
        self,
        *,
        activation: TestnetExecutionActivationAuthorityV384,
        submitter: ControlledTestnetSubmitAuthorityV385,
        config: OperatorSessionConfigV386 | None = None,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.activation = activation
        self.submitter = submitter
        self.config = config or OperatorSessionConfigV386()
        self.config.validate()
        self.clock = clock
        self.state = OperatorSessionStateV386.PRECHECK
        self._closed = False

    def preflight(
        self,
        *,
        connectivity: ConnectivityEvidenceV383,
        user_data: UserDataHealthV386,
        reconciliation_green: bool,
        credentials: RuntimeCredentialValues | None,
        now: datetime,
    ) -> GateResultV386:
        activation_snapshot = self.activation.snapshot(now)
        checks: list[tuple[str, bool]] = [
            ("TESTNET_ENVIRONMENT", self.config.environment == "TESTNET"),
            ("CONNECTIVITY_VERIFIED", connectivity.status is PreflightStatus.VERIFIED),
            ("RECONCILIATION_GREEN", bool(reconciliation_green)),
            ("ACTIVATION_ACTIVE", activation_snapshot.status is ActivationStatusV384.ACTIVE),
            ("ACTIVATION_RECONCILIATION_GREEN", activation_snapshot.reconciliation_green),
            ("RUNTIME_CREDENTIALS_PRESENT", credentials is not None),
        ]
        if self.config.require_user_data_stream:
            fresh = False
            if user_data.last_event_epoch is not None:
                fresh = (now.timestamp() - user_data.last_event_epoch) <= self.config.max_event_age_s
            checks.extend([
                ("USER_DATA_CONTROL_HEALTHY", user_data.control_healthy),
                ("USER_DATA_WEBSOCKET_HEALTHY", user_data.websocket_healthy),
                ("USER_DATA_LISTEN_KEY_PRESENT", user_data.listen_key_present),
                ("USER_DATA_EVENT_FRESH", fresh),
            ])
        allowed = all(ok for _, ok in checks)
        self.state = OperatorSessionStateV386.READY if allowed else OperatorSessionStateV386.BLOCKED
        reason = "READY_FOR_CONTROLLED_TESTNET_MUTATION" if allowed else next(name for name, ok in checks if not ok)
        return GateResultV386(
            allowed=allowed,
            reason=reason,
            state=self.state,
            activation_id=activation_snapshot.activation_id,
            checks=tuple(checks),
        )

    def submit_once(
        self,
        *,
        gate: GateResultV386,
        intent: OrderIntent,
        credentials: RuntimeCredentialValues,
        pre_trade_snapshot: PreTradeSnapshotV385,
        now: datetime,
        reference_price=None,
    ) -> ControlledSubmitResultV385:
        if self._closed:
            raise PermissionError("OPERATOR_SESSION_CLOSED")
        if not gate.allowed or gate.state is not OperatorSessionStateV386.READY:
            raise PermissionError("OPERATOR_MUTATION_GATE_BLOCKED")
        result = self.submitter.submit(
            intent,
            credentials=credentials,
            pre_trade_snapshot=pre_trade_snapshot,
            now=now,
            reference_price=reference_price,
        )
        if result.status == "UNKNOWN":
            self.state = OperatorSessionStateV386.UNKNOWN
        else:
            self.state = OperatorSessionStateV386.SUBMITTED
        return result

    def close(self, *, reason: str = "OPERATOR_SESSION_CLOSED") -> OperatorSessionStateV386:
        self._closed = True
        self.state = OperatorSessionStateV386.CLOSED
        return self.state

    def assert_post_trade_reconciliation(self, *, reconciliation_green: bool) -> None:
        if self.state is OperatorSessionStateV386.UNKNOWN:
            raise ControlledSubmitError("POST_TRADE_RECONCILIATION_REQUIRED_AFTER_UNKNOWN")
        if not reconciliation_green:
            raise ControlledSubmitError("POST_TRADE_RECONCILIATION_NOT_GREEN")
