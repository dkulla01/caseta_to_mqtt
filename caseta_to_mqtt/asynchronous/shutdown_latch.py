from asyncio import Condition
import logging
from typing import Awaitable

LOGGER = logging.getLogger(__name__)


class ShutdownLatchWrapper:
    def __init__(self):
        self._shutdown_latch = Condition()

    async def wrap_with_shutdown_latch(self, future: Awaitable) -> Awaitable:
        try:
            return await future
        except Exception as e:
            LOGGER.error(
                f"encountered an exception: {e}. starting to shutdown.", exc_info=True
            )
            async with self._shutdown_latch:
                self._shutdown_latch.notify()

    async def wait(self):
        async with self._shutdown_latch:
            await self._shutdown_latch.wait()
