from datetime import datetime, timezone

from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.v21.event_store import EventStore
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v408.gate_promotion import GatePromotionAuthorizationLedgerV408


def register_pass_gates(
    *,
    store: EventStore,
    dependency_authority: DependencyInvalidationLedger,
    gate_ids: tuple[str, ...],
    candidate_version: str,
    now: datetime,
    recorded_at_ms: int,
    run_prefix: str,
) -> tuple[str, ...]:
    if now.tzinfo is None:
        raise ValueError("TEST_GATE_NOW_TIMEZONE_REQUIRED")
    ledger = GatePromotionAuthorizationLedgerV408(store)
    authorization_ids = []
    for gate_id in gate_ids:
        gate = Gate(
            gate_id=gate_id,
            candidate_version=candidate_version,
            run_id=f"{run_prefix}:{gate_id}",
            input_versions=(candidate_version,),
            checks=("M7_REQUIRED_GATE_PASS",),
            result=GateResult.PASS,
            required_artifacts=(f"artifact:{gate_id}",),
            evidence_refs=(f"evidence:{gate_id}",),
            owner="test-owner",
            reviewer="test-reviewer",
            timestamp=now.astimezone(timezone.utc).isoformat(),
            expiration=None,
            revalidation_condition="rerun after any dependency change",
        )
        authorization = ledger.authorize(
            gate=gate,
            dependency_authority=dependency_authority,
            recorded_at_ms=recorded_at_ms,
        )
        authorization_ids.append(authorization.authorization_id)
    return tuple(authorization_ids)
