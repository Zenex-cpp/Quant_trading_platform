from __future__ import annotations
import hashlib, hmac, time
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import urlencode

class HttpTransport(Protocol):
    def request(self, method: str, url: str, *, headers: Mapping[str,str] | None = None, params: Mapping[str,str] | None = None) -> Mapping[str,Any]: ...

@dataclass(frozen=True)
class TestnetClientConfig:
    __test__ = False
    base_url: str
    api_key_ref: str
    secret_ref: str
    environment: str = "TESTNET"
    recv_window_ms: int = 5000

    def validate(self) -> None:
        if self.environment != "TESTNET":
            raise ValueError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        if not self.base_url.startswith("https://"):
            raise ValueError("TLS_REQUIRED")
        if not self.api_key_ref or not self.secret_ref:
            raise ValueError("SECRET_REFERENCE_REQUIRED")
        if self.recv_window_ms <= 0:
            raise ValueError("INVALID_RECV_WINDOW")

class BinanceTestnetSigner:
    @staticmethod
    def sign(secret: bytes, params: Mapping[str, str]) -> str:
        payload = urlencode(sorted((str(k), str(v)) for k,v in params.items()))
        return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()

class BinanceTestnetClient:
    """Contract client. Credential values are supplied at call time and never stored."""
    def __init__(self, config: TestnetClientConfig, transport: HttpTransport):
        config.validate(); self.config=config; self.transport=transport

    def signed_request(self, method: str, path: str, *, params: Mapping[str,str], api_key: str, secret: bytes) -> Mapping[str,Any]:
        if self.config.environment != "TESTNET":
            raise RuntimeError("NON_TESTNET_ENVIRONMENT_BLOCKED")
        p=dict(params); p.setdefault("timestamp", str(int(time.time()*1000))); p.setdefault("recvWindow", str(self.config.recv_window_ms))
        p["signature"] = BinanceTestnetSigner.sign(secret, p)
        return self.transport.request(method, self.config.base_url.rstrip("/")+path, headers={"X-MBX-APIKEY": api_key}, params=p)
