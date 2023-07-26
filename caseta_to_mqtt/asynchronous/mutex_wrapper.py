from asyncio import Lock
from contextlib import asynccontextmanager
from typing import Generic, TypeVar


T = TypeVar("T")


class MutexWrapped(Generic[T]):
    """kind of inspired by rust/tokio mutexes
    """
    def __init__(self, wrapped_object: T) -> None:
        self._lock = Lock()
        self._wrapped_object: T = wrapped_object

    @asynccontextmanager
    async def get(self) -> T:
        try:
            await self._lock.acquire()
            yield self._wrapped_object
        finally:
            self._lock.release()
