from __future__ import annotations
from asyncio import Lock
from contextlib import asynccontextmanager
import logging
from typing import Optional

from caseta_to_mqtt.z2m.model import GroupState


LOGGER = logging.getLogger(__name__)


class LockableGroupState:
    def __init__(self, group_friendly_name: str) -> None:
        self._lock: Lock = Lock()
        self.group_friendly_name = group_friendly_name
        self.state: Optional[GroupState] = None

    @asynccontextmanager
    async def lock(self) -> LockableGroupState:
        try:
            await self._lock.acquire()
            yield self
        finally:
            self._lock.release()


class StateManager:
    def __init__(self) -> StateManager:
        self._group_state: dict[str, LockableGroupState] = {}

    # async def set_group_state(self, group_name: str, state: GroupState):
    #     if group_name not in self._group_state:
    #         self._group_state[group_name] = LockableGroupState(state)

    #     async with self._group_state[group_name].get_state() as locked_state:
    #         locked_state[group_name] = state

    def initialize_group_state(self, group_name: str):
        self._group_state[group_name] = LockableGroupState(group_name)

    def get_group_state(self, group_name) -> Optional[LockableGroupState]:
        return self._group_state.get(group_name)
