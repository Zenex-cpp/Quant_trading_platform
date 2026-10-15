# V0.7 Compliance

| Requirement | Priority | Status | Evidence / test | Gap |
|---|---|---|---|---|
| Event envelope preserves source/receive/processing time | CRITICAL | IMPLEMENTED | tests/test_v07.py | durable event bus pending |
| Unknown delivery semantics are not claimed as exactly-once | CRITICAL | IMPLEMENTED | realtime/events.py | venue feed proof pending |
| Order book requires synchronized snapshot | CRITICAL | IMPLEMENTED | tests/test_v07.py | live venue adapter pending |
| Sequence gap blocks synchronized book use | CRITICAL | IMPLEMENTED | tests/test_v07.py | venue-specific resync procedure pending |
| Duplicate/old book updates have no side effects | CRITICAL | IMPLEMENTED | tests/test_v07.py | durable dedupe store pending |
| Crossed/invalid book blocks use | CRITICAL | IMPLEMENTED | tests/test_v07.py | operational alerting pending |
| Higher clock-integrity risk cannot permit new entry | CRITICAL | IMPLEMENTED | realtime/clock.py | system lifecycle integration pending |
| Rate-limit exhaustion is a hard condition | HIGH | IMPLEMENTED | tests/test_v07.py | real exchange counters pending |
| Microstructure requires valid synchronized book | HIGH | IMPLEMENTED | tests/test_v07.py | PIT feature lineage integration pending |
| Binance constraints isolated to adapter/reference layer | HIGH | IMPLEMENTED | docs/25_V07_REALTIME.md | real adapter pending |
| Live credentials/order placement absent from V0.7 | CRITICAL | VERIFIED_BY_ABSENCE | repository scope review | production adapter intentionally deferred |
