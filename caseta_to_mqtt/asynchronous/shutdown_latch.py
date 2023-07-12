from asyncio import Condition, Future
import logging

LOGGER = logging.getLogger(__name__)


class ShutdownLatchWrapper:
    def __init__(self):
        self._shutdown_latch = Condition()

    async def wrap_with_shutdown_latch(self, future: Future) -> Future:
        try:
            return await future
        except Exception as e:
            LOGGER.error(
                f"encountered an exception: {e}. starting to shutdown.", exc_info=True
            )
            async with self._shutdown_latch:
                self._shutdown_latch.notify()
