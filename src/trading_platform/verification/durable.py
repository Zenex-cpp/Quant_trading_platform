from __future__ import annotations
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

@dataclass(frozen=True)
class IdempotencyRecord:
    key: str
    operation: str
    result_hash: str
    created_at: str

class SQLiteIdempotencyStore:
    """Minimal durable dedupe primitive. Production deployment still requires HA/storage validation."""
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, operation TEXT NOT NULL, result_hash TEXT NOT NULL, created_at TEXT NOT NULL)")
            c.commit()

    def claim(self, key: str, operation: str, result_hash: str) -> bool:
        try:
            with sqlite3.connect(self.path) as c:
                c.execute("INSERT INTO idempotency(key,operation,result_hash,created_at) VALUES(?,?,?,?)", (key, operation, result_hash, datetime.now(timezone.utc).isoformat()))
                c.commit()
                return True
        except sqlite3.IntegrityError:
            return False

    def get(self, key: str) -> IdempotencyRecord | None:
        with sqlite3.connect(self.path) as c:
            row = c.execute("SELECT key,operation,result_hash,created_at FROM idempotency WHERE key=?", (key,)).fetchone()
        return IdempotencyRecord(*row) if row else None
