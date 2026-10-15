from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import pytest

from trading_platform.ops.network_policy import TESTNET_POLICY
from trading_platform.v17.workflow import WorkflowConfig, Environment, SafetyGate, MutationApproval, TestnetWorkflow, WorkflowStatus

class DummyTransport:
    def request(self, method, url, *, headers=None, params=None):
        return {'ok': True, 'method': method, 'url': url, 'params': dict(params or {})}

def test_mutation_blocks_without_approval():
    cfg=WorkflowConfig('https://testnet.binancefuture.com', evidence_db=Path(tempfile.mkdtemp())/'e.sqlite')
    gate=SafetyGate(cfg)
    d=gate.decide(mutation_requested=True, approval=None, reconciliation_green=True, kill_switch=False, decision_fresh=True)
    assert not d.allowed and 'EXPLICIT_APPROVAL_REQUIRED' in d.reasons

def test_mutation_blocks_until_reconciliation_green():
    cfg=WorkflowConfig('https://testnet.binancefuture.com', evidence_db=Path(tempfile.mkdtemp())/'e.sqlite')
    approval=MutationApproval('A1','op',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=5),10,'controlled')
    d=SafetyGate(cfg).decide(mutation_requested=True, approval=approval, reconciliation_green=False, kill_switch=False, decision_fresh=True)
    assert not d.allowed and 'RECONCILIATION_NOT_GREEN' in d.reasons

def test_cap_is_hard_upper_bound():
    cfg=WorkflowConfig('https://testnet.binancefuture.com', hard_mutation_cap_usdt=25, evidence_db=Path(tempfile.mkdtemp())/'e.sqlite')
    approval=MutationApproval('A1','op',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=5),26,'controlled')
    d=SafetyGate(cfg).decide(mutation_requested=True, approval=approval, reconciliation_green=True, kill_switch=False, decision_fresh=True)
    assert not d.allowed and 'MUTATION_CAP_EXCEEDED' in d.reasons

def test_expired_decision_blocks():
    cfg=WorkflowConfig('https://testnet.binancefuture.com', evidence_db=Path(tempfile.mkdtemp())/'e.sqlite')
    approval=MutationApproval('A1','op',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=5),10,'controlled')
    d=SafetyGate(cfg).decide(mutation_requested=True, approval=approval, reconciliation_green=True, kill_switch=False, decision_fresh=False)
    assert not d.allowed and 'DECISION_EXPIRED' in d.reasons

def test_kill_switch_blocks():
    cfg=WorkflowConfig('https://testnet.binancefuture.com', evidence_db=Path(tempfile.mkdtemp())/'e.sqlite')
    approval=MutationApproval('A1','op',datetime.now(timezone.utc),datetime.now(timezone.utc)+timedelta(minutes=5),10,'controlled')
    d=SafetyGate(cfg).decide(mutation_requested=True, approval=approval, reconciliation_green=True, kill_switch=True, decision_fresh=True)
    assert not d.allowed and 'KILL_SWITCH_ACTIVE' in d.reasons

def test_read_only_probe_creates_durable_evidence():
    root=Path(tempfile.mkdtemp())
    cfg=WorkflowConfig('https://testnet.binancefuture.com', evidence_db=root/'e.sqlite')
    wf=TestnetWorkflow(cfg, transport=DummyTransport(), operator_id='op')
    art=wf.read_only_probe('TN-01','ping','/fapi/v1/ping')
    assert art.status=='PASS'
    assert wf.evidence.verify()==()

def test_mainnet_is_rejected():
    with pytest.raises(PermissionError):
        WorkflowConfig('https://fapi.binance.com').validate()

def test_plan_is_mutation_free():
    root=Path(tempfile.mkdtemp())
    wf=TestnetWorkflow(WorkflowConfig('https://testnet.binancefuture.com', evidence_db=root/'e.sqlite'), transport=DummyTransport())
    r=wf.offline_report()
    assert r['mutations_enabled'] is False
    assert 'production_ready' in r and r['production_ready'] is False
