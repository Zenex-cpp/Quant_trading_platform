"""Deterministic dataset ingestion/audit primitives for V0.3."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import csv, json, math
from trading_platform.data_v03 import DatasetContract, QualityStatus, content_hash, canonical_json, validate_temporal_order, scan_duplicate_observations

UTC = timezone.utc

@dataclass(frozen=True)
class DatasetAuditReport:
    dataset_id: str
    row_count: int
    columns: tuple[str, ...]
    duplicate_count: int
    out_of_order: bool
    null_counts: dict[str, int]
    invalid_numeric_counts: dict[str, int]
    invalid_ohlc_count: int
    nonpositive_price_count: int
    negative_volume_count: int
    timezone_aware_event_time: bool
    quality_status: QualityStatus
    findings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["quality_status"] = self.quality_status.value
        return d


def load_csv(path: str | Path) -> list[dict[str, str]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    with p.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def _num(value: Any) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    x = float(value)
    return x if math.isfinite(x) else None


def audit_ohlcv(records: list[dict[str, Any]], *, event_time_field: str = "event_time") -> DatasetAuditReport:
    columns = tuple(records[0].keys()) if records else tuple()
    null_counts = {c: sum(1 for r in records if r.get(c) in (None, "")) for c in columns}
    invalid_numeric_counts = {c: 0 for c in ("open", "high", "low", "close", "volume") if c in columns}
    bad_ohlc = bad_price = bad_volume = 0
    aware = True
    temporal = False
    findings: list[str] = []
    parsed_times: list[datetime] = []
    for r in records:
        try:
            dt = _parse_dt(r[event_time_field]); aware = aware and dt.tzinfo is not None
            parsed_times.append(dt)
        except Exception:
            aware = False; findings.append("INVALID_EVENT_TIME")
            continue
        vals = {k: _num(r.get(k)) for k in ("open","high","low","close","volume") if k in columns}
        for k,v in vals.items():
            if v is None and r.get(k) not in (None, ""):
                invalid_numeric_counts[k] += 1
        if all(k in vals and vals[k] is not None for k in ("open","high","low","close")):
            o,h,l,c = (vals[k] for k in ("open","high","low","close"))
            if h < max(o,l,c) or l > min(o,h,c) or h < l:
                bad_ohlc += 1
            if min(o,h,l,c) <= 0: bad_price += 1
        if "volume" in vals and vals["volume"] is not None and vals["volume"] < 0:
            bad_volume += 1
    if parsed_times:
        ordered = all(parsed_times[i] >= parsed_times[i-1] for i in range(1,len(parsed_times)))
        temporal = not ordered
        if temporal: findings.append("OUT_OF_ORDER_DATA")
    dups = scan_duplicate_observations(records, tuple(x for x in (event_time_field, "symbol") if x in columns)) if columns else []
    if dups:
        findings.append("DUPLICATES")
    if not aware: findings.append("NAIVE_TIMESTAMP")
    if bad_ohlc: findings.append("INVALID_OHLC")
    if bad_price: findings.append("INVALID_PRICE")
    if bad_volume: findings.append("NEGATIVE_VOLUME")
    if any(invalid_numeric_counts.values()): findings.append("INVALID_NUMERIC")
    critical = (not aware) or bad_ohlc or bad_price or bad_volume or any(invalid_numeric_counts.values())
    status = QualityStatus.CRITICAL if critical else (QualityStatus.WARNING if findings else QualityStatus.VALID)
    return DatasetAuditReport(
        dataset_id="UNBOUND", row_count=len(records), columns=columns,
        duplicate_count=len(dups), out_of_order=temporal, null_counts=null_counts,
        invalid_numeric_counts=invalid_numeric_counts, invalid_ohlc_count=bad_ohlc,
        nonpositive_price_count=bad_price, negative_volume_count=bad_volume,
        timezone_aware_event_time=aware, quality_status=status, findings=tuple(sorted(set(findings)))
    )
