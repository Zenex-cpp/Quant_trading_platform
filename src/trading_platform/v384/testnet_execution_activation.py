"""V3.84 Testnet execution activation authority.

The v3.83 connectivity preflight proves read-only reachability, but that proof must
be bound to the mutation path before any Testnet order can be submitted.

This module implements that boundary with:
- VERIFIED connectivity evidence binding;
- explicit operator approval and scope;
- short activation TTL;
- green reconciliation prerequisite;
- symbol/notional hard bounds;
- explicit halt/deactivate semantics;
- audit records with no credential retention.

The authority is Testnet-only and fail-closed.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
import hashlib
import json

from trading_platform.execution.models import OrderIntent, OrderType
from trading_platform.ops.network_policy import TESTNET_POLICY
from trading_platform.v35.binance_execution import (
    BinanceTestnetExecutionGateway,
    RuntimeCredentialValues,
    SubmitObservation,
)
from trading_platform.v380.order_adapter import BinanceTestnetOrderAdapterV380


class ActivationStatusV384(str, Enum):
    INACTIVE = "INACTIVE"
    ACTIVE = "ACTIVE"
    HALTED = "HALTED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class ConnectivityProofV384:
    status: str
    evidence_hash: str
    verified_at: datetime
    expires_at: datetime
    rest_endpoint: str
    clock_skew_ms: int | None

    def validate(self, now: datetime) -> None:
        if self.status != "VERIFIED":
            raise PermissionError("CONNECTIVITY_PROOF_NOT_VERIFIED")
        if not self.evidence_hash:
            raise PermissionError("CONNECTIVITY_EVIDENCE_HASH_REQUIRED")
        if self.expires_at <= self.verified_at:
            raise PermissionError("INVALID_CONNECTIVITY_PROOF_WINDOW")
        if now < self.verified_at or now >= self.expires_at:
            raise PermissionError("CONNECTIVITY_PROOF_EXPIRED")
        TESTNET_POLICY.assert_allowed(self.rest_endpoint)
        if self.clock_skew_ms is not None and abs(self.clock_skew_ms) > 1_000:
            raise PermissionError("CONNECTIVITY_CLOCK_SKEW_TOO_LARGE")


@dataclass(frozen=True)
class OperatorApprovalV384:
    approval_id: str
    actor: str
    scope: str
    approved_at: datetime
    expires_at: datetime
    reason: str

    def validate(self, now: datetime) -> None:
        if not self.approval_id or not self.actor:
            raise PermissionError("OPERATOR_APPROVAL_IDENTITY_REQUIRED")
        if self.scope != "TESTNET_ORDER_MUTATION":
            raise PermissionError("OPERATOR_APPROVAL_SCOPE_INVALID")
        if self.expires_at <= self.approved_at:
            raise PermissionError("INVALID_APPROVAL_WINDOW")
        if now < self.approved_at or now >= self.expires_at:
            raise PermissionError("OPERATOR_APPROVAL_EXPIRED")


@dataclass(frozen=True)
class TestnetExecutionActivationConfigV384:
    environment: str = "TESTNET"
    config_version: str = "V384-ACTIVATION-1"
    activation_ttl_s: int = 300
    max_notional: Decimal = Decimal("25")
    allowed_symbols: tuple[str, ...] = ("BTCUSDT",)

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise PermissionError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if not 0 < self.activation_ttl_s <= 900:
            raise ValueError("INVALID_ACTIVATION_TTL")
        if self.max_notional <= 0:
            raise ValueError("TESTNET_MAX_NOTIONAL_REQUIRED")
        if not self.allowed_symbols:
            raise ValueError("SYMBOL_ALLOWLIST_REQUIRED")
        if any(not symbol or symbol.upper() != symbol for symbol in self.allowed_symbols):
            raise ValueError("SYMBOL_ALLOWLIST_CANONICALIZATION_REQUIRED")


@dataclass(frozen=True)
class V384ActivationSnapshot:
    status: ActivationStatusV384
    activation_id: str | None
    operator_approval_id: str | None
    connectivity_evidence_hash: str | None
    activated_at: datetime | None
    expires_at: datetime | None
    reconciliation_green: bool
    reason: str


@dataclass(frozen=True)
class V384Authorization:
    allowed: bool
    reason: str
    activation_id: str | None


@dataclass(frozen=True)
class _AuditEvent:
    event_id: str
    event_type: str
    timestamp: datetime
    activation_id: str | None
    reason: str


class TestnetExecutionActivationAuthorityV384:
    """Single mutation authority for the controlled Testnet execution path."""

    __test__ = False

    def __init__(
        self,
        config: TestnetExecutionActivationConfigV384 | None = None,
        *,
        clock=lambda: datetime.now(timezone.utc),
    ) -> None:
        self.config = config or TestnetExecutionActivationConfigV384()
        self.config.validate()
        self.clock = clock
        self._status = ActivationStatusV384.INACTIVE
        self._activation_id: str | None = None
        self._approval_id: str | None = None
        self._evidence_hash: str | None = None
        self._activated_at: datetime | None = None
        self._expires_at: datetime | None = None
        self._reconciliation_green = False
        self._audit: list[_AuditEvent] = []

    def _now(self) -> datetime:
        return self.clock()

    @staticmethod
    def _make_activation_id(*, evidence_hash: str, approval_id: str, config_version: str, activated_at: datetime) -> str:
        payload = {
            "evidence_hash": evidence_hash,
            "approval_id": approval_id,
            "config_version": config_version,
            "activated_at": activated_at.isoformat(),
        }
        return "ACT-" + hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:24]

    def _audit_event(self, event_type: str, reason: str, now: datetime) -> None:
        event_id = hashlib.sha256(f"{event_type}|{now.isoformat()}|{self._activation_id}|{len(self._audit)}".encode()).hexdigest()[:24]
        self._audit.append(_AuditEvent(event_id, event_type, now, self._activation_id, reason))

    def activate(
        self,
        *,
        connectivity: ConnectivityProofV384,
        approval: OperatorApprovalV384,
        reconciliation_state: str,
        now: datetime | None = None,
    ) -> V384ActivationSnapshot:
        now = self._now() if now is None else now
        connectivity.validate(now)
        approval.validate(now)
        if reconciliation_state != "GREEN":
            raise PermissionError("RECONCILIATION_NOT_GREEN")
        expires_at = min(
            now + timedelta(seconds=self.config.activation_ttl_s),
            connectivity.expires_at,
            approval.expires_at,
        )
        if expires_at <= now:
            raise PermissionError("ACTIVATION_WINDOW_EXPIRED")
        self._activation_id = self._make_activation_id(
            evidence_hash=connectivity.evidence_hash,
            approval_id=approval.approval_id,
            config_version=self.config.config_version,
            activated_at=now,
        )
        self._approval_id = approval.approval_id
        self._evidence_hash = connectivity.evidence_hash
        self._activated_at = now
        self._expires_at = expires_at
        self._reconciliation_green = True
        self._status = ActivationStatusV384.ACTIVE
        self._audit_event("ACTIVATION_GRANTED", "VERIFIED_CONNECTIVITY_OPERATOR_APPROVAL_RECONCILIATION_GREEN", now)
        return self.snapshot(now)

    def _refresh_expiry(self, now: datetime) -> None:
        if self._status is ActivationStatusV384.ACTIVE and self._expires_at is not None and now >= self._expires_at:
            self._status = ActivationStatusV384.EXPIRED
            self._reconciliation_green = False
            self._audit_event("ACTIVATION_EXPIRED", "ACTIVATION_TTL_EXPIRED", now)

    def authorize(
        self,
        *,
        intent: OrderIntent,
        reference_price: Decimal | None = None,
        now: datetime | None = None,
    ) -> V384Authorization:
        now = self._now() if now is None else now
        self._refresh_expiry(now)
        if self._status is not ActivationStatusV384.ACTIVE:
            return V384Authorization(False, "ACTIVATION_NOT_ACTIVE", self._activation_id)
        if not self._reconciliation_green:
            return V384Authorization(False, "RECONCILIATION_NOT_GREEN", self._activation_id)
        if intent.symbol.upper() not in self.config.allowed_symbols:
            return V384Authorization(False, "SYMBOL_NOT_ALLOWLISTED", self._activation_id)
        if intent.order_type not in {OrderType.MARKET, OrderType.LIMIT}:
            return V384Authorization(False, "ORDER_TYPE_UNSUPPORTED", self._activation_id)
        price = intent.price if intent.price is not None else reference_price
        if price is None or price <= 0:
            return V384Authorization(False, "REFERENCE_PRICE_REQUIRED_FOR_NOTIONAL_GUARD", self._activation_id)
        if intent.quantity * price > self.config.max_notional:
            return V384Authorization(False, "TESTNET_NOTIONAL_LIMIT_EXCEEDED", self._activation_id)
        return V384Authorization(True, "AUTHORIZED", self._activation_id)

    def halt(self, reason: str, *, now: datetime | None = None) -> V384ActivationSnapshot:
        now = self._now() if now is None else now
        self._status = ActivationStatusV384.HALTED
        self._reconciliation_green = False
        self._audit_event("ACTIVATION_HALTED", reason, now)
        return self.snapshot(now)

    def deactivate(self, reason: str = "DEACTIVATED", *, now: datetime | None = None) -> V384ActivationSnapshot:
        now = self._now() if now is None else now
        self._status = ActivationStatusV384.INACTIVE
        self._reconciliation_green = False
        self._audit_event("ACTIVATION_REVOKED", reason, now)
        self._activation_id = None
        self._approval_id = None
        self._evidence_hash = None
        self._activated_at = None
        self._expires_at = None
        return self.snapshot(now)

    def snapshot(self, now: datetime | None = None) -> V384ActivationSnapshot:
        now = self._now() if now is None else now
        self._refresh_expiry(now)
        return V384ActivationSnapshot(
            status=self._status,
            activation_id=self._activation_id,
            operator_approval_id=self._approval_id,
            connectivity_evidence_hash=self._evidence_hash,
            activated_at=self._activated_at,
            expires_at=self._expires_at,
            reconciliation_green=self._reconciliation_green,
            reason="ACTIVE" if self._status is ActivationStatusV384.ACTIVE else self._status.value,
        )

    def audit_events(self) -> tuple[dict[str, object], ...]:
        return tuple({
            "event_id": item.event_id,
            "event_type": item.event_type,
            "timestamp": item.timestamp.isoformat(),
            "activation_id": item.activation_id,
            "reason": item.reason,
        } for item in self._audit)


class BinanceTestnetExecutionAdapterV384:
    """v3.84 mutation adapter requiring activation authority before gateway calls."""

    __test__ = False

    def __init__(
        self,
        gateway: BinanceTestnetExecutionGateway,
        authority: TestnetExecutionActivationAuthorityV384,
    ) -> None:
        self.gateway = gateway
        self.authority = authority
        self._delegate = BinanceTestnetOrderAdapterV380(
            gateway=gateway,
            mutation_gate=_DelegatingMutationGate(authority),
        )

    def submit(
        self,
        intent: OrderIntent,
        *,
        credentials: RuntimeCredentialValues,
        now: datetime,
        reference_price: Decimal | None = None,
    ) -> SubmitObservation:
        authorization = self.authority.authorize(intent=intent, reference_price=reference_price, now=now)
        if not authorization.allowed:
            raise PermissionError(authorization.reason)
        return self._delegate.submit(intent, credentials=credentials, now=now, reference_price=reference_price)


class _DelegatingMutationGate:
    def __init__(self, authority: TestnetExecutionActivationAuthorityV384) -> None:
        self.authority = authority

    def authorize(self, *, intent: OrderIntent, reference_price: Decimal | None = None) -> None:
        result = self.authority.authorize(intent=intent, reference_price=reference_price)
        if not result.allowed:
            raise PermissionError(result.reason)
