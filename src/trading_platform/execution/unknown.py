from dataclasses import dataclass
from enum import Enum

class UnknownResolution(str, Enum):
    RECONCILED='RECONCILED'; CANCELLED='CANCELLED'; REJECTED='REJECTED'; FILLED='FILLED'; EXPIRED='EXPIRED'; STILL_UNKNOWN='STILL_UNKNOWN'

@dataclass(frozen=True)
class UnknownOrderCase:
    case_id:str
    client_order_id:str
    exchange_order_id:str|None
    attempts:int=0
    status:str='OPEN'

class UnknownOrderResolver:
    def __init__(self) -> None: self.cases={}
    def open(self, case: UnknownOrderCase) -> None:
        self.cases[case.case_id]=case
    def assert_no_blind_retry(self, case_id:str) -> None:
        c=self.cases[case_id]
        if c.status=='OPEN': raise ValueError('UNKNOWN_ORDER_NO_BLIND_RETRY')
    def resolve(self, case_id:str, resolution: UnknownResolution = UnknownResolution.RECONCILED) -> UnknownOrderCase:
        c=self.cases[case_id]
        return UnknownOrderCase(c.case_id,c.client_order_id,c.exchange_order_id,c.attempts,'RESOLVED:'+resolution.value)
