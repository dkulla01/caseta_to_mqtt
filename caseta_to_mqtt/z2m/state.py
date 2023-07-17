from __future__ import annotations
from asyncio import Lock
from contextlib import asynccontextmanager
import logging
from typing import Iterable, Optional

from caseta_to_mqtt.z2m.model import GroupState, Zigbee2mqttGroup


LOGGER = logging.getLogger(__name__)


class LockedGroupState:
    def __init__(self) -> None:
        self._lock: Lock = Lock()
        self.state: GroupState

    @asynccontextmanager
    async def get_state(self) -> LockedGroupState:
        """yes, a read/write lock would be more efficient here, but it would be more
        work and nothing should be holding the locks here for very long anyway
        """
        try:
            await self.lock.acquire()
            yield self
        finally:
            self.lock.release()


class StateManager:
    def __init__(self) -> StateManager:
        self._group_state: dict[str, LockedGroupState] = {}

    async def set_group_state(self, group_name: str, state: GroupState):
        if group_name not in self._group_state:
            self._group_state[group_name] = LockedGroupState(state)

        async with self._group_state[group_name].get_state() as locked_state:
            locked_state[group_name] = state

    async def get_group_state(self, group_name) -> Optional[GroupState]:
        if group_name not in self._group_state:
            return None
        async with self._group_state[group_name].get_state() as locked_state:
            return locked_state.state
