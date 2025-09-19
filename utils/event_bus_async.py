# utils/event_bus_async.py
import asyncio
from typing import Dict, Any

class AsyncEventBus:
    def __init__(self):
        self._topics: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def _get_q(self, topic: str) -> asyncio.Queue:
        async with self._lock:
            q = self._topics.get(topic)
            if not q:
                q = asyncio.Queue()
                self._topics[topic] = q
            return q

    async def emit(self, topic: str, payload: Any):
        q = await self._get_q(topic)
        await q.put(payload)

    async def take(self, topic: str, timeout: float | None = None) -> Any:
        q = await self._get_q(topic)
        if timeout is None:
            return await q.get()
        return await asyncio.wait_for(q.get(), timeout=timeout)

    async def wait_for_count(self, topic: str, expected: int, timeout: float | None = None) -> bool:
        q = await self._get_q(topic)
        async def consume_expected():
            for _ in range(expected):
                await q.get()
        try:
            if timeout is None:
                await consume_expected()
                return True
            await asyncio.wait_for(consume_expected(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False