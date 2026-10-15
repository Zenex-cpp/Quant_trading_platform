from __future__ import annotations
import argparse
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from trading_platform.promotion.contracts import Approval, GateSummary, PromotionBundle, ScopeCheck, ModelRole, OperationalMode, DeploymentState
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentRequest


def build_request() -> DeploymentRequest:
    now = datetime.now(timezone.utc)
    bundle = PromotionBundle(
        "DEMO-BUNDLE", "S1", "M1", "F1", "T1", "C1", "EXEC1", "CODE1", "SNAP1",
        ("GATE-A",), ("ARTIFACT-A",), "APPROVAL-1", {"mode": "CANARY"}, "ROLLBACK-1", "demo",
        now,
    )
    approval = Approval("APPROVAL-1", ("operator-demo",), now - timedelta(seconds=1), now + timedelta(hours=1), {})
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, DeploymentState.ACTIVE, "HEALTHY", True)
    return DeploymentRequest(
        "DEPLOYMENT-DEMO", bundle, approval, GateSummary(("GATE-A",), ("GATE-A",), ()),
        ScopeCheck(True, "SCOPE_VALID"), True, True, True, "operator-demo", Decimal("10"), Decimal("50"), runtime,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.8 offline deployment-orchestration demo")
    parser.add_argument("--plan", action="store_true", help="print the safe offline deployment lifecycle")
    args = parser.parse_args()
    if not args.plan:
        parser.error("V2.8 is offline-only; run with --plan")
    r = build_request()
    o = DeploymentOrchestrator(policy=RolloutPolicy(Decimal("10"), Decimal("100")))
    now = datetime.now(timezone.utc)
    s = o.prepare(r, now=now, now_ns=1)
    s = o.stage(s, now_ns=2)
    s = o.start_canary(s, now_ns=3)
    print(f"deployment_id={s.request.deployment_id}")
    print(f"phase={s.phase.value}")
    print(f"allocated_risk={s.allocated_risk}")
    print(f"trading_allowed={s.trading_allowed}")
    print("network_access=NONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
