from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
from pathlib import Path
from typing import Any

from trading_platform.promotion.contracts import Approval, DeploymentState as RuntimeDeploymentState, GateSummary, ModelRole, OperationalMode, PromotionBundle, ScopeCheck
from trading_platform.promotion.rollout import RolloutPolicy, RuntimeBundleState
from trading_platform.v21.event_store import EventStore
from trading_platform.v28.deployment import DeploymentOrchestrator, DeploymentPhase, DeploymentRequest
from trading_platform.v28.deployment_authority import activation_capability_context, _issue_activation_capability
from trading_platform.v329.dependency_authority import DependencyInvalidationLedger
from trading_platform.v341.compatibility_authority import CompatibilityAuthorityLedger
from trading_platform.v342.artifact_integrity import ArtifactIntegrityAuthorityLedger
from trading_platform.v345.evidence_snapshot_authority import EvidenceSnapshotAuthorityLedger
from trading_platform.v346.promotion_bundle_authority import PromotionBundleAuthorityLedger


class RollbackExerciseError(RuntimeError):
    """The controlled rollback drill failed one or more hard postconditions."""


@dataclass(frozen=True)
class RollbackExerciseResult:
    evidence_class: str
    result: str
    scenario_id: str
    before_phase: str
    after_phase: str
    after_close_phase: str
    risk_before: str
    risk_after: str
    trading_allowed_after: bool
    rollback_event_present: bool
    chain_valid: bool
    closed_without_residual_risk: bool
    source_kind: str
    content_hash: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_class": self.evidence_class,
            "result": self.result,
            "scenario_id": self.scenario_id,
            "before_phase": self.before_phase,
            "after_phase": self.after_phase,
            "after_close_phase": self.after_close_phase,
            "risk_before": self.risk_before,
            "risk_after": self.risk_after,
            "trading_allowed_after": self.trading_allowed_after,
            "rollback_event_present": self.rollback_event_present,
            "chain_valid": self.chain_valid,
            "closed_without_residual_risk": self.closed_without_residual_risk,
            "source_kind": self.source_kind,
            "content_hash": self.content_hash,
        }

    def write_json(self, path: str | Path) -> Path:
        import json
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.as_dict(), sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return target


def _compatible_report() -> Any:
    from trading_platform.promotion.compatibility import Compatibility, CompatibilityReport
    return CompatibilityReport(*(Compatibility.COMPATIBLE for _ in range(7)))


def _build_request(store: EventStore, *, now: datetime) -> DeploymentRequest:
    bundle = PromotionBundle(
        "V368-BUNDLE",
        "STRAT-V368",
        "MODEL-V368",
        "FEATURE-V368",
        "TARGET-V368",
        "CONFIG-V368",
        "EXEC-V368",
        "CODE-V368",
        "SNAP-V368",
        ("G1-V368",),
        ("HASH-V368",),
        "APP-V368",
        {"mode": "CANARY"},
        "ROLLBACK-TARGET-V368",
        "CONTENT-V368",
        now,
    )
    approval = Approval(
        "APP-V368", ("deployment-operator",), now - timedelta(minutes=1), now + timedelta(hours=1), {"mode": "CANARY"}
    )
    runtime = RuntimeBundleState(ModelRole.CHALLENGER, OperationalMode.CANARY, RuntimeDeploymentState.ACTIVE, "HEALTHY", True)

    dependency = DependencyInvalidationLedger(store)
    dependency.assert_clear((bundle.bundle_id, bundle.evidence_snapshot_id, *bundle.gate_results, *bundle.artifact_hashes))

    compatibility = CompatibilityAuthorityLedger(store).authorize(
        authorization_id="V368-COMPAT",
        artifact_id=bundle.bundle_id,
        artifact_hashes=bundle.artifact_hashes,
        code_version=bundle.code_version,
        configuration_version=bundle.configuration_version,
        execution_model_version=bundle.execution_model_version,
        report=_compatible_report(),
        valid_from=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=30),
        reviewer="v368-control-reviewer",
        recorded_at_ms=max(1, int(now.timestamp() * 1000)),
    )[0]

    integrity = ArtifactIntegrityAuthorityLedger(store).authorize(
        authorization_id="V368-INTEGRITY",
        artifact_id=bundle.bundle_id,
        artifact_hashes=bundle.artifact_hashes,
        observed_artifact_hashes=bundle.artifact_hashes,
        manifest_hash="V368-MANIFEST",
        signature_verified=True,
        valid_from=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=30),
        reviewer="v368-control-reviewer",
        recorded_at_ms=max(1, int(now.timestamp() * 1000)),
    )[0]

    evidence_snapshot = {
        "snapshot_id": bundle.evidence_snapshot_id,
        "evidence_ids": ("EV-V368",),
        "metrics": {"evidence_valid": True, "bundle_id": bundle.bundle_id},
        "gates": bundle.gate_results,
        "dependencies": (bundle.bundle_id, bundle.model_version, *bundle.gate_results, "EV-V368"),
        "versions": (
            bundle.strategy_version, bundle.model_version, bundle.feature_version, bundle.target_version,
            bundle.configuration_version, bundle.execution_model_version, bundle.code_version,
        ),
        "hashes": tuple(bundle.artifact_hashes) + (bundle.content_hash,),
        "methodology": ("V368_ROLLBACK_DRILL",),
        "approvals": (bundle.approval_id,),
        "scope": dict(bundle.scope),
    }
    from trading_platform.evidence.snapshot import build_snapshot
    snapshot = build_snapshot(
        evidence_snapshot["snapshot_id"], evidence_snapshot["evidence_ids"], evidence_snapshot["metrics"],
        evidence_snapshot["gates"], evidence_snapshot["dependencies"], evidence_snapshot["versions"],
        evidence_snapshot["hashes"], evidence_snapshot["methodology"], evidence_snapshot["approvals"],
        evidence_snapshot["scope"],
    )
    EvidenceSnapshotAuthorityLedger(store).authorize(
        snapshot=snapshot,
        promotion_id=bundle.bundle_id,
        bundle_id=bundle.bundle_id,
        model_version=bundle.model_version,
        valid_from=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=30),
        reviewer="v368-control-reviewer",
        recorded_at_ms=max(1, int(now.timestamp() * 1000)),
        dependency_authority=dependency,
    )
    PromotionBundleAuthorityLedger.authorize(
        authorization_id="V368-PB",
        bundle=bundle,
        valid_from=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=30),
        reviewer="v368-control-reviewer",
        recorded_at_ms=max(1, int(now.timestamp() * 1000)),
        dependency_authority=dependency,
        store=store,
    )
    return DeploymentRequest(
        "V368-DEPLOY",
        bundle,
        approval,
        GateSummary(bundle.gate_results, bundle.gate_results, ()),
        ScopeCheck(True, "CONTROLLED_DRILL"),
        True,
        True,
        True,
        "deployment-operator",
        Decimal("5"),
        Decimal("10"),
        runtime,
        compatibility.authorization_id,
        integrity.authorization_id,
        "V368-PB",
    )


