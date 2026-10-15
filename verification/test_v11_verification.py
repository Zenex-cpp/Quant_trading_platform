from pathlib import Path
from trading_platform.verification.durable import SQLiteIdempotencyStore
from trading_platform.verification.backup import backup_directory, verify_backup_manifest
from trading_platform.verification.failure_injection import FailureScenario, run_failure_scenario
from trading_platform.verification.security import assert_research_boundary, scan_secrets
from trading_platform.verification.readiness import *

def test_durable_idempotency(tmp_path):
    s=SQLiteIdempotencyStore(tmp_path/'idem.db')
    assert s.claim('k1','ORDER','h1')
    assert not s.claim('k1','ORDER','h1')
    assert s.get('k1').result_hash=='h1'

def test_backup_manifest_roundtrip(tmp_path):
    src=tmp_path/'src'; src.mkdir(); (src/'a.txt').write_text('x'); (src/'b.txt').write_text('y')
    b=backup_directory(src,tmp_path/'b.tar.gz')
    assert verify_backup_manifest(b,tmp_path/'b.tar.gz.manifest.json')

def test_failure_catalog_blocks():
    for s in FailureScenario:
        r=run_failure_scenario(s)
        assert r.detected and r.blocked and r.expected_action

def test_research_boundary():
    assert_research_boundary('wss://testnet.example/ws')
    try: assert_research_boundary('https://fapi.binance.com')
    except PermissionError: pass
    else: raise AssertionError('boundary failed')

def test_secret_scan_clean_repo():
    assert scan_secrets(Path(__file__).parents[2]) == []

def test_verification_report():
    r=build_verification_report([VerificationItem('X',VerificationStatus.PASS,'evidence')])
    assert r.verified_count==1 and r.failed_count==0
