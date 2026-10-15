from dataclasses import dataclass
from hashlib import sha256

@dataclass(frozen=True)
class Operation:
    idempotency_key: str
    operation_type: str
    payload_hash: str

class IdempotencyStore:
    def __init__(self) -> None:
        self._results: dict[str, tuple[str, object]] = {}

    def execute_once(self, op: Operation, result: object) -> object:
        prior = self._results.get(op.idempotency_key)
        if prior:
            prior_type, prior_result = prior
            if prior_type != op.payload_hash:
                raise RuntimeError("IDEMPOTENCY_KEY_COLLISION")
            return prior_result
        self._results[op.idempotency_key] = (op.payload_hash, result)
        return result


def payload_hash(payload: bytes) -> str:
    return sha256(payload).hexdigest()
