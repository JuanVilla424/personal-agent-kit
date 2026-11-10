import asyncio
import logging
import time

log = logging.getLogger("thread-manager")

_queues: dict[str, asyncio.Queue] = {}
_workers: dict[str, asyncio.Task] = {}
_last_activity: dict[str, float] = {}
_IDLE_CLEANUP_SECS = 600


def get_queue(thread_id: str) -> asyncio.Queue:
    if thread_id not in _queues:
        _queues[thread_id] = asyncio.Queue()
        log.debug("Queue created for thread %s", thread_id)
    _last_activity[thread_id] = time.monotonic()
    return _queues[thread_id]


def active_thread_count() -> int:
    return sum(1 for t in _workers.values() if not t.done())


def cleanup_idle() -> None:
    now = time.monotonic()
    stale = [tid for tid, ts in _last_activity.items() if now - ts > _IDLE_CLEANUP_SECS]
    for tid in stale:
        if tid in _workers and _workers[tid].done():
            _workers.pop(tid, None)
            _queues.pop(tid, None)
            _last_activity.pop(tid, None)
            log.debug("Cleaned up idle thread %s", tid)


def register_worker(thread_id: str, task: asyncio.Task) -> None:
    _workers[thread_id] = task


def queue_size(thread_id: str) -> int:
    q = _queues.get(thread_id)
    return q.qsize() if q else 0


def total_queue_depth() -> int:
    return sum(q.qsize() for q in _queues.values())
