#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'src'))

from trading_platform.v383_connectivity import TestnetConnectivityConfigV383, TestnetConnectivityPreflightV383, PreflightStatus


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--probe-only', action='store_true', default=False)
    args=ap.parse_args()
    cfg=TestnetConnectivityConfigV383(rest_base_url='https://testnet.binancefuture.com', ws_api_url='', ws_private_url='wss://fstream.binancefuture.com/private')
    evidence=TestnetConnectivityPreflightV383(config=cfg).run()
    payload={
        'artifact_type':'V387_FIRST_TESTNET_RUNNER_PREFLIGHT_EVIDENCE',
        'retrieved_at':datetime.now(timezone.utc).isoformat(),
        'probe_only':True,
        'connectivity_status':evidence.status.value,
        'rest_endpoint':evidence.rest_endpoint,
        'ws_private_endpoint':evidence.ws_private_endpoint,
        'rest_dns':evidence.rest_dns,
        'reason':evidence.reason,
        'mutating_api_called':False,
        'production_ready':False,
        'submit_performed':False,
        'operator_gate': 'NOT_REACHED' if evidence.status is not PreflightStatus.VERIFIED else 'READY_FOR_OPERATOR_GATE',
    }
    raw=json.dumps(payload,sort_keys=True,separators=(',',':')).encode()
    payload['evidence_hash']=hashlib.sha256(raw).hexdigest()
    out=ROOT/'V387_FIRST_TESTNET_RUNNER_PREFLIGHT_EVIDENCE.json'
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    print(out)
    print(evidence.status.value, evidence.reason)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
