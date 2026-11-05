"""Per-device serial access: release, user commands, then background reads."""
import asyncio
from contextlib import asynccontextmanager
from itertools import count


class OperationQueue:
    def __init__(self):
        self._condition = asyncio.Condition()
        self._waiting = set()
        self._sequence = count()
        self._busy = False

    @asynccontextmanager
    async def slot(self, priority=1):
        ticket = (priority, next(self._sequence))
        async with self._condition:
            self._waiting.add(ticket)
            try:
                await self._condition.wait_for(
                    lambda: not self._busy and ticket == min(self._waiting)
                )
            finally:
                self._waiting.remove(ticket)
                self._condition.notify_all()
            self._busy = True
        try:
            yield
        finally:
            async with self._condition:
                self._busy = False
                self._condition.notify_all()
