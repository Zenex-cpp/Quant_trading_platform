from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol
from .models import OrderRequest, Fill
from .lifecycle import OrderExecutionState

class TestnetTransport(Protocol):
    def send(self, request:dict)->dict: ...
    def cancel(self, request:dict)->dict: ...
    def query(self, request:dict)->dict: ...

@dataclass(frozen=True)
class TestnetEndpointConfig:
    __test__ = False
    base_url:str
    environment:str='TESTNET'
    credentials_ref:str|None=None

class TestnetExecutionAdapter:
    __test__ = False
    def __init__(self, config:TestnetEndpointConfig, transport:TestnetTransport):
        if config.environment!='TESTNET': raise ValueError('NON_TESTNET_ENVIRONMENT_BLOCKED')
        self.config=config; self.transport=transport
    def submit(self, order:OrderRequest)->dict:
        return self.transport.send({'clientOrderId':order.client_order_id,'symbol':order.symbol,'side':order.side.value,'type':order.order_type.value,'quantity':str(order.quantity)})
    def cancel(self, *, symbol:str, client_order_id:str)->dict:
        return self.transport.cancel({'symbol':symbol,'origClientOrderId':client_order_id})
    def query(self, *, symbol:str, client_order_id:str)->dict:
        return self.transport.query({'symbol':symbol,'origClientOrderId':client_order_id})
