from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class VerificationStatus(str, Enum): PASS='PASS'; FAIL='FAIL'; NOT_VERIFIED='NOT_VERIFIED'
@dataclass(frozen=True)
class VerificationItem:
    requirement_id:str; status:VerificationStatus; evidence:str; reviewer:str|None=None
@dataclass(frozen=True)
class VerificationReport:
    items:tuple[VerificationItem,...]
    verified_count:int
    failed_count:int

def build_verification_report(items:list[VerificationItem])->VerificationReport:
    return VerificationReport(tuple(items), sum(i.status is VerificationStatus.PASS for i in items), sum(i.status is VerificationStatus.FAIL for i in items))
