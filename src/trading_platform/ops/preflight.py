from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import os

class PreflightCheck(str, Enum): PASS='PASS'; FAIL='FAIL'; WARNING='WARNING'; NOT_VERIFIED='NOT_VERIFIED'

@dataclass(frozen=True)
class PreflightItem:
    check_id:str
    status:PreflightCheck
    detail:str

@dataclass(frozen=True)
class PreflightReport:
    environment:str
    items:tuple[PreflightItem,...]
    can_execute:bool


def build_preflight(*, environment: str='TESTNET', endpoint: str='', require_credentials: bool=False) -> PreflightReport:
    items=[]
    items.append(PreflightItem('PF-ENV', PreflightCheck.PASS if environment=='TESTNET' else PreflightCheck.FAIL, environment))
    tls_ok=endpoint.startswith(('https://','wss://')) if endpoint else False
    items.append(PreflightItem('PF-TLS', PreflightCheck.PASS if tls_ok else PreflightCheck.FAIL, endpoint or 'missing endpoint'))
    prod_blocked=all(x not in endpoint.lower() for x in ('fapi.binance.com','dapi.binance.com','api.binance.com','ws-fapi.binance.com','fstream.binance.com'))
    items.append(PreflightItem('PF-NO-PROD', PreflightCheck.PASS if prod_blocked else PreflightCheck.FAIL, 'production endpoints denied' if prod_blocked else 'production marker detected'))
    if require_credentials:
        ok=bool(os.getenv('BINANCE_TESTNET_API_KEY')) and bool(os.getenv('BINANCE_TESTNET_API_SECRET'))
        items.append(PreflightItem('PF-CREDS', PreflightCheck.PASS if ok else PreflightCheck.FAIL, 'runtime credentials present' if ok else 'runtime credentials missing'))
    else:
        items.append(PreflightItem('PF-CREDS', PreflightCheck.NOT_VERIFIED, 'credentials intentionally not required for offline preflight'))
    can=all(i.status is not PreflightCheck.FAIL for i in items[:3])
    if require_credentials: can=can and items[3].status is PreflightCheck.PASS
    return PreflightReport(environment, tuple(items), can)
