from trading_platform.replay.replay import canonical_hash

def test_hash_deterministic():
    a = canonical_hash({"b": 2, "a": 1})
    b = canonical_hash({"a": 1, "b": 2})
    assert a == b