def run_rollback_exercise(*, now: datetime | None = None, scenario_id: str = "V368-ROLLBACK-EXERCISE") -> RollbackExerciseResult:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    store = EventStore()
    dependency = DependencyInvalidationLedger(store)
    orchestrator = DeploymentOrchestrator(
        policy=RolloutPolicy(Decimal("5"), Decimal("10"), True, True),
        dependency_authority=dependency,
    )
    request = _build_request(store, now=now)
    state = orchestrator.prepare(request, now=now, now_ns=1)
    state = orchestrator.stage(state, now_ns=2)
    state = orchestrator.start_canary(state, now_ns=3)
    capability = _issue_activation_capability(
        deployment_id=request.deployment_id,
        activation_fingerprint="V368-CONTROLLED-DRILL",
        target_mode=request.runtime_state.mode.value,
        effective_risk=state.allocated_risk,
        valid_from=now - timedelta(minutes=1),
        expires_at=now + timedelta(minutes=30),
    )
    with activation_capability_context(capability):
        state = orchestrator.activate(state, now=now, now_ns=4)

    before_phase = state.phase
    risk_before = state.allocated_risk
    state = orchestrator.rollback(state, reason="V368_CONTROLLED_ROLLBACK", now_ns=5)
    rollback_event_present = any(e.event_type.value == "ROLLBACK" for e in state.chain.events)
    state.chain.verify()
    chain_valid = True

    if state.phase is not DeploymentPhase.ROLLED_BACK:
        raise RollbackExerciseError("ROLLBACK_PHASE_POSTCONDITION_FAILED")
    if state.allocated_risk != Decimal("0"):
        raise RollbackExerciseError("ROLLBACK_RISK_NOT_ZERO")
    if state.trading_allowed:
        raise RollbackExerciseError("ROLLBACK_TRADING_REMAINS_ALLOWED")
    if not rollback_event_present:
        raise RollbackExerciseError("ROLLBACK_AUDIT_EVENT_MISSING")

    closed = orchestrator.close(state, now_ns=6)
    if closed.phase is not DeploymentPhase.CLOSED or closed.allocated_risk != Decimal("0") or closed.trading_allowed:
        raise RollbackExerciseError("ROLLBACK_CLOSE_POSTCONDITION_FAILED")
    closed.chain.verify()

    body = {
        "scenario_id": scenario_id,
        "before_phase": before_phase.value,
        "after_phase": state.phase.value,
        "after_close_phase": closed.phase.value,
        "risk_before": str(risk_before),
        "risk_after": str(state.allocated_risk),
        "trading_allowed_after": state.trading_allowed,
        "rollback_event_present": rollback_event_present,
        "chain_valid": chain_valid,
        "closed_without_residual_risk": closed.allocated_risk == Decimal("0") and not closed.trading_allowed,
        "source_kind": "INTERNAL",
    }
    content_hash = hashlib.sha256(str(sorted(body.items())).encode("utf-8")).hexdigest()
    return RollbackExerciseResult(
        evidence_class="ROLLBACK",
        result="PASS",
        scenario_id=scenario_id,
        before_phase=before_phase.value,
        after_phase=state.phase.value,
        after_close_phase=closed.phase.value,
        risk_before=str(risk_before),
        risk_after=str(state.allocated_risk),
        trading_allowed_after=state.trading_allowed,
        rollback_event_present=rollback_event_present,
        chain_valid=chain_valid,
        closed_without_residual_risk=closed.allocated_risk == Decimal("0") and not closed.trading_allowed,
        source_kind="INTERNAL",
        content_hash=content_hash,
    )
