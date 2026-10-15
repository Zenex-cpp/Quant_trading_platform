from decimal import Decimal
import pytest
from trading_platform.ops.network_policy import TESTNET_POLICY, NetworkDecision
from trading_platform.ops.dr import DRContract, DRStatus, RecoveryProof
from trading_platform.ops.preflight import build_preflight, PreflightCheck
from trading_platform.verification.acceptance import AcceptanceItem, AcceptanceStatus, build_acceptance
from trading_platform.testnet.readonly_client import BinanceTestnetREST


def test_network_policy_allows_known_testnet_hosts_only():
    assert TESTNET_POLICY.decide('https://testnet.binancefuture.com') is NetworkDecision.ALLOW
    assert TESTNET_POLICY.decide('wss://fstream.binancefuture.com') is NetworkDecision.ALLOW
    assert TESTNET_POLICY.decide('https://fapi.binance.com') is NetworkDecision.DENY
    assert TESTNET_POLICY.decide('http://testnet.binancefuture.com') is NetworkDecision.DENY


def test_preflight_blocks_non_testnet_endpoint():
    r=build_preflight(environment='TESTNET', endpoint='https://fapi.binance.com')
    assert not r.can_execute
    assert any(x.status is PreflightCheck.FAIL for x in r.items)


def test_preflight_without_credentials_is_not_ready_but_can_readonly():
    r=build_preflight(endpoint='https://testnet.binancefuture.com', require_credentials=False)
    assert r.can_execute
    assert any(x.status is PreflightCheck.NOT_VERIFIED for x in r.items)


def test_dr_contract_enforces_rpo():
    DRContract('dr1',60,300,30,3600).validate()
    with pytest.raises(ValueError, match='BACKUP_FREQUENCY_EXCEEDS_RPO'):
        DRContract('dr1',60,300,61,3600).validate()


def test_recovery_proof_requires_all_conditions():
    assert RecoveryProof(True,True,True,True).verified
    assert not RecoveryProof(True,True,True,False).verified


def test_acceptance_blocks_when_blocking_item_not_pass():
    items=[AcceptanceItem('R1',AcceptanceStatus.PASS,'e1',True),AcceptanceItem('R2',AcceptanceStatus.NOT_VERIFIED,'',True)]
    assert not build_acceptance(items).production_ready


def test_acceptance_passes_when_all_blockers_pass():
    items=[AcceptanceItem('R1',AcceptanceStatus.PASS,'e1',True),AcceptanceItem('R2',AcceptanceStatus.PASS,'e2',True)]
    assert build_acceptance(items).production_ready


def test_testnet_client_rejects_mainnet_at_construction():
    with pytest.raises(PermissionError, match='NETWORK_POLICY_DENIED'):
        BinanceTestnetREST('https://fapi.binance.com')


def test_signed_account_requires_runtime_secrets():
    c=BinanceTestnetREST('https://testnet.binancefuture.com')
    with pytest.raises(ValueError, match='RUNTIME_CREDENTIALS_REQUIRED'):
        c.account()
