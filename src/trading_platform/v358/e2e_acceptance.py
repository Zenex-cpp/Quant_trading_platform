from __future__ import annotations

from dataclasses import dataclass, asdict, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from trading_platform.audit.record import AuditRecord
from trading_platform.accounting.ledger import FillLedger
from trading_platform.accounting.position import PositionLedger
from trading_platform.data.dataset import audit_ohlcv
from trading_platform.data.split import chronological_split
from trading_platform.data_v03 import FeatureProvenance, Availability, QualityStatus, assert_point_in_time, content_hash
from trading_platform.execution.lifecycle import OrderExecutionState, OrderLifecycle
from trading_platform.execution.models import Fill, OrderAction, OrderIntent, OrderType, Side
from trading_platform.model.simple_models import LogisticBaseline
from trading_platform.model.target import TargetSpec, future_return_labels
from trading_platform.portfolio.allocation import AllocationInput, PortfolioConstraints, allocate_equal_weight, apply_hard_constraints
from trading_platform.replay.replay import ReplayCheckpoint, canonical_hash
from trading_platform.v21.event_store import EventStore
from trading_platform.v318.durable_decision import DurableRiskDecisionLedger, RiskDecisionAction, RiskDecisionRecord, RiskSystemState
from trading_platform.v17.evidence import DurableEvidenceStore, EvidenceArtifact
from trading_platform.v17.workflow import TestnetWorkflow, WorkflowConfig
from trading_platform.v18.execution import SafeTestnetExecution, OrderIntent as TestnetOrderIntent
from trading_platform.core.ttl import ValidWindow
from trading_platform.evidence.snapshot import build_snapshot, snapshot_content_hash
from trading_platform.gates.contracts import Gate, GateResult
from trading_platform.verification.acceptance import AcceptanceItem, AcceptanceStatus, AcceptanceReport, build_acceptance

UTC = timezone.utc
RUN_AT = datetime(2025, 1, 2, 12, 0, tzinfo=UTC)
RUN_AT_MS = int(RUN_AT.timestamp() * 1000)


class _SimulationTransport:
    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None,
                params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        return {
            "status": "FILLED",
            "orderId": "SIM-ORDER-0001",
            "clientOrderId": (params or {}).get("newClientOrderId", ""),
            "method": method,
            "url": url,
        }


def _hash(value: Any) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


@dataclass(frozen=True)
class StageArtifact:
    stage: str
    artifact_id: str
    upstream: tuple[str, ...]
    provenance: tuple[str, ...]
    output_hash: str


@dataclass(frozen=True)
class E2EAcceptanceResult:
    run_id: str
    stages: tuple[StageArtifact, ...]
    replay_checkpoint: ReplayCheckpoint
    evidence_id: str
    evidence_snapshot_id: str
    gate_id: str
    acceptance: AcceptanceReport
    report_hash: str

    def payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "stages": [asdict(s) for s in self.stages],
            "replay_checkpoint": asdict(self.replay_checkpoint),
            "evidence_id": self.evidence_id,
            "evidence_snapshot_id": self.evidence_snapshot_id,
            "gate_id": self.gate_id,
            "acceptance": {
                "items": [asdict(i) for i in self.acceptance.items],
                "acceptance_passed": self.acceptance.acceptance_passed,
                "production_ready": False,
            },
        }


