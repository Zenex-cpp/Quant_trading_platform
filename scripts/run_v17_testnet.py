#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from trading_platform.v17.workflow import WorkflowConfig, TestnetWorkflow, Environment
from trading_platform.v18.execution import OrderIntent, SafeTestnetExecution

class UrllibJsonTransport:
    def request(self, method, url, *, headers=None, params=None):
        import json, urllib.parse, urllib.request
        q=urllib.parse.urlencode(params or {}, doseq=True)
        target=url + (("?" + q) if q else "")
        req=urllib.request.Request(target, method=method, headers=dict(headers or {}))
        with urllib.request.urlopen(req, timeout=15) as r:
            raw=r.read().decode("utf-8")
            return json.loads(raw) if raw else {}

class RuntimeSignedTransport:
    """Credentials exist only in this runtime object; never serialized or persisted."""
    def __init__(self, api_key, api_secret):
        self.api_key=api_key
        self.api_secret=api_secret

    def request(self, method, url, *, headers=None, params=None):
        import hashlib, hmac, json, time, urllib.parse, urllib.request
        p={str(k):str(v) for k,v in (params or {}).items()}
        p.setdefault("timestamp", str(int(time.time()*1000)))
        p.setdefault("recvWindow", "5000")
        query=urllib.parse.urlencode(sorted(p.items()))
        sig=hmac.new(self.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        query += "&signature=" + sig
        target=url + (("?" + query) if query else "")
        h={"Accept":"application/json", "X-MBX-APIKEY":self.api_key}; h.update(headers or {})
        req=urllib.request.Request(target, method=method, headers=h)
        with urllib.request.urlopen(req, timeout=15) as r:
            raw=r.read().decode("utf-8")
            return json.loads(raw) if raw else {}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--plan-only', action='store_true', default=True)
    p.add_argument('--network-read-only', action='store_true', help='opt in to live Testnet read-only probes')
    p.add_argument('--test-order', action='store_true', help='opt in to signed Test Order on Testnet; no matching-engine mutation')
    p.add_argument('--base-url', default=os.getenv('BINANCE_TESTNET_BASE_URL','https://testnet.binancefuture.com'))
    p.add_argument('--symbol', default=os.getenv('BINANCE_TESTNET_SYMBOL','BTCUSDT'))
    p.add_argument('--evidence-db', default='evidence/v17/evidence.sqlite')
    a=p.parse_args()
    cfg=WorkflowConfig(a.base_url, a.symbol, Environment.TESTNET, Path(a.evidence_db))
    transport=UrllibJsonTransport()
    wf=TestnetWorkflow(cfg, transport=transport, operator_id=os.getenv('TRADING_PLATFORM_OPERATOR_ID','offline'))
    if a.test_order:
        key=os.getenv('BINANCE_TESTNET_API_KEY'); secret=os.getenv('BINANCE_TESTNET_API_SECRET')
        if not key or not secret:
            print(json.dumps({'status':'BLOCKED','reason':'RUNTIME_CREDENTIALS_REQUIRED'}, indent=2))
            return 2
        transport=RuntimeSignedTransport(key, secret)
        wf=TestnetWorkflow(cfg, transport=transport, operator_id=os.getenv('TRADING_PLATFORM_OPERATOR_ID','offline'))
        intent=OrderIntent.deterministic(symbol=a.symbol, side='BUY', order_type='LIMIT', quantity='0.0001', price='1000')
        e=SafeTestnetExecution(wf)
        try:
            print(json.dumps(e.test_order(intent).__dict__, indent=2, sort_keys=True))
        except Exception as exc:
            print(json.dumps({'status':'FAIL','error':f'{type(exc).__name__}:{exc}'}, indent=2))
            return 3
        return 0
    if not a.network_read_only:
        print(json.dumps(wf.offline_report(), indent=2, sort_keys=True))
        return 0
    print(json.dumps({'TN-01': wf.read_only_probe('TN-01','ping','/fapi/v1/ping').status,
                      'TN-02': wf.read_only_probe('TN-02','exchange_rules','/fapi/v1/exchangeInfo').status}, indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
