# utils/event_bus.py
from __future__ import annotations
from queue import Queue, Empty
from threading import Lock, Event
from typing import Dict, Any

class EventBus:
    def __init__(self):
        self._topics: Dict[str, Queue] = {}
        self._lock = Lock()
        self._counters: Dict[str, int] = {}
        self._counter_events: Dict[str, Event] = {}

    def _get_q(self, topic: str) -> Queue:
        with self._lock:
            if topic not in self._topics:
                self._topics[topic] = Queue()
        return self._topics[topic]

    def emit(self, topic: str, payload: Any):
        q = self._get_q(topic)
        q.put(payload)
        # Counted events used by barriers.
        if topic not in ("dev_done",):
            return
        with self._lock:
            self._counters[topic] = self._counters.get(topic, 0) + 1
            if topic not in self._counter_events:
                self._counter_events[topic] = Event()
            # The emitter does not set the event; wait_for_count controls the barrier.

    def take(self, topic: str, timeout: float = None) -> Any:
        q = self._get_q(topic)
        return q.get(timeout=timeout)

    def reset_counter(self, topic: str):
        with self._lock:
            self._counters[topic] = 0
            if topic not in self._counter_events:
                self._counter_events[topic] = Event()
            self._counter_events[topic].clear()

    def wait_for_count(self, topic: str, expected: int, timeout: float = None) -> bool:
        # Simplified polling wait until the count reaches expected.
        self.reset_counter(topic)
        # emit is non-blocking, so consume the queue while polling.
        count = 0
        while count < expected:
            try:
                _ = self.take(topic, timeout=timeout)  # Consume one event.
                count += 1
            except Empty:
                return False
        return True
