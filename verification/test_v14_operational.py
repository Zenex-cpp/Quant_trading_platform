import os, json, tempfile
from pathlib import Path
import pytest
from trading_platform.testnet.session import SessionConfig, SessionStatus, EvidenceArtifact, LiveTestnetSession
from trading_platform.testnet.e2e import READ_ONLY_PLAN

class DummyTransport:
    def signed_request(self, method, path, *, params, api_key, secret):
        assert api_key=='K'; assert secret==b'S'; return {'serverTime':123, 'ok':True}

def test_session_rejects_mainnet():
    with pytest.raises(ValueError, match='MAINNET_HOST_BLOCKED'):
        SessionConfig(base_url='https://api.binance.com').validate()

def test_session_requires_tls():
    with pytest.raises(ValueError, match='TLS_REQUIRED'):
        SessionConfig(base_url='http://testnet.example').validate()

def test_network_execution_is_explicit():
    cfg=SessionConfig(base_url='https://testnet.example')
    s=LiveTestnetSession(cfg, api_key='K', secret=b'S', transport=DummyTransport())
    with pytest.raises(RuntimeError, match='NETWORK_EXECUTION_NOT_ENABLED'):
        READ_ONLY_PLAN.execute(s)

def test_read_only_plan_produces_hashed_evidence(tmp_path):
    cfg=SessionConfig(base_url='https://testnet.example', evidence_dir=tmp_path)
    s=LiveTestnetSession(cfg, api_key='K', secret=b'S', transport=DummyTransport())
    results=READ_ONLY_PLAN.execute(s, allow_network=True)
    assert [r.scenario_id for r in results]==['TN-01','TN-02']
    assert all(r.status==SessionStatus.PASSED for r in results)
    assert all(r.artifact_hash for r in results)
    assert len(list(tmp_path.glob('*.json')))==2

def test_artifact_hash_excludes_self_hash():
    a=EvidenceArtifact('e','s','TN-01',SessionStatus.PASSED,'a','b',{},(),(),None,None,None,'op')
    first=a.artifact_hash
    second=a.artifact_hash
    assert first==second
