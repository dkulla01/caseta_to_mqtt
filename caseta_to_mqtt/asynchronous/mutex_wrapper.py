from asyncio import Lock
from contextlib import asynccontextmanager
from typing import AsyncIterator, Generic, TypeVar


T = TypeVar("T")


class Value(Generic[T]):
    def __init__(self, value: T) -> None:
        self.value = value


class MutexWrapped(Generic[T]):
    """kind of inspired by rust/tokio mutexes"""

    def __init__(self, wrapped_object: T) -> None:
        self._lock = Lock()
        self._wrapped_object: Value[T] = Value(wrapped_object)

    @asynccontextmanager
    async def get(self) -> AsyncIterator[Value[T]]:
        try:
            await self._lock.acquire()
            yield self._wrapped_object
        finally:
            self._lock.release()
