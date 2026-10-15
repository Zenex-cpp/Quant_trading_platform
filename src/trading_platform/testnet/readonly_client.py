from __future__ import annotations
from dataclasses import dataclass
import json, os, time, hmac, hashlib
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from trading_platform.ops.network_policy import TESTNET_POLICY

@dataclass(frozen=True)
class ApiResponse:
    status:int
    body:dict | list | None
    elapsed_ms:int

class BinanceTestnetREST:
    """Small stdlib-only client. Never defaults to mainnet and never stores secrets."""
    def __init__(self, base_url: str='https://testnet.binancefuture.com', api_key: str|None=None, api_secret: str|None=None, timeout_s: float=10.0):
        self.base_url=base_url.rstrip('/')
        TESTNET_POLICY.assert_allowed(self.base_url)
        self.api_key=api_key
        self._api_secret=api_secret
        self.timeout_s=timeout_s

    def _request(self, method: str, path: str, params: dict[str,object]|None=None, signed: bool=False) -> ApiResponse:
        params=dict(params or {})
        headers={'User-Agent':'trading-platform-testnet/1.5','Accept':'application/json'}
        if self.api_key:
            headers['X-MBX-APIKEY']=self.api_key
        if signed:
            if not self.api_key or not self._api_secret:
                raise ValueError('RUNTIME_CREDENTIALS_REQUIRED')
            params.setdefault('timestamp', int(time.time()*1000))
            query=urlencode(params)
            sig=hmac.new(self._api_secret.encode(),query.encode(),hashlib.sha256).hexdigest()
            query += '&signature='+sig
        else:
            query=urlencode(params)
        url=self.base_url+path+(('?'+query) if query else '')
        t=time.monotonic()
        req=Request(url, method=method, headers=headers)
        with urlopen(req, timeout=self.timeout_s) as resp:
            payload=json.loads(resp.read().decode('utf-8')) if resp.length != 0 else None
            return ApiResponse(resp.status,payload,int((time.monotonic()-t)*1000))

    def ping(self)->ApiResponse:
        return self._request('GET','/fapi/v1/ping')

    def exchange_info(self)->ApiResponse:
        return self._request('GET','/fapi/v1/exchangeInfo')

    def account(self)->ApiResponse:
        return self._request('GET','/fapi/v3/account', signed=True)
