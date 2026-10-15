#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from trading_platform.execution.models import OrderAction, OrderIntent, OrderType, Side
from trading_platform.core.ttl import ValidWindow
from trading_platform.v35.binance_execution import RuntimeCredentialValues, SubmitObservation, ExchangeOutcome
from trading_platform.v384 import (
    ActivationStatusV384,
    BinanceTestnetExecutionAdapterV384,
    ConnectivityProofV384,
    OperatorApprovalV384,
    TestnetExecutionActivationAuthorityV384,
    TestnetExecutionActivationConfigV384,
)

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


class FakeGateway:
    def __init__(self):
        self.calls = []

    def submit(self, order, *, credentials):
        self.calls.append((order, credentials))
        return SubmitObservation(
            ExchangeOutcome.ACKNOWLEDGED,
            order.client_order_id,
            "LOCAL-TESTNET-ORDER-1",
            raw={"status": "NEW"},
        )


def make_intent(quantity=Decimal("0.0002"), symbol="BTCUSDT"):
    return OrderIntent(
        intent_id="I-V384-EVIDENCE-001",
        decision_id="D-V384-EVIDENCE-001",
        portfolio_decision_id="P-V384-EVIDENCE-001",
        risk_decision_id="R-V384-EVIDENCE-001",
        strategy_id="S-V384-EVIDENCE",
        model_id="M-V384-EVIDENCE",
        execution_version="V384-ACTIVATION-1",
        symbol=symbol,
        side=Side.BUY,
        action=OrderAction.OPEN,
        quantity=quantity,
        order_type=OrderType.LIMIT,
        window=ValidWindow(NOW, NOW + timedelta(minutes=5)),
        price=Decimal("50000"),
        time_in_force="GTC",
        risk_reservation_id="RR-V384-EVIDENCE-001",
    )


def authority():
    return TestnetExecutionActivationAuthorityV384(
        TestnetExecutionActivationConfigV384(
            activation_ttl_s=300,
            max_notional=Decimal("25"),
            allowed_symbols=("BTCUSDT",),
        ),
        clock=lambda: NOW,
    )


def main() -> int:
    a = authority()
    checks = []

    not_verified = ConnectivityProofV384(
        status="NOT_VERIFIED", evidence_hash="LIVE-NOT-VERIFIED", verified_at=NOW,
        expires_at=NOW + timedelta(minutes=5), rest_endpoint="https://testnet.binancefuture.com", clock_skew_ms=0,
    )
    try:
        a.activate(connectivity=not_verified, approval=OperatorApprovalV384("APR-1", "operator", "TESTNET_ORDER_MUTATION", NOW, NOW + timedelta(minutes=5), "evidence"), reconciliation_state="GREEN", now=NOW)
        blocked = False
    except PermissionError:
        blocked = True
    checks.append({"check": "unverified_connectivity_blocks_activation", "pass": blocked})

    good = ConnectivityProofV384(
        status="VERIFIED", evidence_hash="LOCAL-VERIFIED-EVIDENCE", verified_at=NOW,
        expires_at=NOW + timedelta(minutes=10), rest_endpoint="https://testnet.binancefuture.com", clock_skew_ms=20,
    )
    approval = OperatorApprovalV384("APR-1", "operator", "TESTNET_ORDER_MUTATION", NOW, NOW + timedelta(minutes=10), "controlled testnet verification")
    snap = a.activate(connectivity=good, approval=approval, reconciliation_state="GREEN", now=NOW)
    checks.append({"check": "verified_connectivity_approval_reconciliation_activate", "pass": snap.status is ActivationStatusV384.ACTIVE and bool(snap.activation_id) and snap.connectivity_evidence_hash == good.evidence_hash})
    checks.append({"check": "activation_ttl_bound", "pass": snap.expires_at == NOW + timedelta(minutes=5)})
    checks.append({"check": "symbol_allowlist", "pass": not a.authorize(intent=make_intent(symbol="ETHUSDT"), now=NOW).allowed})
    checks.append({"check": "notional_hard_ceiling", "pass": not a.authorize(intent=make_intent(quantity=Decimal("0.001")), now=NOW).allowed})
    checks.append({"check": "valid_intent_authorized", "pass": a.authorize(intent=make_intent(), now=NOW).allowed})

    gateway = FakeGateway()
    adapter = BinanceTestnetExecutionAdapterV384(gateway, a)  # type: ignore[arg-type]
    creds = RuntimeCredentialValues(api_key="LOCAL_API_KEY", api_secret=b"LOCAL_SECRET")
    obs = adapter.submit(make_intent(), credentials=creds, now=NOW)
    checks.append({"check": "adapter_requires_and_uses_active_activation", "pass": obs.outcome is ExchangeOutcome.ACKNOWLEDGED and len(gateway.calls) == 1})
    checks.append({"check": "credentials_not_retained_by_authority", "pass": "LOCAL_API_KEY" not in json.dumps(a.audit_events()) and "LOCAL_SECRET" not in json.dumps(a.audit_events())})

    halted = a.halt("RECONCILIATION_DRIFT", now=NOW + timedelta(seconds=1))
    checks.append({"check": "kill_switch_blocks_new_risk", "pass": halted.status is ActivationStatusV384.HALTED and not a.authorize(intent=make_intent(), now=NOW + timedelta(seconds=1)).allowed})

    live = json.loads((ROOT / "V383_TESTNET_CONNECTIVITY_EVIDENCE.json").read_text()) if (ROOT / "V383_TESTNET_CONNECTIVITY_EVIDENCE.json").exists() else {"status": "NOT_VERIFIED"}
    payload = {
        "artifact_type": "V384_TESTNET_EXECUTION_ACTIVATION_EVIDENCE",
        "schema_version": "V384_EXECUTION_ACTIVATION_1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "local_status": "PASS" if all(c["pass"] for c in checks) else "FAIL",
        "local_checks": checks,
        "live_connectivity_status": live.get("status", "NOT_VERIFIED"),
        "live_connectivity_reason": live.get("reason", live.get("error")),
        "mutating_testnet_api_called": False,
        "production_endpoint_accepted": False,
        "credentials_in_evidence": False,
        "production_ready": False,
        "activation_status_after_kill": halted.status.value,
        "audit_event_count": len(a.audit_events()),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    payload["evidence_hash"] = hashlib.sha256(canonical).hexdigest()
    out = ROOT / "V384_TESTNET_EXECUTION_ACTIVATION_EVIDENCE.json"
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(out)
    print(payload["local_status"])
    print(payload["evidence_hash"])
    print(payload["live_connectivity_status"])
    return 0 if payload["local_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