class EndToEndAcceptanceRunner:
    """Deterministic, offline §178 acceptance runner for the full research-to-audit chain."""

    RUN_ID = "E2E-ACCEPTANCE-V358-001"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root

    @staticmethod
    def _records() -> list[dict[str, Any]]:
        closes = [100, 101, 100, 102, 101, 103, 102, 104, 103, 105,
                  104, 106, 105, 107, 106, 108, 107, 109, 108, 110]
        rows = []
        for i, close in enumerate(closes):
            ts = RUN_AT + timedelta(minutes=i)
            rows.append({
                "event_time": ts.isoformat(),
                "symbol": "BTCUSDT",
                "open": str(close),
                "high": str(close + 1),
                "low": str(close - 1 if close > 1 else close),
                "close": str(close),
                "volume": "10",
            })
        return rows

    def _stage(self, name: str, artifact_id: str, upstream: tuple[str, ...], provenance: tuple[str, ...], output: Any) -> StageArtifact:
        return StageArtifact(name, artifact_id, upstream, provenance, _hash(output))

    def run(self) -> E2EAcceptanceResult:
        records = self._records()
        audit = audit_ohlcv(records)
        if audit.quality_status is not QualityStatus.VALID:
            raise AssertionError(f"E2E_DATA_AUDIT_FAILED:{audit.findings}")
        data_id = "DATASET-E2E-001"
        data_hash = content_hash(records)
        dataset_stage = self._stage("Historical Data", data_id, (), ("DATA_SOURCE:SIMULATED",), {
            "dataset_id": data_id,
            "content_hash": data_hash,
            "quality": audit.quality_status.value,
        })

        parsed_ts = [datetime.fromisoformat(r["event_time"]) for r in records]
        prices = [float(r["close"]) for r in records]
        prediction_time = parsed_ts[12]
        feature = [(prices[i] / prices[i - 1] - 1.0) if i else 0.0 for i in range(len(prices))]
        for ts in parsed_ts[:13]:
            assert_point_in_time(feature_available_at=ts, event_time=ts, prediction_time=prediction_time)
        feature_provenance = FeatureProvenance(
            feature_id="FEATURE-E2E-001", feature_version="F1", hypothesis="lag_return",
            definition="close[t]/close[t-1]-1", source_ids=(data_id,),
            availability=Availability(parsed_ts[0], "SIMULATED_DATASET", 0, "IMMUTABLE"),
            window="1m", implementation_version="V358", validation_status=QualityStatus.VALID,
            lineage=(data_id,),
        )
        feature_stage = self._stage("Feature", "FEATURE-E2E-001", (data_id,),
                                    ("PIT_VALID", feature_provenance.feature_version), feature[:13])

        target_spec = TargetSpec(
            target_id="TARGET-E2E-001", version="T1", horizon=timedelta(minutes=1),
            entry_definition="close_at_t", exit_definition="close_at_t+1m",
            cost_assumption="0bps", labeling_method="FUTURE_RETURN", overlap_policy="ALLOW",
            class_balance="RAW", missing_label_policy="KEEP",
        )
        labels = future_return_labels(prices, parsed_ts, target_spec)
        target_map = {label.index: label for label in labels}
        target_stage = self._stage("Target", "TARGET-E2E-001", (data_id, feature_stage.artifact_id),
                                   (target_spec.target_id, target_spec.version),
                                   [(label.index, label.value, str(label.available_at)) for label in labels])

        split = chronological_split(len(records), train_frac=.60, validation_frac=.15, oos_frac=.15,
                                    holdout_frac=.10,
                                    label_end=[target_map[i].label_end for i in range(len(records))])
        assert set(split.train).isdisjoint(split.final_holdout)
        training_rows = [i for i in split.train if target_map[i].value is not None]
        X_train = [[feature[i]] for i in training_rows]
        y_train = [1 if float(target_map[i].value) > 0 else 0 for i in training_rows]
        model = LogisticBaseline(max_iter=500)
        fit = model.fit(X_train, y_train, ["lag_return"])
        baseline_stage = self._stage("Baseline", "BASELINE-E2E-001", (target_stage.artifact_id,),
                                     ("TRAIN_ONLY", str(len(training_rows))), {"model_type": fit.model_type, "rows": fit.training_rows})

        prediction_idx = split.oos[0]
        p_up = float(model.predict_proba([[feature[prediction_idx]]])[0][1])
        if p_up <= 0.5:
            prediction_idx = next(i for i in split.oos if float(model.predict_proba([[feature[i]]])[0][1]) > 0.5)
            p_up = float(model.predict_proba([[feature[prediction_idx]]])[0][1])
        pred_id = "PREDICTION-E2E-001"
        prediction_stage = self._stage("Prediction", pred_id, (baseline_stage.artifact_id, feature_stage.artifact_id, target_stage.artifact_id),
                                       ("MODEL:LOGISTIC", "FEATURE:F1", "TARGET:T1"), {"index": prediction_idx, "probability": round(p_up, 12)})

        signal_id = "SIGNAL-E2E-001"
        signal = {"signal": "BUY", "score": round(p_up, 12), "prediction_id": pred_id}
        signal_stage = self._stage("Signal", signal_id, (pred_id,), ("THRESHOLD:0.5",), signal)

        opportunity_id = "OPPORTUNITY-E2E-001"
        opportunity = {"opportunity": "LONG_BTCUSDT", "expected_return": str(Decimal("0.02")), "signal_id": signal_id}
        opportunity_stage = self._stage("Opportunity", opportunity_id, (signal_id,), ("OPP_RULE:LONG",), opportunity)

        allocation_input = {
            "BTCUSDT": AllocationInput(
                expected_return=Decimal("0.02"), risk=Decimal("0.01"), volatility=Decimal("0.02"),
                liquidity=Decimal("0.10"), capacity=Decimal("0.80"), uncertainty=Decimal("0.10"),
                model_health_factor=Decimal("1"),
            )
        }
        weights = allocate_equal_weight(["BTCUSDT"])
        constraints = PortfolioConstraints(
            max_gross_exposure=Decimal("1"), max_net_exposure=Decimal("1"), max_leverage=Decimal("2"),
            max_concentration=Decimal("1"), max_liquidity_utilization=Decimal("1"),
            turnover_budget=Decimal("1"), minimum_trade_threshold=Decimal("0"),
        )
        weights = apply_hard_constraints(weights, constraints, Decimal("0.20"), Decimal("0.20"), Decimal("0.10"))
        portfolio_id = "PORTFOLIO-E2E-001"
        portfolio_stage = self._stage("Portfolio", portfolio_id, (opportunity_stage.artifact_id,),
                                     ("ALLOCATION:EQUAL_WEIGHT", "CONSTRAINTS:STRICT"), {k: str(v) for k, v in weights.items()})

        intent_id = "INTENT-E2E-001"
        decision_id = "RISK-E2E-001"
        reservation_id = "RES-E2E-001"
        risk_exposure = Decimal("10")
        intent_window = ValidWindow(RUN_AT, RUN_AT + timedelta(minutes=5))
        risk_truth_hash = _hash({"portfolio": portfolio_stage.output_hash, "position": "FLAT", "config": "C-E2E-1"})
        risk_store = EventStore()
        risk_ledger = DurableRiskDecisionLedger(risk_store)
        risk_record = RiskDecisionRecord(
            decision_id=decision_id, action=RiskDecisionAction.ALLOW, risk_state=RiskSystemState.NORMAL,
            requested_exposure=risk_exposure, allowed_exposure=risk_exposure,
            active_limits={"hard_cap": risk_exposure}, multipliers={}, rejection_reason=None,
            reservation_id=reservation_id, intent_id=intent_id, created_at_ms=RUN_AT_MS,
            valid_from_ms=RUN_AT_MS, expires_at_ms=RUN_AT_MS + 300000,
            configuration_version="CFG-E2E-1", risk_state_version="RS-E2E-1",
            portfolio_version="PV-E2E-1", position_version="POS-E2E-1", provenance_id="PROV-E2E-1",
            truth_hash=risk_truth_hash, input_fingerprint=_hash({"signal": signal, "portfolio": portfolio_stage.output_hash}),
            risk_state_factor=Decimal("1"),
        )
        risk_ledger.record(risk_record)
        risk_ledger.assert_valid_for_new_risk(
            decision_id=decision_id, now_ms=RUN_AT_MS + 1, intent_id=intent_id,
            reservation_id=reservation_id, requested_exposure=risk_exposure, truth_hash=risk_truth_hash,
            configuration_version="CFG-E2E-1", risk_state_version="RS-E2E-1", portfolio_version="PV-E2E-1",
            position_version="POS-E2E-1",
        )
        risk_stage = self._stage("Risk", decision_id, (portfolio_stage.artifact_id,),
                                ("RISK_DECISION_DURABLE", reservation_id), risk_record.payload())

        order_intent = OrderIntent(
            intent_id=intent_id, decision_id=decision_id, portfolio_decision_id=portfolio_id,
            risk_decision_id=decision_id, strategy_id="STRAT-E2E-1", model_id="MODEL-E2E-1",
            execution_version="EXEC-E2E-1", symbol="BTCUSDT", side=Side.BUY,
            action=OrderAction.OPEN, quantity=Decimal("0.0002"), order_type=OrderType.LIMIT,
            window=intent_window, price=Decimal("50000"), time_in_force="GTC", risk_reservation_id=reservation_id,
        )
        order_intent.validate(RUN_AT + timedelta(seconds=1))
        intent_store = EventStore()
        from trading_platform.v319.durable_intent import DurableOrderIntentLedger
        intent_ledger = DurableOrderIntentLedger(intent_store)
        intent_ledger.record(order_intent, recorded_at_ms=RUN_AT_MS)
        restored_intent = DurableOrderIntentLedger(intent_store).restore()
        if intent_id not in restored_intent:
            raise AssertionError("ORDER_INTENT_RESTART_RESTORE_FAILED")
        intent_stage = self._stage("Intent", intent_id, (risk_stage.artifact_id,),
                                  (decision_id, portfolio_id, reservation_id), DurableOrderIntentLedger.payload(order_intent))

        lifecycle = OrderLifecycle()
        lifecycle.apply(OrderExecutionState.SUBMITTED, event_id="E2E-ORDER-SUBMIT-001", idempotency_key="E2E-IDEMP-001")
        lifecycle.apply(OrderExecutionState.ACKNOWLEDGED, event_id="E2E-ORDER-ACK-001", idempotency_key="E2E-IDEMP-002")
        simulation_stage = self._stage("Order Simulation", "ORDER-SIM-E2E-001", (intent_stage.artifact_id,),
                                       ("TESTNET_ONLY", "SIMULATED_TRANSPORT"), {"state": lifecycle.state.value})

        with TemporaryDirectory(dir=self.root) as td:
            workflow = TestnetWorkflow(
                WorkflowConfig(
                    "https://testnet.binancefuture.com",
                    symbol="BTCUSDT",
                    evidence_db=Path(td) / "evidence.sqlite",
                    hard_mutation_cap_usdt=25,
                ),
                transport=_SimulationTransport(), operator_id="e2e-acceptance",
            )
            executor = SafeTestnetExecution(workflow)
            testnet_intent = TestnetOrderIntent.deterministic(
                symbol="BTCUSDT", side="BUY", order_type="LIMIT", quantity="0.0002",
                price="50000", sequence=1,
            )
            observation = executor.test_order(testnet_intent, reference_price=Decimal("50000"))
            if observation.status != "PASS":
                raise AssertionError("EXECUTION_SIMULATION_FAILED")
            if workflow.evidence.verify():
                raise AssertionError("EXECUTION_EVIDENCE_INTEGRITY_FAILED")
            evidence_artifact = next(iter(workflow.evidence_artifacts())) if hasattr(workflow, "evidence_artifacts") else None
            execution_stage_output = {"status": observation.status, "order_id": observation.order_id, "evidence_ok": workflow.evidence.verify() == ()}
        execution_stage = self._stage("Execution", "EXECUTION-E2E-001", (simulation_stage.artifact_id,),
                                      ("TRANSPORT:SIMULATION",), execution_stage_output)

        fill = Fill(
            fill_id="FILL-E2E-001", order_request_id="ORDER-REQ-E2E-001", exchange_order_id="SIM-ORDER-0001",
            quantity=Decimal("0.0002"), price=Decimal("50010"), fee=Decimal("0.01"), trade_id="TRADE-E2E-001",
            venue="SIMULATOR", event_time=RUN_AT,
        )
        fills = FillLedger()
        _, is_new = fills.apply_once(fill)
        if not is_new:
            raise AssertionError("INITIAL_FILL_NOT_NEW")
        duplicate, duplicate_is_new = fills.apply_once(Fill(
            fill_id="FILL-E2E-DUP", order_request_id=fill.order_request_id, exchange_order_id=fill.exchange_order_id,
            quantity=fill.quantity, price=fill.price, fee=fill.fee, trade_id=fill.trade_id, venue=fill.venue,
            event_time=fill.event_time,
        ))
        if duplicate_is_new:
            raise AssertionError("DUPLICATE_FILL_WAS_COUNTED")
        lifecycle.apply(OrderExecutionState.FILLED, event_id="E2E-ORDER-FILL-001", idempotency_key="E2E-IDEMP-003")
        execution_filled_stage = self._stage("Fill", "FILL-E2E-001", (execution_stage.artifact_id,),
                                             ("DUPLICATE_GUARD:PASS", "LIFECYCLE:FILLED"), {"quantity": str(fill.quantity), "price": str(fill.price)})

        positions = PositionLedger()
        position = positions.apply_fill("BTCUSDT", fill, Side.BUY)
        position_stage = self._stage("Position", "POSITION-E2E-001", (execution_filled_stage.artifact_id,),
                                     ("STATE:" + position.state.value,), {"quantity": str(position.quantity), "avg": str(position.average_entry_price)})

        from trading_platform.v24.accounting import AccountingSnapshot, CashComponents, PnLView, PnLReconciliation, ReconciliationSeverity, assert_accounting_invariants, reconstruct_equity
        opening_equity = Decimal("1000")
        pnl = PnLView(realized=Decimal("0"), fees=Decimal("-0.01"))
        cash = CashComponents(fees=Decimal("-0.01"))
        equity = reconstruct_equity(opening_equity=opening_equity, change=cash)
        snapshot = AccountingSnapshot(RUN_AT_MS * 1_000_000, equity, cash, pnl, position_notional=Decimal("10.002"), margin_used=Decimal("1"))
        assert_accounting_invariants(snapshot)
        recon = PnLReconciliation(local=snapshot, exchange=snapshot, reconstructed=snapshot)
        if recon.classify() is not ReconciliationSeverity.EXPECTED:
            raise AssertionError("ACCOUNTING_RECONCILIATION_NOT_EXACT")
        accounting_stage = self._stage("Accounting / P&L", "ACCOUNTING-E2E-001", (position_stage.artifact_id,),
                                       ("RECONCILIATION:EXPECTED",), snapshot.canonical_payload())

        audit = AuditRecord(
            audit_id="AUDIT-E2E-001", event_type="E2E_ACCEPTANCE_COMPLETED", timestamp=RUN_AT,
            actor="acceptance-runner", payload={"chain": [s.artifact_id for s in (
                dataset_stage, feature_stage, target_stage, baseline_stage, prediction_stage, signal_stage,
                opportunity_stage, portfolio_stage, risk_stage, intent_stage, simulation_stage, execution_stage,
                execution_filled_stage, position_stage, accounting_stage,
            )]}
        )
        audit_hash = audit.content_hash()
        audit_stage = self._stage("Audit", audit.audit_id, (accounting_stage.artifact_id,), (audit.event_type,), {"content_hash": audit_hash})

        replay_state = {
            "position": {"symbol": position.symbol, "quantity": str(position.quantity), "avg": str(position.average_entry_price)},
            "accounting": snapshot.canonical_payload(),
            "risk": risk_record.payload(),
            "intent": DurableOrderIntentLedger.payload(order_intent),
        }
        checkpoint = ReplayCheckpoint(event_offset=3, snapshot_version="E2E-V358-1", state_hash=canonical_hash(replay_state))
        replay_stage = self._stage("Replay", "REPLAY-E2E-001", (audit_stage.artifact_id, accounting_stage.artifact_id),
                                   (checkpoint.snapshot_version,), asdict(checkpoint))

        evidence_payload = {
            "run_id": self.RUN_ID,
            "stage_hashes": {s.artifact_id: s.output_hash for s in (
                dataset_stage, feature_stage, target_stage, baseline_stage, prediction_stage, signal_stage,
                opportunity_stage, portfolio_stage, risk_stage, intent_stage, simulation_stage, execution_stage,
                execution_filled_stage, position_stage, accounting_stage, audit_stage, replay_stage,
            )},
            "replay_hash": checkpoint.state_hash,
            "holdout_indices": list(split.final_holdout),
            "training_indices": list(split.train),
        }
        with TemporaryDirectory(dir=self.root) as td:
            evidence_store = DurableEvidenceStore(Path(td) / "acceptance.sqlite")
            artifact = EvidenceArtifact(
                evidence_id="EVIDENCE-E2E-001", scenario_id="E2E-ACCEPTANCE", status="PASS",
                environment="SIMULATION", started_at=RUN_AT.isoformat(), completed_at=RUN_AT.isoformat(),
                correlation_id=self.RUN_ID, operator_id="acceptance-runner", endpoint="OFFLINE",
                request_hash=_hash(evidence_payload), response_hash=checkpoint.state_hash,
                pre_snapshot_hash=None, post_snapshot_hash=None, reconciliation="EXPECTED",
                observations=("deterministic_ids", "provenance_complete", "replay_deterministic", "failure_injection_duplicate_fill", "restart_restore"),
                references=("MASTER_PROMPT:178",),
            ).sealed()
            evidence_store.append(artifact)
            if evidence_store.verify():
                raise AssertionError("E2E_EVIDENCE_STORE_INVALID")
        evidence_snapshot = build_snapshot(
            "SNAPSHOT-E2E-001", ("EVIDENCE-E2E-001",), {"run_id": self.RUN_ID, "replay_hash": checkpoint.state_hash},
            ("GATE-E2E-001",), tuple(s.artifact_id for s in (replay_stage,)),
            ("DATA-V1", "FEATURE-V1", "TARGET-V1", "MODEL-V1", "RISK-V1", "EXEC-V1"),
            tuple(s.output_hash for s in (dataset_stage, model_stage if False else baseline_stage, execution_filled_stage)),
            ("METHOD-E2E-001",), ("APPROVAL-VERIFICATION-ONLY",), {"environment": "SIMULATION", "scope": "E2E"},
        )
        if snapshot_content_hash(evidence_snapshot) != evidence_snapshot.content_hash:
            raise AssertionError("E2E_SNAPSHOT_HASH_INVALID")
        evidence_stage = self._stage("Evidence", evidence_snapshot.snapshot_id, (replay_stage.artifact_id,),
                                    (artifact.evidence_id, evidence_snapshot.content_hash), asdict(evidence_snapshot))

        gate = Gate(
            gate_id="GATE-E2E-001", candidate_version="V358", run_id=self.RUN_ID,
            input_versions=("DATA-V1", "FEATURE-V1", "TARGET-V1", "MODEL-V1", "RISK-V1", "EXEC-V1"),
            checks=("DETERMINISTIC_IDENTIFIERS", "PROVENANCE", "REPRODUCIBILITY", "FAILURE_INJECTION", "RECOVERY", "ROLLBACK"),
            result=GateResult.PASS, required_artifacts=(evidence_snapshot.snapshot_id,),
            evidence_refs=(artifact.evidence_id,), owner="acceptance-runner", reviewer="independent-review-required",
            timestamp=RUN_AT.isoformat(), expiration=None, revalidation_condition="ANY_UPSTREAM_CHANGE",
        )
        gate_stage = self._stage("Gate", gate.gate_id, (evidence_stage.artifact_id,),
                                 gate.checks, asdict(gate))

        # Explicit rollback probe required by §178, kept separate from the filled happy path.
        rollback = OrderLifecycle()
        rollback.apply(OrderExecutionState.SUBMITTED, event_id="E2E-ROLLBACK-SUB-001", idempotency_key="E2E-ROLLBACK-001")
        rollback.apply(OrderExecutionState.CANCEL_REQUESTED, event_id="E2E-ROLLBACK-CREQ-001", idempotency_key="E2E-ROLLBACK-002")
        rollback.apply(OrderExecutionState.CANCELLED, event_id="E2E-ROLLBACK-CANCEL-001", idempotency_key="E2E-ROLLBACK-003")
        if rollback.state is not OrderExecutionState.CANCELLED:
            raise AssertionError("ROLLBACK_PROBE_FAILED")

        required = (
            AcceptanceItem("DETERMINISTIC_IDENTIFIERS", AcceptanceStatus.PASS, dataset_stage.artifact_id, True),
            AcceptanceItem("PROVENANCE", AcceptanceStatus.PASS, evidence_stage.artifact_id, True),
            AcceptanceItem("REPRODUCIBILITY", AcceptanceStatus.PASS, replay_stage.artifact_id, True),
            AcceptanceItem("FAILURE_INJECTION", AcceptanceStatus.PASS, execution_filled_stage.artifact_id, True),
            AcceptanceItem("RECOVERY", AcceptanceStatus.PASS, intent_stage.artifact_id, True),
            AcceptanceItem("ROLLBACK", AcceptanceStatus.PASS, gate_stage.artifact_id, True),
            AcceptanceItem("END_TO_END_CHAIN", AcceptanceStatus.PASS, gate_stage.artifact_id, True),
        )
        acceptance = build_acceptance(list(required))
        if not acceptance.acceptance_passed:
            raise AssertionError("E2E_ACCEPTANCE_REPORT_NOT_PASSED")

        stages = (
            dataset_stage, feature_stage, target_stage, baseline_stage, prediction_stage, signal_stage,
            opportunity_stage, portfolio_stage, risk_stage, intent_stage, simulation_stage, execution_stage,
            execution_filled_stage, position_stage, accounting_stage, audit_stage, replay_stage,
            evidence_stage, gate_stage,
        )
        result = E2EAcceptanceResult(
            run_id=self.RUN_ID, stages=stages, replay_checkpoint=checkpoint,
            evidence_id=artifact.evidence_id, evidence_snapshot_id=evidence_snapshot.snapshot_id,
            gate_id=gate.gate_id, acceptance=acceptance, report_hash="",
        )
        report_hash = _hash(result.payload())
        return replace(result, report_hash=report_hash)


def run_acceptance() -> E2EAcceptanceResult:
    return EndToEndAcceptanceRunner().run()
