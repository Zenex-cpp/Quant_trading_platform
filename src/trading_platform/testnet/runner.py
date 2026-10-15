from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol
import json, os, hashlib, urllib.request, urllib.parse

from .client import BinanceTestnetClient, TestnetClientConfig
from .evidence import TestnetEvidence, EvidenceStatus
from .scenarios import SCENARIOS, ScenarioStatus

class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str, str] | None = None, params: Mapping[str, str] | None = None) -> Mapping[str, Any]: ...

class UrllibTransport:
    def request(self, method: str, url: str, *, headers=None, params=None):
        params = dict(params or {})
        encoded = urllib.parse.urlencode(params)
        target = url + ("&" if "?" in url else "?") + encoded if encoded else url
        req = urllib.request.Request(target, method=method.upper(), headers=dict(headers or {}))
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

@dataclass(frozen=True)
class RunnerConfig:
    base_url: str
    websocket_url: str | None
    symbol: str = "BTCUSDT"
    environment: str = "TESTNET"
    evidence_dir: Path = Path("evidence/testnet")
    request_timeout_s: int = 15

    @classmethod
    def from_env(cls) -> "RunnerConfig":
        base = os.environ.get("BINANCE_TESTNET_BASE_URL", "").strip()
        ws = os.environ.get("BINANCE_TESTNET_WS_URL", "").strip() or None
        symbol = os.environ.get("BINANCE_TESTNET_SYMBOL", "BTCUSDT").strip().upper()
        return cls(base, ws, symbol)

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise ValueError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if not self.base_url.startswith("https://"):
            raise ValueError("TLS_REQUIRED")
        if "binance.com" in self.base_url and "testnet" not in self.base_url:
            raise ValueError("MAINNET_HOST_BLOCKED")
        if self.websocket_url:
            if not self.websocket_url.startswith("wss://"):
                raise ValueError("WEBSOCKET_TLS_REQUIRED")
            if "binance.com" in self.websocket_url and "testnet" not in self.websocket_url:
                raise ValueError("MAINNET_WS_HOST_BLOCKED")
        if not self.symbol or not self.symbol.isalnum():
            raise ValueError("INVALID_SYMBOL")

@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    name: str
    status: ScenarioStatus
    started_at: str
    completed_at: str
    environment: str
    endpoint: str
    request_ref: str
    response_hash: str | None
    observations: tuple[str, ...]
    invariant_results: tuple[str, ...]
    failure: str | None = None

    def canonical_bytes(self) -> bytes:
        data = asdict(self)
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()

    @property
    def artifact_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

class LiveTestnetEvidenceRunner:
    """Explicitly TESTNET-only runner. It never accepts a production environment."""
    def __init__(self, config: RunnerConfig, *, api_key: str, secret: bytes, transport: Transport | None = None):
        config.validate()
        if not api_key or not secret:
            raise ValueError("TESTNET_CREDENTIALS_REQUIRED")
        self.config = config
        self.client = BinanceTestnetClient(
            TestnetClientConfig(config.base_url, "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET", "TESTNET"),
            transport or UrllibTransport(),
        )
        self.api_key = api_key
        self.secret = secret

    def _write_result(self, result: ScenarioResult) -> None:
        self.config.evidence_dir.mkdir(parents=True, exist_ok=True)
        p = self.config.evidence_dir / f"{result.scenario_id}.json"
        p.write_bytes(result.canonical_bytes())
        (self.config.evidence_dir / f"{result.scenario_id}.sha256").write_text(result.artifact_hash + "  " + p.name + "\n")

    def run_signed_query(self, *, scenario_id: str, name: str, method: str, path: str, params: Mapping[str, str], request_ref: str) -> ScenarioResult:
        started = datetime.now(timezone.utc).isoformat()
        status = ScenarioStatus.PASS
        failure = None
        obs: list[str] = []
        inv: list[str] = []
        response_hash = None
        try:
            response = self.client.signed_request(method, path, params=params, api_key=self.api_key, secret=self.secret)
            payload = json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
            response_hash = hashlib.sha256(payload).hexdigest()
            obs.append("response_received")
            inv.append("transport_response_present=PASS")
        except Exception as exc:
            status = ScenarioStatus.FAIL
            failure = type(exc).__name__ + ":" + str(exc)
            inv.append("transport_response_present=FAIL")
        completed = datetime.now(timezone.utc).isoformat()
        result = ScenarioResult(scenario_id, name, status, started, completed, self.config.environment, self.config.base_url + path, request_ref, response_hash, tuple(obs), tuple(inv), failure)
        self._write_result(result)
        return result

def offline_runner_contract_summary() -> dict[str, Any]:
    return {
        "required_scenarios": [s.scenario_id for s in SCENARIOS if s.required],
        "live_network_required": [s.scenario_id for s in SCENARIOS if s.live_network_required],
        "offline_only": [s.scenario_id for s in SCENARIOS if not s.live_network_required],
        "production_ready": False,
    }
