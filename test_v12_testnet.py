import hashlib
from trading_platform.testnet import TestnetClientConfig, BinanceTestnetSigner, EvidenceStatus, TestnetEvidence, offline_verification_summary

def test_testnet_config_blocks_non_testnet_and_requires_tls():
    try:
        TestnetClientConfig("http://example", "key", "secret").validate()
        assert False
    except ValueError as e:
        assert str(e)=="TLS_REQUIRED"
    try:
        TestnetClientConfig("https://example", "key", "secret", environment="LIVE").validate()
        assert False
    except ValueError as e:
        assert str(e)=="NON_TESTNET_ENVIRONMENT_BLOCKED"

def test_signer_matches_hmac_sha256():
    got=BinanceTestnetSigner.sign(b"secret", {"b":"2","a":"1"})
    exp=hmac_sha256(b"secret", b"a=1&b=2")
    assert got==exp

def hmac_sha256(secret, payload):
    import hmac
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()

def test_evidence_is_hashable_and_deterministic():
    e=TestnetEvidence("E1","TN-11",EvidenceStatus.PASS,"2026-01-01T00:00:00+00:00","2026-01-01T00:00:01+00:00","TESTNET",("ref",),("ok",)).with_hash()
    assert e.artifact_hash and len(e.artifact_hash)==64
    assert e.with_hash().artifact_hash==e.artifact_hash

def test_offline_summary_never_claims_production_ready():
    s=offline_verification_summary()
    assert s.failed==0
    assert s.not_verified==10
    assert s.production_ready is False
