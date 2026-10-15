from dataclasses import dataclass

@dataclass(frozen=True)
class EventSchemaRegistration:
    schema_id: str
    event_type: str
    version: str
    compatibility_mode: str
    producer: str
    consumer: str
    effective_from: str
    deprecation_date: str | None=None
    migration_reference: str | None=None

class EventSchemaRegistry:
    def __init__(self): self._schemas={}
    def register(self, schema: EventSchemaRegistration):
        key=(schema.event_type,schema.version)
        if key in self._schemas: raise ValueError("EVENT_SCHEMA_ALREADY_REGISTERED")
        self._schemas[key]=schema
    def get(self,event_type,version): return self._schemas[(event_type,version)]
