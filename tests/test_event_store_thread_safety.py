from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from trading_platform.v21.event_store import EventStore


def test_shared_event_store_serializes_concurrent_appends_and_verifies_chain():
    store = EventStore()
    worker_count = 6
    events_per_worker = 12
    barrier = Barrier(worker_count)

    def append_for_worker(worker_id: int) -> None:
        barrier.wait(timeout=5)
        for event_index in range(events_per_worker):
            store.append(
                event_id=f"thread:{worker_id}:{event_index}",
                occurred_at_ms=worker_id * events_per_worker + event_index,
                event_type="THREAD_SAFETY_TEST",
                aggregate_id=f"worker:{worker_id}",
                payload={"worker_id": worker_id, "event_index": event_index},
            )

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(append_for_worker, worker_id) for worker_id in range(worker_count)]
        for future in futures:
            future.result(timeout=10)

    events = list(store.iter_events())
    assert len(events) == worker_count * events_per_worker
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert store.latest_sequence() == len(events)
    assert store.verify_chain()
    store.close()
