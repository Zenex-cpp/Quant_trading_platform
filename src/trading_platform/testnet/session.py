from __future__ import annotations
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping
import hashlib, json, os, secrets
from datetime import datetime, timezone

class SessionStatus(str, Enum):
    PLANNED='PLANNED'; RUNNING='RUNNING'; PASSED='PASSED'; FAILED='FAILED'; NOT_VERIFIED='NOT_VERIFIED'

@dataclass(frozen=True)
class SessionConfig:
    environment: str = 'TESTNET'
    base_url: str = ''
    websocket_url: str = ''
    symbol: str = 'BTCUSDT'
    evidence_dir: Path = Path('evidence/testnet_live')
    max_order_notional: str = '25'
    request_timeout_s: int = 15

    @classmethod
    def from_env(cls) -> 'SessionConfig':
        return cls(
            environment=os.getenv('BINANCE_TESTNET_ENV', 'TESTNET'),
            base_url=os.getenv('BINANCE_TESTNET_BASE_URL', ''),
            websocket_url=os.getenv('BINANCE_TESTNET_WS_URL', ''),
            symbol=os.getenv('BINANCE_TESTNET_SYMBOL', 'BTCUSDT').upper(),
            evidence_dir=Path(os.getenv('BINANCE_EVIDENCE_DIR', 'evidence/testnet_live')),
            max_order_notional=os.getenv('BINANCE_TESTNET_MAX_ORDER_NOTIONAL', '25'),
            request_timeout_s=int(os.getenv('BINANCE_TESTNET_TIMEOUT_S', '15')),
        )

    def validate(self) -> None:
        if self.environment != 'TESTNET':
            raise ValueError('NON_TESTNET_ENVIRONMENT_BLOCKED')
        if not self.base_url.startswith('https://'):
            raise ValueError('TLS_REQUIRED')
        if 'binance.com' in self.base_url and 'testnet' not in self.base_url:
            raise ValueError('MAINNET_HOST_BLOCKED')
        if self.websocket_url and not self.websocket_url.startswith('wss://'):
            raise ValueError('WEBSOCKET_TLS_REQUIRED')
        if self.websocket_url and 'binance.com' in self.websocket_url and 'testnet' not in self.websocket_url:
            raise ValueError('MAINNET_WS_HOST_BLOCKED')
        if not self.symbol.isalnum():
            raise ValueError('INVALID_SYMBOL')
        if self.request_timeout_s <= 0:
            raise ValueError('INVALID_TIMEOUT')

@dataclass(frozen=True)
class EvidenceArtifact:
    evidence_id: str
    session_id: str
    scenario_id: str
    status: SessionStatus
    started_at: str
    completed_at: str
    request_meta: Mapping[str, Any]
    observations: tuple[str, ...]
    invariant_results: tuple[str, ...]
    response_hash: str | None
    state_snapshot_hash: str | None
    error_code: str | None
    operator: str

    def canonical_bytes(self) -> bytes:
        return json.dumps(asdict(self), sort_keys=True, separators=(',', ':'), default=lambda x: x.value if isinstance(x, Enum) else x).encode()

    @property
    def artifact_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

class LiveTestnetSession:
    """Execution coordinator. It never obtains production credentials and never persists secret values."""
    def __init__(self, config: SessionConfig, *, api_key: str, secret: bytes, transport: Any):
        config.validate()
        if not api_key or not secret:
            raise ValueError('TESTNET_CREDENTIALS_REQUIRED')
        self.config=config
        self.api_key=api_key
        self.secret=secret
        self.transport=transport
        self.session_id='tns_'+secrets.token_hex(12)
        self.status=SessionStatus.PLANNED
        self.config.evidence_dir.mkdir(parents=True, exist_ok=True)

    def _artifact(self, scenario_id: str, status: SessionStatus, *, started: str, request_meta: Mapping[str,Any], observations=(), invariants=(), response_hash=None, state_snapshot_hash=None, error_code=None) -> EvidenceArtifact:
        a=EvidenceArtifact('evid_'+secrets.token_hex(12), self.session_id, scenario_id, status, started, datetime.now(timezone.utc).isoformat(), request_meta, tuple(observations), tuple(invariants), response_hash, state_snapshot_hash, error_code, os.getenv('USER','unknown'))
        p=self.config.evidence_dir/f'{scenario_id}_{a.evidence_id}.json'
        payload=asdict(a); payload['artifact_hash']=a.artifact_hash
        p.write_text(json.dumps(payload, sort_keys=True, indent=2, default=lambda x: x.value if isinstance(x, Enum) else x))
        (p.with_suffix('.sha256')).write_text(a.artifact_hash+'  '+p.name+'\n')
        return a

    def run_probe(self, scenario_id: str, method: str, path: str, params: Mapping[str,str], probe: Callable[[Mapping[str,Any]], tuple[bool, tuple[str,...], tuple[str,...]]], request_meta: Mapping[str,Any] | None = None) -> EvidenceArtifact:
        started=datetime.now(timezone.utc).isoformat(); self.status=SessionStatus.RUNNING
        req={**(request_meta or {}), 'method':method, 'path':path, 'params_keys':sorted(params.keys())}
        try:
            response=self.transport.signed_request(method, path, params=params, api_key=self.api_key, secret=self.secret)
            response_hash=hashlib.sha256(json.dumps(response,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            ok,obs,inv=probe(response)
            status=SessionStatus.PASSED if ok else SessionStatus.FAILED
            result=self._artifact(scenario_id,status,started=started,request_meta=req,observations=obs,invariants=inv,response_hash=response_hash)
            self.status=status
            return result
        except Exception as exc:
            result=self._artifact(scenario_id,SessionStatus.FAILED,started=started,request_meta=req,error_code=type(exc).__name__+':'+str(exc))
            self.status=SessionStatus.FAILED
            return result
