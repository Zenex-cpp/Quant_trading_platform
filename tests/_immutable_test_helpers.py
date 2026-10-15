from __future__ import annotations
from typing import Any

def tamper_event_store(store, sql: str, params: tuple[Any, ...] = ()) -> None:
    store._db.execute("DROP TRIGGER IF EXISTS deny_event_update")
    store._db.execute("DROP TRIGGER IF EXISTS deny_event_delete")
    store._db.execute(sql, params)
    store._db.commit()

def tamper_checkpoint_store(store, sql: str, params: tuple[Any, ...] = ()) -> None:
    store._db.execute("DROP TRIGGER IF EXISTS deny_checkpoint_update")
    store._db.execute("DROP TRIGGER IF EXISTS deny_checkpoint_delete")
    store._db.execute(sql, params)
    store._db.commit()
