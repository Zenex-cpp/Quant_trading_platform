"""Central leakage scanner producing machine-readable findings."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable
from trading_platform.data_v03 import LeakageFinding, LEAKAGE_CATEGORIES

@dataclass(frozen=True)
class LeakageScanResult:
    findings: tuple[LeakageFinding, ...]
    blocked: bool


def scan(*, observations: list[dict[str, Any]], prediction_time_field: str="prediction_time", availability_field: str="available_at",
         event_time_field: str="event_time", split_field: str|None=None) -> LeakageScanResult:
    findings: list[LeakageFinding] = []
    now = datetime.now(timezone.utc)
    for i,row in enumerate(observations):
        def dt(k):
            v=row.get(k)
            if isinstance(v, datetime): return v
            return datetime.fromisoformat(str(v).replace("Z","+00:00")) if v else None
        try:
            pt, av, et = dt(prediction_time_field), dt(availability_field), dt(event_time_field)
            if pt and av and av > pt:
                findings.append(LeakageFinding(f"pit:{i}","FEATURE_LEAKAGE","CRITICAL",str(i),"available_at>prediction_time","remove future information",now))
            if pt and et and et > pt:
                findings.append(LeakageFinding(f"event:{i}","TIMESTAMP_LEAKAGE","CRITICAL",str(i),"event_time>prediction_time","exclude future event",now))
        except Exception:
            findings.append(LeakageFinding(f"time:{i}","TIMESTAMP_LEAKAGE","HIGH",str(i),"unparseable temporal field","reject row or normalize using explicit policy",now))
    seen: set[Any] = set()
    for i,row in enumerate(observations):
        key = row.get(split_field) if split_field else tuple(sorted((k,repr(v)) for k,v in row.items()))
        if key in seen:
            findings.append(LeakageFinding(f"seldup:{i}","DUPLICATED_OBSERVATION","HIGH",str(i),"duplicate key","deduplicate before model evaluation",now))
        seen.add(key)
    return LeakageScanResult(tuple(findings), any(f.severity in {"CRITICAL","EMERGENCY"} for f in findings))
