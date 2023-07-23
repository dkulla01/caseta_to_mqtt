from __future__ import annotations
from asyncio import Lock
from contextlib import asynccontextmanager
import logging
from typing import Optional
from caseta_to_mqtt.asynchronous.mutex_wrapper import MutexWrapped

from caseta_to_mqtt.z2m.model import GroupState, Zigbee2mqttGroup


LOGGER = logging.getLogger(__name__)


class AllGroups:
    def __init__(self) -> None:
        self._groups: MutexWrapped[set[Zigbee2mqttGroup]] = MutexWrapped(set())

    async def update_groups(self, new_groups: set[Zigbee2mqttGroup]):
        async with self._groups.get() as current_groups:
            removed_groups = current_groups.difference(new_groups)
            added_groups = new_groups.difference(current_groups)
            unchanged_groups = new_groups.intersection(current_groups)
            LOGGER.debug(
                "%s removed groups, %s added groups, %s unchanged groups",
                len(removed_groups),
                len(added_groups),
                len(unchanged_groups),
            )
            current_groups = added_groups.union(unchanged_groups)

    async def get_groups(self) -> set[Zigbee2mqttGroup]:
        """N.B. don't modify the groups that you get returned here"""
        async with self._groups.get() as groups:
            return groups


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
