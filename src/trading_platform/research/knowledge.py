from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class KnowledgeStatus(str, Enum):
    SUPPORTED='SUPPORTED'; DISPROVED='DISPROVED'; UNCERTAIN='UNCERTAIN'; OBSOLETE='OBSOLETE'

@dataclass(frozen=True)
class KnowledgeItem:
    knowledge_id: str
    claim: str
    status: KnowledgeStatus
    evidence_ids: tuple[str, ...]
    scope: str
    created_at: datetime
    supersedes: str | None = None

class KnowledgeBase:
    def __init__(self, items: tuple[KnowledgeItem,...]=()):
        self._items = {x.knowledge_id:x for x in items}
    def upsert_immutable(self, item: KnowledgeItem) -> None:
        old = self._items.get(item.knowledge_id)
        if old is not None and old != item:
            raise ValueError('IMMUTABLE_KNOWLEDGE_CHANGE')
        self._items[item.knowledge_id] = item
    def query(self, text: str) -> tuple[KnowledgeItem,...]:
        q = {x.lower() for x in text.split() if x}
        ranked=[]
        for item in self._items.values():
            t={x.lower() for x in item.claim.split()}
            score=len(q & t)
            if score: ranked.append((score,item))
        return tuple(x[1] for x in sorted(ranked,key=lambda p:(-p[0],p[1].knowledge_id)))
