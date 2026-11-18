from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
import json
from functools import wraps
from threading import RLock
from typing import Any, Mapping

from trading_platform.v21.event_store import EventStore, sha256_json
from trading_platform.v24.accounting import (
    AccountingSnapshot,
    AccountingTruth,
    CashComponents,
    PnLView,
    assert_accounting_invariants,
)


class DrawdownHistoryError(RuntimeError):
    """Raised when durable equity history cannot support a current drawdown."""


def _history_locked(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


def _is_sha256(value: str) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class DrawdownAssessment:
    portfolio_id: str
    assessment_id: str
    history_evidence_id: str
    current_snapshot_id: str
    current_snapshot_hash: str
    current_equity: Decimal
    peak_snapshot_id: str
    peak_snapshot_hash: str
    peak_equity: Decimal
    observed_at_ns: int
    valid_until_ns: int
    history_fingerprint: str

    @property
    def drawdown(self) -> Decimal:
        if self.peak_equity <= 0:
            return Decimal("1")
        return max(Decimal("0"), (self.peak_equity - self.current_equity) / self.peak_equity)

    @property
    def source_fingerprint(self) -> str:
        return sha256(json.dumps(self.payload(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def payload(self) -> dict[str, str | int]:
        return {
            "portfolio_id": self.portfolio_id,
            "assessment_id": self.assessment_id,
            "history_evidence_id": self.history_evidence_id,
            "current_snapshot_id": self.current_snapshot_id,
            "current_snapshot_hash": self.current_snapshot_hash,
            "current_equity": str(self.current_equity),
            "peak_snapshot_id": self.peak_snapshot_id,
            "peak_snapshot_hash": self.peak_snapshot_hash,
            "peak_equity": str(self.peak_equity),
            "observed_at_ns": self.observed_at_ns,
            "valid_until_ns": self.valid_until_ns,
            "history_fingerprint": self.history_fingerprint,
            "drawdown": str(self.drawdown),
        }

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "DrawdownAssessment":
        try:
            assessment = cls(
                portfolio_id=str(payload["portfolio_id"]),
                assessment_id=str(payload["assessment_id"]),
                history_evidence_id=str(payload["history_evidence_id"]),
                current_snapshot_id=str(payload["current_snapshot_id"]),
                current_snapshot_hash=str(payload["current_snapshot_hash"]),
                current_equity=Decimal(str(payload["current_equity"])),
                peak_snapshot_id=str(payload["peak_snapshot_id"]),
                peak_snapshot_hash=str(payload["peak_snapshot_hash"]),
                peak_equity=Decimal(str(payload["peak_equity"])),
                observed_at_ns=int(payload["observed_at_ns"]),
                valid_until_ns=int(payload["valid_until_ns"]),
                history_fingerprint=str(payload["history_fingerprint"]),
            )
            if str(payload["drawdown"]) != str(assessment.drawdown):
                raise ValueError("DRAWDOWN_ASSESSMENT_VALUE_MISMATCH")
            if str(payload.get("source_fingerprint", assessment.source_fingerprint)) != assessment.source_fingerprint:
                raise ValueError("DRAWDOWN_ASSESSMENT_FINGERPRINT_MISMATCH")
            if not assessment.is_valid():
                raise ValueError("INVALID_DRAWDOWN_ASSESSMENT")
            return assessment
        except Exception as exc:
            raise DrawdownHistoryError("INVALID_DRAWDOWN_ASSESSMENT_PAYLOAD") from exc

    def is_valid(self) -> bool:
        return (
            isinstance(self.portfolio_id, str) and bool(self.portfolio_id.strip())
            and isinstance(self.assessment_id, str) and bool(self.assessment_id.strip())
            and isinstance(self.history_evidence_id, str) and bool(self.history_evidence_id.strip())
            and isinstance(self.current_snapshot_id, str) and bool(self.current_snapshot_id.strip())
            and isinstance(self.peak_snapshot_id, str) and bool(self.peak_snapshot_id.strip())
            and _is_sha256(self.current_snapshot_hash)
            and _is_sha256(self.peak_snapshot_hash)
            and _is_sha256(self.history_fingerprint)
            and isinstance(self.current_equity, Decimal)
            and self.current_equity.is_finite()
            and isinstance(self.peak_equity, Decimal)
            and self.peak_equity.is_finite()
            and self.peak_equity >= self.current_equity
            and isinstance(self.observed_at_ns, int)
            and not isinstance(self.observed_at_ns, bool)
            and self.observed_at_ns >= 0
            and isinstance(self.valid_until_ns, int)
            and not isinstance(self.valid_until_ns, bool)
            and self.valid_until_ns > self.observed_at_ns
        )

    def source_fresh_at(self, now_ns: int) -> bool:
        return (
            isinstance(now_ns, int)
            and not isinstance(now_ns, bool)
            and self.is_valid()
            and self.observed_at_ns <= now_ns < self.valid_until_ns
        )


class DrawdownHistoryLedger:
    """Durable, hash-chained portfolio equity observations for dynamic drawdown."""

    INITIALIZED = "DRAWDOWN_HISTORY_INITIALIZED"
    OBSERVED = "DRAWDOWN_EQUITY_OBSERVED"

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self._history_evidence_ids: dict[str, str] = {}
        self._lock = RLock()

    @staticmethod
    def _snapshot_payload(snapshot_id: str, snapshot: AccountingSnapshot) -> dict[str, Any]:
        return {"snapshot_id": snapshot_id, "snapshot": snapshot.canonical_payload(), "snapshot_hash": snapshot.state_hash}

    @staticmethod
    def _snapshot_from_payload(payload: Mapping[str, Any]) -> tuple[str, AccountingSnapshot]:
        try:
            raw = dict(payload["snapshot"])
            cash = dict(raw["cash"])
            pnl = dict(raw["pnl"])
            snapshot = AccountingSnapshot(
                timestamp_ns=int(raw["timestamp_ns"]),
                equity=Decimal(str(raw["equity"])),
                cash=CashComponents(
                    pnl=Decimal(str(cash["pnl"])), fees=Decimal(str(cash["fees"])),
                    funding=Decimal(str(cash["funding"])),
                    deposits_withdrawals=Decimal(str(cash["deposits_withdrawals"])),
                    other_events=Decimal(str(cash["other_events"])),
                ),
                pnl=PnLView(**{key: Decimal(str(value)) for key, value in pnl.items()}),
                position_notional=Decimal(str(raw["position_notional"])),
                margin_used=Decimal(str(raw["margin_used"])),
                source=AccountingTruth(str(raw["source"])),
            )
            assert_accounting_invariants(snapshot)
            if snapshot.state_hash != str(payload["snapshot_hash"]):
                raise ValueError("DRAWDOWN_ACCOUNTING_SNAPSHOT_HASH_MISMATCH")
            snapshot_id = str(payload["snapshot_id"])
            if not snapshot_id:
                raise ValueError("DRAWDOWN_SNAPSHOT_ID_REQUIRED")
            return snapshot_id, snapshot
        except Exception as exc:
            raise DrawdownHistoryError("INVALID_DRAWDOWN_EQUITY_EVENT") from exc

    @_history_locked
    def initialize(
        self,
        *,
        portfolio_id: str,
        history_evidence_id: str,
        verified: bool,
        opening_snapshot_id: str,
        opening_snapshot: AccountingSnapshot,
    ) -> bool:
        """Anchor the history to an explicitly declared opening accounting record.

        ``verified`` is a caller assertion, not a cryptographic attestation. Production
        verification still requires a trusted, independently authenticated source.
        """
        if (
            not isinstance(portfolio_id, str) or not portfolio_id.strip()
            or not isinstance(history_evidence_id, str) or not history_evidence_id.strip()
            or verified is not True
            or not isinstance(opening_snapshot_id, str) or not opening_snapshot_id.strip()
        ):
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_INITIALIZATION_EVIDENCE_REQUIRED")
        try:
            assert_accounting_invariants(opening_snapshot)
        except (AssertionError, AttributeError, TypeError) as exc:
            raise DrawdownHistoryError("DRAWDOWN_ACCOUNTING_SNAPSHOT_INVALID") from exc
        aggregate_id = f"portfolio:{portfolio_id}"
        event_id = f"drawdown:initialize:{portfolio_id}"
        payload = {
            "portfolio_id": portfolio_id,
            "history_evidence_id": history_evidence_id,
            "verified": True,
            **self._snapshot_payload(opening_snapshot_id, opening_snapshot),
        }
        if not self.store.verify_chain():
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_CHAIN_INVALID")
        existing = self.store.get(event_id)
        if existing is not None:
            if (
                existing.event_type != self.INITIALIZED
                or existing.aggregate_id != aggregate_id
                or dict(existing.payload) != payload
            ):
                raise DrawdownHistoryError("DRAWDOWN_HISTORY_INITIALIZATION_CONFLICT")
            return False
        if any(event.aggregate_id == aggregate_id for event in self.store.iter_events()):
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_ALREADY_STARTED")
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=opening_snapshot.timestamp_ns // 1_000_000,
            event_type=self.INITIALIZED,
            aggregate_id=aggregate_id,
            payload=payload,
        )
        if result.duplicate:
            if (
                result.event.event_type != self.INITIALIZED
                or result.event.aggregate_id != aggregate_id
                or result.event.occurred_at_ms != opening_snapshot.timestamp_ns // 1_000_000
                or dict(result.event.payload) != payload
            ):
                raise DrawdownHistoryError("DRAWDOWN_HISTORY_INITIALIZATION_CONFLICT")
            return False
        return True

    def _observations(self, portfolio_id: str) -> tuple[tuple[str, AccountingSnapshot], ...]:
        if not self.store.verify_chain():
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_CHAIN_INVALID")
        aggregate_id = f"portfolio:{portfolio_id}"
        events = tuple(event for event in self.store.iter_events() if event.aggregate_id == aggregate_id)
        if not events or events[0].event_type != self.INITIALIZED:
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_INITIALIZATION_REQUIRED")
        initialization = events[0]
        if (
            initialization.event_id != f"drawdown:initialize:{portfolio_id}"
            or str(initialization.payload.get("portfolio_id", "")) != portfolio_id
            or not str(initialization.payload.get("history_evidence_id", "")).strip()
            or initialization.payload.get("verified") is not True
        ):
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_INITIALIZATION_INVALID")
        history_evidence_id = str(initialization.payload["history_evidence_id"])
        rows: list[tuple[str, AccountingSnapshot]] = [self._snapshot_from_payload(initialization.payload)]
        if initialization.occurred_at_ms != rows[0][1].timestamp_ns // 1_000_000:
            raise DrawdownHistoryError("DRAWDOWN_HISTORY_EVENT_TIME_MISMATCH")
        seen: set[str] = set()
        seen.add(rows[0][0])
        for event in events[1:]:
            if event.event_type != self.OBSERVED:
                raise DrawdownHistoryError("DRAWDOWN_HISTORY_EVENT_ORDER_INVALID")
            if str(event.payload.get("portfolio_id", "")) != portfolio_id:
                raise DrawdownHistoryError("DRAWDOWN_PORTFOLIO_ID_MISMATCH")
            snapshot_id, snapshot = self._snapshot_from_payload(event.payload)
            if event.occurred_at_ms != snapshot.timestamp_ns // 1_000_000:
                raise DrawdownHistoryError("DRAWDOWN_HISTORY_EVENT_TIME_MISMATCH")
            if snapshot_id in seen:
                raise DrawdownHistoryError("DUPLICATE_DRAWDOWN_SNAPSHOT_ID")
            if rows and snapshot.timestamp_ns <= rows[-1][1].timestamp_ns:
                raise DrawdownHistoryError("DRAWDOWN_SNAPSHOT_TIME_NOT_INCREASING")
            seen.add(snapshot_id)
            rows.append((snapshot_id, snapshot))
        self._history_evidence_ids[portfolio_id] = history_evidence_id
        return tuple(rows)

    @_history_locked
    def observe(self, *, portfolio_id: str, snapshot_id: str, snapshot: AccountingSnapshot) -> bool:
        if not portfolio_id or not portfolio_id.strip() or not snapshot_id or not snapshot_id.strip():
            raise DrawdownHistoryError("DRAWDOWN_OBSERVATION_IDENTITY_REQUIRED")
        try:
            assert_accounting_invariants(snapshot)
        except (AssertionError, AttributeError, TypeError) as exc:
            raise DrawdownHistoryError("DRAWDOWN_ACCOUNTING_SNAPSHOT_INVALID") from exc
        observations = self._observations(portfolio_id)
        event_id = f"drawdown:snapshot:{portfolio_id}:{snapshot_id}"
        payload = {"portfolio_id": portfolio_id, **self._snapshot_payload(snapshot_id, snapshot)}
        existing = self.store.get(event_id)
        if existing is not None:
            if (
                existing.event_type != self.OBSERVED
                or existing.aggregate_id != f"portfolio:{portfolio_id}"
                or dict(existing.payload) != payload
            ):
                raise DrawdownHistoryError("DRAWDOWN_SNAPSHOT_ID_CONFLICT")
            return False
        if snapshot.timestamp_ns <= observations[-1][1].timestamp_ns:
            raise DrawdownHistoryError("DRAWDOWN_SNAPSHOT_TIME_NOT_INCREASING")
        result = self.store.append(
            event_id=event_id,
            occurred_at_ms=snapshot.timestamp_ns // 1_000_000,
            event_type=self.OBSERVED,
            aggregate_id=f"portfolio:{portfolio_id}",
            payload=payload,
        )
        if result.duplicate:
            if (
                result.event.event_type != self.OBSERVED
                or result.event.aggregate_id != f"portfolio:{portfolio_id}"
                or result.event.occurred_at_ms != snapshot.timestamp_ns // 1_000_000
                or dict(result.event.payload) != payload
            ):
                raise DrawdownHistoryError("DRAWDOWN_SNAPSHOT_ID_CONFLICT")
            return False
        return True

    @_history_locked
    def assess(
        self,
        *,
        portfolio_id: str,
        now_ns: int,
        ttl_ns: int,
        snapshot_id: str | None = None,
    ) -> DrawdownAssessment:
        if not portfolio_id or not portfolio_id.strip():
            raise DrawdownHistoryError("DRAWDOWN_PORTFOLIO_ID_REQUIRED")
        if not isinstance(now_ns, int) or isinstance(now_ns, bool) or now_ns < 0:
            raise DrawdownHistoryError("INVALID_DRAWDOWN_ASSESSMENT_TIME")
        if not isinstance(ttl_ns, int) or isinstance(ttl_ns, bool) or ttl_ns <= 0:
            raise DrawdownHistoryError("INVALID_DRAWDOWN_ASSESSMENT_TTL")
        observations = self._observations(portfolio_id)
        if not observations:
            raise DrawdownHistoryError("DRAWDOWN_EQUITY_HISTORY_REQUIRED")
        if snapshot_id is None:
            current_index = len(observations) - 1
        else:
            current_index = next((i for i, row in enumerate(observations) if row[0] == snapshot_id), -1)
            if current_index < 0:
                raise DrawdownHistoryError("DRAWDOWN_CURRENT_SNAPSHOT_NOT_FOUND")
        current_id, current = observations[current_index]
        if current.timestamp_ns > now_ns:
            raise DrawdownHistoryError("DRAWDOWN_CURRENT_SNAPSHOT_IN_FUTURE")
        valid_until_ns = current.timestamp_ns + ttl_ns
        if now_ns >= valid_until_ns:
            raise DrawdownHistoryError("DRAWDOWN_CURRENT_SNAPSHOT_EXPIRED")
        history = observations[: current_index + 1]
        peak_id, peak = max(history, key=lambda row: (row[1].equity, row[1].timestamp_ns))
        history_fingerprint = sha256_json({
            "portfolio_id": portfolio_id,
            "history_evidence_id": self._history_evidence_ids[portfolio_id],
            "observations": [
                {"snapshot_id": item_id, "snapshot_hash": item.state_hash, "equity": str(item.equity)}
                for item_id, item in history
            ],
        })
        assessment_id = f"DD-{sha256_json({'portfolio_id': portfolio_id, 'current': current.state_hash, 'history': history_fingerprint})[:24]}"
        return DrawdownAssessment(
            portfolio_id=portfolio_id,
            assessment_id=assessment_id,
            history_evidence_id=self._history_evidence_ids[portfolio_id],
            current_snapshot_id=current_id,
            current_snapshot_hash=current.state_hash,
            current_equity=current.equity,
            peak_snapshot_id=peak_id,
            peak_snapshot_hash=peak.state_hash,
            peak_equity=peak.equity,
            observed_at_ns=current.timestamp_ns,
            valid_until_ns=valid_until_ns,
            history_fingerprint=history_fingerprint,
        )
