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
from trading_platform.data.dataset import audit_ohlcv
from trading_platform.data.split import chronological_split
from trading_platform.data_v03 import FeatureProvenance, Availability, QualityStatus, assert_point_in_time, content_hash
from trading_platform.execution.lifecycle import OrderExecutionState, OrderLifecycle
from trading_platform.execution.models import Fill, OrderAction, OrderIntent, OrderType, Side
from trading_platform.model.simple_models import LogisticBaseline
from trading_platform.model.target import TargetSpec, future_return_labels
from trading_platform.portfolio.allocation import PortfolioConstraints, allocate_equal_weight, apply_hard_constraints
from trading_platform.replay.replay import ReplayCheckpoint, canonical_hash
from trading_platform.v21.event_store import EventStore
from trading_platform.v318.durable_decision import (
    DurableRiskDecisionLedger,
    RiskDecisionAction,
    RiskDecisionConflict,
    RiskDecisionRecord,
    RiskSystemState,
)
from trading_platform.v315.durable_accounting import (
    AccountingConflict,
    AccountingReconciliation,
    DurableAccountingLedger,
    DurableFill,
    ExchangeAccountingSnapshot,
    prove_recovery,
)
from trading_platform.v339.fill_authority import DurableFillAuthority, FillIdentityConflict
from trading_platform.v368.rollback_exercise import run_rollback_exercise
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
    gate_required_artifacts: tuple[str, ...]
    training_target_indices: tuple[int, ...]
    final_holdout_target_count: int
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
            "gate_required_artifacts": list(self.gate_required_artifacts),
            "training_target_indices": list(self.training_target_indices),
            "final_holdout_target_count": self.final_holdout_target_count,
            "environment": "OFFLINE_SIMULATION",
            "external_evidence": False,
            "activation_flag": "NOT_SET",
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
            "row_count": len(records),
        })
        validation_output = audit.to_dict()
        validation_output.update({
            "dataset_id": data_id,
            "source_content_hash": data_hash,
            "accepted": True,
        })
        validation_stage = self._stage(
            "Validation", "VALIDATION-E2E-001", (dataset_stage.artifact_id,),
            ("QUALITY_STATUS:VALID", "DUPLICATES:0", "TIME_ORDER:STRICT"), validation_output,
        )

        parsed_ts = [datetime.fromisoformat(r["event_time"]) for r in records]
        target_spec = TargetSpec(
            target_id="TARGET-E2E-001", version="T1", horizon=timedelta(minutes=1),
            entry_definition="close_at_t", exit_definition="close_at_t+1m",
            cost_assumption="0bps", labeling_method="FUTURE_RETURN", overlap_policy="ALLOW",
            class_balance="RAW", missing_label_policy="KEEP",
        )
        label_end = [parsed_ts[min(i + 1, len(parsed_ts) - 1)] for i in range(len(parsed_ts))]
        split = chronological_split(
            len(records), train_frac=.60, validation_frac=.15, oos_frac=.15,
            holdout_frac=.10, event_time=parsed_ts, label_end=label_end,
        )
        assert set(split.train).isdisjoint(split.final_holdout)
        if not split.oos:
            raise AssertionError("E2E_OOS_SPLIT_EMPTY_AFTER_PURGE")

        # Features are materialized only through OOS. The final holdout remains
        # outside both the feature artifact and the target-label construction.
        feature_indices = tuple(sorted(set(split.train) | set(split.validation) | set(split.oos)))
        feature_values = {
            index: (
                float(records[index]["close"]) / float(records[index - 1]["close"]) - 1.0
                if index else 0.0
            )
            for index in feature_indices
        }
        for index in feature_indices:
            assert_point_in_time(
                feature_available_at=parsed_ts[index],
                event_time=parsed_ts[index],
                prediction_time=parsed_ts[index],
            )
        feature_provenance = FeatureProvenance(
            feature_id="FEATURE-E2E-001", feature_version="F1", hypothesis="lag_return",
            definition="close[t]/close[t-1]-1", source_ids=(data_id,),
            availability=Availability(parsed_ts[0], "SIMULATED_DATASET", 0, "IMMUTABLE"),
            window="1m", implementation_version="V358", validation_status=QualityStatus.VALID,
            lineage=(data_id,),
        )
        feature_stage = self._stage(
            "Feature", "FEATURE-E2E-001", (validation_stage.artifact_id,),
            ("PIT_VALID", feature_provenance.feature_version, "FINAL_HOLDOUT_EXCLUDED"),
            {str(i): feature_values[i] for i in feature_indices},
        )

        # Only construct labels in the raw training partition. Validation, OOS,
        # and final-holdout target values stay outside the fit and prediction path.
        raw_train_end = int(len(records) * .60)
        training_prices = [float(records[i]["close"]) for i in range(raw_train_end)]
        training_times = parsed_ts[:raw_train_end]
        training_labels = future_return_labels(training_prices, training_times, target_spec)
        target_map = {label.index: label for label in training_labels}
        training_rows = [
            i for i in split.train
            if i in target_map and target_map[i].value is not None
        ]
        if not training_rows:
            raise AssertionError("E2E_TRAINING_TARGETS_EMPTY_AFTER_PURGE")
        target_stage = self._stage(
            "Target", "TARGET-E2E-001", (feature_stage.artifact_id, validation_stage.artifact_id),
            (target_spec.target_id, target_spec.version, "TRAIN_ONLY"),
            [(i, target_map[i].value, str(target_map[i].available_at)) for i in training_rows],
        )
        final_holdout_target_count = len(set(target_map).intersection(split.final_holdout))
        if final_holdout_target_count:
            raise AssertionError("E2E_FINAL_HOLDOUT_TARGETS_ACCESSED")

        X_train = [[feature_values[i]] for i in training_rows]
        y_train = [1 if float(target_map[i].value) > 0 else 0 for i in training_rows]
        if len(set(y_train)) < 2:
            raise AssertionError("E2E_TRAINING_TARGET_CLASSES_INSUFFICIENT")
        baseline_probability = sum(y_train) / len(y_train)
        baseline_stage = self._stage(
            "Baseline", "BASELINE-E2E-001",
            (target_stage.artifact_id, feature_stage.artifact_id),
            ("TRAIN_ONLY", "CONSTANT_CLASS_PRIOR"),
            {
                "positive_class_probability": baseline_probability,
                "threshold": 0.5,
                "training_rows": len(y_train),
                "action": "BUY" if baseline_probability > 0.5 else "HOLD",
            },
        )

        model = LogisticBaseline(max_iter=500)
        fit = model.fit(X_train, y_train, ["lag_return"])
        model_output = {
            "model_type": fit.model_type,
            "feature_names": list(fit.feature_names),
            "training_rows": fit.training_rows,
            "classes": [int(value) for value in fit.model.classes_],
            "coefficients": [[float(value) for value in row] for row in fit.model.coef_],
            "intercept": [float(value) for value in fit.model.intercept_],
            "random_state": 0,
        }
        model_stage = self._stage(
            "Model", "MODEL-E2E-001",
            (baseline_stage.artifact_id, target_stage.artifact_id, feature_stage.artifact_id),
            ("FIT:LOGISTIC", "TRAIN_TARGETS_ONLY", f"TRAIN_ROWS:{fit.training_rows}"),
            model_output,
        )

        prediction_idx = None
        p_up = None
        prediction_feature = None
        for index in split.oos:
            # Simulate online evaluation: consume OOS rows in timestamp order and
            # stop at the first predeclared signal threshold crossing.
            candidate_feature = feature_values[index]
            candidate_probability = float(model.predict_proba([[candidate_feature]])[0][1])
            if candidate_probability > 0.5:
                prediction_idx = index
                p_up = candidate_probability
                prediction_feature = candidate_feature
                break
        if prediction_idx is None or p_up is None or prediction_feature is None:
            raise AssertionError("E2E_NO_OOS_SIGNAL_AT_PREDECLARED_THRESHOLD")
        pred_id = "PREDICTION-E2E-001"
        prediction_stage = self._stage(
            "Prediction", pred_id,
            (model_stage.artifact_id, baseline_stage.artifact_id, feature_stage.artifact_id),
            ("MODEL:LOGISTIC", "FEATURE:F1", "TARGET:T1", "EVALUATION:OOS_ONLY"),
            {"index": prediction_idx, "feature_value": prediction_feature,
             "probability": round(p_up, 12), "baseline_probability": baseline_probability,
             "threshold": 0.5, "available_at": parsed_ts[prediction_idx].isoformat()},
        )

        signal_id = "SIGNAL-E2E-001"
        signal = {"signal": "BUY", "score": round(p_up, 12), "prediction_id": pred_id}
        signal_stage = self._stage("Signal", signal_id, (pred_id,), ("THRESHOLD:0.5",), signal)

        opportunity_id = "OPPORTUNITY-E2E-001"
        opportunity = {"opportunity": "LONG_BTCUSDT", "expected_return": str(Decimal("0.02")), "signal_id": signal_id}
        opportunity_stage = self._stage("Opportunity", opportunity_id, (signal_id,), ("OPP_RULE:LONG",), opportunity)

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
        with TemporaryDirectory(dir=self.root) as td:
            risk_db = Path(td) / "risk.sqlite"
            with EventStore(str(risk_db)) as risk_store:
                DurableRiskDecisionLedger(risk_store).record(risk_record)
            with EventStore(str(risk_db)) as risk_store:
                risk_ledger = DurableRiskDecisionLedger(risk_store)
                if risk_ledger.restore().get(decision_id) != risk_record:
                    raise AssertionError("RISK_DECISION_RESTART_RESTORE_FAILED")
                risk_ledger.assert_valid_for_new_risk(
                    decision_id=decision_id, now_ms=RUN_AT_MS + 1, intent_id=intent_id,
                    reservation_id=reservation_id, requested_exposure=risk_exposure, truth_hash=risk_truth_hash,
                    configuration_version="CFG-E2E-1", risk_state_version="RS-E2E-1", portfolio_version="PV-E2E-1",
                    position_version="POS-E2E-1",
                )
                try:
                    risk_ledger.assert_valid_for_new_risk(
                        decision_id=decision_id, now_ms=risk_record.expires_at_ms, intent_id=intent_id,
                        reservation_id=reservation_id, requested_exposure=risk_exposure, truth_hash=risk_truth_hash,
                        configuration_version="CFG-E2E-1", risk_state_version="RS-E2E-1",
                        portfolio_version="PV-E2E-1", position_version="POS-E2E-1",
                    )
                except RiskDecisionConflict as exc:
                    if str(exc) != "RISK_DECISION_EXPIRED_OR_NOT_YET_VALID":
                        raise
                    expired_risk_blocked = True
                else:
                    raise AssertionError("EXPIRED_RISK_DECISION_WAS_ACCEPTED")
        risk_stage = self._stage("Risk", decision_id, (portfolio_stage.artifact_id,),
                                ("RISK_DECISION_DURABLE", reservation_id), risk_record.payload())

        order_intent = OrderIntent(
            intent_id=intent_id, decision_id=decision_id, portfolio_decision_id=portfolio_id,
            risk_decision_id=decision_id, strategy_id="STRAT-E2E-1", model_id="MODEL-E2E-001",
            execution_version="EXEC-E2E-1", symbol="BTCUSDT", side=Side.BUY,
            action=OrderAction.OPEN, quantity=Decimal("0.0002"), order_type=OrderType.LIMIT,
            window=intent_window, price=Decimal("50000"), time_in_force="GTC", risk_reservation_id=reservation_id,
        )
        order_intent.validate(RUN_AT + timedelta(seconds=1))
        from trading_platform.v319.durable_intent import DurableOrderIntentLedger
        with TemporaryDirectory(dir=self.root) as td:
            intent_db = Path(td) / "intent.sqlite"
            with EventStore(str(intent_db)) as intent_store:
                DurableOrderIntentLedger(intent_store).record(order_intent, recorded_at_ms=RUN_AT_MS)
            with EventStore(str(intent_db)) as intent_store:
                intent_ledger = DurableOrderIntentLedger(intent_store)
                restored_intent = intent_ledger.restore()
                if intent_id not in restored_intent:
                    raise AssertionError("ORDER_INTENT_RESTART_RESTORE_FAILED")
                intent_ledger.assert_matches(order_intent)
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
        durable_fill = DurableFill(
            fill_id=fill.fill_id, order_request_id=fill.order_request_id, symbol="BTCUSDT", side="BUY",
            quantity=fill.quantity, price=fill.price, fee=fill.fee, occurred_at_ms=RUN_AT_MS,
            exchange_order_id=fill.exchange_order_id, trade_id=fill.trade_id, venue=fill.venue,
        )
        with TemporaryDirectory(dir=self.root) as td:
            fill_db = Path(td) / "fills.sqlite"
            with EventStore(str(fill_db)) as fill_store:
                first_fill = DurableFillAuthority(fill_store).accept(fill, occurred_at_ms=RUN_AT_MS)
                if not first_fill.created:
                    raise AssertionError("INITIAL_FILL_NOT_NEW")
            with EventStore(str(fill_db)) as fill_store:
                fill_authority = DurableFillAuthority(fill_store)
                duplicate_fill = replace(fill, fill_id="FILL-E2E-DUP")
                duplicate_acceptance = fill_authority.accept(duplicate_fill, occurred_at_ms=RUN_AT_MS + 1)
                if duplicate_acceptance.created:
                    raise AssertionError("DUPLICATE_FILL_WAS_ACCEPTED_AFTER_RESTART")
                try:
                    fill_authority.accept(
                        replace(fill, fill_id="FILL-E2E-CONFLICT", quantity=Decimal("0.0003")),
                        occurred_at_ms=RUN_AT_MS + 2,
                    )
                except FillIdentityConflict:
                    conflicting_fill_blocked = True
                else:
                    raise AssertionError("CONFLICTING_FILL_IDENTITY_WAS_ACCEPTED")
                fill_authority.assert_chain()

            accounting_db = Path(td) / "accounting.sqlite"
            with EventStore(str(accounting_db)) as accounting_store:
                initial_accounting = DurableAccountingLedger(accounting_store)
                _, accounting_fill_created = initial_accounting.append_fill_once(durable_fill)
                if not accounting_fill_created:
                    raise AssertionError("INITIAL_ACCOUNTING_FILL_NOT_NEW")
            with EventStore(str(accounting_db)) as accounting_store:
                durable_accounting = DurableAccountingLedger(accounting_store)
                accounting_before_retry = durable_accounting.reconstruct()
                _, duplicate_accounting_created = durable_accounting.append_fill_once(
                    replace(durable_fill, fill_id="FILL-E2E-DUP")
                )
                if duplicate_accounting_created:
                    raise AssertionError("DUPLICATE_FILL_DOUBLE_COUNTED_AFTER_RESTART")
                try:
                    durable_accounting.append_fill_once(
                        replace(durable_fill, fill_id="FILL-E2E-CONFLICT", quantity=Decimal("0.0003"))
                    )
                except AccountingConflict:
                    conflicting_accounting_fill_blocked = True
                else:
                    raise AssertionError("CONFLICTING_ACCOUNTING_FILL_WAS_ACCEPTED")
                accounting_projection, recovery_proof = prove_recovery(durable_accounting)
                if accounting_projection != accounting_before_retry or not recovery_proof.passed:
                    raise AssertionError("ACCOUNTING_RESTART_RECOVERY_FAILED")
                if len(accounting_projection.positions) != 1:
                    raise AssertionError("ACCOUNTING_POSITION_RECONSTRUCTION_FAILED")

        lifecycle.apply(OrderExecutionState.FILLED, event_id="E2E-ORDER-FILL-001", idempotency_key="E2E-IDEMP-003")
        execution_filled_stage = self._stage("Fill", "FILL-E2E-001", (execution_stage.artifact_id,),
                                             ("DUPLICATE_GUARD:PASS", "LIFECYCLE:FILLED"),
                                             {"quantity": str(fill.quantity), "price": str(fill.price),
                                              "fill_identity": DurableFillAuthority.identity_key(fill)})
        failure_stage = self._stage(
            "Failure Injection", "FAILURE-E2E-001",
            (execution_filled_stage.artifact_id, risk_stage.artifact_id),
            ("DUPLICATE_FILL_REJECTED", "CONFLICTING_FILL_BLOCKED", "EXPIRED_RISK_BLOCKED"),
            {
                "duplicate_fill_accepted": duplicate_acceptance.created,
                "conflicting_fill_blocked": conflicting_fill_blocked,
                "duplicate_accounting_created": duplicate_accounting_created,
                "conflicting_accounting_fill_blocked": conflicting_accounting_fill_blocked,
                "expired_risk_blocked": expired_risk_blocked,
                "accounting_event_count": len(accounting_projection.processed_event_ids),
            },
        )

        position = accounting_projection.positions[0]
        fill_position = {
            "symbol": durable_fill.symbol,
            "quantity": str(durable_fill.quantity),
            "avg": str(durable_fill.price),
        }
        if (
            position.symbol != fill_position["symbol"]
            or str(position.quantity) != fill_position["quantity"]
            or str(position.avg_entry_price) != fill_position["avg"]
        ):
            raise AssertionError("POSITION_ACCOUNTING_FILL_MISMATCH")
        position_stage = self._stage(
            "Position", "POSITION-E2E-001", (execution_filled_stage.artifact_id,),
            ("STATE:OPEN", "SOURCE:DURABLE_FILL", "ACCOUNTING_MATCH:PASS"), fill_position,
        )

        opening_equity = Decimal("1000")
        marked_position = position.quantity * fill.price
        equity_expected = opening_equity + accounting_projection.cash + marked_position
        exchange_snapshot = ExchangeAccountingSnapshot(
            equity=equity_expected,
            positions={position.symbol: position.quantity},
            snapshot_id="SIM-ACCOUNT-E2E-001",
        )
        accounting_reconciliation = AccountingReconciliation(
            reconstructed=accounting_projection,
            exchange=exchange_snapshot,
            equity_expected=equity_expected,
        )
        if not accounting_reconciliation.reconciled:
            raise AssertionError("ACCOUNTING_RECONCILIATION_NOT_EXACT")
        accounting_stage = self._stage(
            "Accounting", "ACCOUNTING-E2E-001", (position_stage.artifact_id,),
            ("DURABLE_LEDGER:RECONSTRUCTED", "RECONCILIATION:SIMULATED_MATCH"),
            {"projection": accounting_projection.payload()},
        )
        pnl_stage = self._stage(
            "P&L", "PNL-E2E-001", (accounting_stage.artifact_id, position_stage.artifact_id),
            ("EQUITY:MARKED", "FEES:INCLUDED"),
            {
                "opening_equity": str(opening_equity),
                "equity": str(equity_expected),
                "equity_change": str(equity_expected - opening_equity),
                "fees": str(accounting_projection.fees),
                "realized_pnl": str(accounting_projection.realized_pnl),
                "unrealized_pnl": str(position.quantity * (fill.price - position.avg_entry_price)),
            },
        )

        recovery_stage = self._stage(
            "Recovery", "RECOVERY-E2E-001",
            (pnl_stage.artifact_id, intent_stage.artifact_id, risk_stage.artifact_id),
            ("SQLITE_REOPEN", "EVENT_CHAIN_VALID", "ACCOUNTING_STATE_HASH_MATCH"),
            {
                "accounting_state_hash": accounting_projection.state_hash,
                "recovery_proof": asdict(recovery_proof),
                "restored_intent_ids": sorted(restored_intent),
                "restored_risk_decision_id": decision_id,
            },
        )
        rollback = run_rollback_exercise(now=RUN_AT, scenario_id="E2E-ROLLBACK-V358-001")
        if rollback.result != "PASS" or not rollback.closed_without_residual_risk:
            raise AssertionError("DEPLOYMENT_ROLLBACK_EXERCISE_FAILED")
        rollback_stage = self._stage("Rollback", "ROLLBACK-E2E-001",
                                     (execution_filled_stage.artifact_id, risk_stage.artifact_id),
                                     ("DEPLOYMENT_ROLLBACK", "NO_RESIDUAL_RISK"), rollback.as_dict())

        audit = AuditRecord(
            audit_id="AUDIT-E2E-001", event_type="E2E_ACCEPTANCE_COMPLETED", timestamp=RUN_AT,
            actor="acceptance-runner", payload={"chain": [s.artifact_id for s in (
                dataset_stage, validation_stage, feature_stage, target_stage, baseline_stage, model_stage,
                prediction_stage, signal_stage,
                opportunity_stage, portfolio_stage, risk_stage, intent_stage, simulation_stage, execution_stage,
                execution_filled_stage, failure_stage, position_stage, accounting_stage, pnl_stage,
                recovery_stage, rollback_stage,
            )]}
        )
        audit_hash = audit.content_hash()
        audit_stage = self._stage(
            "Audit", audit.audit_id,
            (pnl_stage.artifact_id, recovery_stage.artifact_id, failure_stage.artifact_id,
             rollback_stage.artifact_id, model_stage.artifact_id, validation_stage.artifact_id),
            (audit.event_type,), {"content_hash": audit_hash},
        )

        replay_state = {
            "research_chain": {
                s.artifact_id: s.output_hash for s in (
                    dataset_stage, validation_stage, feature_stage, target_stage,
                    baseline_stage, model_stage, prediction_stage,
                )
            },
            "position": {"symbol": position.symbol, "quantity": str(position.quantity), "avg": str(position.avg_entry_price)},
            "accounting": accounting_projection.payload(),
            "pnl": pnl_stage.output_hash,
            "risk": risk_record.payload(),
            "intent": DurableOrderIntentLedger.payload(order_intent),
            "failure_injection": failure_stage.output_hash,
            "rollback": rollback.content_hash,
        }
        checkpoint = ReplayCheckpoint(
            event_offset=len(accounting_projection.processed_event_ids),
            snapshot_version="E2E-V358-3", state_hash=canonical_hash(replay_state),
        )
        replay_stage = self._stage("Replay", "REPLAY-E2E-001",
                                   (audit_stage.artifact_id, pnl_stage.artifact_id, recovery_stage.artifact_id,
                                    rollback_stage.artifact_id, model_stage.artifact_id, validation_stage.artifact_id),
                                   (checkpoint.snapshot_version,), asdict(checkpoint))

        pre_evidence_stages = (
            dataset_stage, validation_stage, feature_stage, target_stage, baseline_stage, model_stage,
            prediction_stage, signal_stage, opportunity_stage, portfolio_stage, risk_stage, intent_stage,
            simulation_stage, execution_stage, execution_filled_stage, failure_stage, position_stage,
            accounting_stage, pnl_stage, recovery_stage, rollback_stage, audit_stage, replay_stage,
        )
        evidence_payload = {
            "run_id": self.RUN_ID,
            "stage_hashes": {s.artifact_id: s.output_hash for s in pre_evidence_stages},
            "replay_hash": checkpoint.state_hash,
            "training_target_indices": list(training_rows),
            "final_holdout_target_count": final_holdout_target_count,
        }
        with TemporaryDirectory(dir=self.root) as td:
            evidence_store = DurableEvidenceStore(Path(td) / "acceptance.sqlite")
            artifact = EvidenceArtifact(
                evidence_id="EVIDENCE-E2E-001", scenario_id="E2E-ACCEPTANCE", status="PASS",
                environment="SIMULATION", started_at=RUN_AT.isoformat(), completed_at=RUN_AT.isoformat(),
                correlation_id=self.RUN_ID, operator_id="acceptance-runner", endpoint="OFFLINE",
                request_hash=_hash(evidence_payload), response_hash=checkpoint.state_hash,
                pre_snapshot_hash=None, post_snapshot_hash=None, reconciliation="SIMULATED_MATCH",
                observations=(
                    "deterministic_ids", "provenance_complete", "replay_deterministic",
                    "training_targets_only", "duplicate_and_conflict_fill_blocked",
                    "risk_expiry_blocked", "sqlite_restart_recovery", "deployment_rollback_zero_residual_risk",
                ),
                references=("MASTER_PROMPT:178",),
            ).sealed()
            evidence_store.append(artifact)
            if evidence_store.verify():
                raise AssertionError("E2E_EVIDENCE_STORE_INVALID")
        evidence_snapshot = build_snapshot(
            "SNAPSHOT-E2E-001", ("EVIDENCE-E2E-001",), {"run_id": self.RUN_ID, "replay_hash": checkpoint.state_hash},
            ("GATE-E2E-001",), tuple(s.artifact_id for s in pre_evidence_stages),
            ("DATA-V1", "VALIDATION-V1", "FEATURE-V1", "TARGET-V1", "BASELINE-V1", "MODEL-V1", "RISK-V1", "EXEC-V1"),
            tuple(s.output_hash for s in pre_evidence_stages),
            ("METHOD-E2E-001",), ("APPROVAL-VERIFICATION-ONLY",), {"environment": "SIMULATION", "scope": "E2E"},
        )
        if snapshot_content_hash(evidence_snapshot) != evidence_snapshot.content_hash:
            raise AssertionError("E2E_SNAPSHOT_HASH_INVALID")
        evidence_stage = self._stage("Evidence", evidence_snapshot.snapshot_id,
                                    (replay_stage.artifact_id, recovery_stage.artifact_id,
                                     failure_stage.artifact_id, rollback_stage.artifact_id,
                                     validation_stage.artifact_id, model_stage.artifact_id),
                                    (artifact.evidence_id, evidence_snapshot.content_hash), asdict(evidence_snapshot))

        gate = Gate(
            gate_id="GATE-E2E-001", candidate_version="V358", run_id=self.RUN_ID,
            input_versions=("DATA-V1", "FEATURE-V1", "TARGET-V1", "MODEL-V1", "RISK-V1", "EXEC-V1"),
            checks=("DETERMINISTIC_IDENTIFIERS", "PROVENANCE", "REPRODUCIBILITY", "FAILURE_INJECTION", "RECOVERY", "ROLLBACK"),
            result=GateResult.PASS,
            required_artifacts=(evidence_snapshot.snapshot_id, validation_stage.artifact_id,
                                model_stage.artifact_id, recovery_stage.artifact_id,
                                failure_stage.artifact_id, rollback_stage.artifact_id),
            evidence_refs=(artifact.evidence_id,), owner="acceptance-runner", reviewer="independent-review-required",
            timestamp=RUN_AT.isoformat(), expiration=None, revalidation_condition="ANY_UPSTREAM_CHANGE",
        )
        gate_stage = self._stage("Gate", gate.gate_id,
                                 (evidence_stage.artifact_id, recovery_stage.artifact_id,
                                  failure_stage.artifact_id, rollback_stage.artifact_id),
                                 gate.checks, asdict(gate))

        required = (
            AcceptanceItem("DETERMINISTIC_IDENTIFIERS", AcceptanceStatus.PASS, dataset_stage.artifact_id, True),
            AcceptanceItem("DATA_VALIDATION", AcceptanceStatus.PASS, validation_stage.artifact_id, True),
            AcceptanceItem("MODEL_TRAINING", AcceptanceStatus.PASS, model_stage.artifact_id, True),
            AcceptanceItem("PROVENANCE", AcceptanceStatus.PASS, evidence_stage.artifact_id, True),
            AcceptanceItem("REPRODUCIBILITY", AcceptanceStatus.PASS, replay_stage.artifact_id, True),
            AcceptanceItem("FAILURE_INJECTION", AcceptanceStatus.PASS, failure_stage.artifact_id, True),
            AcceptanceItem("RECOVERY", AcceptanceStatus.PASS, recovery_stage.artifact_id, True),
            AcceptanceItem("P_AND_L", AcceptanceStatus.PASS, pnl_stage.artifact_id, True),
            AcceptanceItem("ROLLBACK", AcceptanceStatus.PASS, rollback_stage.artifact_id, True),
            AcceptanceItem("END_TO_END_CHAIN", AcceptanceStatus.PASS, gate_stage.artifact_id, True),
        )
        acceptance = build_acceptance(list(required))
        if not acceptance.acceptance_passed:
            raise AssertionError("E2E_ACCEPTANCE_REPORT_NOT_PASSED")

        stages = (
            dataset_stage, validation_stage, feature_stage, target_stage, baseline_stage, model_stage,
            prediction_stage, signal_stage,
            opportunity_stage, portfolio_stage, risk_stage, intent_stage, simulation_stage, execution_stage,
            execution_filled_stage, failure_stage, position_stage, accounting_stage, pnl_stage,
            recovery_stage, rollback_stage, audit_stage, replay_stage, evidence_stage, gate_stage,
        )
        result = E2EAcceptanceResult(
            run_id=self.RUN_ID, stages=stages, replay_checkpoint=checkpoint,
            evidence_id=artifact.evidence_id, evidence_snapshot_id=evidence_snapshot.snapshot_id,
            gate_id=gate.gate_id, gate_required_artifacts=gate.required_artifacts,
            training_target_indices=tuple(training_rows),
            final_holdout_target_count=final_holdout_target_count,
            acceptance=acceptance, report_hash="",
        )
        report_hash = _hash(result.payload())
        return replace(result, report_hash=report_hash)


def run_acceptance() -> E2EAcceptanceResult:
    return EndToEndAcceptanceRunner().run()
