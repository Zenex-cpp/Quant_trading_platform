"""V3.88 evidence-closed boundary for the first real Testnet execution.

The first Testnet mutation is not considered operationally complete from an ACK
alone. V3.88 makes the complete causal chain explicit and hash-bound:

preconditions -> dispatch -> ORDER_TRADE_UPDATE -> ACCOUNT_UPDATE ->
order/position/accounting reconciliation -> session closure.

Only identifiers, statuses and content hashes are durably represented here.
Runtime credentials and raw secret values are intentionally out of scope.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
from typing import Any, Mapping


class EvidenceBundleErrorV388(RuntimeError):
    """Raised when an execution evidence bundle cannot safely advance."""


class EvidenceBundleStateV388(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    OBSERVED = "OBSERVED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    BLOCKED = "BLOCKED"
    INVALIDATED = "INVALIDATED"


def _iso(value: datetime, name: str) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise EvidenceBundleErrorV388(f"{name}_TIMEZONE_REQUIRED")
    return value.astimezone(timezone.utc).isoformat()


def _hash(payload: Any) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()


def _looks_like_secret(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("secret", "api_secret", "private_key", "password", "passphrase"))


@dataclass(frozen=True)
class TestnetEvidenceRefV388:
    __test__ = False
    name: str
    source: str
    captured_at: datetime
    content_hash: str
    required: bool = True

    def validate(self) -> None:
        if not self.name or not self.source or not self.content_hash:
            raise EvidenceBundleErrorV388("EVIDENCE_REF_REQUIRED_FIELDS")
        _iso(self.captured_at, "EVIDENCE_REF_CAPTURED_AT")
        if len(self.content_hash) != 64:
            raise EvidenceBundleErrorV388("EVIDENCE_REF_HASH_INVALID")
        if _looks_like_secret(self.name) or _looks_like_secret(self.source):
            raise EvidenceBundleErrorV388("SECRET_METADATA_NOT_ALLOWED")


@dataclass(frozen=True)
class FirstTestnetExecutionEvidenceV388:
    bundle_id: str
    state: EvidenceBundleStateV388
    environment: str
    symbol: str
    run_started_at: datetime
    run_closed_at: datetime | None
    connectivity_ref: TestnetEvidenceRefV388
    approval_id: str
    activation_id: str
    pre_trade_snapshot_id: str
    pre_trade_snapshot_hash: str
    dispatch_attempt_id: str
    order_request_id: str
    client_order_id: str
    exchange_order_id: str | None
    submit_status: str
    order_event_ref: TestnetEvidenceRefV388 | None
    account_event_ref: TestnetEvidenceRefV388 | None
    reconciliation_ref: TestnetEvidenceRefV388 | None
    accounting_ref: TestnetEvidenceRefV388 | None
    terminal_status: str | None
    mutation_performed: bool
    content_hash: str
    invalidation_reason: str | None = None

    @staticmethod
    def _ref_payload(ref: TestnetEvidenceRefV388 | None) -> dict[str, Any] | None:
        if ref is None:
            return None
        return {
            "name": ref.name,
            "source": ref.source,
            "captured_at": _iso(ref.captured_at, "EVIDENCE_REF_CAPTURED_AT"),
            "content_hash": ref.content_hash,
            "required": ref.required,
        }

    def payload(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "state": self.state.value,
            "environment": self.environment,
            "symbol": self.symbol,
            "run_started_at": _iso(self.run_started_at, "RUN_STARTED_AT"),
            "run_closed_at": _iso(self.run_closed_at, "RUN_CLOSED_AT") if self.run_closed_at else None,
            "connectivity_ref": self._ref_payload(self.connectivity_ref),
            "approval_id": self.approval_id,
            "activation_id": self.activation_id,
            "pre_trade_snapshot_id": self.pre_trade_snapshot_id,
            "pre_trade_snapshot_hash": self.pre_trade_snapshot_hash,
            "dispatch_attempt_id": self.dispatch_attempt_id,
            "order_request_id": self.order_request_id,
            "client_order_id": self.client_order_id,
            "exchange_order_id": self.exchange_order_id,
            "submit_status": self.submit_status,
            "order_event_ref": self._ref_payload(self.order_event_ref),
            "account_event_ref": self._ref_payload(self.account_event_ref),
            "reconciliation_ref": self._ref_payload(self.reconciliation_ref),
            "accounting_ref": self._ref_payload(self.accounting_ref),
            "terminal_status": self.terminal_status,
            "mutation_performed": self.mutation_performed,
            "invalidation_reason": self.invalidation_reason,
        }

    def verify_content_hash(self) -> bool:
        return _hash(self.payload()) == self.content_hash

    @property
    def fingerprint(self) -> str:
        return _hash({"content_hash": self.content_hash, "bundle_id": self.bundle_id})


class FirstTestnetExecutionEvidenceBuilderV388:
    """Append-only operational evidence builder for exactly one Testnet run."""

    __test__ = False

    _TERMINAL = {"FILLED", "CANCELED", "CANCELLED", "EXPIRED", "EXPIRED_IN_MATCH", "REJECTED"}

    def __init__(self, *, bundle_id: str, environment: str, symbol: str, started_at: datetime) -> None:
        if not bundle_id or environment != "TESTNET" or symbol != "BTCUSDT":
            raise EvidenceBundleErrorV388("TESTNET_EVIDENCE_SCOPE_INVALID")
        _iso(started_at, "STARTED_AT")
        self.bundle_id = bundle_id
        self.environment = environment
        self.symbol = symbol
        self.started_at = started_at
        self.state = EvidenceBundleStateV388.OPEN
        self.closed_at: datetime | None = None
        self.connectivity_ref: TestnetEvidenceRefV388 | None = None
        self.approval_id: str | None = None
        self.activation_id: str | None = None
        self.pre_trade_snapshot_id: str | None = None
        self.pre_trade_snapshot_hash: str | None = None
        self.dispatch_attempt_id: str | None = None
        self.order_request_id: str | None = None
        self.client_order_id: str | None = None
        self.exchange_order_id: str | None = None
        self.submit_status: str | None = None
        self.order_event_ref: TestnetEvidenceRefV388 | None = None
        self.account_event_ref: TestnetEvidenceRefV388 | None = None
        self.reconciliation_ref: TestnetEvidenceRefV388 | None = None
        self.accounting_ref: TestnetEvidenceRefV388 | None = None
        self.terminal_status: str | None = None
        self.mutation_performed = False
        self.invalidation_reason: str | None = None

    def _ensure_open(self) -> None:
        if self.state in {EvidenceBundleStateV388.CLOSED, EvidenceBundleStateV388.INVALIDATED}:
            raise EvidenceBundleErrorV388("EVIDENCE_BUNDLE_TERMINAL")
        if self.state is EvidenceBundleStateV388.BLOCKED:
            raise EvidenceBundleErrorV388("EVIDENCE_BUNDLE_BLOCKED")

    def record_preconditions(
        self,
        *,
        connectivity_ref: TestnetEvidenceRefV388,
        approval_id: str,
        activation_id: str,
        pre_trade_snapshot_id: str,
        pre_trade_snapshot_hash: str,
    ) -> None:
        self._ensure_open()
        connectivity_ref.validate()
        required = (approval_id, activation_id, pre_trade_snapshot_id, pre_trade_snapshot_hash)
        if any(not x for x in required) or len(pre_trade_snapshot_hash) != 64:
            raise EvidenceBundleErrorV388("PRECONDITION_EVIDENCE_REQUIRED")
        if self.connectivity_ref is not None:
            raise EvidenceBundleErrorV388("PRECONDITION_EVIDENCE_ALREADY_SET")
        self.connectivity_ref = connectivity_ref
        self.approval_id = approval_id
        self.activation_id = activation_id
        self.pre_trade_snapshot_id = pre_trade_snapshot_id
        self.pre_trade_snapshot_hash = pre_trade_snapshot_hash

    def record_submit(
        self,
        *,
        dispatch_attempt_id: str,
        order_request_id: str,
        client_order_id: str,
        exchange_order_id: str | None,
        status: str,
        mutation_performed: bool,
    ) -> None:
        self._ensure_open()
        if self.connectivity_ref is None or self.approval_id is None:
            raise EvidenceBundleErrorV388("PRECONDITIONS_MISSING")
        if self.dispatch_attempt_id is not None:
            raise EvidenceBundleErrorV388("DUPLICATE_SUBMIT_EVIDENCE")
        if not all((dispatch_attempt_id, order_request_id, client_order_id, status)):
            raise EvidenceBundleErrorV388("SUBMIT_EVIDENCE_REQUIRED")
        if mutation_performed and self.environment != "TESTNET":
            raise EvidenceBundleErrorV388("NON_TESTNET_MUTATION_EVIDENCE")
        self.dispatch_attempt_id = dispatch_attempt_id
        self.order_request_id = order_request_id
        self.client_order_id = client_order_id
        self.exchange_order_id = exchange_order_id
        self.submit_status = status.upper()
        self.mutation_performed = bool(mutation_performed)
        self.state = EvidenceBundleStateV388.SUBMITTED

    def record_order_event(
        self,
        *,
        event_hash: str,
        captured_at: datetime,
        client_order_id: str,
        status: str,
        exchange_order_id: str | None = None,
    ) -> None:
        self._ensure_open()
        if self.state is not EvidenceBundleStateV388.SUBMITTED:
            raise EvidenceBundleErrorV388("ORDER_EVENT_REQUIRES_SUBMIT")
        if client_order_id != self.client_order_id:
            raise EvidenceBundleErrorV388("ORDER_EVENT_CLIENT_CORRELATION_MISMATCH")
        if exchange_order_id is not None and self.exchange_order_id not in (None, exchange_order_id):
            raise EvidenceBundleErrorV388("ORDER_EVENT_EXCHANGE_CORRELATION_MISMATCH")
        status = status.upper()
        ref = TestnetEvidenceRefV388("ORDER_TRADE_UPDATE", "USER_DATA", captured_at, event_hash)
        ref.validate()
        if self.order_event_ref is not None:
            raise EvidenceBundleErrorV388("ORDER_EVENT_EVIDENCE_ALREADY_SET")
        self.order_event_ref = ref
        if exchange_order_id:
            self.exchange_order_id = exchange_order_id
        self.terminal_status = status if status in self._TERMINAL else None
        self.state = EvidenceBundleStateV388.OBSERVED

    def record_account_event(self, *, event_hash: str, captured_at: datetime) -> None:
        self._ensure_open()
        if self.order_event_ref is None:
            raise EvidenceBundleErrorV388("ACCOUNT_EVENT_REQUIRES_ORDER_EVENT")
        ref = TestnetEvidenceRefV388("ACCOUNT_UPDATE", "USER_DATA", captured_at, event_hash)
        ref.validate()
        if self.account_event_ref is not None:
            raise EvidenceBundleErrorV388("ACCOUNT_EVENT_EVIDENCE_ALREADY_SET")
        self.account_event_ref = ref

    def record_reconciliation(self, *, reconciliation_hash: str, captured_at: datetime, green: bool) -> None:
        self._ensure_open()
        if self.terminal_status is None:
            raise EvidenceBundleErrorV388("TERMINAL_ORDER_STATUS_REQUIRED")
        if self.account_event_ref is None:
            raise EvidenceBundleErrorV388("ACCOUNT_EVENT_REQUIRED")
        if not green:
            self.state = EvidenceBundleStateV388.BLOCKED
            raise EvidenceBundleErrorV388("POST_TRADE_RECONCILIATION_NOT_GREEN")
        ref = TestnetEvidenceRefV388("REST_WS_RECONCILIATION", "RECONCILIATION", captured_at, reconciliation_hash)
        ref.validate()
        self.reconciliation_ref = ref
        self.state = EvidenceBundleStateV388.RECONCILED

    def record_accounting(self, *, accounting_hash: str, captured_at: datetime, reconciled: bool) -> None:
        self._ensure_open()
        if self.reconciliation_ref is None:
            raise EvidenceBundleErrorV388("ACCOUNTING_REQUIRES_RECONCILIATION")
        if not reconciled:
            self.state = EvidenceBundleStateV388.BLOCKED
            raise EvidenceBundleErrorV388("ACCOUNTING_RECONCILIATION_NOT_GREEN")
        ref = TestnetEvidenceRefV388("ACCOUNTING_RECONCILIATION", "ACCOUNTING", captured_at, accounting_hash)
        ref.validate()
        self.accounting_ref = ref

    def close(self, *, closed_at: datetime) -> FirstTestnetExecutionEvidenceV388:
        self._ensure_open()
        if self.accounting_ref is None:
            raise EvidenceBundleErrorV388("ACCOUNTING_EVIDENCE_REQUIRED")
        if self.order_event_ref is None or self.terminal_status is None:
            raise EvidenceBundleErrorV388("TERMINAL_ORDER_EVENT_REQUIRED")
        if self.reconciliation_ref is None:
            raise EvidenceBundleErrorV388("RECONCILIATION_EVIDENCE_REQUIRED")
        if self.closed_at is not None:
            raise EvidenceBundleErrorV388("EVIDENCE_BUNDLE_ALREADY_CLOSED")
        _iso(closed_at, "CLOSED_AT")
        if closed_at < self.started_at:
            raise EvidenceBundleErrorV388("CLOSED_AT_BEFORE_START")
        self.closed_at = closed_at
        self.state = EvidenceBundleStateV388.CLOSED
        return self.snapshot()

    def invalidate(self, *, reason: str, at: datetime) -> FirstTestnetExecutionEvidenceV388:
        self._ensure_open()
        if not reason:
            raise EvidenceBundleErrorV388("INVALIDATION_REASON_REQUIRED")
        _iso(at, "INVALIDATION_AT")
        self.invalidation_reason = reason
        self.closed_at = at
        self.state = EvidenceBundleStateV388.INVALIDATED
        return self.snapshot()

    def snapshot(self) -> FirstTestnetExecutionEvidenceV388:
        if any(v is None for v in (
            self.connectivity_ref, self.approval_id, self.activation_id,
            self.pre_trade_snapshot_id, self.pre_trade_snapshot_hash,
            self.dispatch_attempt_id, self.order_request_id, self.client_order_id, self.submit_status,
        )):
            raise EvidenceBundleErrorV388("EVIDENCE_BUNDLE_INCOMPLETE")
        provisional = FirstTestnetExecutionEvidenceV388(
            bundle_id=self.bundle_id,
            state=self.state,
            environment=self.environment,
            symbol=self.symbol,
            run_started_at=self.started_at,
            run_closed_at=self.closed_at,
            connectivity_ref=self.connectivity_ref,
            approval_id=self.approval_id,
            activation_id=self.activation_id,
            pre_trade_snapshot_id=self.pre_trade_snapshot_id,
            pre_trade_snapshot_hash=self.pre_trade_snapshot_hash,
            dispatch_attempt_id=self.dispatch_attempt_id,
            order_request_id=self.order_request_id,
            client_order_id=self.client_order_id,
            exchange_order_id=self.exchange_order_id,
            submit_status=self.submit_status,
            order_event_ref=self.order_event_ref,
            account_event_ref=self.account_event_ref,
            reconciliation_ref=self.reconciliation_ref,
            accounting_ref=self.accounting_ref,
            terminal_status=self.terminal_status,
            mutation_performed=self.mutation_performed,
            content_hash="",
            invalidation_reason=self.invalidation_reason,
        )
        fields = dict(provisional.__dict__)
        fields["content_hash"] = _hash(provisional.payload())
        return FirstTestnetExecutionEvidenceV388(**fields)
