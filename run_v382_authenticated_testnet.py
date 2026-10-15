#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from trading_platform.v382 import AuthenticatedTestnetConfigV382, AuthSessionState, BinanceAuthenticatedTestnetSessionV382
from trading_platform.v39.binance_user_data_control import BinanceUserDataControl, BinanceUserDataControlConfig

class FakeControlTransport:
    def __init__(self): self.key="LK-LOCAL"; self.calls=[]
    def request(self, *, url, payload, api_key):
        self.calls.append(payload["method"])
        method=payload["method"]
        if method == "userDataStream.start": return {"id":payload["id"],"status":200,"result":{"listenKey":self.key}}
        if method == "userDataStream.ping": return {"id":payload["id"],"status":200,"result":{"listenKey":self.key}}
        if method == "userDataStream.stop": return {"id":payload["id"],"status":200,"result":{}}
        raise AssertionError(method)

class FakeStream:
    def __init__(self): self.urls=[]; self.q=[]
    def connect(self,url): self.urls.append(url)
    def send(self,payload): pass
    def recv(self,timeout_s): return self.q.pop(0) if self.q else None
    def close(self): pass

def local_checks():
    c=FakeControlTransport()
    control=BinanceUserDataControl(transport=c, config=BinanceUserDataControlConfig(url="wss://testnet.binancefuture.com/ws-fapi/v1", keepalive_interval_s=3300), request_id=lambda:"RID")
    s=FakeStream()
    session=BinanceAuthenticatedTestnetSessionV382(config=AuthenticatedTestnetConfigV382(control_url="wss://testnet.binancefuture.com/ws-fapi/v1"), control=control, stream_transport=s, clock=lambda:1.0)
    checks=[]
    snap=session.start(api_key="LOCAL_API_KEY", now_epoch=1.0)
    checks.append({"check":"control_start","pass":snap.state is AuthSessionState.STREAMING and c.calls==["userDataStream.start"]})
    s.q.append(json.dumps({"e":"ORDER_TRADE_UPDATE","E":1000,"T":1000,"o":{"s":"BTCUSDT","c":"cid","S":"BUY","o":"LIMIT","f":"GTC","q":"0.001","ap":"0","x":"NEW","X":"NEW","i":1,"l":"0","z":"0","L":"0","t":"0"}}))
    r=session.receive_once(now_epoch=1.001)
    checks.append({"check":"private_event_projection","pass":bool(r and r.accepted) and session.snapshot(1.001).trading_allowed})
    c.key="LK-ROTATED"
    keep=session.keepalive(now_epoch=2.0)
    checks.append({"check":"listen_key_rotation","pass":keep.state is AuthSessionState.STREAMING and session.listen_key=="LK-ROTATED" and len(s.urls)==2})
    s.q.append(json.dumps({"e":"listenKeyExpired","E":2000,"T":2000}))
    session.receive_once(now_epoch=2.001)
    expired=session.snapshot(2.001)
    checks.append({"check":"expiry_fail_closed","pass":expired.state is AuthSessionState.EXPIRED and not expired.trading_allowed})
    stop=session.stop(now_epoch=2.002)
    checks.append({"check":"stop_control_plane","pass":c.calls[-1]=="userDataStream.stop" and stop.state is AuthSessionState.STOPPED})
    return checks

def main():
    cfg=AuthenticatedTestnetConfigV382.from_env()
    checks=local_checks()
    live_status="NOT_VERIFIED" if not cfg.control_url or not os.getenv("BINANCE_TESTNET_API_KEY") else "PLANNED"
    payload={
      "artifact_type":"V382_AUTHENTICATED_TESTNET_EVIDENCE",
      "schema_version":"V382_AUTHENTICATED_TESTNET_1",
      "generated_at":datetime.now(timezone.utc).isoformat(),
      "local_status":"PASS" if all(x["pass"] for x in checks) else "FAIL",
      "local_checks":checks,
      "live_status":live_status,
      "live_reason":"LIVE_AUTHENTICATED_TESTNET_REQUIRES_OPERATOR_API_KEY_AND_EXPLICIT_TESTNET_WS_API_URL",
      "mutation":"NONE",
      "production_ready":False,
    }
    canonical=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()
    payload["evidence_hash"]=hashlib.sha256(canonical).hexdigest()
    out=ROOT/"V382_AUTHENTICATED_TESTNET_EVIDENCE.json"
    out.write_text(json.dumps(payload,indent=2,sort_keys=True)+"\n")
    print(out)
    print(payload["evidence_hash"])
    return 0 if payload["local_status"]=="PASS" else 1
if __name__=="__main__": raise SystemExit(main())
