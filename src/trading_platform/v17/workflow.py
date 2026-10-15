from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol
import hashlib, json, os, uuid

from trading_platform.ops.network_policy import TESTNET_POLICY, NetworkDecision
from trading_platform.ops.preflight import build_preflight, PreflightCheck
from trading_platform.v17.evidence import DurableEvidenceStore, EvidenceArtifact, canonical_json, utc_now

class Environment(str, Enum): TESTNET='TESTNET'
class WorkflowStatus(str, Enum): PLAN='PLAN'; READ_ONLY='READ_ONLY'; MUTATION_BLOCKED='MUTATION_BLOCKED'; MUTATION_READY='MUTATION_READY'; FAIL='FAIL'; PASS='PASS'

class JsonTransport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str,str] | None=None, params: Mapping[str,Any] | None=None) -> Mapping[str,Any]: ...

@dataclass(frozen=True)
class MutationApproval:
    approval_id: str
    operator_id: str
    approved_at: datetime
    expires_at: datetime
    max_notional_usdt: float
    purpose: str
    environment: Environment = Environment.TESTNET

    def valid(self, now: datetime) -> bool:
        return self.environment is Environment.TESTNET and bool(self.operator_id) and bool(self.approval_id) and self.approved_at <= now < self.expires_at and self.max_notional_usdt > 0

@dataclass(frozen=True)
class WorkflowConfig:
    base_url: str
    symbol: str = 'BTCUSDT'
    environment: Environment = Environment.TESTNET
    evidence_db: Path = Path('evidence/v17/evidence.sqlite')
    hard_mutation_cap_usdt: float = 25.0
    require_reconciliation_before_mutation: bool = True

    def validate(self) -> None:
        if self.environment is not Environment.TESTNET:
            raise ValueError('NON_TESTNET_ENVIRONMENT_BLOCKED')
        if TESTNET_POLICY.decide(self.base_url) is not NetworkDecision.ALLOW:
            raise PermissionError('NETWORK_POLICY_DENIED')
        if not self.symbol.isalnum():
            raise ValueError('INVALID_SYMBOL')
        if self.hard_mutation_cap_usdt <= 0:
            raise ValueError('INVALID_MUTATION_CAP')

@dataclass(frozen=True)
class WorkflowDecision:
    status: WorkflowStatus
    allowed: bool
    reasons: tuple[str, ...]

class SafetyGate:
    def __init__(self, config: WorkflowConfig):
        self.config=config

    def decide(self, *, mutation_requested: bool, approval: MutationApproval | None,
               reconciliation_green: bool, kill_switch: bool, decision_fresh: bool) -> WorkflowDecision:
        reasons=[]
        pf=build_preflight(environment=self.config.environment.value, endpoint=self.config.base_url, require_credentials=mutation_requested)
        if not pf.can_execute: reasons.append('PREFLIGHT_FAIL')
        if kill_switch: reasons.append('KILL_SWITCH_ACTIVE')
        if not decision_fresh: reasons.append('DECISION_EXPIRED')
        if self.config.require_reconciliation_before_mutation and not reconciliation_green: reasons.append('RECONCILIATION_NOT_GREEN')
        if mutation_requested:
            if approval is None or not approval.valid(datetime.now(timezone.utc)): reasons.append('EXPLICIT_APPROVAL_REQUIRED')
            elif approval.max_notional_usdt > self.config.hard_mutation_cap_usdt: reasons.append('MUTATION_CAP_EXCEEDED')
        if reasons:
            return WorkflowDecision(WorkflowStatus.MUTATION_BLOCKED if mutation_requested else WorkflowStatus.READ_ONLY, False, tuple(reasons))
        return WorkflowDecision(WorkflowStatus.MUTATION_READY if mutation_requested else WorkflowStatus.READ_ONLY, True, tuple())

class TestnetWorkflow:
    __test__ = False
    """Fail-closed operational harness. Mutations require an explicit approval and a separate gate."""
    def __init__(self, config: WorkflowConfig, *, transport: JsonTransport, operator_id: str = 'offline'):
        config.validate()
        self.config=config
        self.transport=transport
        self.operator_id=operator_id
        self.evidence=DurableEvidenceStore(config.evidence_db)
        self.gate=SafetyGate(config)
        self.correlation_id=str(uuid.uuid4())
        self._reconciliation_green=False
        self._kill_switch=False

    def set_kill_switch(self, active: bool) -> None:
        self._kill_switch=active

    def set_reconciliation(self, green: bool) -> None:
        self._reconciliation_green=green

    @staticmethod
    def _sha(value: Any) -> str:
        return hashlib.sha256(canonical_json(value)).hexdigest()

    def _request(self, method: str, path: str, params: Mapping[str,Any] | None=None, headers: Mapping[str,str] | None=None) -> Mapping[str,Any]:
        return self.transport.request(method, self.config.base_url.rstrip('/') + path, headers=headers, params=params or {})

    def read_only_probe(self, scenario_id: str, name: str, path: str, *, params: Mapping[str,Any] | None=None) -> EvidenceArtifact:
        start=utc_now(); req_hash=self._sha({'method':'GET','path':path,'params':dict(params or {})})
        try:
            response=self._request('GET', path, params=params)
            status='PASS'; obs=('response_received','mutation=false')
            response_hash=self._sha(response)
        except Exception as exc:
            status='FAIL'; obs=(type(exc).__name__ + ':' + str(exc),); response_hash=None
        end=utc_now()
        artifact=EvidenceArtifact(
            evidence_id=f'{scenario_id}-{uuid.uuid4().hex[:12]}', scenario_id=scenario_id, status=status,
            environment=self.config.environment.value, started_at=start, completed_at=end,
            correlation_id=self.correlation_id, operator_id=self.operator_id, endpoint=self.config.base_url+path,
            request_hash=req_hash, response_hash=response_hash, pre_snapshot_hash=None, post_snapshot_hash=None,
            reconciliation='NOT_APPLICABLE', observations=obs,
            references=('https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/',),
        ).sealed()
        self.evidence.append(artifact)
        return artifact

    def mutation_gate(self, approval: MutationApproval | None, *, decision_fresh: bool=True) -> WorkflowDecision:
        return self.gate.decide(mutation_requested=True, approval=approval,
                                 reconciliation_green=self._reconciliation_green,
                                 kill_switch=self._kill_switch,
                                 decision_fresh=decision_fresh)

    def plan(self) -> tuple[str, ...]:
        return ('TN-01 connectivity','TN-02 exchange rules','TN-03 authenticated account','TN-04 order test contract','TN-05 controlled order','TN-06 cancellation','TN-07 unknown-order reconciliation','TN-08 account/position reconciliation','TN-09 restart/recovery','TN-10 failure injection')

    def offline_report(self) -> dict[str,Any]:
        return {
            'environment': self.config.environment.value,
            'status': WorkflowStatus.PLAN.value,
            'mutations_enabled': False,
            'required_reconciliation_before_mutation': self.config.require_reconciliation_before_mutation,
            'hard_mutation_cap_usdt': self.config.hard_mutation_cap_usdt,
            'plan': list(self.plan()),
            'evidence_integrity_failures': list(self.evidence.verify()),
            'production_ready': False,
        }
